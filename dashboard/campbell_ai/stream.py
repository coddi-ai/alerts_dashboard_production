"""Same-origin SSE proxy so the browser can stream Campbell AI answers.

A standard Dash callback returns only when it finishes, so progressive text needs
a route the browser can read directly. This blueprint keeps the trust boundary
intact:

- the browser never learns the internal API URL or token;
- identity comes from the signed Dash session, not from the request body;
- the company is re-validated by the API for every event stream.
"""

from __future__ import annotations

import json
import logging
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from flask import Blueprint, Response, request

from dashboard.auth import resolve_authenticated_username


logger = logging.getLogger(__name__)

campbell_stream = Blueprint("campbell_ai_stream", __name__)

# Upper bound on a single answer; the API's own timeout is the real limit.
STREAM_TIMEOUT_SECONDS = float(os.getenv("CAMPBELL_AI_STREAM_TIMEOUT_SECONDS", "300"))


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def streaming_enabled() -> bool:
    return os.getenv("CAMPBELL_AI_STREAMING", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


@campbell_stream.route("/campbell-ai/stream", methods=["POST"])
@campbell_stream.route("/<path:_prefix>/campbell-ai/stream", methods=["POST"])
def stream(_prefix: str = "") -> Response:
    """Relay the API's event stream to the browser under the Dash session."""
    if not streaming_enabled():
        return Response(
            _sse("error", {"type": "error", "detail": "Streaming deshabilitado"}),
            mimetype="text/event-stream",
            status=200,
        )

    username = resolve_authenticated_username()
    if not username:
        return Response(
            _sse("error", {"type": "error", "detail": "Sesión expirada"}),
            mimetype="text/event-stream",
            status=200,
        )

    body = request.get_json(silent=True) or {}
    company_id = str(body.get("company_id", "")).strip().lower()
    session_id = str(body.get("session_id", "")).strip()
    message = str(body.get("message", "")).strip()
    if not (company_id and session_id and message):
        return Response(
            _sse("error", {"type": "error", "detail": "Solicitud incompleta"}),
            mimetype="text/event-stream",
            status=200,
        )

    token = os.getenv("CAMPBELL_AI_INTERNAL_TOKEN", "").strip()
    base_url = os.getenv("CAMPBELL_AI_API_URL", "http://127.0.0.1:8000").rstrip("/")
    if not token:
        return Response(
            _sse(
                "error",
                {"type": "error", "detail": "Campbell AI no tiene credencial interna"},
            ),
            mimetype="text/event-stream",
            status=200,
        )

    # The username is taken from the signed session, never from the request body.
    payload = json.dumps(
        {
            "username": username,
            "company_id": company_id,
            "session_id": session_id,
            "message": message,
        }
    ).encode("utf-8")
    upstream = Request(
        f"{base_url}/api/v1/campbell-ai/message/stream",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "X-Campbell-Token": token,
        },
        method="POST",
    )

    def relay():
        try:
            with urlopen(upstream, timeout=STREAM_TIMEOUT_SECONDS) as response:
                for raw in response:
                    line = raw.decode("utf-8", errors="replace")
                    yield line
        except HTTPError as exc:
            detail = "Campbell AI rechazó la solicitud de streaming"
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail", detail)
            except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                pass
            logger.warning("Campbell AI stream rejected: %s", exc.code)
            yield _sse("error", {"type": "error", "detail": detail})
        except (URLError, TimeoutError) as exc:
            logger.warning("Campbell AI stream unreachable: %s", exc)
            yield _sse(
                "error",
                {"type": "error", "detail": "No fue posible conectar con Campbell AI"},
            )

    return Response(
        relay(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def register_campbell_ai_stream(app) -> None:
    """Attach the SSE proxy to the Dash Flask server."""
    app.server.register_blueprint(campbell_stream)
