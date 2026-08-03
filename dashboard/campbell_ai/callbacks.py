"""Callbacks connecting the Campbell AI Dash view to its internal FastAPI API."""

from __future__ import annotations

import logging

import dash
from dash import ALL, Input, Output, State, callback_context, ctx, no_update
from dash.exceptions import PreventUpdate
from flask import session as flask_session

from dashboard.campbell_ai.client import CampbellAPIClient, CampbellAPIClientError
from dashboard.campbell_ai.layout import render_chat_history


logger = logging.getLogger(__name__)


def _current_username() -> str | None:
    username = flask_session.get("dashboard_user")
    return str(username).strip() if username else None


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
        Input("client-selector", "value"),
        Input("campbell-ai-send", "n_clicks"),
        Input("campbell-ai-clear", "n_clicks"),
        State("campbell-ai-input", "value"),
        State("campbell-ai-session-store", "data"),
        State("campbell-ai-history-store", "data"),
        State("campbell-ai-company-store", "data"),
    )
    def synchronize_chat(
        selected_client,
        _send_clicks,
        _clear_clicks,
        message,
        session_id,
        history,
        session_company,
    ):
        username = _current_username()
        company_id = str(selected_client or "").strip().lower()
        if not username:
            return (
                None,
                [],
                "",
                "Sesión expirada",
                "danger",
                "Vuelve a iniciar sesión en el dashboard.",
                True,
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
                None,
            )

        client = CampbellAPIClient.from_env()
        triggered_id = callback_context.triggered_id
        try:
            company_changed = bool(session_company and session_company != company_id)
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
                    company_id,
                )

            if triggered_id == "campbell-ai-send":
                normalized_message = str(message or "").strip()
                if not normalized_message:
                    return (
                        session_id,
                        history or [],
                        no_update,
                        f"Listo · {company_id.upper()}",
                        "success",
                        "Escribe una consulta antes de enviarla.",
                        True,
                        session_company or company_id,
                    )
                if not session_id or company_changed:
                    initialized = client.initialize(username, company_id)
                    session_id = initialized["session_id"]
                    history = []
                result = client.send_message(
                    username, company_id, session_id, normalized_message
                )
                updated_history = client.history(
                    username, company_id, result["session_id"]
                ).get("messages", [])
                return (
                    result["session_id"],
                    updated_history,
                    "",
                    f"Listo · {company_id.upper()}",
                    "success",
                    "",
                    False,
                    company_id,
                )

            reusable_session = session_id if session_company == company_id else None
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
                company_id,
            )
        except CampbellAPIClientError as exc:
            logger.warning("Campbell AI request failed: %s", exc)
            if session_company and session_company != company_id:
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
            )

    @app.callback(
        Output("campbell-ai-messages", "children"),
        Input("campbell-ai-history-store", "data"),
        Input("campbell-ai-feedback-store", "data"),
    )
    def display_history(history, feedback):
        return render_chat_history(history, feedback)

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

        username = _current_username()
        if not username or not company_id or not session_id:
            raise PreventUpdate
        current = dict(feedback or {})
        if message_id in current:
            raise PreventUpdate
        try:
            CampbellAPIClient.from_env().submit_feedback(
                username,
                str(company_id),
                str(session_id),
                message_id,
                rating,
            )
        except CampbellAPIClientError as exc:
            logger.warning("Campbell AI feedback failed: %s", exc)
            raise PreventUpdate from exc
        current[message_id] = rating
        return current
