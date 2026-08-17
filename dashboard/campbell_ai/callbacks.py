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
    CAMPBELL_AI_VERSION,
    KEEP_WAITING_EXTENSION_SECONDS,
    SLOW_ANSWER_SECONDS,
    render_chat_history,
    render_conversation_list,
    service_error_content,
    unavailable_placeholder,
)
from dashboard.campbell_ai.stream import streaming_enabled
from src.campbell_ai.log_archive import start_ui_log_archiver
from src.campbell_ai.logging_setup import configure_ui_logging


logger = logging.getLogger("campbell_ai.ui.callbacks")

_HISTORY_PANEL_ID = "campbell-ai-history-offcanvas"


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


def _state_stamp(username: str | None) -> dict:
    """Identity of whoever owns this tab's stored conversation, plus the build.

    `sessionStorage` is scoped to the tab and to nothing else, so it survives both a
    logout and a redeploy. Both need to invalidate it, for different reasons, and one
    comparison covers both.
    """
    return {"user": str(username or ""), "version": CAMPBELL_AI_VERSION}


def _stale_browser_state(stamp, username: str | None) -> str | None:
    """Why the stored conversation cannot be trusted, or None when it can.

    Three real failures, all of them reported from production:

    - **a different user.** Nothing scoped this state to an account, so logging out and
      back in as someone else left the previous user's thread in the tab. The dashboard
      would even re-render it, because when the API has no history for a session id the
      view falls back to the copy the browser is holding.
    - **a different build.** A tab left open across a deploy keeps feeding state written
      by the old code into the new code. The stores gained fields over this work
      (`client_message_id`, `job_id`); older values flowing into newer callbacks is a
      whole class of bug that is miserable to reproduce.
    - **no stamp at all**, which is any tab that predates this mechanism.

    Returning a reason rather than a bool so the log says which of the three it was.
    """
    current = _state_stamp(username)
    if not isinstance(stamp, dict):
        return "sin sello previo"
    if stamp.get("user") != current["user"]:
        return "cambio de usuario"
    if stamp.get("version") != current["version"]:
        return f"cambio de version ({stamp.get('version')} -> {current['version']})"
    return None


def _stored_session_company(session_company) -> str | None:
    """Company the session-storage conversation belongs to."""
    normalized = str(session_company or "").strip().lower()
    return normalized or None


# Status-badge text for a background answer that ended badly.
_JOB_ERROR_LABELS = {
    "busy": "Servicio ocupado",
    "timeout": "Tiempo excedido",
    "forbidden": "Sin acceso",
    "unavailable": "Datos no disponibles",
    "not_configured": "Sin configurar",
    "server_error": "Error del servicio",
}

# What the user can actually do about each. A timeout is the one worth spelling out:
# repeating the identical question will hit the same budget, so the advice is to make
# it smaller rather than to try again.
_JOB_ERROR_GUIDANCE = {
    "busy": (
        "El asistente alcanzó su límite de consultas simultáneas. Espera unos segundos "
        "y reintenta: tu consulta se conservó."
    ),
    "timeout": (
        "La consulta superó el tiempo máximo. Acota el periodo o divídela en partes; "
        "si la conversación es muy larga, inicia una nueva para reducir el contexto."
    ),
    "unavailable": (
        "El servicio respondió pero no pudo atender la consulta, normalmente por datos "
        "faltantes para esta empresa."
    ),
    "server_error": (
        "El servicio falló procesando la consulta. Reintenta; si persiste, avisa al "
        "equipo de plataforma."
    ),
}


def _answers(history: list[dict] | None, question: str) -> bool:
    """Whether the thread already contains an answer to `question`.

    Used to decide what a lost job actually means. The messages arrive as user/assistant
    pairs, so the question having a message after it is what makes it answered.
    """
    messages = [
        message
        for message in (history or [])
        if not str(message.get("message_id", "")).startswith("pending-")
    ]
    for index, message in enumerate(messages):
        if message.get("role") == "user" and str(message.get("content", "")).strip() == (
            question.strip()
        ):
            if index + 1 < len(messages) and messages[index + 1].get("role") == "assistant":
                return True
    return False


def _recover_expired_job(client, username, company_id, job, history, question):
    """Decide what a forgotten job means by reading the conversation.

    A job the service no longer knows about has two very different explanations, and
    guessing wrong is what produced the original complaint. Either it finished and aged
    out — in which case the answer is in the thread and showing it is all that is needed
    — or it was lost with the question unanswered, and the user must be told so plainly
    rather than left looking at a bubble that will never be replied to.
    """
    try:
        restored = client.history(
            username, company_id, str(job.get("session_id") or "")
        ).get("messages", [])
    except CampbellAPIClientError as exc:
        logger.warning("Campbell AI history recovery failed (%s): %s", exc.kind, exc)
        restored = []

    if _answers(restored, question):
        logger.info("Campbell AI recovered an answer from history for an expired job")
        return (
            restored,
            no_update,
            f"Listo · {company_id.upper()}" if company_id else "Listo",
            "success",
            None,
            None,
            None,
            False,
            "",
        )
    return (
        restored or _strip_pending_messages(history),
        no_update,
        "Consulta perdida",
        "warning",
        _failure_state(
            "expired",
            "El asistente perdió el seguimiento de esta consulta",
            "No quedó registro de una respuesta. Vuelve a enviarla; se conservó abajo.",
            retryable=True,
            question=question,
        ),
        None,
        None,
        False,
        "",
    )


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
    """Register state, API and rendering callbacks for Campbell AI.

    Also brings up the frontend's own rotating log file and its S3 archival. This is the
    hook the dashboard already calls, which is what lets Campbell AI own its observability
    without any change to `dashboard/app.py`: the frontend's failures and call durations
    are Campbell AI's to keep, and they used to exist only in a log nobody rotates.

    Both are best-effort. A frontend that will not register its callbacks because it could
    not open a log file would be a worse outcome than missing logs.
    """
    try:
        configure_ui_logging()
        start_ui_log_archiver()
    except Exception:  # pragma: no cover - observability must never block the UI
        logger.exception("Campbell AI no pudo configurar su registro de frontend")

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
        Output("campbell-ai-state-stamp", "data"),
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
        State("campbell-ai-state-stamp", "data"),
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
        state_stamp,
    ):
        username = _current_username(session_company)
        company_id = str(selected_client or "").strip().lower()

        # Drop a conversation this tab has no business showing, before anything reads
        # it. Discarding rather than clearing the stores separately: this callback
        # already owns the session, history and company outputs, so overwriting them
        # below is enough and there is no second callback to race.
        stale = _stale_browser_state(state_stamp, username)
        if stale and (session_id or history):
            logger.info("Campbell AI descarta el estado del navegador: %s", stale)
        if stale:
            session_id, history, stored_session_company = None, [], None
        stamp = _state_stamp(username)
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
                stamp,
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
                stamp,
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
                        # A fresh key: the previous attempt is over, and reusing its key
                        # would attach this retry to a job that already failed.
                        "client_message_id": uuid4().hex,
                        "stream": bool(streaming_enabled() and session_id),
                    },
                    company_id,
                    stamp,
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
                    stamp,
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
                        stamp,
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
                        # Minted here, at the one place a question enters the system, so
                        # everything downstream that resubmits it carries the same key
                        # and attaches to one run instead of starting another.
                        "client_message_id": uuid4().hex,
                        # Streaming needs an existing session id, because the browser
                        # cannot create one; the first message of a thread stays blocking.
                        "stream": bool(streaming_enabled() and session_id),
                    },
                    company_id,
                    stamp,
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
                stamp,
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
                stamp,
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
                stamp,
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
        Output("campbell-ai-job-store", "data", allow_duplicate=True),
        Input("campbell-ai-pending-message-store", "data"),
        State("campbell-ai-session-store", "data"),
        State("campbell-ai-history-store", "data"),
        State("campbell-ai-company-store", "data"),
        prevent_initial_call=True,
    )
    def process_pending_message(pending, session_id, history, session_company):
        """Hand the question to the API as a background job and return immediately.

        This callback used to block for the whole agent run. That was the freeze: Dash
        holds a worker thread for the duration, the composer it disabled is only
        re-enabled when the callback returns, and if the HTTP request died in between —
        a proxy idle timeout, a reload, a network blip — it never returned at all. The
        run carried on regardless, persisted its answer, and the user found the question
        already answered the next time the page loaded.

        Now the only thing that happens here is a submit, which takes milliseconds. The
        answer is collected by `poll_pending_job`.
        """
        if not isinstance(pending, dict) or not pending.get("message"):
            raise PreventUpdate
        if pending.get("stream"):
            # The browser is streaming this one; finalize_stream re-dispatches here
            # with stream=False if the stream fails.
            raise PreventUpdate
        if pending.get("job_id"):
            # Already submitted; the poll owns it from here. Without this guard the
            # store update we make below would re-enter this callback and submit again.
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
                None,
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
                None,
            )

        client = CampbellAPIClient.from_env()
        question = str(pending["message"])
        try:
            active_session_id = str(pending.get("session_id") or session_id or "").strip()
            # Initialization validates data availability and mints a session id; once a
            # session exists, /message/submit alone is enough.
            if not active_session_id:
                active_session_id = client.initialize(username, company_id)["session_id"]
            # Reuse the id the dispatcher minted rather than making a new one: a retry
            # of the same question carries the same key, so the API attaches it to the
            # run already in progress instead of answering it twice.
            client_message_id = str(pending.get("client_message_id") or uuid4().hex)
            submitted = client.submit_message(
                username, company_id, active_session_id, question, client_message_id
            )
            return (
                submitted.get("session_id") or active_session_id,
                no_update,
                "Pensando...",
                "info",
                None,
                {
                    **pending,
                    "session_id": active_session_id,
                    "client_message_id": client_message_id,
                    "job_id": submitted["job_id"],
                },
                _updated_company_state(session_company, company_id),
                company_id,
                {
                    "job_id": submitted["job_id"],
                    "session_id": active_session_id,
                    "company_id": company_id,
                    "question": question,
                    "client_message_id": client_message_id,
                    # Stamped so a tab that changes hands does not poll — or display —
                    # an answer belonging to whoever was logged in before.
                    "username": username,
                },
            )
        except CampbellAPIClientError as exc:
            logger.warning("Campbell AI submit failed (%s): %s", exc.kind, exc)
            return (
                session_id,
                # Drop the optimistic bubble: the exchange did not happen.
                _strip_pending_messages(history),
                _status_label(exc),
                "danger",
                _failure_from_client_error(exc, question=question),
                None,
                session_company,
                no_update,
                None,
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
                    question=question,
                ),
                None,
                session_company,
                no_update,
                None,
            )

    # --- Background answers ------------------------------------------------------
    # A question is submitted, then polled. The job lives on the server, so none of
    # this depends on a single HTTP request surviving for the length of an answer.

    @app.callback(
        Output("campbell-ai-job-poll", "disabled"),
        Input("campbell-ai-job-store", "data"),
    )
    def toggle_job_poll(job):
        """Poll only while an answer is outstanding.

        Note the absent `prevent_initial_call`: this must run on mount. The job store is
        session-scoped, so a page that reloaded mid-question starts with a job id
        already in it, and polling has to resume on its own for the answer to be
        collected rather than abandoned.
        """
        return not (isinstance(job, dict) and job.get("job_id"))

    @app.callback(
        Output("campbell-ai-history-store", "data", allow_duplicate=True),
        Output("campbell-ai-session-store", "data", allow_duplicate=True),
        Output("campbell-ai-status", "children", allow_duplicate=True),
        Output("campbell-ai-status", "color", allow_duplicate=True),
        Output("campbell-ai-failure-store", "data", allow_duplicate=True),
        Output("campbell-ai-pending-message-store", "data", allow_duplicate=True),
        Output("campbell-ai-job-store", "data", allow_duplicate=True),
        Output("campbell-ai-waiting", "is_open"),
        Output("campbell-ai-waiting-body", "children"),
        Input("campbell-ai-job-poll", "n_intervals"),
        State("campbell-ai-job-store", "data"),
        State("campbell-ai-history-store", "data"),
        State("campbell-ai-company-store", "data"),
        State("campbell-ai-waiting-ack", "data"),
        prevent_initial_call=True,
    )
    def poll_pending_job(_ticks, job, history, session_company, waiting_ack):
        """Collect a background answer, or explain why it is still running.

        Every branch here ends in a definite state — answered, failed, or still running
        with a visible way out. There is no path that leaves the composer disabled with
        nothing happening, which is what the old blocking callback did whenever its
        request died.
        """
        if not (isinstance(job, dict) and job.get("job_id")):
            raise PreventUpdate

        job_id = str(job["job_id"])
        question = str(job.get("question") or "")
        company_id = str(
            job.get("company_id") or _company_id_from_state(session_company) or ""
        ).strip().lower()
        username = _current_username(session_company)

        # The job handle lives in sessionStorage so a reload can resume it, which also
        # means it outlives a logout. Polling someone else's job would at best show
        # their answer in this tab; drop it instead. `synchronize_chat` clears the rest
        # of the stale state, but it cannot own this store as well (Dash forbids a
        # duplicate output on a callback that must run on mount), so the check lives
        # here where the job is actually used.
        owner = job.get("username")
        if owner and username and owner != username:
            logger.info("Campbell AI descarta un job de otro usuario tras el cambio")
            return (
                no_update, no_update, no_update, no_update,
                None, None, None, False, "",
            )

        client = CampbellAPIClient.from_env()

        try:
            status = client.message_status(job_id)
        except CampbellAPIClientError as exc:
            if exc.kind == "expired":
                # The service no longer knows this job. It may well have answered before
                # forgetting it, so read the conversation before concluding anything —
                # this is the exact case that used to surface as "it was answered all
                # along" only after a manual refresh.
                return _recover_expired_job(
                    client, username, company_id, job, history, question
                )
            logger.warning("Campbell AI job poll failed (%s): %s", exc.kind, exc)
            return (
                _strip_pending_messages(history),
                no_update,
                _status_label(exc),
                "danger",
                _failure_from_client_error(exc, question=question),
                None,
                None,
                False,
                "",
            )

        state = str(status.get("status") or "")
        elapsed = float(status.get("elapsed_seconds") or 0.0)

        if state in {"queued", "running"}:
            # Still working. Show the way out once the wait becomes unreasonable, and
            # again each time an extension the user asked for runs out.
            threshold = SLOW_ANSWER_SECONDS + float(waiting_ack or 0)
            show_panel = elapsed >= threshold
            return (
                no_update,
                no_update,
                f"Pensando… {int(elapsed)}s",
                "info",
                no_update,
                no_update,
                no_update,
                show_panel,
                f"La consulta lleva {int(elapsed)} segundos" if show_panel else "",
            )

        if state == "done":
            result = status.get("result") or {}
            messages = result.get("messages") or []
            if not messages:
                # Defensive: the answer exists, so read the thread rather than dropping
                # the optimistic bubble and pretending nothing happened.
                try:
                    messages = client.history(
                        username, company_id, result.get("session_id") or job["session_id"]
                    ).get("messages", [])
                except CampbellAPIClientError:
                    messages = _strip_pending_messages(history)
            return (
                messages,
                result.get("session_id") or job.get("session_id") or no_update,
                f"Listo · {company_id.upper()}" if company_id else "Listo",
                "success",
                None,
                None,
                None,
                False,
                "",
            )

        if state == "cancelled":
            return (
                _strip_pending_messages(history),
                no_update,
                "Cancelada",
                "secondary",
                _failure_state(
                    "cancelled",
                    "Cancelaste la consulta",
                    "Puedes reformularla de forma más acotada y volver a enviarla.",
                    retryable=True,
                    question=question,
                ),
                None,
                None,
                False,
                "",
            )

        # state == "error"
        error = status.get("error") or {}
        kind = str(error.get("kind") or "server_error")
        return (
            _strip_pending_messages(history),
            no_update,
            _JOB_ERROR_LABELS.get(kind, "Error del servicio"),
            "danger",
            _failure_state(
                kind,
                str(error.get("detail") or "Campbell AI no pudo completar la consulta"),
                _JOB_ERROR_GUIDANCE.get(kind, ""),
                retryable=bool(error.get("retryable", True)),
                question=question,
            ),
            None,
            None,
            False,
            "",
        )

    @app.callback(
        Output("campbell-ai-waiting-ack", "data"),
        Input("campbell-ai-keep-waiting", "n_clicks"),
        Input("campbell-ai-pending-message-store", "data"),
        State("campbell-ai-waiting-ack", "data"),
        prevent_initial_call=True,
    )
    def extend_the_wait(_clicks, pending, waiting_ack):
        """"Seguir esperando" buys another stretch before the panel returns.

        Reset whenever a new question starts, so the extension a user granted one slow
        answer does not silently apply to the next.
        """
        if ctx.triggered_id == "campbell-ai-pending-message-store":
            return 0
        return float(waiting_ack or 0) + KEEP_WAITING_EXTENSION_SECONDS

    # Cancelling must also tear down a live SSE stream, or the browser keeps consuming
    # a stream for an answer the user has already walked away from.
    app.clientside_callback(
        "function(_clicks) { return window.dash_clientside.campbellAiStream.stop(); }",
        Output("campbell-ai-stream-store", "data", allow_duplicate=True),
        Input("campbell-ai-cancel-job", "n_clicks"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("campbell-ai-job-store", "data", allow_duplicate=True),
        Output("campbell-ai-pending-message-store", "data", allow_duplicate=True),
        Output("campbell-ai-history-store", "data", allow_duplicate=True),
        Output("campbell-ai-status", "children", allow_duplicate=True),
        Output("campbell-ai-status", "color", allow_duplicate=True),
        Output("campbell-ai-failure-store", "data", allow_duplicate=True),
        Output("campbell-ai-waiting", "is_open", allow_duplicate=True),
        Output("campbell-ai-input", "value", allow_duplicate=True),
        Input("campbell-ai-cancel-job", "n_clicks"),
        State("campbell-ai-job-store", "data"),
        State("campbell-ai-history-store", "data"),
        State("campbell-ai-pending-message-store", "data"),
        prevent_initial_call=True,
    )
    def cancel_pending_answer(_clicks, job, history, pending):
        """Abandon a running answer and give the user their question back.

        Covers both paths: a background job is cancelled on the server, and a streamed
        answer is torn down by the clientside callback above. Cancelling server-side
        matters as much as clearing the view — the run holds a concurrency slot, and
        with five users sharing ten of them, an answer nobody will ever read is a slot
        taken from someone still waiting.

        The question goes back into the composer rather than being discarded, since the
        usual reason to cancel is wanting to narrow it and ask again.
        """
        has_job = isinstance(job, dict) and bool(job.get("job_id"))
        has_stream = isinstance(pending, dict) and bool(pending.get("message"))
        if not (has_job or has_stream):
            raise PreventUpdate

        question = str(
            (job or {}).get("question") or (pending or {}).get("message") or ""
        )
        if has_job:
            try:
                CampbellAPIClient.from_env().cancel_message(str(job["job_id"]))
            except CampbellAPIClientError as exc:
                # The view still clears: the user asked to stop waiting, and refusing to
                # release the UI because the cancel call failed helps nobody.
                logger.warning("Campbell AI cancel failed (%s): %s", exc.kind, exc)
        return (
            None,
            None,
            _strip_pending_messages(history),
            "Cancelada",
            "secondary",
            None,
            False,
            question,
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
        # A failure always wins over "in flight". The pending store is cleared on every
        # terminal outcome, but if one ever slipped through, a live failure means this
        # question is over — re-enabling the composer is the right call, and leaving it
        # dead is the exact state users described as the page being stuck.
        disabled = blocked or (in_flight and kind is None)
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

    # --- Estado de inicializacion ---------------------------------------------
    # `synchronize_chat` hace una llamada bloqueante a la API (dos al refrescar, porque la
    # sesion sobrevive en sessionStorage y entonces tambien se recupera el hilo). Un callback
    # de Dash es atomico: no puede emitir un estado intermedio, asi que el badge se queda con
    # su texto inicial durante toda la espera y se lee como si se hubiera colgado.
    #
    # Estos tres callbacks son clientside a proposito: informan sin agregar una sola peticion
    # al servidor que ya esta ocupado, y no hubo que tocar `synchronize_chat`, que tiene diez
    # salidas y ocho puntos de retorno.
    app.clientside_callback(
        "function(clientValue, sessionId, currentText) {"
        " return window.dash_clientside.campbellAiStatus"
        ".begin(clientValue, sessionId, currentText); }",
        Output("campbell-ai-status", "children", allow_duplicate=True),
        Output("campbell-ai-status", "color", allow_duplicate=True),
        Output("campbell-ai-init-poll", "disabled", allow_duplicate=True),
        Input("client-selector", "value"),
        State("campbell-ai-session-store", "data"),
        # El texto actual del badge: si el servidor ya gano la carrera y escribio un estado
        # final, arrancar el latido dejaria el badge contando sobre una sesion ya lista.
        State("campbell-ai-status", "children"),
        # Tiene que correr en el montaje, que es justo cuando el badge se quedaria mudo, y
        # escribe una salida duplicada: Dash exige este valor para esa combinacion.
        prevent_initial_call="initial_duplicate",
    )

    # La unica pieza de servidor del ciclo, y la que convierte el cronometro en un estado
    # real: le pregunta a la API en que fase esta la inicializacion que sigue en vuelo.
    #
    # Puede responder justamente porque `initialize` ya no bloquea el event loop de la API
    # (el trabajo de archivos corre en un thread): antes esta consulta habria quedado
    # encolada detras de la llamada lenta, es decir muda durante los unicos segundos en que
    # tiene algo que decir.
    #
    # Solo late mientras el intervalo esta habilitado, o sea durante la inicializacion. Si la
    # API no contesta - o contesta que no sabe nada, lo que pasa cuando el poll llega a una
    # replica distinta de la que trabaja - el store queda vacio y el badge se queda con su
    # etiqueta generica.
    @app.callback(
        Output("campbell-ai-init-phase", "data"),
        Input("campbell-ai-init-poll", "n_intervals"),
        State("client-selector", "value"),
        State("campbell-ai-session-company", "data"),
        prevent_initial_call=True,
    )
    def poll_initialization_phase(ticks, client_value, session_company):
        # Un tick por medio, o sea una consulta por segundo. El intervalo late a 500 ms
        # porque de eso depende que el contador se vea vivo; la fase, en cambio, cambia en
        # escala de segundos, y preguntarla al doble de frecuencia solo agrega carga sobre la
        # API que estamos esperando.
        if not ticks or ticks % 2:
            raise PreventUpdate
        username = _current_username(session_company)
        if not username or not client_value:
            return None
        state = CampbellAPIClient.from_env().initialization_progress(
            username, client_value
        )
        if not state.get("active") or not state.get("label"):
            return None
        return {"label": state["label"], "phase": state.get("phase", "")}

    app.clientside_callback(
        "function(ticks, currentText, sessionId, phase) {"
        " return window.dash_clientside.campbellAiStatus"
        ".tick(ticks, currentText, sessionId, phase); }",
        Output("campbell-ai-status", "children", allow_duplicate=True),
        Output("campbell-ai-status", "color", allow_duplicate=True),
        Input("campbell-ai-init-poll", "n_intervals"),
        State("campbell-ai-status", "children"),
        State("campbell-ai-session-store", "data"),
        State("campbell-ai-init-phase", "data"),
        prevent_initial_call=True,
    )

    # El badge es la fuente de verdad del ciclo: cuando deja de decir un estado de progreso,
    # la inicializacion termino y el latido se apaga.
    app.clientside_callback(
        "function(currentText) {"
        " return window.dash_clientside.campbellAiStatus.settle(currentText); }",
        Output("campbell-ai-init-poll", "disabled", allow_duplicate=True),
        Input("campbell-ai-status", "children"),
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

    # Progress reporting, in the browser. The same interval drives it, but nothing leaves
    # the tab: counting seconds and deciding a wait has become unreasonable are pure
    # functions of the clock and two values the browser already holds.
    #
    # This used to arrive at `finalize_stream` as a `running` payload on the store above.
    # That store is the input of a *server* callback which declares the whole conversation
    # as State, so every tick uploaded the entire history for the server to answer with
    # no_update plus a new status string - about one wasted round trip per second for the
    # length of every answer, each holding a dashboard worker thread. The interval itself
    # was never the problem and stays at 350 ms, because `collect()` above is also what
    # delivers the finished answer.
    #
    # SLOW_ANSWER_SECONDS is interpolated rather than duplicated in JavaScript, so the
    # threshold has one definition (layout.py) for both the streaming and the job path.
    app.clientside_callback(
        "function(_ticks, ack) { return window.dash_clientside.campbellAiStream"
        f".progress(ack, {SLOW_ANSWER_SECONDS}); }}",
        Output("campbell-ai-status", "children", allow_duplicate=True),
        Output("campbell-ai-status", "color", allow_duplicate=True),
        Output("campbell-ai-waiting", "is_open", allow_duplicate=True),
        Output("campbell-ai-waiting-body", "children", allow_duplicate=True),
        Input("campbell-ai-stream-poll", "n_intervals"),
        State("campbell-ai-waiting-ack", "data"),
        prevent_initial_call=True,
    )

    @app.callback(
        Output("campbell-ai-history-store", "data", allow_duplicate=True),
        Output("campbell-ai-session-store", "data", allow_duplicate=True),
        Output("campbell-ai-status", "children", allow_duplicate=True),
        Output("campbell-ai-status", "color", allow_duplicate=True),
        Output("campbell-ai-pending-message-store", "data", allow_duplicate=True),
        Output("campbell-ai-waiting", "is_open", allow_duplicate=True),
        Output("campbell-ai-waiting-body", "children", allow_duplicate=True),
        Input("campbell-ai-stream-store", "data"),
        State("campbell-ai-pending-message-store", "data"),
        State("campbell-ai-history-store", "data"),
        State("campbell-ai-session-store", "data"),
        State("campbell-ai-company-store", "data"),
        State("campbell-ai-waiting-ack", "data"),
        prevent_initial_call=True,
    )
    def finalize_stream(result, pending, history, session_id, company_state, waiting_ack):
        """Apply a finished stream, report its progress, or fall back to a job.

        Three inputs arrive on this one store, because the browser is the only thing
        that knows what the stream is doing: a terminal payload, a periodic `running`
        tick, or a failure.
        """
        if not isinstance(result, dict):
            raise PreventUpdate

        if result.get("running"):
            # Legacy path, kept deliberately. Progress is now reported entirely in the
            # browser (see the `progress` clientside callback), so current JavaScript
            # never puts a `running` payload on this store.
            #
            # It stays because a tab left open across a deploy still runs the previous
            # asset: without this branch its progress ticks would fall through to the
            # failure handling below and turn a perfectly healthy answer into a fallback.
            # Costs one comparison; buys a deploy nobody has to reload through.
            elapsed = int(result.get("elapsed") or 0)
            threshold = SLOW_ANSWER_SECONDS + float(waiting_ack or 0)
            show_panel = elapsed >= threshold
            return (
                no_update,
                no_update,
                f"Pensando… {elapsed}s",
                "info",
                no_update,
                show_panel,
                f"La consulta lleva {elapsed} segundos" if show_panel else "",
            )

        if not result.get("ok"):
            if not (isinstance(pending, dict) and pending.get("message")):
                raise PreventUpdate
            question = str(pending.get("message") or "")
            if result.get("stalled"):
                logger.warning("Campbell AI stream stalled; recovering the answer")
            else:
                logger.info("Campbell AI stream unavailable; falling back to a job")

            # The stream may well have died *after* the server finished answering — a
            # stall is most likely exactly that. Re-sending the question would run the
            # whole thing a second time and append a duplicate exchange, so read the
            # thread first and adopt the answer if it is already there.
            username = _current_username(company_state)
            company_id = str(
                pending.get("company_id") or _company_id_from_state(company_state) or ""
            ).strip().lower()
            active_session = str(pending.get("session_id") or session_id or "")
            if username and company_id and active_session:
                try:
                    restored = CampbellAPIClient.from_env().history(
                        username, company_id, active_session
                    ).get("messages", [])
                except CampbellAPIClientError as exc:
                    logger.warning("Campbell AI stream recovery failed: %s", exc.kind)
                    restored = []
                if _answers(restored, question):
                    logger.info("Campbell AI adopted the answer a broken stream missed")
                    return (
                        restored,
                        active_session,
                        f"Listo · {company_id.upper()}",
                        "success",
                        None,
                        False,
                        "",
                    )

            # Genuinely unanswered: hand it to the background job path, which does not
            # depend on a connection staying alive.
            return (
                no_update,
                no_update,
                "Pensando...",
                "info",
                {**pending, "stream": False},
                False,
                "",
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
            False,
            "",
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
        """Reload the archived list after every exchange, so titles stay current.

        The button is the only caller that asks for a real re-read. The other two
        triggers fire after every exchange, where the cached index is both correct and
        much cheaper — reconciling on each message would list the bucket constantly.

        Pressing the button is how a conversation deleted straight from S3 disappears
        from the sidebar: the listing is served from an index document, so until
        something re-reads the stored objects the deleted rows keep showing, and
        clicking one opens nothing.
        """
        company_id = _company_id_from_state(company_state)
        username = _current_username(company_state)
        if not username or not company_id:
            return []
        asked_for_it = ctx.triggered_id == "campbell-ai-refresh-conversations"
        try:
            payload = CampbellAPIClient.from_env().list_conversations(
                username, company_id, refresh=asked_for_it
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
