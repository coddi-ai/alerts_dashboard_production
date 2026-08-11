"""Regression guards for the Campbell AI latency and concurrency work.

Deliberately small. One test per mechanism that was actually broken in production,
chosen so that a regression in any of them fails here rather than in front of a user.
Everything else about Campbell AI is covered by the older suites alongside this file.

The five failures these pin, in the order they were found:

1. Synchronous tool bodies ran inline on the event loop, so one user's pandas work
   froze the worker for everyone.
2. An agent run had no wall-clock bound, and retries could triple it.
3. Replayed history was bounded by message count, not size, so long conversations got
   slower every turn until they timed out.
4. The answer belonged to the HTTP request, so a caller that went away orphaned the run
   and its result was only discovered on the next page load.
5. The session lock was held across the whole agent run, so a second question in one
   conversation waited 20s and was then rejected however idle the service was.

Timings are coarse — tens of milliseconds against budgets several times larger — so the
suite stays honest on a loaded machine.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.campbell_ai.concurrency import (
    ConcurrencyGuard,
    ConcurrencyLimits,
    execute_with_retry,
)
from src.campbell_ai.errors import CampbellBusyError, CampbellTimeoutError
from src.campbell_ai.jobs import JobRegistry
from src.campbell_ai.models import ConversationMessage, DashboardPrincipal


PRINCIPAL = DashboardPrincipal(
    username="ana.perez", role="admin", company_id="cda", allowed_clients=["cda"]
)


# -- 1. the event loop stays free --------------------------------------------


def test_sync_tool_bodies_run_off_the_event_loop():
    """`_offloading` is the fix for the freeze; assert on it directly.

    The Agents SDK calls a non-async tool body inline, and every data tool here is a
    plain `def` doing pandas work. Wrapped, it must come back as a coroutine function —
    and the tool schema, which the SDK derives from the signature, annotations and
    docstring, must survive the wrapping untouched.
    """
    from src.campbell_ai.agents_runtime import _offloading

    registered = []
    decorate = _offloading(lambda func: registered.append(func) or func)

    @decorate
    def query_alerts(unit_id: str = "", limit: int = 20) -> str:
        """Alerts for a unit."""
        time.sleep(0.3)
        return f"{unit_id}:{limit}"

    wrapped = registered[0]
    assert inspect.iscoroutinefunction(wrapped), (
        "a sync tool body was registered as-is and will block the event loop"
    )
    assert list(inspect.signature(wrapped).parameters) == ["unit_id", "limit"]
    assert wrapped.__doc__ == "Alerts for a unit."

    async def scenario():
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        beat = asyncio.create_task(heartbeat())
        result = await wrapped(unit_id="CAEX-01", limit=5)
        beat.cancel()
        return result, ticks

    result, ticks = asyncio.run(scenario())

    assert result == "CAEX-01:5"
    # The loop kept serving other work during the blocking call. Inline it could not
    # have ticked at all.
    assert ticks > 5, f"the loop only ticked {ticks} times during a 0.3s tool call"


# -- 2. a run is bounded ------------------------------------------------------


def test_retries_cannot_overrun_the_wall_clock_budget():
    """Three attempts at a long run must not become three times the budget.

    An unbounded run outlived the caller that gave up on it, finished, and persisted an
    answer nobody was waiting for — which is how a question turned out to be already
    answered after a refresh.
    """
    attempts = []

    async def scenario():
        started = time.monotonic()

        async def always_throttled():
            attempts.append(1)
            await asyncio.sleep(0.15)
            raise RuntimeError("rate limit exceeded")

        with pytest.raises((CampbellTimeoutError, RuntimeError)):
            await execute_with_retry(
                always_throttled,
                attempts=5,
                initial_delay=0.05,
                label="la consulta a los agentes",
                deadline=time.monotonic() + 0.4,
            )
        return time.monotonic() - started

    elapsed = asyncio.run(scenario())

    assert elapsed < 1.0, f"retries overran the deadline: {elapsed:.2f}s"
    assert len(attempts) < 5, "every attempt ran despite the budget being spent"


def test_our_own_timeout_is_not_mistaken_for_a_transient_failure():
    """`CampbellTimeoutError` has "timeout" in its name and the check matches on text.

    Without an explicit exemption the retry loop immediately re-runs a question whose
    whole problem was having no time left.
    """
    from src.campbell_ai.concurrency import is_transient_failure

    assert is_transient_failure(CampbellTimeoutError("agotó el tiempo")) is False
    assert is_transient_failure(TimeoutError("upstream timed out")) is True


# -- 3. long conversations stay bounded ---------------------------------------


def _fat_answer(index: int, size: int = 6000) -> str:
    header = f"Respuesta {index}: alertas del periodo\n\n| unidad | severidad |\n"
    return header + "| CAEX-01 | alta |\n" * (max(1, size // 26))


def _long_conversation(turns: int) -> list[ConversationMessage]:
    messages = []
    for index in range(turns):
        messages.append(ConversationMessage(role="user", content=f"Pregunta {index}"))
        messages.append(
            ConversationMessage(role="assistant", content=_fat_answer(index))
        )
    return messages


def _runtime(tmp_path, **overrides):
    from src.campbell_ai.agents_runtime import CampbellAgentRuntime
    from src.campbell_ai.data import DashboardDataRepository
    from src.campbell_ai.sessions import InMemorySessionStore
    from tests.test_campbell_ai import _settings

    settings = _settings(tmp_path)
    for name, value in overrides.items():
        object.__setattr__(settings, name, value)
    return CampbellAgentRuntime(
        DashboardDataRepository(tmp_path),
        settings,
        session_store=InMemorySessionStore(ttl_seconds=1800, lock_wait_seconds=5),
    )


def test_the_replayed_prompt_stops_growing_with_the_conversation(tmp_path):
    """Latency must stop tracking chat length.

    History was bounded by message count, which says nothing about cost: twenty answers
    containing markdown tables is an enormous prompt, replayed into every later turn
    until an ordinary question crossed the timeout.
    """
    runtime = _runtime(tmp_path, max_history_messages=40, max_history_chars=24000)

    def size(turns):
        payload = runtime._conversation_input(_long_conversation(turns), "¿Y ahora?")
        return sum(len(item["content"]) for item in payload)

    small, large = size(4), size(40)

    assert large < 26000, f"a 40-turn conversation replayed {large} characters"
    # Tenfold conversation, flat prompt.
    assert large < small * 1.5, f"prompt still grows with the chat: {small} -> {large}"

    # The newest turn always survives trimming; the oldest is what goes.
    replayed = "\n".join(
        item["content"]
        for item in runtime._conversation_input(_long_conversation(10), "¿Y el detalle?")
    )
    assert "Pregunta 9" in replayed, "the newest turn was dropped"
    assert "Pregunta 0" not in replayed, "the oldest turn should have been trimmed"


# -- 4. the answer outlives its caller ----------------------------------------


class _SlowService:
    """A service with the timing profile of a real answer, wired to the real job code."""

    def __init__(self, delay=0.2, failure=None):
        from src.campbell_ai.config import get_campbell_settings
        from src.campbell_ai.service import CampbellAIService

        self.delay, self.failure, self.calls = delay, failure, []
        self.settings = get_campbell_settings()
        self.jobs = JobRegistry(retention_seconds=60.0)
        for name in ("submit_message", "message_status", "cancel_message"):
            setattr(
                self, name, getattr(CampbellAIService, name).__get__(self, _SlowService)
            )
        # A staticmethod: binding it would pass `self` as the exception.
        self._job_error = CampbellAIService._job_error
        self._ensure_enabled = lambda: None

    async def send_message(self, username, company_id, session_id, message):
        from src.campbell_ai.models import MessageResponse

        self.calls.append(message)
        await asyncio.sleep(self.delay)
        if self.failure:
            raise self.failure
        return MessageResponse(
            response=f"Respuesta para {message}",
            message_id="msg_test",
            session_id=session_id,
            company_id=company_id.lower(),
        )


@contextmanager
def _api(monkeypatch, **kwargs):
    """An API client sharing one event loop across requests, as uvicorn does.

    `TestClient` outside a `with` block spins a fresh loop per request and tears it down
    afterwards, cancelling the background answer the previous request started.
    """
    from src.campbell_ai.api import app
    from src.campbell_ai.config import reset_campbell_settings

    monkeypatch.setenv("CAMPBELL_AI_INTERNAL_TOKEN", "secret-token")
    reset_campbell_settings()
    service = _SlowService(**kwargs)
    app.state.service = service
    with TestClient(app) as client:
        yield client, service


HEADERS = {"X-Campbell-Token": "secret-token"}


def _submit(client, message="consulta", key="msg-1"):
    return client.post(
        "/api/v1/campbell-ai/message/submit",
        json={
            "username": "admin",
            "company_id": "CDA",
            "session_id": "campbell_test",
            "message": message,
            "client_message_id": key,
        },
        headers=HEADERS,
    )


def _poll(client, job_id, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.post(
            "/api/v1/campbell-ai/message/status",
            json={"job_id": job_id},
            headers=HEADERS,
        )
        if response.status_code == 404 or response.json()["status"] not in {
            "queued",
            "running",
        }:
            return response
        time.sleep(0.05)
    raise AssertionError("the job never reached a terminal state")


def test_an_answer_completes_and_waits_even_if_nobody_is_listening(monkeypatch):
    """Submit returns immediately, and the result survives the caller disappearing.

    Both halves of the fix in one test: accepting a question must not cost the length of
    answering it, and the browser that went away must still find its answer on return.
    """
    with _api(monkeypatch, delay=0.3) as (client, service):
        started = time.monotonic()
        accepted = _submit(client, "¿Cuántas alertas hay?")
        submit_cost = time.monotonic() - started

        assert accepted.status_code == 202
        assert submit_cost < 0.25, f"submit blocked for {submit_cost:.2f}s"

        time.sleep(0.6)  # nobody polls for the whole duration of the answer
        final = client.post(
            "/api/v1/campbell-ai/message/status",
            json={"job_id": accepted.json()["job_id"]},
            headers=HEADERS,
        ).json()
        calls = list(service.calls)

    assert final["status"] == "done", "the answer was abandoned when its caller left"
    assert final["result"]["response"] == "Respuesta para ¿Cuántas alertas hay?"
    assert len(calls) == 1


def test_resubmitting_the_same_question_never_answers_it_twice(monkeypatch):
    """A double click, a retry, or a reloaded tab must attach to the run in progress."""
    with _api(monkeypatch, delay=0.4) as (client, service):
        job_ids = {_submit(client, "misma", "msg-igual").json()["job_id"] for _ in range(4)}
        assert len(job_ids) == 1, "the same question was given several jobs"
        _poll(client, job_ids.pop())
        calls = list(service.calls)

    assert len(calls) == 1, f"the agents ran {len(calls)} times for one question"


def test_a_failed_answer_reports_a_kind_the_view_can_act_on(monkeypatch):
    """A crash must become a poll payload, never an unpolled silence."""
    failure = CampbellBusyError("sin capacidad", retry_after=7)
    with _api(monkeypatch, delay=0.05, failure=failure) as (client, _):
        final = _poll(client, _submit(client).json()["job_id"]).json()

    assert final["status"] == "error"
    assert final["error"]["kind"] == "busy"
    assert final["error"]["retryable"] is True


def test_a_forgotten_job_is_a_404_so_the_view_reads_the_history(monkeypatch):
    """404 means "look in the conversation", not "this failed".

    A finished-then-expired answer is the first case; treating it as the second is how a
    perfectly good answer got thrown away.
    """
    with _api(monkeypatch) as (client, _):
        response = client.post(
            "/api/v1/campbell-ai/message/status",
            json={"job_id": "job_inexistente"},
            headers=HEADERS,
        )

    assert response.status_code == 404
    assert "historial" in response.json()["detail"]


# -- 5. one conversation is not serialized ------------------------------------


def _runtime_with_slow_agent(tmp_path, answer_seconds=0.3):
    """Real session store, locking and append path; only the agent run is stubbed."""

    async def no_gatekeeper(Runner, bundle, message, deadline=None):
        return None

    async def no_archive(principal, session_id, messages):
        return None

    class _Runner:
        @staticmethod
        async def run(starting_agent=None, input=None, max_turns=None):
            await asyncio.sleep(answer_seconds)
            return SimpleNamespace(final_output="respuesta")

    runtime = _runtime(tmp_path, max_history_messages=40)
    runtime._build_bundle = lambda principal: (
        SimpleNamespace(head="head", gatekeeper="gate"),
        _Runner,
        [],
        [],
        [],
    )
    runtime._gatekeeper_refusal = no_gatekeeper
    runtime._archive_exchange = no_archive
    runtime._audit = lambda response, tool_outputs, question="": SimpleNamespace(
        as_dict=lambda: {}, is_grounded=True
    )
    return runtime


def test_several_questions_in_one_conversation_run_in_parallel(tmp_path, monkeypatch):
    """The reported failure: one account firing several questions at once.

    The session lock used to be held for the whole agent run, so a second question in
    the same conversation waited out the lock timeout and was rejected however idle the
    service was — six questions produced one answer and five rejections. Serializing a
    conversation is right for *writes*; it was never right for the run itself.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")

    async def scenario():
        runtime = _runtime_with_slow_agent(tmp_path, answer_seconds=0.3)
        await runtime.initialize(PRINCIPAL, "campbell_uno")
        started = time.monotonic()
        results = await asyncio.gather(
            *(runtime.answer(PRINCIPAL, "campbell_uno", f"consulta {i}") for i in range(6)),
            return_exceptions=True,
        )
        return results, time.monotonic() - started, await runtime.history(
            PRINCIPAL, "campbell_uno"
        )

    results, elapsed, history = asyncio.run(scenario())

    failures = [item for item in results if isinstance(item, BaseException)]
    assert not failures, f"questions in one conversation were rejected: {failures}"
    # Six 0.3s answers: concurrent is ~0.3s, serialized would be ~1.8s.
    assert elapsed < 1.0, (
        f"six questions took {elapsed:.2f}s; still serialized behind the session lock"
    )

    # Nothing lost. This is what the re-read inside `_commit_exchange` protects: all six
    # started from the same snapshot, and appending to that stale copy would let the
    # last writer overwrite the rest.
    contents = [item.content for item in history]
    for index in range(6):
        assert f"consulta {index}" in contents, f"question {index} vanished from the thread"
    assert len(history) == 12


def test_a_follow_up_still_sees_the_previous_answer(tmp_path, monkeypatch):
    """Dropping the lock must not cost sequential conversations their context."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")
    seen = []

    async def scenario():
        runtime = _runtime_with_slow_agent(tmp_path, answer_seconds=0.01)
        original = runtime._conversation_input
        runtime._conversation_input = lambda messages, message: (
            seen.append(len(messages)) or original(messages, message)
        )
        await runtime.initialize(PRINCIPAL, "campbell_dos")
        await runtime.answer(PRINCIPAL, "campbell_dos", "primera")
        await runtime.answer(PRINCIPAL, "campbell_dos", "segunda")

    asyncio.run(scenario())

    assert seen == [0, 2], (
        f"the follow-up saw {seen[-1]} prior messages; it must see the first exchange"
    )


def test_one_user_cannot_take_every_slot_and_is_told_so_immediately(tmp_path):
    """Admission control is the bound now that the lock is not. It must reject fast."""

    async def scenario():
        guard = ConcurrencyGuard(
            ConcurrencyLimits(
                max_concurrent=10, max_concurrent_per_user=2, queue_timeout_seconds=5.0
            )
        )

        async def hold():
            async with guard.slot("ana|cda"):
                await asyncio.sleep(0.2)

        tasks = [asyncio.create_task(hold()) for _ in range(4)]
        return await asyncio.gather(*tasks, return_exceptions=True)

    outcomes = asyncio.run(scenario())
    rejected = [item for item in outcomes if isinstance(item, CampbellBusyError)]

    assert len(rejected) == 2, "the per-user cap should admit exactly two"
    assert all(item.scope == "user" for item in rejected)
    assert all(item.retry_after > 0 for item in rejected)


# -- configuration ------------------------------------------------------------


def test_the_dashboard_and_the_api_agree_on_the_internal_token(monkeypatch):
    """With no configuration at all, both halves must resolve the same secret.

    They read the variable in different processes with fallbacks in different files.
    Leaving it without a default was tried and broke production: not every deployment
    goes through docker-compose, so a container started any other way had no token and
    the API answered 503 to everything while `/health` still said "ok".
    """
    from dashboard.campbell_ai.client import CampbellAPIClient
    from src.campbell_ai.config import (
        DEFAULT_INTERNAL_TOKEN,
        CampbellSettings,
        reset_campbell_settings,
    )

    for name in list(__import__("os").environ):
        if name.startswith("CAMPBELL_"):
            monkeypatch.delenv(name, raising=False)
    reset_campbell_settings()

    assert (
        CampbellSettings.from_env().internal_token
        == CampbellAPIClient.from_env().internal_token
        == DEFAULT_INTERNAL_TOKEN
    )

    monkeypatch.setenv("CAMPBELL_AI_INTERNAL_TOKEN", "un-secreto-propio")
    assert CampbellSettings.from_env().internal_token == "un-secreto-propio"
    assert CampbellAPIClient.from_env().internal_token == "un-secreto-propio"


def test_no_setting_declares_two_different_defaults():
    """One default per setting, on the field; `from_env` reads it from there.

    Two copies drift silently. `max_concurrent_per_user` was declared 5 on the field
    while `from_env` fell back to 2, and deployments only saw 5 because an ENV line in
    the Dockerfile propped it up.
    """
    from dataclasses import MISSING, fields

    from src.campbell_ai.config import CampbellSettings

    # Storage is deliberately off for a directly-constructed settings object and on for
    # a deployment; everything else must agree.
    deployment_overrides = {
        "persistence_enabled",
        "persistence_local_dir",
        "conversation_summary_enabled",
    }
    resolved = CampbellSettings.from_env()

    drifted = []
    for item in fields(CampbellSettings):
        if item.default is MISSING or item.name in deployment_overrides:
            continue
        current = getattr(resolved, item.name)
        numeric = isinstance(item.default, (int, float)) and not isinstance(
            item.default, bool
        )
        same = (
            float(item.default) == float(current)
            if numeric and isinstance(current, (int, float))
            else item.default == current
        )
        if not same:
            drifted.append((item.name, item.default, current))

    assert not drifted, (
        f"these settings declare two different defaults: {drifted}. Read the fallback "
        "from `_declared()` instead of repeating the literal."
    )


# -- 6. stale browser state ---------------------------------------------------
# `sessionStorage` is scoped to the tab and to nothing else, so it survives a logout
# and a redeploy as happily as it survives the reload it exists for.


def test_stored_state_is_discarded_when_the_tab_changes_hands_or_builds():
    """A conversation belongs to a user and a build; the tab remembers neither.

    Logging out and back in as somebody else used to leave the previous user's thread
    in the tab — and the view would re-render it, because when the API has no history
    for a session id it falls back to the copy the browser is holding.
    """
    from dashboard.campbell_ai.callbacks import _stale_browser_state, _state_stamp
    from dashboard.campbell_ai.layout import CAMPBELL_AI_VERSION

    mine = _state_stamp("ana.perez")

    assert _stale_browser_state(mine, "ana.perez") is None, "own state must survive"
    assert "usuario" in _stale_browser_state(mine, "otro.usuario")
    assert "version" in _stale_browser_state(
        {"user": "ana.perez", "version": "0.0.1"}, "ana.perez"
    )
    # A tab predating the stamp holds state of unknown provenance.
    assert _stale_browser_state(None, "ana.perez") == "sin sello previo"
    assert mine["version"] == CAMPBELL_AI_VERSION


def test_a_background_job_is_not_polled_by_a_different_user():
    """The job handle also lives in sessionStorage, so it outlives a logout too.

    Polling it as the new user would show them somebody else's answer.
    """
    import dash
    from dash import dcc, html

    from dashboard.campbell_ai.callbacks import register_campbell_ai_callbacks
    from dashboard.campbell_ai.layout import create_campbell_ai_layout

    app = dash.Dash(__name__, suppress_callback_exceptions=True)
    app.layout = html.Div(
        [dcc.Dropdown(id="client-selector"), create_campbell_ai_layout({})]
    )
    register_campbell_ai_callbacks(app)

    poll = next(
        getattr(m["callback"], "__wrapped__", m["callback"])
        for m in app.callback_map.values()
        if m.get("callback")
        and getattr(m["callback"], "__wrapped__", m["callback"]).__name__
        == "poll_pending_job"
    )

    import dashboard.campbell_ai.callbacks as module

    original = module._current_username
    module._current_username = lambda *_a, **_k: "usuario.nuevo"
    try:
        result = poll(
            1,
            {
                "job_id": "job_del_anterior",
                "username": "usuario.anterior",
                "session_id": "s",
                "question": "q",
            },
            [],
            {},
            0,
        )
    finally:
        module._current_username = original

    # The job handle and any in-flight markers are cleared, and nothing is rendered
    # from it. Indexes: 4=failure, 5=pending, 6=job, 7=waiting panel.
    assert result[5] is None and result[6] is None, "a foreign job was kept"
    assert result[7] is False


def test_the_app_shell_is_never_cached_but_assets_still_are():
    """A stale page asking for the previous build's JavaScript is a silent breakage.

    Dash cache-busts `assets/` by mtime, which only helps if the browser re-fetches the
    page carrying those URLs. The index used to go out with no cache headers at all.
    """
    import dashboard.app as dashboard_app

    client = dashboard_app.app.server.test_client()

    for path in ("/", "/agents/campbell-ai", "/_dash-layout", "/_dash-dependencies"):
        header = client.get(path).headers.get("Cache-Control", "")
        assert "no-store" in header, f"{path} may be cached across a deploy ({header!r})"

    # The large, fingerprinted files must stay cacheable or every page load re-downloads
    # the component bundles.
    assert "no-store" not in client.get("/assets/campbell_ai_stream.js").headers.get(
        "Cache-Control", ""
    )


# -- 7. the sidebar reflects what is actually stored --------------------------


def _archive(tmp_path):
    """Two backends, as in production: a primary and a local mirror behind it."""
    from src.campbell_ai.persistence import ConversationArchive, LocalArchiveBackend

    primary = LocalArchiveBackend(tmp_path / "primary")
    archive = ConversationArchive(
        [primary, LocalArchiveBackend(tmp_path / "mirror")], base_prefix="campbellAI"
    )
    for index in range(3):
        archive.save_exchange(
            PRINCIPAL,
            f"sesion{index}",
            [
                ConversationMessage(role="user", content=f"pregunta {index}"),
                ConversationMessage(role="assistant", content=f"respuesta {index}"),
            ],
        )
    stored = tmp_path / "primary" / "campbellAI" / "conversations" / "cda" / PRINCIPAL.username
    return archive, primary, stored


def test_refreshing_reflects_a_conversation_deleted_from_the_bucket(tmp_path):
    """Deleting in S3 has to reach the sidebar, and has to stay deleted.

    Two things kept the row alive: the listing is served from an index document rather
    than from the objects, and reads fall back to the local mirror when the primary
    answers nothing — which is indistinguishable from the primary being empty. So
    emptying the bucket just handed the question to the disk copy.
    """
    import shutil

    archive, _, stored = _archive(tmp_path)
    assert len(archive.list_conversations(PRINCIPAL)) == 3

    shutil.rmtree(stored / "sesion1")
    (stored / "index.json").unlink(missing_ok=True)

    refreshed = sorted(row.session_id for row in archive.list_conversations(PRINCIPAL, refresh=True))
    assert refreshed == ["sesion0", "sesion2"], "the deleted conversation survived"

    # And the mirror must not bring it back on the next ordinary read. An index that
    # exists and lists nothing is an answer, not a reason to rebuild from disk.
    after = sorted(row.session_id for row in archive.list_conversations(PRINCIPAL))
    assert after == ["sesion0", "sesion2"], "the mirror resurrected a deleted row"

    for name in ("sesion0", "sesion2"):
        shutil.rmtree(stored / name)
    assert archive.list_conversations(PRINCIPAL, refresh=True) == []
    assert archive.list_conversations(PRINCIPAL) == []


def test_a_storage_outage_is_not_mistaken_for_an_empty_bucket(tmp_path):
    """Refresh must never wipe the listing because the primary was briefly unreachable.

    "Nothing came back" has two very different causes and only one of them means the
    conversations are gone.
    """
    archive, primary, _ = _archive(tmp_path)

    def unreachable(prefix):
        raise OSError("S3 no responde")

    primary.list_keys = unreachable

    assert len(archive.list_conversations(PRINCIPAL, refresh=True)) == 3, (
        "an outage was treated as the user having deleted everything"
    )
