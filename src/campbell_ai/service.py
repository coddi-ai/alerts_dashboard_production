"""Application service used by FastAPI and future internal consumers."""

from __future__ import annotations

import uuid

from src.campbell_ai.agents_runtime import CampbellAgentRuntime
from src.campbell_ai.config import CampbellSettings, get_campbell_settings
from src.campbell_ai.data import DashboardDataRepository
from src.campbell_ai.errors import CampbellConfigurationError, CampbellDataError
from src.campbell_ai.identity import (
    normalize_session_id,
    resolve_dashboard_principal,
)
from src.campbell_ai.models import (
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

    def _ensure_enabled(self) -> None:
        if not self.settings.enabled:
            raise CampbellConfigurationError("Campbell AI esta deshabilitado")

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
        return InitializeResponse(
            session_id=resolved_session,
            company_id=principal.company_id,
            username=principal.username,
            data_ready=True,
            datasets=self._public_data_status(validation),
        )

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
        else:
            response, request_type, message_id, visualizations = await self.runtime.answer(
                principal, resolved_session, normalized_message
            )
        return MessageResponse(
            response=response,
            message_id=message_id,
            session_id=resolved_session,
            company_id=principal.company_id,
            request_type=request_type,
            visualizations=visualizations,
        )

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
