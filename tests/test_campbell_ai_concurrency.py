"""Tests for admission control under parallel use.

The failure these guard against is not a crash: it is every user's request slowing down
together until they all time out, with nobody able to tell whether waiting would help.
So the properties asserted here are that load is bounded, that one user cannot occupy the
whole service, that a rejection is fast and labelled as load rather than as a fault, and
that a bounded rejection reaches the dashboard as something retryable.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from src.campbell_ai.api import app
from src.campbell_ai.concurrency import (
    ConcurrencyGuard,
    ConcurrencyLimits,
    execute_with_retry,
    is_transient_failure,
)
from src.campbell_ai.config import CampbellSettings, reset_campbell_settings
from src.campbell_ai.errors import CampbellBusyError
from src.campbell_ai.models import MessageResponse
from src.campbell_ai.sessions import InMemorySessionStore


KEY = ("ana.perez", "cda", "s1")


# ------------------------------------------------------------------- admission


def test_limits_are_read_from_settings():
    limits = ConcurrencyLimits.from_settings(
        CampbellSettings(
            enabled=True,
            data_root="data",
            feedback_path="logs/f.jsonl",
            internal_token="t",
            session_ttl_seconds=1800,
            max_history_messages=20,
            max_message_chars=4000,
            model_gatekeeper="m",
            model_head="m",
            model_planner="m",
            model_data_analyst="m",
            model_technical_expert="m",
            model_dashboard_guide="m",
            max_turns_data_analyst=10,
            max_turns_head=10,
            session_backend="memory",
            redis_url="",
            redis_namespace="ns",
            session_lock_timeout_seconds=300,
            streaming_enabled=False,
            max_concurrent_requests=4,
            max_concurrent_per_user=1,
        )
    )

    assert limits.max_concurrent == 4
    assert limits.max_concurrent_per_user == 1


def test_concurrent_answers_are_capped_at_the_configured_limit():
    guard = ConcurrencyGuard(ConcurrencyLimits(max_concurrent=2, max_concurrent_per_user=4))
    observed: list[int] = []

    async def scenario():
        active = 0

        async def work(index):
            nonlocal active
            # Distinct users, so the per-user cap is not what bounds this.
            async with guard.slot(f"user{index}|cda"):
                active += 1
                observed.append(active)
                await asyncio.sleep(0.02)
                active -= 1

        await asyncio.gather(*(work(index) for index in range(6)))

    asyncio.run(scenario())

    assert len(observed) == 6
    # Never more than two answers in flight, even with six callers.
    assert max(observed) == 2


def test_one_user_cannot_occupy_every_slot():
    """A user with several tabs must not be able to starve the rest of the fleet."""
    guard = ConcurrencyGuard(
        ConcurrencyLimits(max_concurrent=10, max_concurrent_per_user=2)
    )

    async def scenario():
        held = []

        async def hold():
            async with guard.slot("ana.perez|cda"):
                held.append(1)
                await asyncio.sleep(0.05)

        first = asyncio.create_task(hold())
        second = asyncio.create_task(hold())
        await asyncio.sleep(0.01)
        with pytest.raises(CampbellBusyError) as excinfo:
            async with guard.slot("ana.perez|cda"):
                pass
        await asyncio.gather(first, second)
        return excinfo.value

    error = asyncio.run(scenario())

    assert error.scope == "user"
    # The wording has to say what the user should do, not name an internal limit.
    assert "en curso" in str(error)


def test_a_different_user_is_still_served_while_another_is_at_their_limit():
    guard = ConcurrencyGuard(
        ConcurrencyLimits(max_concurrent=10, max_concurrent_per_user=1)
    )

    async def scenario():
        async def hold(user):
            async with guard.slot(user):
                await asyncio.sleep(0.03)
            return True

        first = asyncio.create_task(hold("ana.perez|cda"))
        await asyncio.sleep(0.005)
        served = await hold("bruno.diaz|cda")
        await first
        return served

    assert asyncio.run(scenario()) is True


def test_saturation_fails_fast_instead_of_queueing_forever():
    """A rejection the user can act on beats a wait that ends in a timeout."""
    guard = ConcurrencyGuard(
        ConcurrencyLimits(
            max_concurrent=1, max_concurrent_per_user=5, queue_timeout_seconds=1
        )
    )

    async def scenario():
        async def hold():
            # Longer than the queue timeout, so waiting cannot succeed.
            async with guard.slot("ana.perez|cda"):
                await asyncio.sleep(1.4)

        holder = asyncio.create_task(hold())
        await asyncio.sleep(0.01)
        started = asyncio.get_running_loop().time()
        with pytest.raises(CampbellBusyError) as excinfo:
            async with guard.slot("bruno.diaz|cda"):
                pass
        elapsed = asyncio.get_running_loop().time() - started
        await holder
        return excinfo.value, elapsed

    error, elapsed = asyncio.run(scenario())

    assert error.scope == "global"
    assert error.retry_after >= 1
    # Bounded by the queue timeout, not by however long the answer takes.
    assert elapsed < 1.5


def test_the_per_minute_window_rejects_once_the_quota_is_spent():
    guard = ConcurrencyGuard(
        ConcurrencyLimits(
            max_requests_per_minute=2, queue_timeout_seconds=1, max_concurrent_per_user=5
        )
    )

    async def scenario():
        for _ in range(2):
            async with guard.slot("ana.perez|cda"):
                pass
        with pytest.raises(CampbellBusyError, match="por minuto"):
            async with guard.slot("ana.perez|cda"):
                pass

    asyncio.run(scenario())


def test_a_rejected_request_frees_the_user_counter():
    """A rejection that leaked its counter would lock the user out permanently."""
    guard = ConcurrencyGuard(
        ConcurrencyLimits(
            max_requests_per_minute=1, queue_timeout_seconds=1, max_concurrent_per_user=1
        )
    )

    async def scenario():
        async with guard.slot("ana.perez|cda"):
            pass
        with pytest.raises(CampbellBusyError):
            async with guard.slot("ana.perez|cda"):
                pass
        return guard.stats()

    stats = asyncio.run(scenario())

    assert stats["active_users"] == 0
    assert stats["in_flight"] == 0
    assert stats["rejected"] == 1


def test_stats_report_load_without_identifying_anyone():
    guard = ConcurrencyGuard(ConcurrencyLimits(max_concurrent=3))

    async def scenario():
        async with guard.slot("ana.perez|cda"):
            return guard.stats()

    stats = asyncio.run(scenario())

    assert stats["in_flight"] == 1
    assert stats["peak_in_flight"] == 1
    assert stats["max_concurrent"] == 3
    assert "ana.perez" not in str(stats)


# ------------------------------------------------------------------- retrying


def test_only_transient_failures_are_retried():
    assert is_transient_failure(TimeoutError("timed out")) is True
    assert is_transient_failure(RuntimeError("Rate limit reached")) is True
    assert is_transient_failure(RuntimeError("502 Bad Gateway")) is True
    assert is_transient_failure(ValueError("columna inexistente")) is False
    # Our own admission control: an immediate retry would only be rejected again.
    assert is_transient_failure(CampbellBusyError("ocupado")) is False


def test_a_throttled_call_succeeds_on_a_later_attempt():
    attempts = {"count": 0}

    async def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("Rate limit reached for gpt-4.1")
        return "respuesta"

    result = asyncio.run(
        execute_with_retry(flaky, attempts=3, initial_delay=0.0, max_delay=0.0)
    )

    assert result == "respuesta"
    assert attempts["count"] == 3


def test_a_permanent_failure_is_raised_immediately():
    attempts = {"count": 0}

    async def broken():
        attempts["count"] += 1
        raise ValueError("dataset no registrado")

    with pytest.raises(ValueError):
        asyncio.run(execute_with_retry(broken, attempts=3, initial_delay=0.0))

    # No point spending three model calls on an error that cannot change.
    assert attempts["count"] == 1


def test_retries_stop_at_the_configured_attempt_count():
    attempts = {"count": 0}

    async def always_throttled():
        attempts["count"] += 1
        raise RuntimeError("429 too many requests")

    with pytest.raises(RuntimeError):
        asyncio.run(
            execute_with_retry(
                always_throttled, attempts=2, initial_delay=0.0, max_delay=0.0
            )
        )

    assert attempts["count"] == 2


# --------------------------------------------------------------- session locks


def test_a_second_request_for_the_same_conversation_is_told_to_wait():
    """Two tabs of one user share a conversation; interleaving would corrupt it."""
    store = InMemorySessionStore(ttl_seconds=1800, lock_wait_seconds=1)

    async def scenario():
        async def hold():
            async with store.lock(KEY):
                await asyncio.sleep(1.4)

        holder = asyncio.create_task(hold())
        await asyncio.sleep(0.01)
        with pytest.raises(CampbellBusyError, match="ocupada"):
            async with store.lock(KEY):
                pass
        await holder

    asyncio.run(scenario())


def test_the_session_lock_is_released_after_a_bounded_wait_failure():
    store = InMemorySessionStore(ttl_seconds=1800, lock_wait_seconds=1)

    async def scenario():
        async with store.lock(KEY):
            pass
        # A failed acquisition must not leave the lock held for the next request.
        async with store.lock(KEY):
            return True

    assert asyncio.run(scenario()) is True


# ------------------------------------------------------------------ API and UI


class BusyService:
    def __init__(self):
        self.concurrency = ConcurrencyGuard(ConcurrencyLimits(max_concurrent=1))

    async def send_message(self, username, company_id, session_id, message):
        raise CampbellBusyError("Campbell AI está atendiendo muchas consultas", retry_after=7)


class QuietService:
    async def send_message(self, username, company_id, session_id, message):
        return MessageResponse(
            response="ok",
            message_id="msg_1",
            session_id=session_id,
            company_id=company_id.lower(),
        )


def test_the_api_answers_saturation_with_429_and_retry_after(monkeypatch):
    monkeypatch.setenv("CAMPBELL_AI_INTERNAL_TOKEN", "secret-token")
    reset_campbell_settings()
    app.state.service = BusyService()
    client = TestClient(app)

    response = client.post(
        "/api/v1/campbell-ai/message",
        headers={"X-Campbell-Token": "secret-token"},
        json={
            "username": "ana.perez",
            "company_id": "CDA",
            "session_id": "s1",
            "message": "¿Cuántas alertas hay?",
        },
    )

    # 429 rather than 503: nothing is broken, the caller only has to wait.
    assert response.status_code == 429
    assert response.headers["Retry-After"] == "7"


def test_capabilities_expose_current_load(monkeypatch):
    monkeypatch.setenv("CAMPBELL_AI_INTERNAL_TOKEN", "secret-token")
    reset_campbell_settings()
    app.state.service = BusyService()
    client = TestClient(app)

    payload = client.get(
        "/api/v1/campbell-ai/capabilities",
        headers={"X-Campbell-Token": "secret-token"},
    ).json()

    assert payload["concurrency"]["max_concurrent"] == 1


def test_capabilities_survive_a_service_without_admission_control(monkeypatch):
    monkeypatch.setenv("CAMPBELL_AI_INTERNAL_TOKEN", "secret-token")
    reset_campbell_settings()
    app.state.service = QuietService()
    client = TestClient(app)

    response = client.get(
        "/api/v1/campbell-ai/capabilities",
        headers={"X-Campbell-Token": "secret-token"},
    )

    assert response.status_code == 200
    assert response.json()["concurrency"] == {}


def test_the_quality_suite_is_not_throttled_by_its_own_user_cap():
    """Every case runs as one user; the default cap of two would fail cases 3 and 4."""
    from tests.quality.runner import QualityRunner

    class StubService:
        concurrency = ConcurrencyGuard(
            ConcurrencyLimits(max_concurrent=10, max_concurrent_per_user=2)
        )

    class StubRunner:
        service = StubService()
        _admit_batch = QualityRunner._admit_batch

    runner = StubRunner()
    runner._admit_batch(4)

    limits = runner.service.concurrency.limits
    assert limits.max_concurrent_per_user == 4
    # Widened, never narrowed: a deployment with a higher bound keeps it.
    assert limits.max_concurrent == 10


def test_the_dashboard_treats_saturation_as_retryable_and_keeps_composing():
    from dashboard.campbell_ai.callbacks import _BLOCKING_FAILURES, _status_label
    from dashboard.campbell_ai.client import _failure

    error = _failure("busy")

    assert error.retryable is True
    assert "reintenta" in error.guidance.lower()
    assert _status_label(error) == "Servicio ocupado"
    # The composer stays usable: the same question will work in a few seconds.
    assert "busy" not in _BLOCKING_FAILURES
