"""UI contracts for the Campbell AI Dash view."""

from __future__ import annotations

import dash
from flask import Flask, session as flask_session

import dashboard.auth as dashboard_auth
from dashboard.auth import (
    IDENTITY_PROOF_FIELD,
    add_identity_proof,
    current_dashboard_user_data,
    resolve_authenticated_username,
    should_process_login,
)
from dashboard.campbell_ai.callbacks import (
    _pending_user_message,
    _resolve_outgoing_message,
    _strip_pending_messages,
    register_campbell_ai_callbacks,
)
from dashboard.campbell_ai.layout import (
    ALERT_SUGGESTIONS,
    _initial_company_state,
    create_campbell_ai_layout,
)


def _walk(component):
    if isinstance(component, (list, tuple)):
        for item in component:
            yield from _walk(item)
        return
    yield component
    children = getattr(component, "children", None)
    if children is not None:
        yield from _walk(children)


def test_layout_has_alert_suggestions_without_removed_copy():
    components = list(_walk(create_campbell_ai_layout()))
    visible_text = " ".join(item for item in components if isinstance(item, str))
    suggestion_buttons = [
        item
        for item in components
        if isinstance(getattr(item, "id", None), dict)
        and item.id.get("type") == "campbell-ai-suggested-question"
    ]

    assert len(ALERT_SUGGESTIONS) == 4
    assert len(suggestion_buttons) == 4
    assert "Diagnóstico y 5 porqués" not in visible_text
    assert "Reportes, PDF, descargas y archivos están deshabilitados" not in visible_text


def test_textarea_and_callback_support_enter_to_send():
    components = list(_walk(create_campbell_ai_layout()))
    textarea = next(
        item for item in components if getattr(item, "id", None) == "campbell-ai-input"
    )
    assert textarea.submit_on_enter is True

    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)
    synchronize = next(
        metadata
        for callback_id, metadata in app.callback_map.items()
        if "campbell-ai-session-store.data" in callback_id
    )
    inputs = synchronize["inputs"]

    assert {
        "id": "campbell-ai-input",
        "property": "n_submit",
    } in inputs
    assert any(
        item["property"] == "n_clicks"
        and "campbell-ai-suggested-question" in item["id"]
        for item in inputs
    )
    assert any(
        "campbell-ai-pending-message-store.data" in callback_id
        and metadata["inputs"]
        and metadata["inputs"][0]["id"] == "campbell-ai-pending-message-store"
        for callback_id, metadata in app.callback_map.items()
    )


def test_enter_button_and_suggestions_resolve_to_an_outgoing_message():
    assert _resolve_outgoing_message("campbell-ai-input", "  Estado de alertas  ") == (
        "Estado de alertas"
    )
    assert _resolve_outgoing_message("campbell-ai-send", "Pareto por equipo") == (
        "Pareto por equipo"
    )
    assert _resolve_outgoing_message(
        {
            "type": "campbell-ai-suggested-question",
            "question_id": "equipment-pareto",
        },
        "",
    ) == ALERT_SUGGESTIONS["equipment-pareto"]
    assert _resolve_outgoing_message("campbell-ai-clear", "No enviar") is None


def test_login_hydration_is_not_treated_as_a_login_attempt():
    assert should_process_login(0, None) is False
    assert should_process_login(None, 0) is False
    assert should_process_login(1, None) is True
    assert should_process_login(0, 1) is True


def test_campbell_identity_proof_survives_without_a_cookie(monkeypatch):
    monkeypatch.setitem(
        dashboard_auth.USERS,
        "test-user",
        {"password": "unused", "role": "client", "clients": ["CDA"]},
    )
    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret-key-with-enough-entropy"

    with flask_app.test_request_context("/"):
        user_data = add_identity_proof(
            {
                "username": "test-user",
                "role": "client",
                "clients": ["CDA"],
            }
        )
        company_state = _initial_company_state(user_data)
        flask_session.clear()

        assert company_state["identity"][IDENTITY_PROOF_FIELD]
        assert resolve_authenticated_username(company_state["identity"]) == "test-user"


def test_campbell_layout_can_issue_identity_from_flask_session(monkeypatch):
    monkeypatch.setitem(
        dashboard_auth.USERS,
        "session-user",
        {"password": "unused", "role": "client", "clients": ["CDA"]},
    )
    flask_app = Flask(__name__)
    flask_app.secret_key = "test-secret-key-with-enough-entropy"

    with flask_app.test_request_context("/"):
        flask_session["dashboard_user"] = "session-user"
        user_data = current_dashboard_user_data()
        company_state = _initial_company_state(None)

        assert user_data["username"] == "session-user"
        assert company_state["identity"]["username"] == "session-user"
        assert company_state["identity"][IDENTITY_PROOF_FIELD]


def test_pending_message_helpers_render_user_message_before_agent_response():
    pending = _pending_user_message("Resumen de alertas")
    history = [pending, {"role": "assistant", "message_id": "real-1"}]

    assert pending["role"] == "user"
    assert pending["pending"] is True
    assert _strip_pending_messages(history) == [
        {"role": "assistant", "message_id": "real-1"}
    ]
