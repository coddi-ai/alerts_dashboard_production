"""The submit-and-poll message flow, and the recovery paths it exists to enable.

Waiting for an answer inside the HTTP request coupled three unrelated things to one
fragile connection: whether the work ran, whether the user saw it, and whether the
composer ever came back. Any dropped connection broke all three at once, and the user's
experience of that was a frozen page whose question turned out to be answered as soon as
they reloaded.

These tests cover the contract that decouples them — submit returns immediately, the job
outlives its caller, polling collects the result — and the recovery decisions the
dashboard makes on top of it.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager

from fastapi.testclient import TestClient

from src.campbell_ai.api import app
from src.campbell_ai.config import reset_campbell_settings
from src.campbell_ai.errors import CampbellBusyError, CampbellTimeoutError
from src.campbell_ai.jobs import JobRegistry
from src.campbell_ai.models import MessageResponse


HEADERS = {"X-Campbell-Token": "secret-token"}


class SlowService:
    """A service whose answers take a controllable amount of time."""

    def __init__(self, delay: float = 0.2, failure: Exception | None = None):
        self.delay = delay
        self.failure = failure
        self.calls: list[str] = []
        self.jobs = JobRegistry(retention_seconds=60.0)

    async def send_message(self, username, company_id, session_id, message):
        self.calls.append(message)
        await asyncio.sleep(self.delay)
        if self.failure is not None:
            raise self.failure
        return MessageResponse(
            response=f"Respuesta para {message}",
            message_id="msg_test",
            session_id=session_id,
            company_id=company_id.lower(),
        )

    # The real service's submit/status/cancel are inherited behaviour we want under
    # test, so borrow them rather than reimplementing a second version here.
    submit_message = None  # replaced in _service() below
    message_status = None
    cancel_message = None


def _service(**kwargs) -> SlowService:
    """A SlowService wired to the real CampbellAIService job methods."""
    from src.campbell_ai.config import get_campbell_settings
    from src.campbell_ai.service import CampbellAIService

    service = SlowService(**kwargs)
    service.settings = get_campbell_settings()
    for name in ("submit_message", "message_status", "cancel_message"):
        setattr(
            service,
            name,
            getattr(CampbellAIService, name).__get__(service, SlowService),
        )
    # A staticmethod, so it is already a plain function and must not be bound — binding
    # it would pass `service` as the exception and the error payload would never be
    # built, leaving a failed job with no reason attached.
    service._job_error = CampbellAIService._job_error
    service._ensure_enabled = lambda: None
    return service


@contextmanager
def _api(monkeypatch, **kwargs):
    """An API client sharing one event loop across requests, as uvicorn does.

    `TestClient` used outside a `with` block spins up a fresh event loop per request and
    tears it down afterwards, which cancels the background answer the previous request
    started. Entering the context keeps one portal — and therefore one loop — alive for
    every request in the test, matching the deployed server where the loop outlives any
    single request. Without this the jobs under test would all come back "cancelled",
    which says something about the test harness and nothing about the code.
    """
    service = _service(**kwargs)
    monkeypatch.setenv("CAMPBELL_AI_INTERNAL_TOKEN", "secret-token")
    reset_campbell_settings()
    app.state.service = service
    with TestClient(app) as client:
        yield client, service


def _submit(client, message="consulta", client_message_id="msg-1", **overrides):
    payload = {
        "username": "admin",
        "company_id": "CDA",
        "session_id": "campbell_test",
        "message": message,
        "client_message_id": client_message_id,
    }
    payload.update(overrides)
    return client.post(
        "/api/v1/campbell-ai/message/submit", json=payload, headers=HEADERS
    )


def _poll_until_done(client, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.post(
            "/api/v1/campbell-ai/message/status",
            json={"job_id": job_id},
            headers=HEADERS,
        )
        if response.status_code == 404:
            return response
        if response.json()["status"] not in {"queued", "running"}:
            return response
        time.sleep(0.05)
    raise AssertionError("the job never reached a terminal state")


# -- the contract --------------------------------------------------------------


def test_submit_returns_immediately_instead_of_waiting_for_the_answer(monkeypatch):
    """The whole point: accepting a question must not cost the length of answering it.

    A submit that took as long as the answer would reintroduce the long-lived
    connection this design removes.
    """
    with _api(monkeypatch, delay=1.0) as (client, _service_):
        started = time.monotonic()
        response = _submit(client, "¿Cuántas alertas hay?")
        elapsed = time.monotonic() - started

    assert response.status_code == 202
    assert elapsed < 0.5, f"submit blocked for {elapsed:.2f}s on a 1s answer"
    body = response.json()
    assert body["job_id"].startswith("job_")
    assert body["status"] in {"queued", "running"}
    assert body["result"] is None


def test_polling_collects_the_answer_once_it_is_ready(monkeypatch):
    with _api(monkeypatch, delay=0.15) as (client, _service_):
        job_id = _submit(client, "¿Cuántas alertas hay?").json()["job_id"]
        final = _poll_until_done(client, job_id).json()

    assert final["status"] == "done"
    assert final["result"]["response"] == "Respuesta para ¿Cuántas alertas hay?"
    assert final["elapsed_seconds"] >= 0.15


def test_the_same_client_message_id_never_answers_twice(monkeypatch):
    """Idempotency, from the outside.

    A double click, a retry after a dead connection and a reloaded tab all resubmit the
    same question. Each must attach to the run already in progress — running it again is
    what produced two answers to one question.
    """
    with _api(monkeypatch, delay=0.4) as (client, service):
        job_ids = {
            _submit(client, "¿Cuántas alertas hay?", "msg-identico").json()["job_id"]
            for _ in range(4)
        }
        assert len(job_ids) == 1, "the same question was given several jobs"
        _poll_until_done(client, job_ids.pop())
        calls = list(service.calls)

    assert len(calls) == 1, f"the agents ran {len(calls)} times for one question"


def test_distinct_questions_in_one_session_get_distinct_jobs(monkeypatch):
    """Idempotency must key on the question, not merely on the session."""
    with _api(monkeypatch, delay=0.1) as (client, service):
        job_ids = {
            _submit(client, f"consulta {index}", f"msg-{index}").json()["job_id"]
            for index in range(3)
        }
        assert len(job_ids) == 3
        for job_id in job_ids:
            _poll_until_done(client, job_id)
        calls = sorted(service.calls)

    assert calls == ["consulta 0", "consulta 1", "consulta 2"]


def test_an_unknown_job_is_a_404_not_an_error_state(monkeypatch):
    """The status code carries a meaning the dashboard acts on.

    404 says "look in the conversation history"; an error state says "this failed". A
    finished-then-forgotten answer is the first case, and treating it as the second is
    how a perfectly good answer got thrown away.
    """
    with _api(monkeypatch) as (client, _service_):
        response = client.post(
            "/api/v1/campbell-ai/message/status",
            json={"job_id": "job_inexistente"},
            headers=HEADERS,
        )

    assert response.status_code == 404
    assert "historial" in response.json()["detail"]


def test_a_failed_answer_is_reported_with_a_kind_the_view_can_act_on(monkeypatch):
    failure = CampbellBusyError("sin capacidad", retry_after=7)
    with _api(monkeypatch, delay=0.05, failure=failure) as (client, _service_):
        job_id = _submit(client).json()["job_id"]
        final = _poll_until_done(client, job_id).json()

    assert final["status"] == "error"
    assert final["error"]["kind"] == "busy"
    assert final["error"]["retryable"] is True
    assert final["error"]["retry_after"] == 7


def test_a_timed_out_answer_is_marked_retryable_but_distinct_from_busy(monkeypatch):
    """A timeout and a busy service need different advice, so they need different kinds.

    Repeating an identical question that just blew its budget will blow it again; the
    useful advice is to narrow it. "Ocupado" means the opposite — wait and resend.
    """
    failure = CampbellTimeoutError("agotó el tiempo", elapsed_seconds=180)
    with _api(monkeypatch, delay=0.05, failure=failure) as (client, _service_):
        job_id = _submit(client, "consulta enorme").json()["job_id"]
        final = _poll_until_done(client, job_id).json()

    assert final["status"] == "error"
    assert final["error"]["kind"] == "timeout"
    assert final["error"]["elapsed_seconds"] == 180


def test_cancelling_stops_a_running_answer(monkeypatch):
    with _api(monkeypatch, delay=5.0) as (client, _service_):
        job_id = _submit(client, "consulta larga").json()["job_id"]
        cancelled = client.post(
            "/api/v1/campbell-ai/message/cancel",
            json={"job_id": job_id},
            headers=HEADERS,
        )
        assert cancelled.status_code == 200
        assert cancelled.json()["cancelled"] is True
        final = _poll_until_done(client, job_id).json()

    assert final["status"] == "cancelled"


def test_an_oversized_message_is_rejected_at_submit_not_inside_the_job(monkeypatch):
    """Validation that needs no agents must produce a real HTTP error.

    Accepting a question that cannot possibly succeed, only to fail it on the first
    poll, hides a straightforward input error behind an asynchronous round trip.
    """
    with _api(monkeypatch) as (client, _service_):
        response = _submit(client, "x" * 5000)

    assert response.status_code == 422


def test_the_async_endpoints_require_the_internal_token(monkeypatch):
    with _api(monkeypatch) as (client, _service_):
        for path, body in (
            (
                "submit",
                {"username": "u", "company_id": "cda", "session_id": "s", "message": "m"},
            ),
            ("status", {"job_id": "job_x"}),
            ("cancel", {"job_id": "job_x"}),
        ):
            response = client.post(f"/api/v1/campbell-ai/message/{path}", json=body)
            assert response.status_code == 401, f"{path} is unauthenticated"


def test_health_advertises_the_async_capability(monkeypatch):
    with _api(monkeypatch) as (client, _service_):
        body = client.get("/api/v1/campbell-ai/health").json()

    assert body["async_messages"] is True
    assert body["answer_timeout_seconds"] > 0


def test_an_answer_completes_even_when_nobody_polls_for_it(monkeypatch):
    """The disconnect case, through the real API.

    Submit, then ask nothing for longer than the answer takes — the browser is gone.
    The work must finish anyway and still be collectable, because that vanished browser
    is exactly who comes back for it after a reload.
    """
    with _api(monkeypatch, delay=0.3) as (client, service):
        job_id = _submit(client, "consulta").json()["job_id"]
        time.sleep(0.6)  # nobody is listening for the whole duration of the answer
        final = client.post(
            "/api/v1/campbell-ai/message/status",
            json={"job_id": job_id},
            headers=HEADERS,
        ).json()
        calls = list(service.calls)

    assert final["status"] == "done", "the answer was abandoned when its caller left"
    assert final["result"]["response"] == "Respuesta para consulta"
    assert len(calls) == 1


# -- what the dashboard does with a lost job -----------------------------------


def test_the_view_recognises_a_question_the_thread_already_answered():
    """`_answers` is what turns a lost job into a recovered answer.

    When a job is forgotten, the dashboard reads the conversation and asks this: is my
    question already answered in there? A yes means show it — the old behaviour, showing
    an error and dropping the exchange, is what made users reload to find it.
    """
    from dashboard.campbell_ai.callbacks import _answers

    answered = [
        {"role": "user", "content": "¿Cuántas alertas hay?", "message_id": "m1"},
        {"role": "assistant", "content": "Hay 12 alertas.", "message_id": "m2"},
    ]
    assert _answers(answered, "¿Cuántas alertas hay?") is True
    # Whitespace differences must not defeat the match.
    assert _answers(answered, "  ¿Cuántas alertas hay?  ") is True
    # A different question is not answered by this thread.
    assert _answers(answered, "¿Y ayer?") is False
    assert _answers([], "¿Cuántas alertas hay?") is False


def test_a_question_still_awaiting_its_reply_is_not_treated_as_answered():
    """The dangerous false positive: claiming an unanswered question was answered."""
    from dashboard.campbell_ai.callbacks import _answers

    trailing = [
        {"role": "user", "content": "primera", "message_id": "m1"},
        {"role": "assistant", "content": "respuesta a la primera", "message_id": "m2"},
        {"role": "user", "content": "segunda", "message_id": "m3"},
    ]

    assert _answers(trailing, "primera") is True
    assert _answers(trailing, "segunda") is False, (
        "a question with no reply after it was reported as answered"
    )


def test_the_optimistic_bubble_never_counts_as_an_answer():
    """The pending bubble is client-side only and must be ignored when matching."""
    from dashboard.campbell_ai.callbacks import _answers

    optimistic = [
        {"role": "user", "content": "consulta", "message_id": "pending-abc"},
    ]

    assert _answers(optimistic, "consulta") is False


def test_a_live_failure_always_releases_the_composer():
    """No failure may leave the user with a dead input box.

    The composer is disabled while a message is in flight. If a failure arrives, the
    question is over — keeping it disabled is the "se pega" state itself.
    """
    from dashboard.campbell_ai.callbacks import _BLOCKING_FAILURES

    # A failure the user can act on must not be in the blocking set, or the composer
    # stays disabled with a retryable error on screen.
    for kind in ("timeout", "busy", "expired", "unavailable", "cancelled"):
        assert kind not in _BLOCKING_FAILURES, (
            f"{kind!r} disables the composer despite being recoverable"
        )
