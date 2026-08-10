"""Application service used by FastAPI and future internal consumers."""

from __future__ import annotations

import uuid
from typing import AsyncIterator

from src.campbell_ai.agents_runtime import CampbellAgentRuntime
from src.campbell_ai.concurrency import ConcurrencyGuard, ConcurrencyLimits
from src.campbell_ai.config import CampbellSettings, get_campbell_settings
from src.campbell_ai.data import DashboardDataRepository
from src.campbell_ai.errors import CampbellConfigurationError, CampbellDataError
from src.campbell_ai.grounding import GroundingReport
from src.campbell_ai.identity import (
    normalize_session_id,
    resolve_dashboard_principal,
)
from src.campbell_ai.models import (
    ConversationListResponse,
    FeedbackResponse,
    HistoryResponse,
    InitializeResponse,
    MessageResponse,
)
from src.campbell_ai.security import (
    UNSUPPORTED_CAPABILITY_MESSAGE,
    requests_unsupported_capability,
)


class CampbellAIService:
    def __init__(self, settings: CampbellSettings | None = None):
        self.settings = settings or get_campbell_settings()
        self.repository = DashboardDataRepository(self.settings.data_root)
        self.runtime = CampbellAgentRuntime(self.repository, self.settings)
        # Admission control lives at the service boundary, so both the blocking and the
        # streaming endpoint are bounded by the same counters.
        self.concurrency = ConcurrencyGuard(
            ConcurrencyLimits.from_settings(self.settings)
        )

    def _ensure_enabled(self) -> None:
        if not self.settings.enabled:
            raise CampbellConfigurationError("Campbell AI esta deshabilitado")

    @staticmethod
    def _user_key(principal) -> str:
        return f"{principal.username}|{principal.company_id}"

    @staticmethod
    def _public_data_status(validation: dict) -> dict:
        """Remove filesystem paths before returning initialization metadata."""
        return {
            "data_ready": bool(validation.get("data_ready")),
            "available_datasets": int(validation.get("available_datasets", 0)),
            "manifest": {
                "exists": bool(validation.get("manifest", {}).get("exists")),
                "valid": bool(validation.get("manifest", {}).get("valid")),
            },
            "datasets": {
                key: {
                    "label": item.get("label", key),
                    "exists": bool(item.get("exists")),
                    "valid": bool(item.get("valid")),
                    "rows": int(item.get("rows", 0)),
                    "missing_columns": item.get("missing_columns", []),
                }
                for key, item in validation.get("datasets", {}).items()
            },
        }

    async def initialize(
        self, username: str, company_id: str, session_id: str | None = None
    ) -> InitializeResponse:
        self._ensure_enabled()
        principal = resolve_dashboard_principal(username, company_id)
        resolved_session = normalize_session_id(
            session_id or f"campbell_{uuid.uuid4().hex}"
        )
        validation = self.repository.validate_client(principal.company_id)
        if not validation["data_ready"]:
            raise CampbellDataError(
                f"No hay fuentes de datos disponibles para {principal.company_id.upper()}"
            )
        await self.runtime.initialize(principal, resolved_session)
        # A session that expired, or a worker that restarted, must not take the
        # conversation with it: if the live thread is empty and the archive holds one for
        # this exact session, restore it before answering anything.
        restored = await self._rehydrate(principal, resolved_session)
        return InitializeResponse(
            session_id=resolved_session,
            company_id=principal.company_id,
            username=principal.username,
            data_ready=True,
            datasets=self._public_data_status(validation),
            capabilities=self.repository.client_capabilities(principal.company_id),
            restored_messages=restored,
        )

    async def _rehydrate(self, principal, session_id: str) -> int:
        """Restore an archived conversation into an empty session. Returns its length."""
        if await self.runtime.history(principal, session_id):
            return 0
        archived = await self.runtime.archived_conversation(principal, session_id)
        if not archived:
            return 0
        await self.runtime.restore(principal, session_id, archived)
        return len(archived)

    async def send_message(
        self,
        username: str,
        company_id: str,
        session_id: str,
        message: str,
    ) -> MessageResponse:
        self._ensure_enabled()
        principal = resolve_dashboard_principal(username, company_id)
        resolved_session = normalize_session_id(session_id)
        normalized_message = str(message or "").strip()
        if len(normalized_message) > self.settings.max_message_chars:
            raise CampbellConfigurationError("La consulta supera el largo permitido")

        if requests_unsupported_capability(normalized_message):
            response, request_type = UNSUPPORTED_CAPABILITY_MESSAGE, "unsupported"
            message_id = await self.runtime.record_exchange(
                principal, resolved_session, normalized_message, response
            )
            visualizations = []
            grounding = GroundingReport()
        else:
            # Only real agent runs are metered. A deterministic refusal costs nothing and
            # should not consume a slot another user is waiting for.
            async with self.concurrency.slot(self._user_key(principal)):
                (
                    response,
                    request_type,
                    message_id,
                    visualizations,
                    grounding,
                ) = await self.runtime.answer(
                    principal, resolved_session, normalized_message
                )
        return MessageResponse(
            response=response,
            message_id=message_id,
            session_id=resolved_session,
            company_id=principal.company_id,
            request_type=request_type,
            # `messages` is the canonical render payload for Dash. Sending the same
            # figures again here doubles response size and transient memory.
            visualizations=[],
            messages=await self.runtime.history(principal, resolved_session),
            grounding=grounding.as_dict(),
        )

    async def stream_message(
        self,
        username: str,
        company_id: str,
        session_id: str,
        message: str,
    ) -> AsyncIterator[dict]:
        """Yield progress events for one exchange, ending with a `done` payload.

        The final event carries the same fields as `send_message` plus the refreshed
        history, so a streaming consumer never needs a follow-up call.
        """
        self._ensure_enabled()
        if not self.settings.streaming_enabled:
            raise CampbellConfigurationError("El streaming de Campbell AI está deshabilitado")
        principal = resolve_dashboard_principal(username, company_id)
        resolved_session = normalize_session_id(session_id)
        normalized_message = str(message or "").strip()
        if len(normalized_message) > self.settings.max_message_chars:
            raise CampbellConfigurationError("La consulta supera el largo permitido")

        if requests_unsupported_capability(normalized_message):
            message_id = await self.runtime.record_exchange(
                principal, resolved_session, normalized_message, UNSUPPORTED_CAPABILITY_MESSAGE
            )
            yield await self._finalize_stream_event(
                {
                    "type": "done",
                    "response": UNSUPPORTED_CAPABILITY_MESSAGE,
                    "request_type": "unsupported",
                    "message_id": message_id,
                    "visualizations": [],
                    "grounding": GroundingReport().as_dict(),
                },
                principal,
                resolved_session,
            )
            return

        # The slot is held for as long as the stream is consumed, so a streamed answer
        # counts against the same limits as a blocking one.
        async with self.concurrency.slot(self._user_key(principal)):
            async for event in self.runtime.answer_stream(
                principal, resolved_session, normalized_message
            ):
                if event.get("type") == "done":
                    yield await self._finalize_stream_event(
                        event, principal, resolved_session
                    )
                else:
                    yield event

    async def _finalize_stream_event(
        self, event: dict, principal, resolved_session: str
    ) -> dict:
        messages = await self.runtime.history(principal, resolved_session)
        return {
            **event,
            # The final stream event also includes `messages`; avoid a second copy of
            # the same figure payload at the top level.
            "visualizations": [],
            "session_id": resolved_session,
            "company_id": principal.company_id,
            "messages": [message.model_dump(mode="json") for message in messages],
        }

    async def history(
        self, username: str, company_id: str, session_id: str
    ) -> HistoryResponse:
        self._ensure_enabled()
        principal = resolve_dashboard_principal(username, company_id)
        resolved_session = normalize_session_id(session_id)
        messages = await self.runtime.history(principal, resolved_session)
        return HistoryResponse(
            session_id=resolved_session,
            company_id=principal.company_id,
            messages=messages,
        )

    async def conversations(
        self, username: str, company_id: str
    ) -> ConversationListResponse:
        """List the user's archived conversations for the active company.

        Scoped by the resolved principal, so a caller cannot list another user's
        conversations by asking for a different username than the one it authenticated
        with.
        """
        self._ensure_enabled()
        principal = resolve_dashboard_principal(username, company_id)
        rows = await self.runtime.archived_conversations(principal)
        return ConversationListResponse(
            company_id=principal.company_id,
            conversations=[row.as_dict() for row in rows],
        )

    async def open_conversation(
        self, username: str, company_id: str, session_id: str
    ) -> HistoryResponse:
        """Reopen an archived conversation as the live session and return it."""
        self._ensure_enabled()
        principal = resolve_dashboard_principal(username, company_id)
        resolved_session = normalize_session_id(session_id)
        await self.runtime.initialize(principal, resolved_session)
        await self._rehydrate(principal, resolved_session)
        messages = await self.runtime.history(principal, resolved_session)
        if not messages:
            raise CampbellDataError(
                "La conversación solicitada no está disponible en el respaldo"
            )
        return HistoryResponse(
            session_id=resolved_session,
            company_id=principal.company_id,
            messages=messages,
        )

    async def clear(self, username: str, company_id: str, session_id: str) -> None:
        self._ensure_enabled()
        principal = resolve_dashboard_principal(username, company_id)
        resolved_session = normalize_session_id(session_id)
        await self.runtime.clear(principal, resolved_session)

    async def submit_feedback(
        self,
        username: str,
        company_id: str,
        session_id: str,
        message_id: str,
        rating: str,
        comment: str | None = None,
    ) -> FeedbackResponse:
        self._ensure_enabled()
        principal = resolve_dashboard_principal(username, company_id)
        resolved_session = normalize_session_id(session_id)
        accepted = await self.runtime.record_feedback(
            principal,
            resolved_session,
            message_id,
            rating,
            comment,
        )
        return FeedbackResponse(
            accepted=accepted,
            message_id=message_id,
            rating=rating,
        )
