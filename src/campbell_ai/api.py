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
from src.campbell_ai.config import DEFAULT_INTERNAL_TOKEN, get_campbell_settings
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
from src.campbell_ai.diagnostics import snapshot as diagnostics_snapshot, tail_log
from src.campbell_ai.janitor import (
    get_janitor,
    reset_janitor,
    start_janitor,
    touch_activity,
)
from src.campbell_ai.log_archive import (
    get_log_archiver,
    reset_log_archiver,
    start_log_archiver,
)
from src.campbell_ai.logging_setup import configure_api_logging
from src.campbell_ai.resources import reclaim


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


@app.on_event("startup")
async def warn_about_internal_auth() -> None:
    """Report the credential situation at boot, not at the first question.

    A misconfigured token is otherwise invisible until somebody sends a message and
    gets "Campbell AI no está configurado" — potentially long after the deployment that
    caused it, and with nothing in the logs connecting the two.
    """
    settings = get_campbell_settings()
    if not settings.internal_token:
        logger.error(
            "CAMPBELL_AI_INTERNAL_TOKEN está vacío: la API rechazará toda consulta "
            "con 503."
        )
    elif settings.internal_token == DEFAULT_INTERNAL_TOKEN:
        logger.warning(
            "Campbell AI está usando el token interno por defecto. Sirve para que el "
            "servicio funcione sin configuración extra, pero cualquier despliegue "
            "expuesto debería definir CAMPBELL_AI_INTERNAL_TOKEN."
        )


@app.on_event("startup")
async def start_background_maintenance() -> None:
    """Bring up this service's own log file, its archival and the memory janitor.

    All three run on a startup hook rather than at import time, and that is the reason
    this package can own its logging without affecting anything else: importing
    ``src.campbell_ai.*`` acquires no file handler and starts no thread, so only the
    process that actually serves this app - `uvicorn src.campbell_ai.api:app` - gets
    them. Tests and the dashboard import parts of this package and are untouched.
    """
    configure_api_logging()
    start_log_archiver()
    start_janitor()


@app.on_event("shutdown")
async def stop_background_maintenance() -> None:
    """Stop the helper threads so a container stop is not waiting on them."""
    reset_janitor()
    reset_log_archiver()


@app.middleware("http")
async def record_activity(request: Request, call_next):
    """Mark the process active so idle reclamation only fires when it truly is.

    Placed in middleware rather than in each endpoint so a route added later cannot
    forget to do it and quietly make the janitor believe the service is asleep while
    it is answering questions.
    """
    touch_activity()
    return await call_next(request)


@app.get("/api/v1/campbell-ai/health")
async def health() -> dict[str, object]:
    settings = get_campbell_settings()
    return {
        "status": "ok" if settings.enabled else "disabled",
        # Reported because `status` alone is misleading here: the service is running and
        # will still answer this endpoint, while every endpoint that matters returns
        # 503. A deployment check that only looks at `status` sees a healthy service
        # that cannot answer a single question.
        "internal_auth_configured": bool(settings.internal_token),
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


@app.get(
    "/api/v1/campbell-ai/diagnostics",
    dependencies=[Depends(require_internal_token)],
)
async def diagnostics(
    service: CampbellAIService = Depends(resolve_service),
) -> dict[str, object]:
    """Memory, caches, threads, logs and job counts in one payload.

    The endpoint that replaces console access. Read it when the service has been up for
    a while and feels slower than it did after a restart: `memory.rss_pct_of_limit`
    against `caches` tells you whether the footprint is cache (tunable) or not (a leak),
    and `janitor.last_reclaim.freed_mb` says whether dropping the caches even helped.
    """
    payload = diagnostics_snapshot()
    payload["concurrency"] = _concurrency_stats(service)
    payload["jobs"] = _job_stats(service)
    payload["session_backend"] = get_campbell_settings().session_backend
    return payload


@app.get(
    "/api/v1/campbell-ai/diagnostics/logs",
    dependencies=[Depends(require_internal_token)],
)
async def diagnostics_logs(lines: int = 200) -> dict[str, object]:
    """Tail of this process's log file, so an incident can be read from a browser."""
    return tail_log(lines)


@app.post(
    "/api/v1/campbell-ai/diagnostics/reclaim",
    dependencies=[Depends(require_internal_token)],
)
async def diagnostics_reclaim() -> dict[str, object]:
    """Drop every cache now and report what it freed.

    An escape hatch for the case where memory is high, the watermark has not tripped,
    and restarting the container is the only other option. Costs the next few requests
    a cold read; it is not destructive and touches no conversation state.
    """
    janitor = get_janitor()
    if janitor is not None:
        return janitor.force_reclaim("manual_endpoint")
    # No janitor (disabled by configuration): the caches are still reclaimable.
    return reclaim("manual_endpoint")


@app.post(
    "/api/v1/campbell-ai/diagnostics/archive-logs",
    dependencies=[Depends(require_internal_token)],
)
async def diagnostics_archive_logs() -> dict[str, object]:
    """Seal and ship the current log file to S3 immediately."""
    archiver = get_log_archiver()
    if archiver is None:
        return {"archived": 0, "detail": "log archiver is not running"}
    return archiver.run_cycle()


def _job_stats(service: object) -> dict[str, object]:
    """Job registry counts when the service exposes one; empty dict otherwise.

    Read defensively for the same reason as `_concurrency_stats`: a test double is not
    required to own a job registry to answer a diagnostics call.
    """
    registry = getattr(service, "jobs", None)
    stats = getattr(registry, "stats", None)
    if not callable(stats):
        return {}
    try:
        return dict(stats())
    except Exception:  # pragma: no cover - diagnostics must not break the endpoint
        return {}


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
        return await service.conversations(
            body.username, body.company_id, body.refresh
        )
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
