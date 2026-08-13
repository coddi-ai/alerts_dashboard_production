"""Application service used by FastAPI and future internal consumers."""

from __future__ import annotations

import uuid
from typing import AsyncIterator

from src.campbell_ai.agents_runtime import CampbellAgentRuntime
from src.campbell_ai.concurrency import ConcurrencyGuard, ConcurrencyLimits
from src.campbell_ai.config import CampbellSettings, get_campbell_settings
from src.campbell_ai.data import DashboardDataRepository
from src.campbell_ai.errors import CampbellConfigurationError, CampbellDataError
from src.campbell_ai.errors import (
    CampbellAuthorizationError,
    CampbellBusyError,
    CampbellSessionError,
    CampbellTimeoutError,
)
from src.campbell_ai.grounding import GroundingReport
from src.campbell_ai.identity import (
    normalize_session_id,
    resolve_dashboard_principal,
)
from src.campbell_ai.jobs import Job, JobRegistry
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
from src.campbell_ai.temporal import current_temporal_context


class CampbellAIService:
    def __init__(self, settings: CampbellSettings | None = None):
        self.settings = settings or get_campbell_settings()
        self.repository = DashboardDataRepository(
            self.settings.data_root, timezone=self.settings.timezone
        )
        self.runtime = CampbellAgentRuntime(self.repository, self.settings)
        # Admission control lives at the service boundary, so both the blocking and the
        # streaming endpoint are bounded by the same counters.
        self.concurrency = ConcurrencyGuard(
            ConcurrencyLimits.from_settings(self.settings)
        )
        # Background answers. The job owns the work, so a caller that disconnects,
        # reloads or retries never orphans a run nor starts a duplicate one.
        self.jobs = JobRegistry(retention_seconds=self.settings.job_retention_seconds)

    def _ensure_enabled(self) -> None:
        if not self.settings.enabled:
            raise CampbellConfigurationError("Campbell AI esta deshabilitado")

    @staticmethod
    def _user_key(principal) -> str:
        return f"{principal.username}|{principal.company_id}"

    def temporal_context(self) -> dict[str, str]:
        return current_temporal_context(self.settings.timezone)

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
        # Whether the caller is resuming a thread it already knows about, or starting a new
        # one. The distinction decides if the archive is worth consulting at all, below.
        # A supplied id is still validated exactly as before and rejects a malformed value.
        if session_id:
            resolved_session = normalize_session_id(session_id)
            resuming = True
        else:
            resolved_session = normalize_session_id(f"campbell_{uuid.uuid4().hex}")
            resuming = False
        validation = self.repository.validate_client(principal.company_id)
        if not validation["data_ready"]:
            raise CampbellDataError(
                f"No hay fuentes de datos disponibles para {principal.company_id.upper()}"
            )
        await self.runtime.initialize(principal, resolved_session)
        # A session that expired, or a worker that restarted, must not take the
        # conversation with it: if the live thread is empty and the archive holds one for
        # this exact session, restore it before answering anything.
        #
        # Only when resuming. The archive is keyed by session id, so a lookup for an id
        # this method just minted from `uuid4` cannot match anything - it was a storage
        # round trip guaranteed to miss, paid inside the blocking call the user is waiting
        # on. It happened on every first page load and on every new tab (the browser store
        # is session-scoped, so it arrives empty), and on every client switch for a user
        # with more than one client.
        restored = await self._rehydrate(principal, resolved_session) if resuming else 0
        return InitializeResponse(
            session_id=resolved_session,
            company_id=principal.company_id,
            username=principal.username,
            temporal_context=self.temporal_context(),
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
            temporal_context=self.temporal_context(),
            request_type=request_type,
            # `messages` is the canonical render payload for Dash. Sending the same
            # figures again here doubles response size and transient memory.
            visualizations=[],
            messages=await self.runtime.history(principal, resolved_session),
            grounding=grounding.as_dict(),
        )

    # -- background answers -------------------------------------------------

    async def submit_message(
        self,
        username: str,
        company_id: str,
        session_id: str,
        message: str,
        client_message_id: str | None = None,
    ) -> dict:
        """Register the answer as a background job and return its handle immediately.

        Everything that can be judged without running the agents — the service being
        enabled, the identity, the message length — is validated here so the caller gets
        a real HTTP error rather than a job that fails on its first poll.

        `client_message_id` is the idempotency key. Two submissions carrying the same one
        for the same session attach to a single run, so a double click, a retry after a
        dead connection, or a reloaded tab re-dispatching its pending message cannot
        produce two answers to one question.
        """
        self._ensure_enabled()
        principal = resolve_dashboard_principal(username, company_id)
        resolved_session = normalize_session_id(session_id)
        normalized_message = str(message or "").strip()
        if not normalized_message:
            raise CampbellSessionError("La consulta está vacía")
        if len(normalized_message) > self.settings.max_message_chars:
            raise CampbellConfigurationError("La consulta supera el largo permitido")

        dedup_key = "|".join(
            [
                principal.username,
                principal.company_id,
                resolved_session,
                str(client_message_id or "").strip() or f"auto_{uuid.uuid4().hex}",
            ]
        )
        job = await self.jobs.submit(
            dedup_key,
            lambda: self.send_message(
                username, company_id, resolved_session, normalized_message
            ),
            to_result=lambda response: response.model_dump(mode="json"),
            on_error=self._job_error,
        )
        return {**job.as_dict(), "session_id": resolved_session}

    @staticmethod
    def _job_error(exc: BaseException) -> dict:
        """Translate a failed run into the shape the caller polls for.

        `retryable` is the part that matters to the UI: the same question is worth
        resending after a busy rejection, but not after it was blocked or rejected for
        length, and after a timeout the user should narrow it rather than repeat it.
        """
        if isinstance(exc, CampbellBusyError):
            return {
                "detail": str(exc),
                "kind": "busy",
                "retryable": True,
                "retry_after": exc.retry_after,
            }
        if isinstance(exc, CampbellTimeoutError):
            return {
                "detail": str(exc),
                "kind": "timeout",
                "retryable": True,
                "elapsed_seconds": exc.elapsed_seconds,
            }
        if isinstance(exc, CampbellAuthorizationError):
            return {"detail": str(exc), "kind": "forbidden", "retryable": False}
        if isinstance(exc, CampbellDataError):
            return {"detail": str(exc), "kind": "unavailable", "retryable": True}
        if isinstance(exc, CampbellConfigurationError):
            return {"detail": str(exc), "kind": "not_configured", "retryable": False}
        return {
            "detail": "Campbell AI no pudo completar la consulta",
            "kind": "server_error",
            "retryable": True,
        }

    async def message_status(self, job_id: str) -> dict | None:
        """Current state of a background answer, or None once it is unknown.

        None means the job is finished *and* past its retention window, or never
        existed. Either way the caller's recovery is the same and does not involve
        re-asking: the answer, if there was one, is in the conversation history.
        """
        job = await self.jobs.get(job_id)
        return job.as_dict() if job is not None else None

    async def cancel_message(self, job_id: str) -> bool:
        return await self.jobs.cancel(job_id)

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
            "temporal_context": self.temporal_context(),
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
        self, username: str, company_id: str, refresh: bool = False
    ) -> ConversationListResponse:
        """List the user's archived conversations for the active company.

        Scoped by the resolved principal, so a caller cannot list another user's
        conversations by asking for a different username than the one it authenticated
        with.
        """
        self._ensure_enabled()
        principal = resolve_dashboard_principal(username, company_id)
        rows = await self.runtime.archived_conversations(principal, refresh=refresh)
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
