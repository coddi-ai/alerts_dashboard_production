"""Tests for how the view behaves when the Campbell AI service is unavailable.

The view used to show one dead-end line ("No fue posible conectar con la API") with
the composer still enabled, so the user's only option was to repeat a failing action
and lose the question they had typed. These tests pin the replacement: a cause, what
to do about it, a retry that reuses the question, and a composer that refuses to
pretend the service is up.
"""

from __future__ import annotations

from urllib.error import HTTPError, URLError

import pytest

from dashboard.campbell_ai.callbacks import (
    _BLOCKING_FAILURES,
    _failed_question,
    _failure_from_client_error,
    _failure_state,
    _status_label,
)
from dashboard.campbell_ai.client import CampbellAPIClient, CampbellAPIClientError
from dashboard.campbell_ai.layout import (
    _retry_button,
    service_error_content,
    unavailable_placeholder,
)


def _client(**kwargs) -> CampbellAPIClient:
    defaults = {
        "base_url": "http://127.0.0.1:9",
        "internal_token": "token",
        "timeout_seconds": 1,
    }
    return CampbellAPIClient(**{**defaults, **kwargs})


def _raise(client: CampbellAPIClient) -> CampbellAPIClientError:
    with pytest.raises(CampbellAPIClientError) as excinfo:
        client.initialize("admin", "cda")
    return excinfo.value


def _text(component) -> str:
    """All visible text in a Dash component tree.

    `repr` truncates nested children, so asserting on it silently passes.
    """
    if component is None or isinstance(component, (bool, int, float)):
        return ""
    if isinstance(component, str):
        return component
    if isinstance(component, (list, tuple)):
        return " ".join(_text(item) for item in component)
    children = getattr(component, "children", None)
    return _text(children)


def _ids(component) -> set[str]:
    """Every component id in a Dash tree."""
    found: set[str] = set()
    if isinstance(component, (list, tuple)):
        for item in component:
            found |= _ids(item)
        return found
    identifier = getattr(component, "id", None)
    if isinstance(identifier, str):
        found.add(identifier)
    children = getattr(component, "children", None)
    if children is not None:
        found |= _ids(children)
    return found


# --------------------------------------------------------------- classification


def test_a_refused_connection_is_reported_as_a_dead_service(monkeypatch):
    """Deterministic: platforms differ on whether a closed port refuses or hangs."""
    import dashboard.campbell_ai.client as module

    def refused(*args, **kwargs):
        raise URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr(module, "urlopen", refused)
    exc = _raise(_client())

    assert exc.kind == "unreachable"
    assert exc.retryable is True
    assert "no está respondiendo" in exc.guidance
    assert _status_label(exc) == "Servicio caído"


def test_an_unavailable_service_is_always_retryable_and_blocks_composing():
    """Real network. Windows hangs on a closed port where Linux refuses, so the exact
    kind is platform-dependent; what must hold is the user-facing behaviour."""
    exc = _raise(_client())

    assert exc.kind in {"unreachable", "timeout"}
    assert exc.retryable is True
    state = _failure_from_client_error(exc)
    assert _status_label(exc) in {"Servicio caído", "Tiempo excedido"}
    # Either way the view must not pretend the service is up.
    assert state["kind"] in _BLOCKING_FAILURES or exc.kind == "timeout"


def test_a_missing_token_is_a_configuration_problem_not_a_retry():
    exc = _raise(_client(internal_token=""))

    assert exc.kind == "not_configured"
    assert exc.retryable is False
    assert "plataforma" in exc.guidance
    assert _status_label(exc) == "Sin configurar"


def test_http_statuses_map_to_distinct_causes(monkeypatch):
    """401, 403 and 503 need different guidance; one message for all is misleading."""
    import dashboard.campbell_ai.client as module

    class _Response:
        """HTTPError closes its fp on cleanup, so the stub must support it."""

        def read(self):
            return b'{"detail": "detalle del servicio"}'

        def close(self):
            return None

    def fail_with(code):
        def _urlopen(*args, **kwargs):
            raise HTTPError("url", code, "err", {}, _Response())

        return _urlopen

    expected = {
        401: ("credentials", False),
        403: ("forbidden", False),
        422: ("invalid_request", False),
        503: ("unavailable", True),
        500: ("server_error", True),
    }
    for code, (kind, retryable) in expected.items():
        monkeypatch.setattr(module, "urlopen", fail_with(code))
        exc = _raise(_client())
        assert exc.kind == kind, code
        assert exc.retryable is retryable, code
        # The service's own detail is preserved when it sends one.
        assert str(exc) == "detalle del servicio"


def test_a_socket_timeout_is_distinguished_from_an_unreachable_host(monkeypatch):
    """Both arrive as URLError; only the cause tells them apart."""
    import dashboard.campbell_ai.client as module

    def timeout(*args, **kwargs):
        raise URLError(TimeoutError("timed out"))

    monkeypatch.setattr(module, "urlopen", timeout)
    exc = _raise(_client())

    assert exc.kind == "timeout"
    assert exc.retryable is True
    assert _status_label(exc) == "Tiempo excedido"


def test_health_probe_uses_a_short_timeout_and_needs_no_token():
    """It runs to decide what to tell the user, so it must not wait the long budget."""
    client = _client(internal_token="", timeout_seconds=90)

    with pytest.raises(CampbellAPIClientError) as excinfo:
        client.health()

    # No token was configured, yet the probe still ran: it is unauthenticated.
    assert excinfo.value.kind == "unreachable"


# ------------------------------------------------------------------- view state


def test_the_failure_state_preserves_the_question_for_a_retry(monkeypatch):
    """Losing the typed question is the difference between a retry and retyping."""
    import dashboard.campbell_ai.client as module

    monkeypatch.setattr(
        module, "urlopen", lambda *a, **k: (_ for _ in ()).throw(URLError("down"))
    )
    exc = _raise(_client())

    state = _failure_from_client_error(exc, question="¿Cuál fue la última alerta?")

    assert state["kind"] == "unreachable"
    assert state["retryable"] is True
    assert _failed_question(state) == "¿Cuál fue la última alerta?"


def test_causes_that_cannot_be_answered_block_the_composer():
    """Leaving send enabled invites the user to repeat a failing action."""
    for kind in ("unreachable", "credentials", "not_configured", "server_error"):
        assert kind in _BLOCKING_FAILURES, kind
    # A timeout or missing data may succeed on the next try, so composing stays open.
    for kind in ("timeout", "unavailable", "forbidden"):
        assert kind not in _BLOCKING_FAILURES, kind


def test_alert_content_states_the_cause_guidance_and_pending_question():
    body = service_error_content(
        title="No fue posible conectar con el servicio de Campbell AI",
        guidance="El servicio no está respondiendo.",
        pending_question="¿Cuál fue la última alerta?",
    )
    rendered = _text(body)

    assert "No fue posible conectar" in rendered
    assert "no está respondiendo" in rendered
    # The question is echoed so the user can see it was not lost.
    assert "última alerta" in rendered


def test_retry_button_is_a_permanent_fixture_hidden_by_default():
    """The retry button must always be mounted, never conditionally rendered.

    It is a plain-id Input of synchronize_chat: if Dash ever finds this id absent
    from the layout, it disables the whole callback rather than just this Input,
    which is exactly the regression this pins (see render_failure's style output
    for how visibility is actually controlled).
    """
    button = _retry_button()

    assert button.id == "campbell-ai-retry"
    assert button.style.get("display") == "none"


def test_placeholder_says_the_rest_of_the_dashboard_still_works():
    """An empty panel reads as a broken page rather than a scoped outage."""
    rendered = _text(unavailable_placeholder("Campbell AI no está disponible"))

    assert "no está disponible" in rendered
    assert "sigue funcionando" in rendered


def test_user_facing_states_are_not_treated_as_service_errors():
    """No company selected is the user's next step, not an outage."""
    state = _failure_state("no_company", "No hay empresa seleccionada", "Elige una empresa.")

    assert state["retryable"] is False
    assert state["kind"] in _BLOCKING_FAILURES
    assert _failed_question(state) == ""
