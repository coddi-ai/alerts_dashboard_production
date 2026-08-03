"""FastAPI entry point for Campbell AI internal consumers."""

from __future__ import annotations

import hmac
import logging
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status

from src.campbell_ai.config import get_campbell_settings
from src.campbell_ai.errors import (
    CampbellAuthenticationError,
    CampbellAuthorizationError,
    CampbellConfigurationError,
    CampbellDataError,
    CampbellSessionError,
)
from src.campbell_ai.models import (
    CapabilitiesResponse,
    FeedbackRequest,
    FeedbackResponse,
    HistoryResponse,
    InitializeRequest,
    InitializeResponse,
    MessageRequest,
    MessageResponse,
    SessionRequest,
)
from src.campbell_ai.service import CampbellAIService


logger = logging.getLogger("campbell_ai.api")

app = FastAPI(
    title="Campbell AI Internal API",
    description="Multi-agent API backed by dashboard identity and data contracts.",
    version="1.0.0",
)


@lru_cache(maxsize=1)
def get_service() -> CampbellAIService:
    return CampbellAIService()


def resolve_service(request: Request) -> CampbellAIService:
    return getattr(request.app.state, "service", None) or get_service()


def require_internal_token(
    x_campbell_token: str | None = Header(default=None, alias="X-Campbell-Token"),
) -> None:
    configured = get_campbell_settings().internal_token
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Campbell AI internal authentication is not configured",
        )
    if not x_campbell_token or not hmac.compare_digest(x_campbell_token, configured):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal credentials",
        )


def _translate_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CampbellAuthenticationError):
        return HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, CampbellAuthorizationError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, CampbellSessionError):
        return HTTPException(status_code=422, detail=str(exc))
    if isinstance(exc, CampbellDataError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, CampbellConfigurationError):
        return HTTPException(status_code=503, detail=str(exc))
    logger.exception("Unexpected Campbell AI API error")
    return HTTPException(status_code=500, detail="Campbell AI internal error")


@app.get("/api/v1/campbell-ai/health")
async def health() -> dict[str, object]:
    settings = get_campbell_settings()
    return {
        "status": "ok" if settings.enabled else "disabled",
        "profile": "campbell_agents",
        "reports": False,
        "visualizations": True,
        "chart_types": ["bar", "line", "pie", "pareto", "heatmap", "stacked_bar"],
        "explicit_time_windows": True,
        "feedback": True,
        "five_whys": True,
    }


@app.get(
    "/api/v1/campbell-ai/capabilities",
    response_model=CapabilitiesResponse,
    dependencies=[Depends(require_internal_token)],
)
async def capabilities() -> CapabilitiesResponse:
    return CapabilitiesResponse(
        agents=[
            "Gatekeeper",
            "Head Maintenance",
            "Planner",
            "Data Analyst Query",
            "Data Visualization Analyst",
            "Technical Expert",
        ]
    )


@app.post(
    "/api/v1/campbell-ai/initialize",
    response_model=InitializeResponse,
    dependencies=[Depends(require_internal_token)],
)
async def initialize_chat(
    body: InitializeRequest,
    service: CampbellAIService = Depends(resolve_service),
) -> InitializeResponse:
    try:
        return await service.initialize(body.username, body.company_id, body.session_id)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.post(
    "/api/v1/campbell-ai/message",
    response_model=MessageResponse,
    dependencies=[Depends(require_internal_token)],
)
async def send_message(
    body: MessageRequest,
    service: CampbellAIService = Depends(resolve_service),
) -> MessageResponse:
    try:
        return await service.send_message(
            body.username,
            body.company_id,
            body.session_id,
            body.message,
        )
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.post(
    "/api/v1/campbell-ai/history",
    response_model=HistoryResponse,
    dependencies=[Depends(require_internal_token)],
)
async def get_history(
    body: SessionRequest,
    service: CampbellAIService = Depends(resolve_service),
) -> HistoryResponse:
    try:
        return await service.history(body.username, body.company_id, body.session_id)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.post(
    "/api/v1/campbell-ai/feedback",
    response_model=FeedbackResponse,
    dependencies=[Depends(require_internal_token)],
)
async def submit_feedback(
    body: FeedbackRequest,
    service: CampbellAIService = Depends(resolve_service),
) -> FeedbackResponse:
    try:
        return await service.submit_feedback(
            body.username,
            body.company_id,
            body.session_id,
            body.message_id,
            body.rating,
            body.comment,
        )
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.delete(
    "/api/v1/campbell-ai/clear",
    dependencies=[Depends(require_internal_token)],
)
async def clear_conversation(
    body: SessionRequest,
    service: CampbellAIService = Depends(resolve_service),
) -> dict[str, str]:
    try:
        await service.clear(body.username, body.company_id, body.session_id)
        return {"detail": "Conversation cleared", "session_id": body.session_id}
    except Exception as exc:
        raise _translate_error(exc) from exc
