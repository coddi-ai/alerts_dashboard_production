"""Callbacks connecting the Campbell AI Dash view to its internal FastAPI API."""

from __future__ import annotations

import logging
from uuid import uuid4

import dash
from dash import ALL, Input, Output, State, callback_context, ctx, no_update
from dash.exceptions import PreventUpdate

from dashboard.auth import resolve_authenticated_username
from dashboard.campbell_ai.client import CampbellAPIClient, CampbellAPIClientError
from dashboard.campbell_ai.layout import ALERT_SUGGESTIONS, render_chat_history
from dashboard.campbell_ai.stream import streaming_enabled


logger = logging.getLogger(__name__)


def _company_id_from_state(company_state) -> str | None:
    value = (
        company_state.get("company_id")
        if isinstance(company_state, dict)
        else company_state
    )
    normalized = str(value or "").strip().lower()
    return normalized or None


def _identity_from_state(company_state) -> dict | None:
    if not isinstance(company_state, dict):
        return None
    identity = company_state.get("identity")
    return identity if isinstance(identity, dict) else None


def _updated_company_state(company_state, company_id: str | None) -> dict:
    return {
        "company_id": company_id,
        "identity": _identity_from_state(company_state),
    }


def _current_username(company_state=None) -> str | None:
    username = resolve_authenticated_username()
    if username:
        return username
    return resolve_authenticated_username(_identity_from_state(company_state))


def _strip_pending_messages(history: list[dict] | None) -> list[dict]:
    return [
        message
        for message in (history or [])
        if not str(message.get("message_id", "")).startswith("pending-")
    ]


def _pending_user_message(content: str) -> dict:
    return {
        "role": "user",
        "content": content,
        "message_id": f"pending-{uuid4().hex}",
        "pending": True,
    }


def _resolve_outgoing_message(triggered_id, typed_message) -> str | None:
    """Resolve button, Enter and suggested-question events into one message."""
    if (
        isinstance(triggered_id, dict)
        and triggered_id.get("type") == "campbell-ai-suggested-question"
    ):
        question = ALERT_SUGGESTIONS.get(triggered_id.get("question_id"))
        return str(question).strip() if question else None
    if triggered_id in ("campbell-ai-send", "campbell-ai-input"):
        return str(typed_message or "").strip()
    return None


def register_campbell_ai_callbacks(app: dash.Dash) -> None:
    """Register state, API and rendering callbacks for Campbell AI."""

    @app.callback(
        Output("campbell-ai-session-store", "data"),
        Output("campbell-ai-history-store", "data"),
        Output("campbell-ai-input", "value"),
        Output("campbell-ai-status", "children"),
        Output("campbell-ai-status", "color"),
        Output("campbell-ai-error", "children"),
        Output("campbell-ai-error", "is_open"),
        Output("campbell-ai-company-store", "data"),
        Output("campbell-ai-pending-message-store", "data"),
        Input("client-selector", "value"),
        Input("campbell-ai-send", "n_clicks"),
        Input("campbell-ai-input", "n_submit"),
        Input(
            {
                "type": "campbell-ai-suggested-question",
                "question_id": ALL,
            },
            "n_clicks",
        ),
        Input("campbell-ai-clear", "n_clicks"),
        State("campbell-ai-input", "value"),
        State("campbell-ai-session-store", "data"),
        State("campbell-ai-history-store", "data"),
        State("campbell-ai-company-store", "data"),
    )
    def synchronize_chat(
        selected_client,
        _send_clicks,
        _input_submits,
        _suggested_clicks,
        _clear_clicks,
        message,
        session_id,
        history,
        session_company,
    ):
        username = _current_username(session_company)
        company_id = str(selected_client or "").strip().lower()
        if not username:
            return (
                session_id,
                history or [],
                no_update,
                "Sesión expirada",
                "danger",
                "Vuelve a iniciar sesión en el dashboard.",
                True,
                session_company,
                None,
            )
        if not company_id:
            return (
                None,
                [],
                "",
                "Sin empresa",
                "warning",
                "Selecciona una empresa para iniciar Campbell AI.",
                True,
                _updated_company_state(session_company, None),
                None,
            )

        client = CampbellAPIClient.from_env()
        triggered_id = callback_context.triggered_id
        stored_company_id = _company_id_from_state(session_company)
        try:
            company_changed = bool(
                stored_company_id and stored_company_id != company_id
            )
            if triggered_id == "campbell-ai-clear":
                if not session_id or company_changed:
                    initialized = client.initialize(username, company_id)
                    session_id = initialized["session_id"]
                else:
                    client.clear(username, company_id, session_id)
                return (
                    session_id,
                    [],
                    "",
                    f"Listo · {company_id.upper()}",
                    "success",
                    "",
                    False,
                    _updated_company_state(session_company, company_id),
                    None,
                )

            normalized_message = _resolve_outgoing_message(triggered_id, message)
            if normalized_message is not None:
                if not normalized_message:
                    return (
                        session_id,
                        history or [],
                        no_update,
                        f"Listo · {company_id.upper()}",
                        "success",
                        "Escribe una consulta antes de enviarla.",
                        True,
                        _updated_company_state(session_company, company_id),
                        None,
                    )
                if not session_id or company_changed:
                    session_id = None
                    history = []
                optimistic_history = _strip_pending_messages(history)
                optimistic_history.append(_pending_user_message(normalized_message))
                return (
                    session_id,
                    optimistic_history,
                    "",
                    "Pensando...",
                    "info",
                    "",
                    False,
                    _updated_company_state(session_company, company_id),
                    {
                        "message": normalized_message,
                        "company_id": company_id,
                        "session_id": session_id,
                        # Streaming needs an existing session id, because the browser
                        # cannot create one; the first message of a thread stays blocking.
                        "stream": bool(streaming_enabled() and session_id),
                    },
                )


            reusable_session = (
                session_id if stored_company_id == company_id else None
            )
            initialized = client.initialize(username, company_id, reusable_session)
            resolved_session = initialized["session_id"]
            restored_history: list[dict] = []
            if reusable_session:
                restored_history = client.history(
                    username, company_id, resolved_session
                ).get("messages", [])
            return (
                resolved_session,
                restored_history,
                "",
                f"Listo · {company_id.upper()}",
                "success",
                "",
                False,
                _updated_company_state(session_company, company_id),
                None,
            )
        except CampbellAPIClientError as exc:
            logger.warning("Campbell AI request failed: %s", exc)
            if stored_company_id and stored_company_id != company_id:
                session_id, history = None, []
            return (
                session_id,
                history or [],
                no_update,
                "No disponible",
                "danger",
                str(exc),
                True,
                session_company,
                None,
            )
        except Exception:
            logger.exception("Unexpected Campbell AI Dash callback error")
            return (
                session_id,
                history or [],
                no_update,
                "Error",
                "danger",
                "Ocurrió un error inesperado al usar Campbell AI.",
                True,
                session_company,
                None,
            )

    @app.callback(
        Output("campbell-ai-session-store", "data", allow_duplicate=True),
        Output("campbell-ai-history-store", "data", allow_duplicate=True),
        Output("campbell-ai-status", "children", allow_duplicate=True),
        Output("campbell-ai-status", "color", allow_duplicate=True),
        Output("campbell-ai-error", "children", allow_duplicate=True),
        Output("campbell-ai-error", "is_open", allow_duplicate=True),
        Output("campbell-ai-pending-message-store", "data", allow_duplicate=True),
        Output("campbell-ai-company-store", "data", allow_duplicate=True),
        Input("campbell-ai-pending-message-store", "data"),
        State("campbell-ai-session-store", "data"),
        State("campbell-ai-history-store", "data"),
        State("campbell-ai-company-store", "data"),
        prevent_initial_call=True,
        running=[
            (Output("campbell-ai-send", "disabled"), True, False),
            (Output("campbell-ai-input", "disabled"), True, False),
            (Output("campbell-ai-clear", "disabled"), True, False),
        ],
    )
    def process_pending_message(pending, session_id, history, session_company):
        if not isinstance(pending, dict) or not pending.get("message"):
            raise PreventUpdate
        if pending.get("stream"):
            # The browser is streaming this one; finalize_stream re-dispatches here
            # with stream=False if the stream fails.
            raise PreventUpdate

        company_id = str(
            pending.get("company_id") or _company_id_from_state(session_company) or ""
        ).strip().lower()
        username = _current_username(session_company)
        if not username:
            return (
                session_id,
                history or [],
                "Sesión expirada",
                "danger",
                "Vuelve a iniciar sesión en el dashboard.",
                True,
                None,
                session_company,
            )
        if not company_id:
            return (
                None,
                [],
                "Sin empresa",
                "warning",
                "Selecciona una empresa para iniciar Campbell AI.",
                True,
                None,
                _updated_company_state(session_company, None),
            )

        client = CampbellAPIClient.from_env()
        try:
            active_session_id = str(pending.get("session_id") or session_id or "").strip()
            # Initialization validates data availability and mints a session id; once a
            # session exists, /message alone is enough and avoids two extra round trips.
            if not active_session_id:
                active_session_id = client.initialize(username, company_id)["session_id"]
            result = client.send_message(
                username,
                company_id,
                active_session_id,
                str(pending["message"]),
            )
            updated_history = result.get("messages")
            if not updated_history:
                updated_history = client.history(
                    username, company_id, result["session_id"]
                ).get("messages", [])
            return (
                result["session_id"],
                updated_history,
                f"Listo · {company_id.upper()}",
                "success",
                "",
                False,
                None,
                _updated_company_state(session_company, company_id),
            )
        except CampbellAPIClientError as exc:
            logger.warning("Campbell AI pending request failed: %s", exc)
            return (
                session_id,
                history or [],
                "No disponible",
                "danger",
                str(exc),
                True,
                None,
                session_company,
            )
        except Exception:
            logger.exception("Unexpected Campbell AI pending callback error")
            return (
                session_id,
                history or [],
                "Error",
                "danger",
                "Ocurrió un error inesperado al usar Campbell AI.",
                True,
                None,
                session_company,
            )

    @app.callback(
        Output("campbell-ai-messages", "children"),
        Input("campbell-ai-history-store", "data"),
        Input("campbell-ai-feedback-store", "data"),
    )
    def display_history(history, feedback):
        return render_chat_history(history, feedback)

    # --- Streaming -------------------------------------------------------------
    # The browser reads the SSE proxy so text appears while the agents work. Dash
    # still owns the final render, and a failed stream falls back to the blocking
    # request instead of losing the question.

    app.clientside_callback(
        "function(pending) { return window.dash_clientside.campbellAiStream.start(pending); }",
        Output("campbell-ai-stream-poll", "n_intervals"),
        Input("campbell-ai-pending-message-store", "data"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("campbell-ai-stream-poll", "disabled"),
        Input("campbell-ai-pending-message-store", "data"),
    )
    def toggle_stream_poll(pending):
        """Poll only while a streamed message is in flight."""
        return not (isinstance(pending, dict) and pending.get("stream"))

    app.clientside_callback(
        "function(_ticks) { return window.dash_clientside.campbellAiStream.collect(); }",
        Output("campbell-ai-stream-store", "data"),
        Input("campbell-ai-stream-poll", "n_intervals"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("campbell-ai-history-store", "data", allow_duplicate=True),
        Output("campbell-ai-session-store", "data", allow_duplicate=True),
        Output("campbell-ai-status", "children", allow_duplicate=True),
        Output("campbell-ai-status", "color", allow_duplicate=True),
        Output("campbell-ai-pending-message-store", "data", allow_duplicate=True),
        Input("campbell-ai-stream-store", "data"),
        State("campbell-ai-pending-message-store", "data"),
        State("campbell-ai-history-store", "data"),
        State("campbell-ai-session-store", "data"),
        prevent_initial_call=True,
    )
    def finalize_stream(result, pending, history, session_id):
        """Apply a finished stream, or hand the message back to the blocking path."""
        if not isinstance(result, dict):
            raise PreventUpdate
        if not result.get("ok"):
            if not (isinstance(pending, dict) and pending.get("message")):
                raise PreventUpdate
            logger.info("Campbell AI stream unavailable; using the blocking request")
            return (
                no_update,
                no_update,
                "Pensando...",
                "info",
                {**pending, "stream": False},
            )

        event = result.get("event") or {}
        messages = event.get("messages") or []
        company_id = str(event.get("company_id") or "").upper()
        return (
            messages if messages else _strip_pending_messages(history),
            event.get("session_id") or session_id,
            f"Listo · {company_id}" if company_id else "Listo",
            "success",
            None,
        )

    @app.callback(
        Output("campbell-ai-feedback-store", "data"),
        Input(
            {
                "type": "campbell-ai-feedback-button",
                "message_id": ALL,
                "rating": ALL,
            },
            "n_clicks",
        ),
        State("campbell-ai-feedback-store", "data"),
        State("campbell-ai-session-store", "data"),
        State("campbell-ai-company-store", "data"),
        prevent_initial_call=True,
    )
    def submit_response_feedback(_clicks, feedback, session_id, company_id):
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict):
            raise PreventUpdate
        message_id = str(triggered.get("message_id", "")).strip()
        rating = str(triggered.get("rating", "")).strip()
        click_count = ctx.triggered[0].get("value") if ctx.triggered else 0
        if not click_count or not message_id or rating not in {"positive", "negative"}:
            raise PreventUpdate

        resolved_company_id = _company_id_from_state(company_id)
        username = _current_username(company_id)
        if not username or not resolved_company_id or not session_id:
            raise PreventUpdate
        current = dict(feedback or {})
        if message_id in current:
            raise PreventUpdate
        try:
            CampbellAPIClient.from_env().submit_feedback(
                username,
                resolved_company_id,
                str(session_id),
                message_id,
                rating,
            )
        except CampbellAPIClientError as exc:
            logger.warning("Campbell AI feedback failed: %s", exc)
            raise PreventUpdate from exc
        current[message_id] = rating
        return current
