"""Campbell AI multi-agent runtime backed by dashboard identity and data."""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator

from src.campbell_ai.chart_registry import DashboardChartRegistry
from src.campbell_ai.concurrency import execute_with_retry
from src.campbell_ai.config import CampbellSettings
from src.campbell_ai.data import DashboardDataRepository
from src.campbell_ai.errors import (
    CampbellAIError,
    CampbellConfigurationError,
    CampbellSessionError,
    CampbellTimeoutError,
)
from src.campbell_ai.feedback import FeedbackStore
from src.campbell_ai.identity import known_dashboard_clients
from src.campbell_ai.persistence import (
    ConversationArchive,
    ConversationSummary,
    build_conversation_archive,
)
from src.campbell_ai.sessions import SessionStore, build_session_store
from src.campbell_ai.summary import generate_conversation_summary
from src.campbell_ai.models import (
    ConversationMessage,
    DashboardPrincipal,
    SecurityDecision,
    VisualizationArtifact,
)
from src.campbell_ai.prompts import load_prompt
from src.campbell_ai.security import deterministic_guard
from src.campbell_ai.temporal import current_temporal_context
from src.campbell_ai.tool_errors import tool_failure
from src.campbell_ai.grounding import GroundingReport, audit_response
from src.campbell_ai.visualization import DashboardVisualizationService
from src.charts.signals import describe_signals as describe_signal_catalog


logger = logging.getLogger("campbell_ai.runtime")


def _offloading(function_tool):
    """Wrap the SDK's tool decorator so synchronous tool bodies leave the event loop.

    The Agents SDK calls a non-async tool body inline (``agents/tool.py``: if the
    function is not a coroutine function it is simply invoked). Every data tool here is
    a plain ``def`` doing pandas filtering, and the chart tools build Plotly figures, so
    that inline call blocks the *whole* uvicorn worker: while one user's query scans a
    frame, no other user's request is even read off the socket. With five people asking
    at once the answers stop overlapping and start queueing, which is the freeze this
    guards against.

    ``functools.wraps`` copies ``__annotations__``, ``__doc__`` and ``__wrapped__``, and
    ``inspect.signature`` follows ``__wrapped__``, so the generated tool schema is
    identical to the one the bare decorator would have produced. Async tool bodies (the
    agents-as-tools) already yield to the loop and are passed through untouched.
    """

    def decorator(func):
        if inspect.iscoroutinefunction(func):
            return function_tool(func)

        @functools.wraps(func)
        async def offloaded(*args, **kwargs):
            return await asyncio.to_thread(func, *args, **kwargs)

        return function_tool(offloaded)

    return decorator


@dataclass
class _AgentBundle:
    gatekeeper: Any
    head: Any
    planner: Any
    data_analyst: Any
    visualization_analyst: Any
    technical_expert: Any
    dashboard_guide: Any


class CampbellAgentRuntime:
    """Own agent construction and per-session conversation history."""

    def __init__(
        self,
        repository: DashboardDataRepository,
        settings: CampbellSettings,
        session_store: SessionStore | None = None,
        archive: ConversationArchive | None = None,
    ):
        self.repository = repository
        self.settings = settings
        self.visualizations = DashboardVisualizationService(repository)
        self.charts = DashboardChartRegistry(repository)
        self.archive = archive if archive is not None else build_conversation_archive(settings)
        self.feedback = FeedbackStore(settings.feedback_path, archive=self.archive)
        self.sessions = session_store or build_session_store(settings)

    @staticmethod
    def _session_key(
        principal: DashboardPrincipal, session_id: str
    ) -> tuple[str, str, str]:
        return principal.username, principal.company_id, session_id

    async def initialize(self, principal: DashboardPrincipal, session_id: str) -> None:
        await self.sessions.create_if_absent(self._session_key(principal, session_id))

    async def history(
        self, principal: DashboardPrincipal, session_id: str
    ) -> list[ConversationMessage]:
        return await self.sessions.read(self._session_key(principal, session_id))

    async def clear(self, principal: DashboardPrincipal, session_id: str) -> None:
        """Empty the visible thread. The archived copy is kept, not deleted."""
        await self.sessions.write(self._session_key(principal, session_id), [])
        self.archive.forget(principal, session_id)

    # -- durable backup -----------------------------------------------------

    async def _archive_exchange(
        self,
        principal: DashboardPrincipal,
        session_id: str,
        messages: list[ConversationMessage],
    ) -> None:
        """Back up the conversation after an interaction, without ever failing it.

        Runs on every exchange, as the durable copy has to be current: a session that
        expires or a worker that restarts must not take the conversation with it. The
        blocking storage calls go to a thread so the event loop keeps serving.
        """
        if not self.archive.enabled or not messages:
            return
        try:
            result = await asyncio.to_thread(
                self.archive.save_exchange, principal, session_id, messages
            )
            if result.failed and not result.written:
                logger.warning(
                    "Campbell AI no pudo respaldar la conversación en %s",
                    ", ".join(result.failed),
                )
            await self._maybe_summarize(principal, session_id, messages)
        except Exception:
            # Archiving is a side effect of answering; a failure here cannot be allowed
            # to turn a good answer into an error for the user.
            logger.warning("Campbell AI falló al respaldar la conversación", exc_info=True)

    async def _maybe_summarize(
        self,
        principal: DashboardPrincipal,
        session_id: str,
        messages: list[ConversationMessage],
    ) -> None:
        """Title a thread with an AI summary once it is long enough to need one.

        Skipped for the first exchange: the first message is a perfectly good label for
        a one-question conversation, and a model call per conversation start would be
        paid on every session that never becomes one.
        """
        if not self.settings.conversation_summary_enabled:
            return
        if len(messages) < 4 or self.archive.has_summary(principal, session_id):
            return
        summary = await generate_conversation_summary(
            messages, self.settings.model_summary
        )
        if summary:
            await asyncio.to_thread(
                self.archive.set_summary, principal, session_id, summary
            )

    async def restore(
        self,
        principal: DashboardPrincipal,
        session_id: str,
        messages: list[ConversationMessage],
    ) -> None:
        """Load an archived conversation into the live session store."""
        key = self._session_key(principal, session_id)
        async with self.sessions.lock(key):
            current = await self.sessions.read(key)
            if current:
                # A live thread is newer than the archive; never overwrite it.
                return
            max_items = max(2, self.settings.max_history_messages)
            await self.sessions.write(key, list(messages)[-max_items:])

    async def archived_conversations(
        self, principal: DashboardPrincipal, refresh: bool = False
    ) -> list[ConversationSummary]:
        """Archived conversations. `refresh` re-reads the objects instead of the index."""
        if not self.archive.enabled:
            return []
        return await asyncio.to_thread(
            lambda: self.archive.list_conversations(principal, refresh=refresh)
        )

    async def archived_conversation(
        self, principal: DashboardPrincipal, session_id: str
    ) -> list[ConversationMessage]:
        if not self.archive.enabled:
            return []
        return await asyncio.to_thread(
            self.archive.load_conversation, principal, session_id
        )

    def _appended(
        self,
        messages: list[ConversationMessage],
        user_message: str,
        assistant_message: str,
        visualizations: list[VisualizationArtifact] | None = None,
    ) -> tuple[list[ConversationMessage], str]:
        """Return the trimmed conversation plus the new assistant message id."""
        assistant = ConversationMessage(
            role="assistant",
            content=assistant_message,
            visualizations=visualizations or [],
        )
        updated = list(messages) + [
            ConversationMessage(role="user", content=user_message),
            assistant,
        ]
        max_items = max(2, self.settings.max_history_messages)
        return updated[-max_items:], assistant.message_id

    async def _snapshot(self, key: tuple[str, str, str]) -> list[ConversationMessage]:
        """The conversation as it stands, for use as context in one answer.

        Held under the lock only for the read itself. Two questions asked at the same
        moment therefore see the same history and neither waits for the other — which is
        what the user asking them expects, since they asked both before seeing either
        answer.
        """
        async with self.sessions.lock(key):
            return await self.sessions.read(key)

    async def _commit_exchange(
        self,
        key: tuple[str, str, str],
        user_message: str,
        assistant_message: str,
        visualizations: list[VisualizationArtifact] | None = None,
    ) -> tuple[list[ConversationMessage], str]:
        """Append one exchange to whatever the conversation holds *now*.

        Deliberately re-reads inside the lock rather than appending to the snapshot the
        answer started from. Two answers running in parallel both began from the same
        history; appending to that stale copy would make whichever finished second
        overwrite the first, and the user would watch one of their questions vanish from
        the thread.

        The lock is held for a read and a write — microseconds — not for an agent run.
        """
        async with self.sessions.lock(key):
            current = await self.sessions.read(key)
            updated, message_id = self._appended(
                current, user_message, assistant_message, visualizations
            )
            await self.sessions.write(key, updated)
        return updated, message_id

    async def record_exchange(
        self,
        principal: DashboardPrincipal,
        session_id: str,
        user_message: str,
        assistant_message: str,
    ) -> str:
        """Record deterministic refusals as part of the visible conversation."""
        key = self._session_key(principal, session_id)
        async with self.sessions.lock(key):
            messages = await self.sessions.read(key)
            updated, message_id = self._appended(
                messages, user_message, assistant_message
            )
            await self.sessions.write(key, updated)
        await self._archive_exchange(principal, session_id, updated)
        return message_id

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
        if not await self.sessions.exists(key):
            raise CampbellSessionError("La sesión de Campbell AI no existe o expiró")
        async with self.sessions.lock(key):
            messages = await self.sessions.read(key)
            target = next(
                (
                    item
                    for item in messages
                    if item.message_id == message_id and item.role == "assistant"
                ),
                None,
            )
            if target is None:
                raise CampbellSessionError("La respuesta evaluada no pertenece a esta sesión")
        # Outside the session lock and off the event loop: the local log and the S3
        # backup are both blocking, and neither should hold up the conversation.
        return await asyncio.to_thread(
            self.feedback.record, principal, session_id, message_id, rating, comment
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
    ) -> tuple[_AgentBundle, Any, list[VisualizationArtifact], list[str], list[str]]:
        Agent, ModelSettings, Runner, function_tool = self._load_sdk()
        # Every `@function_tool` below is registered through the offloading wrapper, so
        # a blocking tool body never runs on the event loop. See `_offloading`.
        function_tool = _offloading(function_tool)
        client = principal.company_id
        repository = self.repository
        generated_visualizations: list[VisualizationArtifact] = []
        executed_tools: list[str] = []
        # Raw tool results for this turn. Every number in the final answer must be
        # traceable to one of these; see grounding.audit_response.
        tool_outputs: list[str] = []

        def record(payload: str) -> str:
            tool_outputs.append(payload)
            return payload

        def safe_data_call(tool_name: str, callback, *args, **kwargs) -> str:
            """Run a query tool, turning any failure into an actionable retry hint."""
            try:
                return record(callback(*args, **kwargs))
            except Exception as exc:
                dataset = kwargs.get("domain") and (
                    "predictive_transmission"
                    if str(kwargs["domain"]).lower().startswith("transmis")
                    else "predictive_motor"
                )
                payload = tool_failure(tool_name, exc, dataset=dataset or None)
                if not isinstance(exc, CampbellAIError):
                    logger.exception("Campbell AI tool %s failed unexpectedly", tool_name)
                return record(payload)

        @function_tool
        def inspect_available_data() -> str:
            """List datasets and columns available for the active dashboard client."""
            return record(repository.describe_catalog(client))

        @function_tool
        def client_capabilities() -> str:
            """Which analyses are possible for the active client, and why others are not."""
            return safe_data_call(
                "client_capabilities", repository.describe_capabilities, client
            )

        @function_tool
        def inspect_dataset(dataset: str = "") -> str:
            """Schema and allowed filter values of a dataset; use it to fix a failed query."""
            return safe_data_call(
                "inspect_dataset", repository.describe_dataset, client, dataset
            )

        @function_tool
        def describe_signals(signal_codes: str = "") -> str:
            """Official name of telemetry signals. States that no unit is published."""
            codes = [
                code.strip()
                for code in str(signal_codes or "").replace(";", ",").split(",")
                if code.strip()
            ]
            return record(
                json.dumps(describe_signal_catalog(codes or None), ensure_ascii=False)
            )

        @function_tool
        def query_alerts(
            days: int = 60,
            unit_id: str = "",
            system: str = "",
            component: str = "",
            trigger_type: str = "",
            subsystem: str = "",
            trigger_var: str = "",
            start_date: str = "",
            end_date: str = "",
            limit: int = 20,
        ) -> str:
            """Query alerts using a relative number of days or an explicit ISO date window."""
            return safe_data_call(
                "query_alerts",
                repository.query_alerts,
                client,
                days=days,
                unit_id=unit_id,
                system=system,
                component=component,
                trigger_type=trigger_type,
                subsystem=subsystem,
                trigger_var=trigger_var,
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
                "query_maintenance",
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
                "query_oil_status",
                repository.query_oil_status,
                client,
                unit_id=unit_id,
                limit=limit,
            )

        @function_tool
        def query_telemetry_health(
            unit_id: str = "", latest_only: bool = True, limit: int = 20
        ) -> str:
            """Query telemetry equipment health, by default only the latest evaluated week."""
            return safe_data_call(
                "query_telemetry_health",
                repository.query_telemetry_health,
                client,
                unit_id=unit_id,
                latest_only=latest_only,
                limit=limit,
            )

        @function_tool
        def query_telemetry_components(
            unit_id: str = "",
            component: str = "",
            status: str = "",
            latest_only: bool = True,
            limit: int = 25,
        ) -> str:
            """Component-level telemetry status including the signals that triggered it."""
            return safe_data_call(
                "query_telemetry_components",
                repository.query_telemetry_components,
                client,
                unit_id=unit_id,
                component=component,
                status=status,
                latest_only=latest_only,
                limit=limit,
            )

        @function_tool
        def query_oil_components(
            unit_id: str = "",
            component: str = "",
            status: str = "",
            latest_only: bool = True,
            limit: int = 25,
        ) -> str:
            """Component-level oil condition with breached essays, severity and evolution."""
            return safe_data_call(
                "query_oil_components",
                repository.query_oil_components,
                client,
                unit_id=unit_id,
                component=component,
                status=status,
                latest_only=latest_only,
                limit=limit,
            )

        @function_tool
        def query_alert_detail(
            alert_id: str = "",
            unit_id: str = "",
            trigger: str = "",
            limit: int = 10,
        ) -> str:
            """Measured peak value and applicable limit of the signal that raised an alert."""
            return safe_data_call(
                "query_alert_detail",
                repository.query_alert_detail,
                client,
                alert_id=alert_id,
                unit_id=unit_id,
                trigger=trigger,
                limit=limit,
            )

        @function_tool
        def query_alert_signals(alert_id: str = "", unit_id: str = "") -> str:
            """Signals of an alert that have captured values, and which carry limits."""
            return safe_data_call(
                "query_alert_signals",
                repository.query_alert_signals,
                client,
                alert_id=alert_id,
                unit_id=unit_id,
            )

        @function_tool
        def query_telemetry_series(
            unit_id: str,
            signals: str = "",
            days: int = 30,
            start_date: str = "",
            end_date: str = "",
        ) -> str:
            """Continuous raw telemetry series for a unit, any signal, any date window.

            Unlike query_alert_signals/alert_sensor_trend (scoped to one alert's own
            sampling window), reads the raw continuous source so the agent can report
            on or plot a signal the user asks about even when it did not trigger an
            alert. days is capped at 90; use start_date/end_date for a longer window.
            """
            return safe_data_call(
                "query_telemetry_series",
                repository.query_telemetry_series,
                client,
                unit_id=unit_id,
                signals=signals,
                days=days,
                start_date=start_date,
                end_date=end_date,
            )

        @function_tool
        def query_maintenance_summary(unit_id: str = "", limit: int = 10) -> str:
            """Weekly written maintenance summary per equipment."""
            return safe_data_call(
                "query_maintenance_summary",
                repository.query_maintenance_summary,
                client,
                unit_id=unit_id,
                limit=limit,
            )

        @function_tool
        def query_predictive_risk(
            domain: str = "motor", unit_id: str = "", limit: int = 15
        ) -> str:
            """Predictive-model ranking and failure-mode risks for motor or transmision."""
            return safe_data_call(
                "query_predictive_risk",
                repository.query_predictive_risk,
                client,
                domain=domain,
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
                return record(
                    json.dumps(
                        {
                            "created": True,
                            "chart_id": artifact.chart_id,
                            "title": artifact.title,
                            "description": artifact.description,
                            "summary": artifact.summary,
                        },
                        ensure_ascii=False,
                    )
                )
            except Exception as exc:
                if not isinstance(exc, CampbellAIError):
                    logger.exception("Campbell AI chart build failed unexpectedly")
                return record(
                    tool_failure(
                        "create_dashboard_chart",
                        exc,
                        dataset=str(dataset or "") or None,
                        extra={"created": False},
                    )
                )

        planner = Agent(
            name="Maintenance Planner",
            model=self.settings.model_planner,
            instructions=load_prompt("planner_base.md"),
            tools=[],
            model_settings=ModelSettings(temperature=0.1),
        )

        data_tools = [
            client_capabilities,
            inspect_available_data,
            inspect_dataset,
            describe_signals,
            query_alerts,
            query_alert_detail,
            query_alert_signals,
            query_maintenance,
            query_maintenance_summary,
            query_oil_status,
            query_oil_components,
            query_telemetry_health,
            query_telemetry_components,
            query_telemetry_series,
            query_predictive_risk,
        ]
        data_analyst = Agent(
            name="Data Analyst Query",
            model=self.settings.model_data_analyst,
            instructions=load_prompt("data_analyst_query.md"),
            tools=data_tools,
            model_settings=ModelSettings(temperature=0),
        )

        @function_tool
        def list_dashboard_charts() -> str:
            """List the named dashboard charts this client is allowed to reproduce."""
            return record(
                json.dumps({"charts": self.charts.list_charts(client)}, ensure_ascii=False)
            )

        @function_tool
        def render_dashboard_chart(
            chart_id: str,
            unit_id: str = "",
            alert_id: str = "",
            signal: str = "",
            days: int = 0,
            start_date: str = "",
            end_date: str = "",
            top_n: int = 0,
        ) -> str:
            """Render a named dashboard chart, reproducing the dashboard's own visual."""
            parameters = {
                key: value
                for key, value in (
                    ("unit_id", unit_id),
                    ("alert_id", alert_id),
                    ("signal", signal),
                    ("days", days),
                    ("start_date", start_date),
                    ("end_date", end_date),
                    ("top_n", top_n),
                )
                if value
            }
            try:
                artifact = self.charts.render(client, chart_id, parameters)
                generated_visualizations.append(artifact)
                return record(
                    json.dumps(
                        {
                            "created": True,
                            "chart_id": artifact.chart_id,
                            "title": artifact.title,
                            "description": artifact.description,
                            "summary": artifact.summary,
                        },
                        ensure_ascii=False,
                    )
                )
            except Exception as exc:
                if not isinstance(exc, CampbellAIError):
                    logger.exception("Campbell AI named chart failed unexpectedly")
                return record(
                    tool_failure(
                        "render_dashboard_chart",
                        exc,
                        hint=(
                            "Llama a list_dashboard_charts para ver los chart_id y "
                            "parametros validos, y reintenta una sola vez."
                        ),
                        extra={"created": False},
                    )
                )

        visualization_analyst = Agent(
            name="Data Visualization Analyst",
            model=self.settings.model_data_analyst,
            instructions=load_prompt("data_analyst_visualization.md"),
            tools=[
                list_dashboard_charts,
                render_dashboard_chart,
                create_dashboard_chart,
            ],
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

        dashboard_guide = Agent(
            name="Dashboard Navigation Guide",
            model=self.settings.model_dashboard_guide,
            instructions=load_prompt("dashboard_guide.md"),
            tools=[],
            model_settings=ModelSettings(temperature=0.1),
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
                max_turns=self.settings.max_turns_data_analyst,
            )
            return str(result.final_output)

        @function_tool
        async def visualization_analysis(question: str, context: str = "") -> str:
            """Create validated interactive charts from active-company dashboard data."""
            executed_tools.append("visualization_analysis")
            result = await Runner.run(
                starting_agent=visualization_analyst,
                input=f"Solicitud de gráfico: {question}\nContexto: {context}",
                # Room for more than one chart-building call per request (a single
                # question can legitimately ask for several distinct figures).
                max_turns=8,
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
        async def dashboard_navigation(question: str) -> str:
            """Explain where to find something in the dashboard's menu and sections."""
            executed_tools.append("dashboard_navigation")
            result = await Runner.run(
                starting_agent=dashboard_guide,
                input=f"Pregunta de navegación: {question}",
                max_turns=2,
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
                dashboard_navigation,
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
                dashboard_guide=dashboard_guide,
            ),
            Runner,
            generated_visualizations,
            executed_tools,
            tool_outputs,
        )

    async def answer(
        self, principal: DashboardPrincipal, session_id: str, message: str
    ) -> tuple[str, str, str, list[VisualizationArtifact], GroundingReport]:
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
            return response, "blocked", message_id, [], GroundingReport()
        if not os.getenv("OPENAI_API_KEY"):
            raise CampbellConfigurationError(
                "OPENAI_API_KEY no esta configurada en el servicio Campbell AI"
            )

        key = self._session_key(principal, session_id)
        await self.initialize(principal, session_id)
        # One wall-clock budget for the whole exchange, gatekeeper and retries included.
        # Without it a run has no upper bound at all, and the only thing that ever ends
        # it is the caller hanging up — after which the answer still completes and is
        # persisted, which is precisely how a question ends up "already answered" on the
        # next page load.
        deadline = time.monotonic() + self.settings.answer_timeout_seconds

        # Read the conversation under the lock, then let go of it. The agent run below
        # is NOT serialized per session, and that is the point: holding the lock across
        # a run meant a second question in the same conversation waited the full
        # `queue_timeout_seconds` and was then rejected, however much headroom the
        # service had. Someone who fires several questions at once got one answer and a
        # row of "la sesión está ocupada".
        #
        # The lock only ever protected the read-modify-write of the message list, and
        # `_commit_exchange` still holds it for that — re-reading before appending, so
        # two answers finishing together cannot overwrite each other.
        messages = await self._snapshot(key)
        (
            bundle,
            Runner,
            generated_visualizations,
            executed_tools,
            tool_outputs,
        ) = self._build_bundle(principal)

        blocked = await self._gatekeeper_refusal(
            Runner, bundle, message, deadline=deadline
        )
        if blocked is not None:
            updated, message_id = await self._commit_exchange(key, message, blocked)
            await self._archive_exchange(principal, session_id, updated)
            return blocked, "blocked", message_id, [], GroundingReport()

        # A model-side throttle or a transient upstream error would otherwise
        # surface as a failed question the user has to retype.
        result = await execute_with_retry(
            lambda: Runner.run(
                starting_agent=bundle.head,
                input=self._conversation_input(messages, message),
                max_turns=self.settings.max_turns_head,
            ),
            attempts=self.settings.retry_attempts,
            initial_delay=self.settings.retry_initial_delay,
            max_delay=self.settings.retry_max_delay,
            label="la consulta a los agentes",
            deadline=deadline,
        )
        response = self._normalized_response(result.final_output)
        grounding = self._audit(response, tool_outputs, question=message)
        updated, message_id = await self._commit_exchange(
            key, message, response, generated_visualizations
        )

        # Archiving happens outside the session lock so a slow backup cannot
        # delay the next question in the same conversation.
        await self._archive_exchange(principal, session_id, updated)
        return (
            response,
            self._request_type(generated_visualizations, executed_tools),
            message_id,
            generated_visualizations,
            grounding,
        )

    _TRUNCATION_NOTE = "\n\n[...respuesta anterior recortada por longitud...]"

    def _budgeted_history(
        self, messages: list[ConversationMessage]
    ) -> list[dict[str, str]]:
        """Replay the most recent conversation that fits the character budget.

        `max_history_messages` alone does not bound prompt size: a data answer can be a
        multi-kilobyte markdown table, so twenty of them replay an enormous prompt into
        every subsequent turn — and into each sub-agent the head hands off to. Latency
        then climbs with conversation length until an ordinary question crosses the
        answer timeout, which is exactly the "it hangs once the chat gets long" report.

        Two bounds, applied newest-first because recent turns carry the context the user
        is actually referring to:

        - each individual message is capped, so one huge table cannot evict everything
          else in the thread;
        - the total is capped, and older messages are dropped once it is reached.

        Truncation is marked in the text rather than done silently, so the model treats
        a shortened answer as incomplete instead of as the whole story.
        """
        per_message = max(500, int(self.settings.max_history_message_chars))
        budget = max(1000, int(self.settings.max_history_chars))
        note = self._TRUNCATION_NOTE

        selected: list[dict[str, str]] = []
        used = 0
        for item in reversed(messages):
            content = item.content or ""
            if len(content) > per_message:
                content = content[: per_message - len(note)] + note
            if used + len(content) > budget and selected:
                # Budget spent. Everything older than this is dropped; `selected` is
                # non-empty, so the most recent turn always survives.
                break
            selected.append({"role": item.role, "content": content})
            used += len(content)
        selected.reverse()
        if len(selected) < len(messages):
            logger.info(
                "Campbell AI recortó el historial replicado: %s de %s mensajes, %s caracteres",
                len(selected),
                len(messages),
                used,
            )
        return selected

    def _conversation_input(
        self, messages: list[ConversationMessage], message: str
    ) -> list[dict[str, str]]:
        context = self._temporal_context()
        conversation = self._budgeted_history(messages)
        conversation.append(
            {
                "role": "user",
                "content": (
                    f"{self._temporal_context_prompt(context)}\n\n"
                    f"Consulta del usuario: {message}"
                ),
            }
        )
        return conversation

    def _temporal_context(self) -> dict[str, str]:
        return current_temporal_context(self.settings.timezone)

    @staticmethod
    def _temporal_context_prompt(context: dict[str, str]) -> str:
        return (
            "Contexto temporal obligatorio para esta consulta: "
            f"hoy es {context.get('today')} ({context.get('weekday')}), "
            f"zona horaria {context.get('timezone')}. Interpreta 'hoy', 'ayer', "
            "'ultimos N dias', 'esta semana' y cualquier ventana relativa usando "
            "esta fecha como referencia, salvo que el usuario entregue fechas "
            "explicitas."
        )

    @staticmethod
    def _normalized_response(final_output: Any) -> str:
        response = str(final_output or "").strip()
        return response or "No fue posible generar una respuesta para la consulta."

    @staticmethod
    def _request_type(
        visualizations: list[VisualizationArtifact], executed_tools: list[str]
    ) -> str:
        if visualizations:
            return "visualization"
        if "five_whys_analysis" in executed_tools:
            return "five_whys"
        return "agents"

    async def _gatekeeper_refusal(
        self, Runner, bundle, message: str, deadline: float | None = None
    ) -> str | None:
        """Return the refusal text when the gatekeeper blocks, otherwise None.

        Bounded by its own slice of the exchange budget: this is a single-turn call, so
        if it has not answered in that time the upstream is unhealthy and spending the
        rest of the budget waiting only delays the error the user is going to get.
        """
        budget = self.settings.gatekeeper_timeout_seconds
        if deadline is not None:
            budget = min(budget, max(0.0, deadline - time.monotonic()))
        if budget <= 0:
            raise CampbellTimeoutError(
                "Campbell AI agotó el tiempo disponible antes de validar la consulta"
            )
        try:
            validation_result = await asyncio.wait_for(
                Runner.run(
                    starting_agent=bundle.gatekeeper,
                    input=message,
                    max_turns=1,
                ),
                timeout=budget,
            )
        except asyncio.TimeoutError as exc:
            raise CampbellTimeoutError(
                "Campbell AI no alcanzó a validar la consulta a tiempo"
            ) from exc
        decision = validation_result.final_output
        if isinstance(decision, SecurityDecision):
            if decision.safe:
                return None
            reason = decision.reason
        else:
            reason = "No fue posible validar la consulta"
        return f"Consulta bloqueada por seguridad: {reason}."

    async def answer_stream(
        self, principal: DashboardPrincipal, session_id: str, message: str
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield progress events for one exchange, ending with a `done` payload.

        Event shapes:
        - ``{"type": "status", "stage": ...}``  coarse progress before text exists
        - ``{"type": "delta", "text": ...}``    incremental answer text
        - ``{"type": "done", ...}``             final response, id and visualizations
        """
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
            yield self._done_event(
                response, "blocked", message_id, [], GroundingReport()
            )
            return
        if not os.getenv("OPENAI_API_KEY"):
            raise CampbellConfigurationError(
                "OPENAI_API_KEY no esta configurada en el servicio Campbell AI"
            )

        key = self._session_key(principal, session_id)
        await self.initialize(principal, session_id)
        deadline = time.monotonic() + self.settings.answer_timeout_seconds

        # Same shape as `answer`: snapshot under the lock, stream without it, commit
        # under it again. Holding the lock for the length of a stream is even worse than
        # for a blocking run, because a stream lives as long as its consumer keeps
        # reading — one slow browser could lock a conversation for minutes.
        messages = await self._snapshot(key)
        (
            bundle,
            Runner,
            generated_visualizations,
            executed_tools,
            tool_outputs,
        ) = self._build_bundle(principal)

        yield {"type": "status", "stage": "validating"}
        blocked = await self._gatekeeper_refusal(
            Runner, bundle, message, deadline=deadline
        )
        if blocked is not None:
            updated, message_id = await self._commit_exchange(key, message, blocked)
            await self._archive_exchange(principal, session_id, updated)
            yield self._done_event(
                blocked, "blocked", message_id, [], GroundingReport()
            )
            return

        yield {"type": "status", "stage": "analyzing"}
        streamed = Runner.run_streamed(
            starting_agent=bundle.head,
            input=self._conversation_input(messages, message),
            max_turns=self.settings.max_turns_head,
        )
        chunks: list[str] = []
        async for event in streamed.stream_events():
            if time.monotonic() > deadline:
                # Checked per event rather than with wait_for: the iteration is the
                # only place the stream yields control, and abandoning it here still
                # lets the caller keep whatever text already arrived.
                raise CampbellTimeoutError(
                    "Campbell AI agotó el tiempo disponible para esta consulta",
                    elapsed_seconds=self.settings.answer_timeout_seconds,
                )
            # Most of the wall clock is spent calling tools before any text
            # exists, so surface which step is running or the user stares at a
            # spinner for most of the answer.
            step = self._tool_progress(event)
            if step:
                yield {"type": "status", "stage": "tool", "detail": step}
                continue
            text = self._delta_text(event)
            if text:
                chunks.append(text)
                yield {"type": "delta", "text": text}

        response = self._normalized_response(
            getattr(streamed, "final_output", None) or "".join(chunks)
        )
        grounding = self._audit(response, tool_outputs, question=message)
        updated, message_id = await self._commit_exchange(
            key, message, response, generated_visualizations
        )
        await self._archive_exchange(principal, session_id, updated)
        yield self._done_event(
            response,
            self._request_type(generated_visualizations, executed_tools),
            message_id,
            generated_visualizations,
            grounding,
        )

    # User-facing labels for the head agent's tools. Internal tool names are never
    # shown; anything unmapped falls back to a generic label.
    _TOOL_LABELS: dict[str, str] = {
        "create_analysis_plan": "Planificando el análisis",
        "data_analysis": "Consultando datos",
        "visualization_analysis": "Construyendo el gráfico",
        "technical_analysis": "Interpretando la evidencia",
        "five_whys_analysis": "Analizando causa raíz",
        "dashboard_navigation": "Ubicando la sección del dashboard",
    }

    @classmethod
    def _tool_progress(cls, event: Any) -> str | None:
        """Return a progress label when the stream reports a tool call starting."""
        if getattr(event, "type", None) != "run_item_stream_event":
            return None
        item = getattr(event, "item", None)
        if item is None or getattr(item, "type", None) != "tool_call_item":
            return None
        raw = getattr(item, "raw_item", None)
        name = str(getattr(raw, "name", "") or "")
        if not name:
            return None
        return cls._TOOL_LABELS.get(name, "Analizando")

    @staticmethod
    def _delta_text(event: Any) -> str:
        """Extract incremental answer text from an Agents SDK stream event.

        Only raw text deltas of the top-level agent are surfaced; tool traffic and
        sub-agent chatter stay internal.
        """
        if getattr(event, "type", None) != "raw_response_event":
            return ""
        data = getattr(event, "data", None)
        if data is None or getattr(data, "type", None) != "response.output_text.delta":
            return ""
        return str(getattr(data, "delta", "") or "")

    def _audit(
        self, response: str, tool_outputs: list[str], question: str = ""
    ) -> GroundingReport:
        """Trace every number in the answer back to a tool result."""
        report = audit_response(response, tool_outputs, question=question)
        if not report.is_grounded:
            # Logged without the answer text: the point is the drift, not the content.
            logger.warning(
                "Campbell AI grounding gap: %s numeros sin origen, unidades inventadas=%s",
                len(report.unverified_numbers),
                report.invented_units,
            )
        return report

    def _done_event(
        self,
        response: str,
        request_type: str,
        message_id: str,
        visualizations: list[VisualizationArtifact],
        grounding: GroundingReport | None = None,
    ) -> dict[str, Any]:
        return {
            "type": "done",
            "response": response,
            "request_type": request_type,
            "message_id": message_id,
            "visualizations": [item.model_dump(mode="json") for item in visualizations],
            "grounding": (grounding or GroundingReport()).as_dict(),
            "temporal_context": self._temporal_context(),
        }
