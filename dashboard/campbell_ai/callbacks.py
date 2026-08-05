"""Callbacks connecting the Campbell AI Dash view to its internal FastAPI API."""

from __future__ import annotations

import logging
from uuid import uuid4

import dash
from dash import ALL, Input, Output, State, callback_context, ctx, no_update
from dash.exceptions import PreventUpdate

from dashboard.auth import resolve_authenticated_username
from dashboard.campbell_ai.client import CampbellAPIClient, CampbellAPIClientError
from dashboard.campbell_ai.layout import (
    ALERT_SUGGESTIONS,
    CONVERSATION_HISTORY_LAYOUT,
    render_chat_history,
    render_conversation_list,
    service_error_content,
    unavailable_placeholder,
)
from dashboard.campbell_ai.stream import streaming_enabled


logger = logging.getLogger(__name__)

# Both dbc.Collapse (inline) and dbc.Offcanvas (sidebar) expose "is_open", so the
# same toggle callback works for either — only the target id depends on which
# layout.CONVERSATION_HISTORY_LAYOUT picked at import time.
_HISTORY_PANEL_ID = (
    "campbell-ai-history-offcanvas"
    if CONVERSATION_HISTORY_LAYOUT == "sidebar"
    else "campbell-ai-history-collapse"
)


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


def _failure_state(
    kind: str,
    title: str,
    guidance: str = "",
    retryable: bool = False,
    question: str = "",
) -> dict:
    """One shape for every failure, so the view renders them uniformly."""
    return {
        "kind": kind,
        "title": title,
        "guidance": guidance,
        "retryable": bool(retryable),
        "question": question,
    }


def _failure_from_client_error(
    exc: CampbellAPIClientError, question: str = ""
) -> dict:
    """Carry the client's per-cause classification into the view."""
    return _failure_state(
        exc.kind,
        exc.title,
        getattr(exc, "guidance", ""),
        retryable=getattr(exc, "retryable", False),
        question=question,
    )


def _failed_question(failure) -> str:
    if not isinstance(failure, dict):
        return ""
    return str(failure.get("question") or "").strip()


def _status_label(exc: CampbellAPIClientError) -> str:
    """Badge text, distinguishing a dead service from a rejected request."""
    labels = {
        "unreachable": "Servicio caído",
        "timeout": "Tiempo excedido",
        "credentials": "Mal configurado",
        "not_configured": "Sin configurar",
        "forbidden": "Sin acceso",
        "unavailable": "Datos no disponibles",
        "invalid_request": "Solicitud inválida",
        "server_error": "Error del servicio",
        # Saturation is temporary and self-resolving; it is not a fault.
        "busy": "Servicio ocupado",
    }
    return labels.get(getattr(exc, "kind", ""), "No disponible")


def _stored_session_company(session_company) -> str | None:
    """Company the session-storage conversation belongs to."""
    normalized = str(session_company or "").strip().lower()
    return normalized or None


# Kinds where sending another message cannot possibly work, so the composer is
# disabled instead of inviting the user to repeat a failing action.
_BLOCKING_FAILURES = {
    "unreachable",
    "credentials",
    "not_configured",
    "server_error",
    "session",
    "no_company",
}


def register_campbell_ai_callbacks(app: dash.Dash) -> None:
    """Register state, API and rendering callbacks for Campbell AI."""

    @app.callback(
        Output("campbell-ai-session-store", "data"),
        Output("campbell-ai-history-store", "data"),
        Output("campbell-ai-input", "value"),
        Output("campbell-ai-status", "children"),
        Output("campbell-ai-status", "color"),
        Output("campbell-ai-failure-store", "data"),
        Output("campbell-ai-company-store", "data"),
        Output("campbell-ai-pending-message-store", "data"),
        Output("campbell-ai-session-company", "data"),
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
        Input("campbell-ai-retry", "n_clicks"),
        State("campbell-ai-input", "value"),
        State("campbell-ai-session-store", "data"),
        State("campbell-ai-history-store", "data"),
        State("campbell-ai-company-store", "data"),
        State("campbell-ai-failure-store", "data"),
        State("campbell-ai-session-company", "data"),
    )
    def synchronize_chat(
        selected_client,
        _send_clicks,
        _input_submits,
        _suggested_clicks,
        _clear_clicks,
        _retry_clicks,
        message,
        session_id,
        history,
        session_company,
        failure,
        stored_session_company,
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
                _failure_state(
                    "session",
                    "Tu sesión del dashboard expiró",
                    "Vuelve a iniciar sesión para seguir usando Campbell AI.",
                ),
                session_company,
                None,
                stored_session_company,
            )
        if not company_id:
            return (
                None,
                [],
                "",
                "Sin empresa",
                "warning",
                _failure_state(
                    "no_company",
                    "No hay empresa seleccionada",
                    "Elige una empresa en el selector para iniciar Campbell AI.",
                ),
                _updated_company_state(session_company, None),
                None,
                None,
            )

        client = CampbellAPIClient.from_env()
        triggered_id = callback_context.triggered_id
        # The in-memory company store is empty on every remount, so returning to this
        # tab would look like a company change and discard the thread. The session-scoped
        # copy is what survives navigation and decides whether the session is reusable.
        stored_company_id = _company_id_from_state(session_company) or (
            _stored_session_company(stored_session_company)
        )
        # A retry replays the question the failure preserved, so the user does not
        # have to retype it; with no saved question it just re-initializes.
        if triggered_id == "campbell-ai-retry":
            saved = _failed_question(failure)
            if saved:
                optimistic = _strip_pending_messages(history)
                optimistic.append(_pending_user_message(saved))
                return (
                    session_id,
                    optimistic,
                    no_update,
                    "Reintentando…",
                    "info",
                    None,
                    _updated_company_state(session_company, company_id),
                    {
                        "message": saved,
                        "company_id": company_id,
                        "session_id": session_id,
                        "stream": bool(streaming_enabled() and session_id),
                    },
                    company_id,
                )
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
                    None,
                    _updated_company_state(session_company, company_id),
                    None,
                    company_id,
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
                        _failure_state(
                            "empty_message",
                            "Escribe una consulta antes de enviarla",
                            "",
                        ),
                        _updated_company_state(session_company, company_id),
                        None,
                        company_id,
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
                    None,
                    _updated_company_state(session_company, company_id),
                    {
                        "message": normalized_message,
                        "company_id": company_id,
                        "session_id": session_id,
                        # Streaming needs an existing session id, because the browser
                        # cannot create one; the first message of a thread stays blocking.
                        "stream": bool(streaming_enabled() and session_id),
                    },
                    company_id,
                )


            # No stored company means a fresh mount, not a company change: the session id
            # in session storage still belongs to this company unless it says otherwise.
            reusable_session = (
                session_id
                if session_id and (not stored_company_id or stored_company_id == company_id)
                else None
            )
            initialized = client.initialize(username, company_id, reusable_session)
            resolved_session = initialized["session_id"]
            restored_history: list[dict] = []
            if reusable_session:
                restored_history = client.history(
                    username, company_id, resolved_session
                ).get("messages", [])
                # The service may have restarted with persistence off; in that case the
                # browser still holds the thread and losing it would be gratuitous.
                if not restored_history:
                    restored_history = _strip_pending_messages(history)
            return (
                resolved_session,
                restored_history,
                "",
                f"Listo · {company_id.upper()}",
                "success",
                None,
                _updated_company_state(session_company, company_id),
                None,
                company_id,
            )
        except CampbellAPIClientError as exc:
            logger.warning(
                "Campbell AI initialization failed (%s): %s", exc.kind, exc
            )
            if stored_company_id and stored_company_id != company_id:
                session_id, history = None, []
            return (
                session_id,
                history or [],
                no_update,
                _status_label(exc),
                "danger",
                _failure_from_client_error(exc),
                session_company,
                None,
                stored_session_company,
            )
        except Exception:
            logger.exception("Unexpected Campbell AI Dash callback error")
            return (
                session_id,
                history or [],
                no_update,
                "Error",
                "danger",
                _failure_state(
                    "unexpected",
                    "Ocurrió un error inesperado al usar Campbell AI",
                    "Reintenta la operación. Si persiste, avisa al equipo de plataforma.",
                    retryable=True,
                ),
                session_company,
                None,
                stored_session_company,
            )

    @app.callback(
        Output("campbell-ai-session-store", "data", allow_duplicate=True),
        Output("campbell-ai-history-store", "data", allow_duplicate=True),
        Output("campbell-ai-status", "children", allow_duplicate=True),
        Output("campbell-ai-status", "color", allow_duplicate=True),
        Output("campbell-ai-failure-store", "data", allow_duplicate=True),
        Output("campbell-ai-pending-message-store", "data", allow_duplicate=True),
        Output("campbell-ai-company-store", "data", allow_duplicate=True),
        Output("campbell-ai-session-company", "data", allow_duplicate=True),
        Input("campbell-ai-pending-message-store", "data"),
        State("campbell-ai-session-store", "data"),
        State("campbell-ai-history-store", "data"),
        State("campbell-ai-company-store", "data"),
        prevent_initial_call=True,
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
                _failure_state(
                    "session",
                    "Tu sesión del dashboard expiró",
                    "Vuelve a iniciar sesión para seguir usando Campbell AI.",
                    question=str(pending.get("message") or ""),
                ),
                None,
                session_company,
                no_update,
            )
        if not company_id:
            return (
                None,
                [],
                "Sin empresa",
                "warning",
                _failure_state(
                    "no_company",
                    "No hay empresa seleccionada",
                    "Elige una empresa en el selector para iniciar Campbell AI.",
                ),
                None,
                _updated_company_state(session_company, None),
                None,
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
                None,
                None,
                _updated_company_state(session_company, company_id),
                company_id,
            )
        except CampbellAPIClientError as exc:
            logger.warning("Campbell AI message failed (%s): %s", exc.kind, exc)
            return (
                session_id,
                # Drop the optimistic bubble: the exchange did not happen.
                _strip_pending_messages(history),
                _status_label(exc),
                "danger",
                _failure_from_client_error(exc, question=str(pending.get("message") or "")),
                None,
                session_company,
                no_update,
            )
        except Exception:
            logger.exception("Unexpected Campbell AI pending callback error")
            return (
                session_id,
                _strip_pending_messages(history),
                "Error",
                "danger",
                _failure_state(
                    "unexpected",
                    "Ocurrió un error inesperado al procesar la consulta",
                    "Reintenta. Si persiste, avisa al equipo de plataforma.",
                    retryable=True,
                    question=str(pending.get("message") or ""),
                ),
                None,
                session_company,
                no_update,
            )

    @app.callback(
        Output("campbell-ai-error-body", "children"),
        Output("campbell-ai-error", "is_open"),
        Output("campbell-ai-error", "color"),
        Output("campbell-ai-retry", "style"),
        Output("campbell-ai-retry-label", "children"),
        Input("campbell-ai-failure-store", "data"),
    )
    def render_failure(failure):
        """Single place that turns a failure into a message, guidance and a retry.

        The retry button itself is a permanent fixture of the layout (see
        _retry_button in layout.py) — only its visibility and label change here.
        """
        hidden = {"display": "none"}
        if not isinstance(failure, dict) or not failure.get("title"):
            return [], False, "danger", hidden, "Reintentar"
        # A missing company or an empty message is the user's next step, not a fault.
        color = "warning" if failure.get("kind") in {"no_company", "empty_message"} else "danger"
        pending_question = _failed_question(failure)
        retryable = bool(failure.get("retryable"))
        return (
            service_error_content(
                title=str(failure.get("title", "")),
                guidance=str(failure.get("guidance", "")),
                pending_question=pending_question,
            ),
            True,
            color,
            {"display": "inline-block"} if retryable else hidden,
            "Reintentar consulta" if pending_question else "Reintentar",
        )

    @app.callback(
        Output("campbell-ai-send", "disabled", allow_duplicate=True),
        Output("campbell-ai-input", "disabled", allow_duplicate=True),
        Output("campbell-ai-clear", "disabled", allow_duplicate=True),
        Output("campbell-ai-input", "placeholder"),
        Input("campbell-ai-failure-store", "data"),
        Input("campbell-ai-pending-message-store", "data"),
        prevent_initial_call=True,
    )
    def gate_composer(failure, pending):
        """Block composing while the service cannot answer, or a message is in flight.

        This is the *only* place that disables the composer. It used to share the
        job with process_pending_message's `running=[...]` clause, which disabled
        the same Outputs for the duration of that one callback's execution — but
        `running=` can't help while a message streams, since that callback exits
        via PreventUpdate almost instantly for a streamed pending message, and
        worse, its own "finished, re-enable" write (queued the instant it starts)
        can land at the client *after* this callback's "disabled" write, silently
        re-enabling the composer while the request is still running. Judging
        campbell-ai-pending-message-store's own lifecycle here — set when a
        message starts, cleared to None only once it truly resolves, in both the
        streamed and blocking paths — is a single source of truth with nothing
        left to race it.
        """
        kind = failure.get("kind") if isinstance(failure, dict) else None
        blocked = kind in _BLOCKING_FAILURES
        in_flight = isinstance(pending, dict) and bool(pending.get("message"))
        disabled = blocked or in_flight
        placeholder = (
            "Campbell AI no está disponible en este momento"
            if blocked
            else "Pregúntame sobre mantenimiento o solicita un gráfico…"
        )
        return disabled, disabled, disabled, placeholder

    @app.callback(
        Output("campbell-ai-messages", "children"),
        Input("campbell-ai-history-store", "data"),
        Input("campbell-ai-feedback-store", "data"),
        Input("campbell-ai-failure-store", "data"),
    )
    def display_history(history, feedback, failure):
        kind = failure.get("kind") if isinstance(failure, dict) else None
        # With no conversation and a dead service, an empty panel reads as a broken
        # page; state the situation instead.
        if not history and kind in _BLOCKING_FAILURES:
            return [unavailable_placeholder(str(failure.get("title", "")))]
        return render_chat_history(history, feedback)

    # Auto-scroll to the newest message, both for a message just sent and for a
    # conversation just loaded (open_archived_conversation goes through the same
    # history-store -> display_history -> campbell-ai-messages.children path).
    # A pure DOM side effect, so the Output is a throwaway store nothing reads.
    app.clientside_callback(
        """
        function(_children) {
            var el = document.getElementById("campbell-ai-scroll-container");
            if (el) { el.scrollTop = el.scrollHeight; }
            return window.dash_clientside.no_update;
        }
        """,
        Output("campbell-ai-scroll-trigger", "data"),
        Input("campbell-ai-messages", "children"),
        prevent_initial_call=True,
    )

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
        prevent_initial_call=True,
    )
    def toggle_stream_poll(pending):
        """Poll only while a streamed message is in flight.

        Locking the composer for that same duration is gate_composer's job (see
        its docstring for why both conditions have to live in one callback).
        """
        return not (isinstance(pending, dict) and bool(pending.get("stream")))

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
        # Stored as a record rather than a bare rating so the view knows whether the
        # written comment was already sent.
        current[message_id] = {"rating": rating, "comment": False}
        return current

    @app.callback(
        Output("campbell-ai-feedback-store", "data", allow_duplicate=True),
        Input(
            {"type": "campbell-ai-feedback-comment-send", "message_id": ALL},
            "n_clicks",
        ),
        State({"type": "campbell-ai-feedback-comment", "message_id": ALL}, "value"),
        State("campbell-ai-feedback-store", "data"),
        State("campbell-ai-session-store", "data"),
        State("campbell-ai-company-store", "data"),
        prevent_initial_call=True,
    )
    def submit_feedback_comment(_clicks, comments, feedback, session_id, company_id):
        """Send the written reason behind a vote, as a second feedback event."""
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict) or not ctx.triggered:
            raise PreventUpdate
        if not ctx.triggered[0].get("value"):
            raise PreventUpdate
        message_id = str(triggered.get("message_id", "")).strip()
        current = dict(feedback or {})
        entry = current.get(message_id)
        rating = (
            str(entry.get("rating", "")) if isinstance(entry, dict) else str(entry or "")
        )
        # A comment only means something attached to a vote, and the API requires one.
        if not message_id or rating not in {"positive", "negative"}:
            raise PreventUpdate
        if isinstance(entry, dict) and entry.get("comment"):
            raise PreventUpdate

        comment = ""
        for state in ctx.states_list[0] if ctx.states_list else []:
            state_id = state.get("id") or {}
            if str(state_id.get("message_id", "")) == message_id:
                comment = str(state.get("value") or "").strip()
                break
        if not comment:
            raise PreventUpdate

        resolved_company_id = _company_id_from_state(company_id)
        username = _current_username(company_id)
        if not username or not resolved_company_id or not session_id:
            raise PreventUpdate
        try:
            CampbellAPIClient.from_env().submit_feedback(
                username,
                resolved_company_id,
                str(session_id),
                message_id,
                rating,
                comment,
            )
        except CampbellAPIClientError as exc:
            logger.warning("Campbell AI feedback comment failed: %s", exc)
            raise PreventUpdate from exc
        current[message_id] = {"rating": rating, "comment": True}
        return current

    # --- Conversation history --------------------------------------------------
    # Conversations are archived per user, so a thread is reachable after the session
    # expires, after leaving this tab, and after the service restarts.

    @app.callback(
        Output(_HISTORY_PANEL_ID, "is_open"),
        Input("campbell-ai-history-toggle", "n_clicks"),
        State(_HISTORY_PANEL_ID, "is_open"),
        prevent_initial_call=True,
    )
    def toggle_conversation_history(_clicks, is_open):
        return not bool(is_open)

    @app.callback(
        Output("campbell-ai-conversations-store", "data"),
        Input("campbell-ai-session-store", "data"),
        Input("campbell-ai-history-store", "data"),
        Input("campbell-ai-refresh-conversations", "n_clicks"),
        State("campbell-ai-company-store", "data"),
        State("campbell-ai-conversations-store", "data"),
    )
    def refresh_conversations(_session_id, _history, _clicks, company_state, current):
        """Reload the archived list after every exchange, so titles stay current."""
        company_id = _company_id_from_state(company_state)
        username = _current_username(company_state)
        if not username or not company_id:
            return []
        try:
            payload = CampbellAPIClient.from_env().list_conversations(
                username, company_id
            )
        except CampbellAPIClientError as exc:
            # The list is a convenience; a failure here must not disturb the chat.
            logger.info("Campbell AI conversation list unavailable (%s)", exc.kind)
            return current or []
        return payload.get("conversations", [])

    @app.callback(
        Output("campbell-ai-conversation-list", "children"),
        Input("campbell-ai-conversations-store", "data"),
        Input("campbell-ai-session-store", "data"),
    )
    def display_conversation_list(conversations, session_id):
        return render_conversation_list(conversations, session_id)

    @app.callback(
        Output("campbell-ai-session-store", "data", allow_duplicate=True),
        Output("campbell-ai-history-store", "data", allow_duplicate=True),
        Output("campbell-ai-session-company", "data", allow_duplicate=True),
        Output("campbell-ai-status", "children", allow_duplicate=True),
        Output("campbell-ai-status", "color", allow_duplicate=True),
        Output("campbell-ai-failure-store", "data", allow_duplicate=True),
        Output("campbell-ai-feedback-store", "data", allow_duplicate=True),
        Output(_HISTORY_PANEL_ID, "is_open", allow_duplicate=True),
        Input({"type": "campbell-ai-open-conversation", "session_id": ALL}, "n_clicks"),
        State("campbell-ai-company-store", "data"),
        prevent_initial_call=True,
    )
    def open_archived_conversation(_clicks, company_state):
        """Reopen a previous conversation and continue it in place."""
        triggered = ctx.triggered_id
        if not isinstance(triggered, dict) or not ctx.triggered:
            raise PreventUpdate
        if not ctx.triggered[0].get("value"):
            raise PreventUpdate
        session_id = str(triggered.get("session_id", "")).strip()
        company_id = _company_id_from_state(company_state)
        username = _current_username(company_state)
        if not session_id or not username or not company_id:
            raise PreventUpdate
        try:
            payload = CampbellAPIClient.from_env().open_conversation(
                username, company_id, session_id
            )
        except CampbellAPIClientError as exc:
            logger.warning("Campbell AI could not open a conversation: %s", exc)
            return (
                no_update,
                no_update,
                no_update,
                _status_label(exc),
                "danger",
                _failure_from_client_error(exc),
                no_update,
                no_update,
            )
        return (
            payload.get("session_id") or session_id,
            payload.get("messages", []),
            company_id,
            f"Listo · {company_id.upper()}",
            "success",
            None,
            # Ratings belong to the thread that was open; the reopened one has its own.
            {},
            # Picking a conversation is the intent to read it, not to keep browsing
            # the list — close the panel so it doesn't cover the chat that just loaded.
            False,
        )

    @app.callback(
        Output("campbell-ai-session-store", "data", allow_duplicate=True),
        Output("campbell-ai-history-store", "data", allow_duplicate=True),
        Output("campbell-ai-session-company", "data", allow_duplicate=True),
        Output("campbell-ai-status", "children", allow_duplicate=True),
        Output("campbell-ai-status", "color", allow_duplicate=True),
        Output("campbell-ai-failure-store", "data", allow_duplicate=True),
        Output("campbell-ai-feedback-store", "data", allow_duplicate=True),
        Input("campbell-ai-new-conversation", "n_clicks"),
        State("campbell-ai-company-store", "data"),
        prevent_initial_call=True,
    )
    def start_new_conversation(clicks, company_state):
        """Open an empty thread without touching the archived one."""
        if not clicks:
            raise PreventUpdate
        company_id = _company_id_from_state(company_state)
        username = _current_username(company_state)
        if not username or not company_id:
            raise PreventUpdate
        try:
            initialized = CampbellAPIClient.from_env().initialize(username, company_id)
        except CampbellAPIClientError as exc:
            logger.warning("Campbell AI could not start a conversation: %s", exc)
            return (
                no_update,
                no_update,
                no_update,
                _status_label(exc),
                "danger",
                _failure_from_client_error(exc),
                no_update,
            )
        return (
            initialized["session_id"],
            [],
            company_id,
            f"Listo · {company_id.upper()}",
            "success",
            None,
            {},
        )
