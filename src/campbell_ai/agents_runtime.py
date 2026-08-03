"""Campbell AI multi-agent runtime backed by dashboard identity and data."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from src.campbell_ai.config import CampbellSettings
from src.campbell_ai.data import DashboardDataRepository
from src.campbell_ai.errors import CampbellConfigurationError, CampbellSessionError
from src.campbell_ai.feedback import FeedbackStore
from src.campbell_ai.identity import known_dashboard_clients
from src.campbell_ai.models import (
    ConversationMessage,
    DashboardPrincipal,
    SecurityDecision,
    VisualizationArtifact,
)
from src.campbell_ai.prompts import load_prompt
from src.campbell_ai.security import deterministic_guard
from src.campbell_ai.visualization import DashboardVisualizationService


@dataclass
class _SessionEntry:
    messages: list[ConversationMessage] = field(default_factory=list)
    last_access: float = field(default_factory=time.time)


@dataclass
class _AgentBundle:
    gatekeeper: Any
    head: Any
    planner: Any
    data_analyst: Any
    visualization_analyst: Any
    technical_expert: Any


class CampbellAgentRuntime:
    """Own agent construction and isolated in-memory conversation histories."""

    def __init__(self, repository: DashboardDataRepository, settings: CampbellSettings):
        self.repository = repository
        self.settings = settings
        self.visualizations = DashboardVisualizationService(repository)
        self.feedback = FeedbackStore(settings.feedback_path)
        self._sessions: dict[tuple[str, str, str], _SessionEntry] = {}
        self._locks: dict[tuple[str, str, str], asyncio.Lock] = {}
        self._pool_lock = asyncio.Lock()

    @staticmethod
    def _session_key(
        principal: DashboardPrincipal, session_id: str
    ) -> tuple[str, str, str]:
        return principal.username, principal.company_id, session_id

    async def initialize(self, principal: DashboardPrincipal, session_id: str) -> None:
        key = self._session_key(principal, session_id)
        async with self._pool_lock:
            self._cleanup_expired_locked()
            self._sessions.setdefault(key, _SessionEntry())
            self._locks.setdefault(key, asyncio.Lock())

    def _cleanup_expired_locked(self) -> None:
        cutoff = time.time() - self.settings.session_ttl_seconds
        expired = [key for key, entry in self._sessions.items() if entry.last_access < cutoff]
        for key in expired:
            self._sessions.pop(key, None)
            self._locks.pop(key, None)

    async def history(
        self, principal: DashboardPrincipal, session_id: str
    ) -> list[ConversationMessage]:
        key = self._session_key(principal, session_id)
        async with self._pool_lock:
            self._cleanup_expired_locked()
            entry = self._sessions.setdefault(key, _SessionEntry())
            entry.last_access = time.time()
            self._locks.setdefault(key, asyncio.Lock())
            return [message.model_copy(deep=True) for message in entry.messages]

    async def clear(self, principal: DashboardPrincipal, session_id: str) -> None:
        key = self._session_key(principal, session_id)
        async with self._pool_lock:
            self._sessions[key] = _SessionEntry()
            self._locks.setdefault(key, asyncio.Lock())

    def _append_to_entry(
        self,
        entry: _SessionEntry,
        user_message: str,
        assistant_message: str,
        visualizations: list[VisualizationArtifact] | None = None,
    ) -> str:
        assistant = ConversationMessage(
            role="assistant",
            content=assistant_message,
            visualizations=visualizations or [],
        )
        entry.messages.extend(
            [
                ConversationMessage(role="user", content=user_message),
                assistant,
            ]
        )
        max_items = max(2, self.settings.max_history_messages)
        entry.messages = entry.messages[-max_items:]
        entry.last_access = time.time()
        return assistant.message_id

    async def record_exchange(
        self,
        principal: DashboardPrincipal,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> str:
        """Record deterministic refusals as part of the visible conversation."""
        key = self._session_key(principal, session_id)
        await self.initialize(principal, session_id)
        async with self._locks[key]:
            return self._append_to_entry(
                self._sessions[key], user_message, assistant_message
            )

    async def record_feedback(
        self,
        principal: DashboardPrincipal,
        session_id: str,
        message_id: str,
        rating: str,
        comment: str | None = None,
    ) -> bool:
        """Validate feedback against an assistant message in the isolated session."""
        key = self._session_key(principal, session_id)
        async with self._pool_lock:
            self._cleanup_expired_locked()
            entry = self._sessions.get(key)
            lock = self._locks.get(key)
        if entry is None or lock is None:
            raise CampbellSessionError("La sesión de Campbell AI no existe o expiró")
        async with lock:
            target = next(
                (
                    item
                    for item in entry.messages
                    if item.message_id == message_id and item.role == "assistant"
                ),
                None,
            )
            if target is None:
                raise CampbellSessionError("La respuesta evaluada no pertenece a esta sesión")
            return self.feedback.record(
                principal, session_id, message_id, rating, comment
            )

    @staticmethod
    def _load_sdk():
        try:
            from agents import Agent, ModelSettings, Runner, function_tool
        except ImportError as exc:
            raise CampbellConfigurationError(
                "La dependencia openai-agents no esta instalada en el servicio Campbell AI"
            ) from exc
        return Agent, ModelSettings, Runner, function_tool

    def _build_bundle(
        self, principal: DashboardPrincipal
    ) -> tuple[_AgentBundle, Any, list[VisualizationArtifact], list[str]]:
        Agent, ModelSettings, Runner, function_tool = self._load_sdk()
        client = principal.company_id
        repository = self.repository
        generated_visualizations: list[VisualizationArtifact] = []
        executed_tools: list[str] = []

        def safe_data_call(callback, *args, **kwargs) -> str:
            try:
                return callback(*args, **kwargs)
            except Exception as exc:
                return json.dumps(
                    {
                        "available": False,
                        "error": type(exc).__name__,
                        "detail": "Fuente no disponible para el cliente activo",
                    },
                    ensure_ascii=False,
                )

        @function_tool
        def inspect_available_data() -> str:
            """List datasets and columns available for the active dashboard client."""
            return repository.describe_catalog(client)

        @function_tool
        def query_alerts(
            days: int = 60,
            unit_id: str = "",
            system: str = "",
            component: str = "",
            trigger_type: str = "",
            start_date: str = "",
            end_date: str = "",
            limit: int = 20,
        ) -> str:
            """Query alerts using a relative number of days or an explicit ISO date window."""
            return safe_data_call(
                repository.query_alerts,
                client,
                days=days,
                unit_id=unit_id,
                system=system,
                component=component,
                trigger_type=trigger_type,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )

        @function_tool
        def query_maintenance(
            unit_id: str = "",
            days: int = 60,
            system: str = "",
            component: str = "",
            action_type: str = "",
            start_date: str = "",
            end_date: str = "",
            limit: int = 20,
        ) -> str:
            """Query maintenance actions with equipment, category and date-window filters."""
            return safe_data_call(
                repository.query_maintenance,
                client,
                unit_id=unit_id,
                days=days,
                system=system,
                component=component,
                action_type=action_type,
                start_date=start_date,
                end_date=end_date,
                limit=limit,
            )

        @function_tool
        def query_oil_status(unit_id: str = "", limit: int = 20) -> str:
            """Query latest oil-analysis equipment status for the active client."""
            return safe_data_call(
                repository.query_oil_status, client, unit_id=unit_id, limit=limit
            )

        @function_tool
        def query_telemetry_health(unit_id: str = "", limit: int = 20) -> str:
            """Query telemetry equipment health for the active client."""
            return safe_data_call(
                repository.query_telemetry_health,
                client,
                unit_id=unit_id,
                limit=limit,
            )

        @function_tool
        def create_dashboard_chart(
            dataset: str,
            chart_type: str,
            dimension: str,
            secondary_dimension: str = "",
            metric: str = "count",
            aggregation: str = "count",
            days: int = 60,
            start_date: str = "",
            end_date: str = "",
            unit_id: str = "",
            filter_dimension: str = "",
            filter_value: str = "",
            top_n: int = 10,
            title: str = "",
        ) -> str:
            """Create a validated Plotly chart, including Pareto, heatmap and time windows."""
            try:
                artifact = self.visualizations.create_chart(
                    client=client,
                    dataset=dataset,
                    chart_type=chart_type,
                    dimension=dimension,
                    secondary_dimension=secondary_dimension,
                    metric=metric,
                    aggregation=aggregation,
                    days=days,
                    start_date=start_date,
                    end_date=end_date,
                    unit_id=unit_id,
                    filter_dimension=filter_dimension,
                    filter_value=filter_value,
                    top_n=top_n,
                    title=title,
                )
                generated_visualizations.append(artifact)
                return json.dumps(
                    {
                        "created": True,
                        "chart_id": artifact.chart_id,
                        "title": artifact.title,
                        "description": artifact.description,
                        "summary": artifact.summary,
                    },
                    ensure_ascii=False,
                )
            except Exception as exc:
                return json.dumps(
                    {
                        "created": False,
                        "error": type(exc).__name__,
                        "detail": str(exc),
                    },
                    ensure_ascii=False,
                )

        planner = Agent(
            name="Maintenance Planner",
            model=self.settings.model_planner,
            instructions=load_prompt("planner_base.md"),
            tools=[],
            model_settings=ModelSettings(temperature=0.1),
        )

        data_tools = [
            inspect_available_data,
            query_alerts,
            query_maintenance,
            query_oil_status,
            query_telemetry_health,
        ]
        data_analyst = Agent(
            name="Data Analyst Query",
            model=self.settings.model_data_analyst,
            instructions=load_prompt("data_analyst_query.md"),
            tools=data_tools,
            model_settings=ModelSettings(temperature=0),
        )

        visualization_analyst = Agent(
            name="Data Visualization Analyst",
            model=self.settings.model_data_analyst,
            instructions=load_prompt("data_analyst_visualization.md"),
            tools=[create_dashboard_chart],
            model_settings=ModelSettings(temperature=0),
        )

        technical_expert = Agent(
            name="Technical Maintenance Expert",
            model=self.settings.model_technical_expert,
            instructions=(
                load_prompt("technical_expert_base.md")
                + "\n\n"
                + load_prompt("five_whys.md")
            ),
            tools=[],
            model_settings=ModelSettings(temperature=0.2),
        )

        gatekeeper = Agent(
            name="Campbell Security Gatekeeper",
            model=self.settings.model_gatekeeper,
            instructions=load_prompt("gate_keeper.md"),
            tools=[],
            output_type=SecurityDecision,
            model_settings=ModelSettings(temperature=0),
        )

        @function_tool
        async def create_analysis_plan(question: str, context: str = "") -> str:
            """Create a short evidence plan for a complex maintenance question."""
            executed_tools.append("create_analysis_plan")
            result = await Runner.run(
                starting_agent=planner,
                input=f"Pregunta: {question}\nContexto: {context}",
                max_turns=2,
            )
            return str(result.final_output)

        @function_tool
        async def data_analysis(question: str, context: str = "") -> str:
            """Analyze dashboard data for the active company with traceable evidence."""
            executed_tools.append("data_analysis")
            result = await Runner.run(
                starting_agent=data_analyst,
                input=f"Pregunta: {question}\nContexto disponible: {context}",
                max_turns=6,
            )
            return str(result.final_output)

        @function_tool
        async def visualization_analysis(question: str, context: str = "") -> str:
            """Create validated interactive charts from active-company dashboard data."""
            executed_tools.append("visualization_analysis")
            result = await Runner.run(
                starting_agent=visualization_analyst,
                input=f"Solicitud de gráfico: {question}\nContexto: {context}",
                max_turns=5,
            )
            return str(result.final_output)

        @function_tool
        async def technical_analysis(question: str, evidence: str = "") -> str:
            """Interpret evidence and provide risks and recommended maintenance actions."""
            executed_tools.append("technical_analysis")
            result = await Runner.run(
                starting_agent=technical_expert,
                input=(
                    "Modo: análisis técnico. No apliques cinco porqués salvo que sea necesario.\n"
                    f"Pregunta: {question}\nEvidencia confirmada: {evidence}"
                ),
                max_turns=3,
            )
            return str(result.final_output)

        @function_tool
        async def five_whys_analysis(question: str, evidence: str = "") -> str:
            """Apply the 5 Whys method while labeling evidence, hypotheses and missing data."""
            executed_tools.append("five_whys_analysis")
            result = await Runner.run(
                starting_agent=technical_expert,
                input=(
                    "Modo obligatorio: análisis causal de 5 porqués.\n"
                    f"Problema: {question}\nEvidencia confirmada: {evidence}"
                ),
                max_turns=3,
            )
            return str(result.final_output)

        head = Agent(
            name="Campbell AI Head Maintenance",
            model=self.settings.model_head,
            instructions=load_prompt("head_maintenance_base.md"),
            tools=[
                create_analysis_plan,
                data_analysis,
                visualization_analysis,
                technical_analysis,
                five_whys_analysis,
            ],
            model_settings=ModelSettings(
                temperature=0,
                parallel_tool_calls=True,
                tool_choice="auto",
            ),
        )
        return (
            _AgentBundle(
                gatekeeper=gatekeeper,
                head=head,
                planner=planner,
                data_analyst=data_analyst,
                visualization_analyst=visualization_analyst,
                technical_expert=technical_expert,
            ),
            Runner,
            generated_visualizations,
            executed_tools,
        )

    async def answer(
        self, principal: DashboardPrincipal, session_id: str, message: str
    ) -> tuple[str, str, str, list[VisualizationArtifact]]:
        deterministic = deterministic_guard(
            message,
            active_company=principal.company_id,
            known_companies=known_dashboard_clients(),
        )
        if not deterministic.safe:
            response = f"Consulta bloqueada por seguridad: {deterministic.reason}."
            message_id = await self.record_exchange(
                principal, session_id, message, response
            )
            return response, "blocked", message_id, []
        if not os.getenv("OPENAI_API_KEY"):
            raise CampbellConfigurationError(
                "OPENAI_API_KEY no esta configurada en el servicio Campbell AI"
            )

        key = self._session_key(principal, session_id)
        await self.initialize(principal, session_id)
        lock = self._locks[key]
        async with lock:
            entry = self._sessions[key]
            entry.last_access = time.time()
            bundle, Runner, generated_visualizations, executed_tools = self._build_bundle(
                principal
            )

            validation_result = await Runner.run(
                starting_agent=bundle.gatekeeper,
                input=message,
                max_turns=1,
            )
            decision = validation_result.final_output
            if isinstance(decision, SecurityDecision):
                safe = decision.safe
                reason = decision.reason
            else:
                safe = False
                reason = "No fue posible validar la consulta"
            if not safe:
                response = f"Consulta bloqueada por seguridad: {reason}."
                message_id = self._append_to_entry(entry, message, response)
                return response, "blocked", message_id, []

            conversation = [
                {"role": item.role, "content": item.content} for item in entry.messages
            ]
            conversation.append({"role": "user", "content": message})
            result = await Runner.run(
                starting_agent=bundle.head,
                input=conversation,
                max_turns=8,
            )
            response = str(result.final_output or "").strip()
            if not response:
                response = "No fue posible generar una respuesta para la consulta."

            message_id = self._append_to_entry(
                entry, message, response, generated_visualizations
            )
            if generated_visualizations:
                request_type = "visualization"
            elif "five_whys_analysis" in executed_tools:
                request_type = "five_whys"
            else:
                request_type = "agents"
            return response, request_type, message_id, generated_visualizations
