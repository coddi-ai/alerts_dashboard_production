"""The view's behaviour while an answer is outstanding.

Every state a slow answer can reach is exercised by actually invoking the callback, so
the number of returned values is checked against the number of declared Outputs by
running the thing rather than by counting them in review. A mismatch there is not a
subtle bug — Dash raises and the view stops updating, which looks to the user exactly
like the freeze this work is meant to remove.

The property tying these together: no branch may leave the page with a message in flight
and no way out. That combination is the freeze.
"""

from __future__ import annotations

import dash
import pytest
from dash import dcc, html
from dash.exceptions import PreventUpdate

from dashboard.campbell_ai.callbacks import register_campbell_ai_callbacks
from dashboard.campbell_ai.layout import (
    JOB_POLL_INTERVAL_MS,
    KEEP_WAITING_EXTENSION_SECONDS,
    SLOW_ANSWER_SECONDS,
    create_campbell_ai_layout,
)


def _app() -> dash.Dash:
    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    app.layout = html.Div(
        [dcc.Dropdown(id="client-selector"), create_campbell_ai_layout({})]
    )
    register_campbell_ai_callbacks(app)
    return app


def _entry(app: dash.Dash, function_name: str) -> dict:
    """The registration Dash will actually use for this callback.

    Read from `callback_map` rather than by importing the closure, so the Output list
    the tests check against is the real one. Clientside callbacks live in the same map
    without a `callback` key, hence the `.get`.
    """
    for metadata in app.callback_map.values():
        function = metadata.get("callback")
        if function is None:
            continue
        inner = getattr(function, "__wrapped__", function)
        if inner.__name__ == function_name:
            return metadata
    raise AssertionError(f"callback {function_name!r} is not registered")


def _function(app: dash.Dash, function_name: str):
    function = _entry(app, function_name)["callback"]
    return getattr(function, "__wrapped__", function)


def _outputs(app: dash.Dash, function_name: str) -> int:
    spec = _entry(app, function_name)["output"]
    return len(spec) if isinstance(spec, (list, tuple)) else 1


# -- the layout carries the machinery ----------------------------------------


def test_the_view_mounts_the_polling_and_escape_hatch_controls():
    """All of these are plain-id callback targets and must always exist.

    Dash silently disables a whole callback whose plain-id Input is absent from the
    layout, so a control that only appears conditionally takes its callback with it.
    """
    from tests.test_campbell_ai_ui import _walk

    ids = {
        getattr(item, "id", None)
        for item in _walk(create_campbell_ai_layout({}))
        if isinstance(getattr(item, "id", None), str)
    }

    for required in (
        "campbell-ai-job-store",
        "campbell-ai-job-poll",
        "campbell-ai-waiting",
        "campbell-ai-waiting-body",
        "campbell-ai-waiting-ack",
        "campbell-ai-keep-waiting",
        "campbell-ai-cancel-job",
    ):
        assert required in ids, f"{required} is missing from the layout"


def test_the_job_handle_lives_in_session_storage():
    """So a reload can resume the same answer instead of abandoning it.

    In memory storage the job id dies with the page, and the reloaded tab has no way to
    know an answer is still coming — it would show an empty chat while the server
    finishes, which is the "refresh and it was already answered" experience.
    """
    from tests.test_campbell_ai_ui import _walk

    stores = {
        item.id: item
        for item in _walk(create_campbell_ai_layout({}))
        if isinstance(getattr(item, "id", None), str)
        and isinstance(item, dcc.Store)
    }

    assert stores["campbell-ai-job-store"].storage_type == "session"


def test_the_poll_cadence_is_frequent_enough_to_feel_immediate():
    assert 500 <= JOB_POLL_INTERVAL_MS <= 3000
    assert 10 <= SLOW_ANSWER_SECONDS <= 60
    assert KEEP_WAITING_EXTENSION_SECONDS >= 10


# -- polling states -----------------------------------------------------------


def test_polling_is_armed_only_while_an_answer_is_outstanding():
    app = _app()
    toggle = _function(app, "toggle_job_poll")

    assert toggle({"job_id": "job_1"}) is False, "polling should be on with a live job"
    assert toggle(None) is True
    assert toggle({}) is True


def test_polling_resumes_on_mount_so_a_reloaded_page_collects_its_answer():
    """`toggle_job_poll` must not prevent its initial call.

    A reloaded tab starts with a job id already in session storage. If the toggle only
    ran on change, polling would never start and the answer would sit uncollected —
    which is the original bug wearing a new hat.
    """
    app = _app()
    assert not _entry(app, "toggle_job_poll").get("prevent_initial_call"), (
        "polling will not resume after a reload"
    )


@pytest.mark.parametrize(
    "elapsed, expected_panel",
    [(1.0, False), (5.0, False), (float(SLOW_ANSWER_SECONDS) - 1, False),
     (float(SLOW_ANSWER_SECONDS), True), (120.0, True)],
)
def test_the_way_out_appears_only_once_the_wait_is_unreasonable(
    monkeypatch, elapsed, expected_panel
):
    """Below the threshold the panel would be noise; above it, its absence is the bug."""
    app = _app()
    poll = _function(app, "poll_pending_job")

    monkeypatch.setattr(
        "dashboard.campbell_ai.callbacks.CampbellAPIClient",
        _FakeClientFactory({"status": "running", "elapsed_seconds": elapsed}),
    )
    result = poll(1, {"job_id": "job_1", "question": "q", "session_id": "s"}, [], {}, 0)

    assert len(result) == _outputs(app, "poll_pending_job")
    assert result[7] is expected_panel
    assert f"{int(elapsed)}s" in str(result[2])


def test_keep_waiting_pushes_the_panel_out_rather_than_dismissing_it_forever():
    """The user asked for more time, not to be left without an exit."""
    app = _app()
    poll = _function(app, "poll_pending_job")
    extend = _function(app, "extend_the_wait")

    with _triggered_by("campbell-ai-keep-waiting"):
        granted = extend(1, None, 0)
    assert granted == KEEP_WAITING_EXTENSION_SECONDS

    # Just past the original threshold, but inside the extension: stay hidden.
    with _patched_client(
        {"status": "running", "elapsed_seconds": SLOW_ANSWER_SECONDS + 1}
    ):
        inside = poll(1, {"job_id": "j", "question": "q", "session_id": "s"}, [], {}, granted)
    assert inside[7] is False

    # Past the extension too: the exit comes back.
    with _patched_client(
        {
            "status": "running",
            "elapsed_seconds": SLOW_ANSWER_SECONDS + granted + 1,
        }
    ):
        outside = poll(1, {"job_id": "j", "question": "q", "session_id": "s"}, [], {}, granted)
    assert outside[7] is True


def test_a_new_question_resets_the_extension():
    """An extension granted to one slow answer must not carry into the next."""
    app = _app()
    extend = _function(app, "extend_the_wait")

    with _triggered_by("campbell-ai-pending-message-store"):
        assert extend(0, {"message": "nueva"}, 999) == 0


def test_a_finished_answer_clears_every_in_flight_marker():
    """Done must leave nothing that could keep the composer disabled."""
    app = _app()
    poll = _function(app, "poll_pending_job")

    messages = [
        {"role": "user", "content": "q", "message_id": "m1"},
        {"role": "assistant", "content": "respuesta", "message_id": "m2"},
    ]
    with _patched_client(
        {
            "status": "done",
            "elapsed_seconds": 30.0,
            "result": {"messages": messages, "session_id": "s", "response": "respuesta"},
        }
    ):
        result = poll(
            5, {"job_id": "j", "question": "q", "session_id": "s", "company_id": "cda"},
            [], {"company_id": "cda"}, 0,
        )

    assert len(result) == _outputs(app, "poll_pending_job")
    assert result[0] == messages
    assert result[4] is None, "a finished answer must not leave a failure on screen"
    assert result[5] is None, "the pending marker must be cleared"
    assert result[6] is None, "the job handle must be cleared"
    assert result[7] is False, "the waiting panel must close"


def test_a_failed_answer_clears_the_markers_and_keeps_the_question():
    """A failure must both release the composer and preserve what was asked."""
    app = _app()
    poll = _function(app, "poll_pending_job")

    with _patched_client(
        {
            "status": "error",
            "elapsed_seconds": 180.0,
            "error": {"kind": "timeout", "detail": "agotó el tiempo", "retryable": True},
        }
    ):
        result = poll(
            5, {"job_id": "j", "question": "mi consulta", "session_id": "s"}, [], {}, 0
        )

    failure = result[4]
    assert failure["kind"] == "timeout"
    assert failure["retryable"] is True
    assert failure["question"] == "mi consulta", "the question was lost on failure"
    assert failure["guidance"], "a timeout must tell the user what to do differently"
    assert result[5] is None and result[6] is None
    assert result[7] is False


def test_cancelling_hands_the_question_back_to_the_composer():
    app = _app()
    cancel = _function(app, "cancel_pending_answer")

    with _patched_client({}):
        result = cancel(
            1,
            {"job_id": "j", "question": "mi consulta larga"},
            [{"role": "user", "content": "x", "message_id": "pending-1"}],
            None,
        )

    assert len(result) == _outputs(app, "cancel_pending_answer")
    assert result[0] is None, "the job handle must be cleared"
    assert result[1] is None, "the pending marker must be cleared"
    assert result[2] == [], "the optimistic bubble must be dropped"
    assert result[6] is False
    assert result[7] == "mi consulta larga", "the question should return to the input"


def test_cancelling_with_nothing_in_flight_does_nothing():
    app = _app()
    cancel = _function(app, "cancel_pending_answer")

    with pytest.raises(PreventUpdate):
        cancel(1, None, [], None)


def test_a_lost_job_whose_answer_is_in_the_thread_shows_the_answer():
    """The recovery that removes the manual refresh.

    The job aged out, but the exchange completed and is in the conversation. Showing it
    is the correct outcome; reporting an error and dropping it is what made users
    reload the page to discover their answer.
    """
    app = _app()
    poll = _function(app, "poll_pending_job")

    answered = [
        {"role": "user", "content": "mi consulta", "message_id": "m1"},
        {"role": "assistant", "content": "la respuesta", "message_id": "m2"},
    ]
    with _patched_client(status_error="expired", history=answered):
        result = poll(
            9,
            {"job_id": "j", "question": "mi consulta", "session_id": "s", "company_id": "cda"},
            [],
            {"company_id": "cda"},
            0,
        )

    assert result[0] == answered, "the recovered answer was not shown"
    assert result[4] is None, "a recovered answer is not a failure"
    assert result[5] is None and result[6] is None
    assert "Listo" in str(result[2])


def test_a_lost_job_with_no_answer_says_so_plainly():
    """The opposite case must not be dressed up as success."""
    app = _app()
    poll = _function(app, "poll_pending_job")

    unanswered = [{"role": "user", "content": "mi consulta", "message_id": "m1"}]
    with _patched_client(status_error="expired", history=unanswered):
        result = poll(
            9,
            {"job_id": "j", "question": "mi consulta", "session_id": "s", "company_id": "cda"},
            [],
            {"company_id": "cda"},
            0,
        )

    assert result[4]["kind"] == "expired"
    assert result[4]["question"] == "mi consulta"
    assert result[4]["retryable"] is True
    assert result[5] is None and result[6] is None


# -- the composer gate --------------------------------------------------------


def test_the_composer_is_released_whenever_a_failure_is_showing():
    """The single invariant: a failure on screen always means a usable input box."""
    app = _app()
    gate = _function(app, "gate_composer")

    in_flight = {"message": "consulta"}
    disabled, *_ = gate(None, in_flight)
    assert disabled is True, "the composer should lock while a question is in flight"

    # A failure arriving alongside a stale pending marker must still free the composer.
    disabled, *_ = gate({"kind": "timeout"}, in_flight)
    assert disabled is False, "a failure left the composer disabled — this is the freeze"

    disabled, *_ = gate(None, None)
    assert disabled is False


# -- helpers ------------------------------------------------------------------


class _FakeClient:
    def __init__(self, status_payload, status_error=None, history=None):
        self._status = status_payload
        self._status_error = status_error
        self._history = history or []

    def message_status(self, job_id):
        if self._status_error:
            from dashboard.campbell_ai.client import CampbellAPIClientError

            raise CampbellAPIClientError(
                "expired", kind=self._status_error, retryable=True
            )
        return self._status

    def history(self, username, company_id, session_id):
        return {"messages": self._history}

    def cancel_message(self, job_id):
        return {"cancelled": True}


class _FakeClientFactory:
    def __init__(self, status_payload, status_error=None, history=None):
        self._args = (status_payload, status_error, history)

    def from_env(self):
        return _FakeClient(*self._args)


def _triggered_by(component_id: str):
    """Stand in for `dash.ctx` outside a real callback invocation."""
    import contextlib

    import dashboard.campbell_ai.callbacks as callbacks_module

    class _Ctx:
        triggered_id = component_id

    @contextlib.contextmanager
    def _patch():
        original = callbacks_module.ctx
        callbacks_module.ctx = _Ctx()
        try:
            yield
        finally:
            callbacks_module.ctx = original

    return _patch()


def _patched_client(status_payload=None, status_error=None, history=None):
    """Swap the API client and the authenticated user for the duration of a call."""
    import contextlib

    import dashboard.campbell_ai.callbacks as callbacks_module

    @contextlib.contextmanager
    def _patch():
        original_client = callbacks_module.CampbellAPIClient
        original_user = callbacks_module._current_username
        callbacks_module.CampbellAPIClient = _FakeClientFactory(
            status_payload or {}, status_error, history
        )
        callbacks_module._current_username = lambda *_args, **_kwargs: "admin"
        try:
            yield
        finally:
            callbacks_module.CampbellAPIClient = original_client
            callbacks_module._current_username = original_user

    return _patch()
