"""FastAPI entry point for Campbell AI internal consumers."""

from __future__ import annotations

import hmac
import json
import logging
from functools import lru_cache

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from src.campbell_ai.chart_registry import CHART_DEFINITIONS
from src.charts import CHART_KINDS
from src.campbell_ai.config import get_campbell_settings
from src.campbell_ai.errors import (
    CampbellAuthenticationError,
    CampbellAuthorizationError,
    CampbellBusyError,
    CampbellConfigurationError,
    CampbellDataError,
    CampbellSessionError,
    CampbellTimeoutError,
)
from src.campbell_ai.models import (
    CapabilitiesResponse,
    ConversationListResponse,
    ConversationsRequest,
    FeedbackRequest,
    FeedbackResponse,
    HistoryResponse,
    InitializeRequest,
    InitializeResponse,
    JobStatusRequest,
    JobStatusResponse,
    MessageRequest,
    MessageResponse,
    SessionRequest,
    SubmitMessageRequest,
)
from src.campbell_ai.service import CampbellAIService
from src.campbell_ai.temporal import current_temporal_context


logger = logging.getLogger("campbell_ai.api")

app = FastAPI(
    title="Campbell AI Internal API",
    description="Multi-agent API backed by dashboard identity and data contracts.",
    version="1.1.0",
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
    if isinstance(exc, CampbellBusyError):
        # 429 with Retry-After, so the caller knows this is load and not a fault, and
        # how long to wait before trying the same question again.
        return HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        )
    if isinstance(exc, CampbellTimeoutError):
        # 504, not 500: the request was valid and nothing is broken, this one question
        # simply outran its budget. The caller should narrow it, not just repeat it.
        return HTTPException(status_code=504, detail=str(exc))
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
        "chart_types": list(CHART_KINDS),
        "explicit_time_windows": True,
        "feedback": True,
        "five_whys": True,
        "streaming": settings.streaming_enabled,
        # Background answers with polling. Advertised so the dashboard can fall back to
        # the blocking endpoint when talking to an older API.
        "async_messages": True,
        "answer_timeout_seconds": settings.answer_timeout_seconds,
        # Surfaced so a deployment can assert it is not running several workers on
        # the process-local session store. The job registry is process-local too, so
        # this is the single thing to check before scaling out.
        "session_backend": settings.session_backend,
        "persistence": settings.persistence_enabled,
        "conversation_history": settings.persistence_enabled,
    }


@app.get(
    "/api/v1/campbell-ai/capabilities",
    response_model=CapabilitiesResponse,
    dependencies=[Depends(require_internal_token)],
)
async def capabilities(
    service: CampbellAIService = Depends(resolve_service),
) -> CapabilitiesResponse:
    settings = get_campbell_settings()
    return CapabilitiesResponse(
        agents=[
            "Gatekeeper",
            "Head Maintenance",
            "Planner",
            "Data Analyst Query",
            "Data Visualization Analyst",
            "Technical Expert",
            "Dashboard Navigation Guide",
        ],
        streaming=settings.streaming_enabled,
        session_backend=settings.session_backend,
        named_charts=[definition.chart_id for definition in CHART_DEFINITIONS],
        persistence=settings.persistence_enabled,
        conversation_history=settings.persistence_enabled,
        concurrency=_concurrency_stats(service),
        temporal_context=current_temporal_context(settings.timezone),
    )


def _concurrency_stats(service: object) -> dict[str, object]:
    """Load snapshot when the service exposes one; an empty dict otherwise.

    Read defensively because a test double or an alternative consumer is not required to
    implement admission control just to answer a capabilities call.
    """
    guard = getattr(service, "concurrency", None)
    stats = getattr(guard, "stats", None)
    if not callable(stats):
        return {}
    try:
        return dict(stats())
    except Exception:  # pragma: no cover - diagnostics must not break the endpoint
        return {}


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
    "/api/v1/campbell-ai/message/submit",
    response_model=JobStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_internal_token)],
)
async def submit_message(
    body: SubmitMessageRequest,
    service: CampbellAIService = Depends(resolve_service),
) -> JobStatusResponse:
    """Accept a question and answer it in the background.

    Returns as soon as the job is registered, so no client is ever holding a connection
    open for the length of an agent run. The answer is collected by polling `/status`,
    and survives the caller disconnecting, reloading, or resubmitting: the work belongs
    to the job, not to this request.
    """
    try:
        payload = await service.submit_message(
            body.username,
            body.company_id,
            body.session_id,
            body.message,
            body.client_message_id,
        )
        return JobStatusResponse(**payload)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.post(
    "/api/v1/campbell-ai/message/status",
    response_model=JobStatusResponse,
    dependencies=[Depends(require_internal_token)],
)
async def message_status(
    body: JobStatusRequest,
    service: CampbellAIService = Depends(resolve_service),
) -> JobStatusResponse:
    """Current state of a background answer.

    A job that is unknown or has aged out answers 404 rather than an error state: the
    distinction matters to the caller, because the recovery is to read the conversation
    history — where a completed answer already is — and not to ask again.
    """
    try:
        payload = await service.message_status(body.job_id)
    except Exception as exc:
        raise _translate_error(exc) from exc
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail="La consulta ya no está disponible; revisa el historial de la conversación",
        )
    return JobStatusResponse(**payload)


@app.post(
    "/api/v1/campbell-ai/message/cancel",
    dependencies=[Depends(require_internal_token)],
)
async def cancel_message(
    body: JobStatusRequest,
    service: CampbellAIService = Depends(resolve_service),
) -> dict[str, object]:
    """Stop a running answer so its slot is freed for someone else."""
    try:
        cancelled = await service.cancel_message(body.job_id)
    except Exception as exc:
        raise _translate_error(exc) from exc
    return {"cancelled": cancelled, "job_id": body.job_id}


@app.post(
    "/api/v1/campbell-ai/message/stream",
    dependencies=[Depends(require_internal_token)],
)
async def stream_message(
    body: MessageRequest,
    service: CampbellAIService = Depends(resolve_service),
) -> StreamingResponse:
    """Server-sent events for one exchange, ending with a `done` event.

    Errors raised before the first event become a normal HTTP status. Once the
    stream is open the status is already committed, so a later failure is delivered
    as an `error` event and the consumer must fall back to the blocking endpoint.
    """

    # Probe the first event eagerly so configuration and authorization problems still
    # produce a real HTTP error instead of a 200 carrying an error event.
    iterator = service.stream_message(
        body.username, body.company_id, body.session_id, body.message
    )
    try:
        first = await iterator.__anext__()
    except StopAsyncIteration:
        first = None
    except Exception as exc:
        raise _translate_error(exc) from exc

    async def publish_from_first():
        try:
            if first is not None:
                yield f"event: {first['type']}\ndata: {json.dumps(first, ensure_ascii=False)}\n\n"
            async for event in iterator:
                yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001 - surfaced to the client as an event
            logger.exception("Campbell AI stream failed mid-flight")
            detail = _translate_error(exc).detail
            payload = json.dumps({"type": "error", "detail": detail}, ensure_ascii=False)
            yield f"event: error\ndata: {payload}\n\n"

    return StreamingResponse(
        publish_from_first(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
    "/api/v1/campbell-ai/conversations",
    response_model=ConversationListResponse,
    dependencies=[Depends(require_internal_token)],
)
async def list_conversations(
    body: ConversationsRequest,
    service: CampbellAIService = Depends(resolve_service),
) -> ConversationListResponse:
    """Archived conversations for the caller's user and active company."""
    try:
        return await service.conversations(body.username, body.company_id)
    except Exception as exc:
        raise _translate_error(exc) from exc


@app.post(
    "/api/v1/campbell-ai/conversations/open",
    response_model=HistoryResponse,
    dependencies=[Depends(require_internal_token)],
)
async def open_conversation(
    body: SessionRequest,
    service: CampbellAIService = Depends(resolve_service),
) -> HistoryResponse:
    """Reopen an archived conversation so the user can keep talking in it."""
    try:
        return await service.open_conversation(
            body.username, body.company_id, body.session_id
        )
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
