"""UI contracts for the Campbell AI Dash view."""

from __future__ import annotations

import re
from pathlib import Path

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
    _STATUS_NAMESPACE_JS,
    _pending_user_message,
    _resolve_outgoing_message,
    _status_js,
    _strip_pending_messages,
    register_campbell_ai_callbacks,
)
from dashboard.campbell_ai.layout import (
    ALERT_SUGGESTIONS,
    CAMPBELL_AI_VERSION,
    _feedback_controls,
    _initial_company_state,
    create_campbell_ai_layout,
    render_conversation_list,
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


def test_the_view_reports_the_current_version():
    components = list(_walk(create_campbell_ai_layout()))
    visible_text = " ".join(item for item in components if isinstance(item, str))

    # The exact version string isn't the point (it changes freely); what must
    # hold is that whatever CAMPBELL_AI_VERSION says is what the view shows.
    assert f"Campbell AI v{CAMPBELL_AI_VERSION}" in visible_text


def test_the_status_badge_knows_which_text_is_its_own():
    """Two couplings that fail silently, both in the badge that shows the wait.

    The badge is written by several callbacks, and `_STATUS_NAMESPACE_JS` decides whether
    to keep updating it by asking "is this still my text?". Get either half of that wrong
    and nothing raises - the badge simply freezes during the initialization, which is the
    one failure this whole mechanism exists to prevent.

    Half one: the first comparison is against the text the layout renders, so the wording
    lives in two files and they must agree.

    Half two: ownership must be decided by what the script last wrote, never by the shape
    of the text. The same badge shows "Pensando… 12s" while an answer runs; recognising a
    trailing ellipsis as "mine" would make the initialization heartbeat overwrite the
    answering state and keep its polling interval alive for the whole conversation.
    """
    badge = next(
        item
        for item in _walk(create_campbell_ai_layout())
        if getattr(item, "id", None) == "campbell-ai-status"
    )
    script = _STATUS_NAMESPACE_JS

    declared = re.search(r'var INITIAL_TEXT = "([^"]+)"', script)
    assert declared, "_STATUS_NAMESPACE_JS dejo de declarar INITIAL_TEXT"
    assert declared.group(1) == badge.children

    ownership = re.search(r"function isOurs\(text\) \{(.+?)\n  \}", script, re.S)
    assert ownership, "isOurs desaparecio o cambio de forma"
    assert "state.written" in ownership.group(1)
    assert "INITIAL_TEXT" in ownership.group(1)
    assert not re.search(r"charAt|endsWith|\bslice\b", ownership.group(1))


def test_the_badge_script_does_not_depend_on_a_file_under_assets():
    """The 500 this replaced: a clientside callback whose code lived in `assets/`.

    Dash registers the files in `assets/` once, on the first request the process serves, and
    then stats each of them on every render to version it by mtime. The deployment bind-mounts
    the checkout into the container, so a checkout that stops carrying the file while the
    process stays alive - an older branch, a rollback - turns every page load into a 500 for a
    script the page could have carried itself. Nothing recovers from it either: the hot reload
    that would drop the file from the list is off in production.

    So each emitted function has to install what it calls, and the namespace must not reappear
    in a file under `assets/`.
    """
    emitted = _status_js("begin", "clientValue, sessionId, currentText")

    assert emitted.startswith("function(clientValue, sessionId, currentText) {")
    # Self-contained: the function builds the namespace instead of trusting that some other
    # file already ran and left it on `window`.
    assert "namespace.campbellAiStatus = {" in emitted
    # Idempotent: the three callbacks emit this same installer into one page, and the state it
    # holds (`written`, `startedAt`) has to survive across them - rebuilding it on the second
    # call would make the badge forget what it wrote and stop recognising its own text.
    assert "if (namespace.campbellAiStatus) return namespace.campbellAiStatus;" in emitted

    assets = Path(__file__).resolve().parents[1] / "dashboard" / "assets"
    strays = sorted(
        path.name
        for path in assets.glob("*.js")
        if "campbellAiStatus" in path.read_text(encoding="utf-8")
    )
    assert not strays, f"el namespace del badge volvio a un archivo de assets: {strays}"


def test_the_session_company_survives_navigation_in_session_storage():
    """The in-memory company store empties on remount; this one must not."""
    stores = {
        item.id: item
        for item in _walk(create_campbell_ai_layout())
        if isinstance(getattr(item, "id", None), str) and item.id.endswith("-store")
        or getattr(item, "id", None) == "campbell-ai-session-company"
    }

    assert stores["campbell-ai-session-company"].storage_type == "session"
    assert stores["campbell-ai-session-store"].storage_type == "session"
    assert stores["campbell-ai-history-store"].storage_type == "session"


def test_every_declared_state_is_bound_to_a_parameter():
    """A callback taking more parameters than it declares raises on every trigger.

    This is not hypothetical: the retry path was broken because `synchronize_chat`
    declared eleven parameters and only ten inputs and states.
    """
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    register_campbell_ai_callbacks(app)

    for callback_id, metadata in app.callback_map.items():
        # Dash wraps the callback; the declared signature is on the original function.
        # Clientside callbacks carry no Python function at all.
        function = getattr(metadata.get("callback"), "__wrapped__", None)
        if function is None:
            continue
        declared = len(metadata["inputs"]) + len(metadata.get("state", []))
        assert function.__code__.co_argcount == declared, callback_id


def test_the_history_panel_offers_listing_opening_and_starting_over():
    components = list(_walk(create_campbell_ai_layout()))
    ids = {
        item.id
        for item in components
        if isinstance(getattr(item, "id", None), str)
    }

    assert {
        "campbell-ai-history-toggle",
        "campbell-ai-history-offcanvas",
        "campbell-ai-conversation-list",
        "campbell-ai-new-conversation",
        "campbell-ai-refresh-conversations",
    } <= ids


def test_conversation_rows_are_labelled_and_the_active_one_is_marked():
    rows = render_conversation_list(
        [
            {
                "session_id": "s1",
                "label": "Alertas de refrigerante en T_18",
                "message_count": 4,
                "updated_at": "2026-08-01T09:30:00+00:00",
            },
            {
                "session_id": "s2",
                "title": "Pareto por equipo",
                "message_count": 2,
                "updated_at": "2026-07-30T18:05:00+00:00",
            },
        ],
        active_session_id="s1",
    )
    text = " ".join(item for item in _walk(rows) if isinstance(item, str))

    assert "Alertas de refrigerante en T_18" in text
    # Falls back to the first-message title when there is no AI summary.
    assert "Pareto por equipo" in text
    # Date and time without inventing a timezone label.
    assert "2026-08-01 09:30" in text
    assert "en curso" in text
    buttons = [
        item
        for item in _walk(rows)
        if isinstance(getattr(item, "id", None), dict)
        and item.id.get("type") == "campbell-ai-open-conversation"
    ]
    assert [button.id["session_id"] for button in buttons] == ["s1", "s2"]
    # The open conversation cannot be reopened onto itself.
    assert buttons[0].disabled is True


def test_an_empty_history_says_so_instead_of_rendering_nothing():
    text = " ".join(
        item for item in _walk(render_conversation_list([])) if isinstance(item, str)
    )

    assert "Aún no hay conversaciones respaldadas" in text


def test_the_comment_box_appears_only_after_a_vote():
    def controls_for(entry):
        return [
            item
            for item in _walk(_feedback_controls("msg_1", entry))
            if isinstance(getattr(item, "id", None), dict)
        ]

    unvoted = {
        item.id["type"] for item in controls_for(None)
    }
    voted = {item.id["type"] for item in controls_for({"rating": "negative"})}
    answered = " ".join(
        item
        for item in _walk(_feedback_controls("msg_1", {"rating": "negative", "comment": True}))
        if isinstance(item, str)
    )

    assert unvoted == {"campbell-ai-feedback-button"}
    # Asking why before knowing whether the answer helped is a question with no context.
    assert "campbell-ai-feedback-comment" in voted
    assert "campbell-ai-feedback-comment-send" in voted
    assert "registramos tu comentario" in answered


def test_the_older_rating_only_feedback_shape_still_renders():
    """Sessions stored before 1.1.0 hold a bare rating string, not a record."""
    rendered = " ".join(
        item for item in _walk(_feedback_controls("msg_1", "positive")) if isinstance(item, str)
    )

    assert "¿Qué te resultó útil?" not in rendered  # placeholder, not text
    buttons = [
        item
        for item in _walk(_feedback_controls("msg_1", "positive"))
        if isinstance(getattr(item, "id", None), dict)
        and item.id.get("type") == "campbell-ai-feedback-button"
    ]
    assert all(button.disabled for button in buttons)


def test_pending_message_helpers_render_user_message_before_agent_response():
    pending = _pending_user_message("Resumen de alertas")
    history = [pending, {"role": "assistant", "message_id": "real-1"}]

    assert pending["role"] == "user"
    assert pending["pending"] is True
    assert _strip_pending_messages(history) == [
        {"role": "assistant", "message_id": "real-1"}
    ]
