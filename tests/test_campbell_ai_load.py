"""Load behaviour of the Campbell AI API under several simultaneous users.

The production report these cover is "the interface freezes with a handful of people
using it at once". Three distinct mechanisms produced that, and each has a test here:

1. **The event loop was blocked.** Every data tool is a synchronous ``def`` doing pandas
   work, and the Agents SDK calls a non-async tool body inline. One user's query
   therefore stalled the whole worker — not just their own answer, but every other
   user's request, including ones that had nothing to do with the agents.
2. **Nothing bounded a run's wall clock.** A slow answer held its slot indefinitely,
   so slots leaked out of the pool under load.
3. **Work was owned by the HTTP request.** A caller that gave up left the run going;
   it finished, persisted, and was never collected — the "already answered after a
   refresh" symptom.

The agents themselves are stubbed. The point is not what they answer, it is whether
five concurrent answers *overlap* or *queue*, and no assertion here should depend on a
model call. Timings are deliberately coarse (tens of milliseconds against budgets
several times larger) so the suite stays honest on a loaded CI machine.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from src.campbell_ai.concurrency import ConcurrencyGuard, ConcurrencyLimits
from src.campbell_ai.errors import CampbellBusyError
from src.campbell_ai.jobs import JobRegistry


# How many users the API must comfortably serve at once. The requirement under test.
CONCURRENT_USERS = 5


class StubAnswerService:
    """Stands in for CampbellAIService with the timing profile of a real answer.

    ``model_latency`` is awaited (a network round trip: the loop is free meanwhile) and
    ``cpu_work`` is a *blocking* sleep run through ``asyncio.to_thread``, standing in for
    the pandas filtering the data tools do. Modelling both matters: only the blocking
    half can freeze other users, so a test that simulated the work with ``asyncio.sleep``
    alone would pass just as happily against the broken version.
    """

    def __init__(self, model_latency: float = 0.05, cpu_work: float = 0.05):
        self.model_latency = model_latency
        self.cpu_work = cpu_work
        self.concurrency = ConcurrencyGuard(
            ConcurrencyLimits(
                max_concurrent=10,
                max_concurrent_per_user=2,
                max_requests_per_minute=500,
                queue_timeout_seconds=10.0,
            )
        )
        self.jobs = JobRegistry(retention_seconds=60.0)
        self.started: list[tuple[str, float]] = []
        self.finished: list[tuple[str, float]] = []

    async def answer(self, user: str, message: str) -> dict:
        async with self.concurrency.slot(user):
            self.started.append((f"{user}:{message}", time.monotonic()))
            await asyncio.sleep(self.model_latency)
            # The tool work, offloaded exactly as `_offloading` now does it.
            await asyncio.to_thread(time.sleep, self.cpu_work)
            await asyncio.sleep(self.model_latency)
            self.finished.append((f"{user}:{message}", time.monotonic()))
            return {"response": f"respuesta a {message}", "user": user}


def _overlap_window(service: StubAnswerService) -> float:
    """Seconds between the first answer starting and the last one starting.

    Near zero means the answers ran together. Approaching the total run time means they
    queued behind one another, which is the failure this file is about.
    """
    starts = [moment for _, moment in service.started]
    return max(starts) - min(starts)


# -- five distinct users at once ---------------------------------------------


def test_five_distinct_users_are_answered_concurrently():
    """Five different people asking at the same time must overlap, not queue."""

    async def scenario():
        service = StubAnswerService(model_latency=0.1, cpu_work=0.1)
        started = time.monotonic()
        results = await asyncio.gather(
            *(
                service.answer(f"usuario{index}|cda", f"consulta {index}")
                for index in range(CONCURRENT_USERS)
            )
        )
        return service, results, time.monotonic() - started

    service, results, elapsed = asyncio.run(scenario())

    assert len(results) == CONCURRENT_USERS
    assert len({result["user"] for result in results}) == CONCURRENT_USERS

    # One answer is ~0.3s (0.1 model + 0.1 tool + 0.1 model). Five of them overlapping
    # should still land near that; five serialized would take ~1.5s.
    assert elapsed < 0.6, (
        f"five concurrent users took {elapsed:.2f}s; answers are serializing "
        "instead of overlapping"
    )
    # All five got going together rather than each waiting for the previous to finish.
    assert _overlap_window(service) < 0.15


async def _heavy_query_alongside_light_ones(offload: bool) -> tuple[float, float]:
    """One 0.5s CPU-bound tool plus four light queries, all dispatched together.

    Returns (when the last light query finished, when the heavy one finished), both
    relative to a single start. `offload` selects the new behaviour (tool body in a
    worker thread) or the old one (tool body inline on the event loop), so the two can
    be compared directly rather than asserted about in the abstract.
    """
    started = time.monotonic()

    async def heavy():
        await asyncio.sleep(0.01)  # the model round trip that precedes the tool call
        if offload:
            await asyncio.to_thread(time.sleep, 0.5)
        else:
            time.sleep(0.5)  # what agents/tool.py does with a sync tool body
        return time.monotonic() - started

    async def light():
        await asyncio.sleep(0.01)
        return time.monotonic() - started

    heavy_task = asyncio.create_task(heavy())
    light_times = await asyncio.gather(*(light() for _ in range(4)))
    return max(light_times), await heavy_task


def test_a_blocking_tool_does_not_stall_other_users():
    """The regression test for the freeze: one heavy query must not delay the rest.

    Four light queries are dispatched at the same instant as one whose tool blocks for
    half a second. With the tool body offloaded to a thread the light ones finish
    immediately; with it inline on the event loop — the SDK's behaviour for a sync tool,
    which every data tool here is — none of them can finish until the heavy one lets go.

    The paired assertion against the old behaviour is what gives this test its teeth: it
    is easy to write a timing test that passes either way.
    """
    fixed_light, fixed_heavy = asyncio.run(_heavy_query_alongside_light_ones(offload=True))
    broken_light, _ = asyncio.run(_heavy_query_alongside_light_ones(offload=False))

    assert fixed_light < 0.1, (
        f"light queries took {fixed_light:.2f}s while one heavy query ran; the "
        "blocking tool is still holding the event loop"
    )
    assert fixed_heavy >= 0.5, "the heavy query should still take its full time"
    # Same scenario without the offload: the light queries are dragged out behind the
    # heavy one. If this ever stops being true the test above has lost its meaning.
    assert broken_light >= 0.5, (
        "the inline-tool control case no longer blocks; this test proves nothing"
    )


def test_the_tool_decorator_moves_sync_bodies_off_the_event_loop():
    """`_offloading` is the actual fix; assert on it directly, not only on timings.

    A sync tool body must come back as a coroutine function (so the SDK awaits it
    instead of calling it inline) while keeping the signature and docstring the tool
    schema is generated from.
    """
    from src.campbell_ai.agents_runtime import _offloading

    registered: list = []

    def fake_function_tool(func):
        registered.append(func)
        return func

    decorate = _offloading(fake_function_tool)

    @decorate
    def query_alerts(unit_id: str = "", limit: int = 20) -> str:
        """Alerts for a unit."""
        time.sleep(0.3)
        return f"{unit_id}:{limit}"

    @decorate
    async def data_analysis(question: str) -> str:
        """Already async; must be passed through untouched."""
        return question

    import inspect

    wrapped_sync = registered[0]
    assert inspect.iscoroutinefunction(wrapped_sync), (
        "a sync tool body was registered as-is and will block the event loop"
    )
    # The schema the SDK derives must be unchanged: it reads the signature (which
    # follows __wrapped__), the annotations and the docstring.
    assert list(inspect.signature(wrapped_sync).parameters) == ["unit_id", "limit"]
    assert wrapped_sync.__doc__ == "Alerts for a unit."
    assert inspect.signature(wrapped_sync).parameters["limit"].default == 20
    assert registered[1] is data_analysis, "an async tool body should not be rewrapped"

    async def check_it_yields():
        started = time.monotonic()
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        beat = asyncio.create_task(heartbeat())
        result = await wrapped_sync(unit_id="CAEX-01", limit=5)
        beat.cancel()
        return result, ticks, time.monotonic() - started

    result, ticks, elapsed = asyncio.run(check_it_yields())

    assert result == "CAEX-01:5"
    assert elapsed >= 0.3
    # The loop kept running other work throughout the blocking call. Inline, it could
    # not have ticked at all.
    assert ticks > 5, f"the event loop only ticked {ticks} times during a 0.3s tool call"


# -- the same user, several distinct questions --------------------------------


def test_one_user_sending_distinct_questions_is_capped_not_queued():
    """One person cannot occupy the pool, and is told so rather than left hanging.

    `max_concurrent_per_user=2` allows a legitimate second tab. The third simultaneous
    question is rejected immediately with a retryable busy error — deliberately not
    queued: the user is not waiting on it, and holding it would occupy a slot someone
    else could use.
    """

    async def scenario():
        service = StubAnswerService(model_latency=0.15, cpu_work=0.05)
        questions = [f"consulta distinta {index}" for index in range(CONCURRENT_USERS)]
        outcomes = await asyncio.gather(
            *(service.answer("ana.perez|cda", question) for question in questions),
            return_exceptions=True,
        )
        return outcomes

    outcomes = asyncio.run(scenario())

    answered = [item for item in outcomes if isinstance(item, dict)]
    rejected = [item for item in outcomes if isinstance(item, CampbellBusyError)]

    assert len(answered) == 2, "the per-user limit should admit exactly two"
    assert len(rejected) == CONCURRENT_USERS - 2
    assert all(error.scope == "user" for error in rejected)
    # Rejection must be immediate and actionable, not a silent stall.
    assert all(error.retry_after > 0 for error in rejected)


def test_one_busy_user_does_not_starve_the_other_four():
    """The per-user cap exists to protect everyone else; prove that it does."""

    async def scenario():
        service = StubAnswerService(model_latency=0.1, cpu_work=0.05)
        hogging = [
            asyncio.create_task(service.answer("hogger|cda", f"pesada {index}"))
            for index in range(CONCURRENT_USERS)
        ]
        await asyncio.sleep(0.02)
        others = await asyncio.gather(
            *(
                service.answer(f"otro{index}|cda", "consulta normal")
                for index in range(4)
            ),
            return_exceptions=True,
        )
        await asyncio.gather(*hogging, return_exceptions=True)
        return others

    others = asyncio.run(scenario())

    assert all(isinstance(item, dict) for item in others), (
        "one user flooding the service starved the others"
    )


def test_mixed_traffic_five_users_some_with_two_tabs():
    """The realistic shape: five users, two of them with a second tab open."""

    async def scenario():
        service = StubAnswerService(model_latency=0.08, cpu_work=0.04)
        calls = [service.answer(f"usuario{index}|cda", "consulta") for index in range(5)]
        # Two of them have the dashboard open twice — allowed, and must still be served.
        calls.append(service.answer("usuario0|cda", "segunda pestaña"))
        calls.append(service.answer("usuario1|cda", "segunda pestaña"))

        started = time.monotonic()
        outcomes = await asyncio.gather(*calls, return_exceptions=True)
        return service, outcomes, time.monotonic() - started

    service, outcomes, elapsed = asyncio.run(scenario())

    assert all(isinstance(item, dict) for item in outcomes), (
        "a second tab per user is within the limits and must be answered"
    )
    assert service.concurrency.stats()["rejected"] == 0
    assert elapsed < 0.8
    assert service.concurrency.stats()["peak_in_flight"] >= 5


def test_the_pool_is_fully_released_after_a_burst():
    """No slot leaks: after everything settles the service is idle again.

    A leaked slot is invisible until the pool is exhausted, at which point every user
    gets a busy error and the service looks dead while doing nothing.
    """

    async def scenario():
        service = StubAnswerService(model_latency=0.02, cpu_work=0.01)
        for _ in range(3):
            await asyncio.gather(
                *(
                    service.answer(f"usuario{index}|cda", "consulta")
                    for index in range(CONCURRENT_USERS)
                ),
                return_exceptions=True,
            )
        return service.concurrency.stats()

    stats = asyncio.run(scenario())

    assert stats["in_flight"] == 0
    assert stats["active_users"] == 0
    assert stats["admitted"] == 3 * CONCURRENT_USERS


# -- background answers under the same load ----------------------------------


def test_five_users_submitting_background_jobs_all_get_their_own_answer():
    """Submitted answers stay independent: no crossed wires between users."""

    async def scenario():
        service = StubAnswerService(model_latency=0.05, cpu_work=0.05)
        jobs = []
        for index in range(CONCURRENT_USERS):
            user = f"usuario{index}|cda"
            question = f"consulta {index}"
            jobs.append(
                await service.jobs.submit(
                    f"{user}|session{index}|msg{index}",
                    lambda user=user, question=question: service.answer(user, question),
                )
            )

        for _ in range(200):
            if all(job.done for job in jobs):
                break
            await asyncio.sleep(0.01)
        return jobs

    jobs = asyncio.run(scenario())

    assert all(job.status == "done" for job in jobs)
    for index, job in enumerate(jobs):
        assert job.result["user"] == f"usuario{index}|cda"
        assert job.result["response"] == f"respuesta a consulta {index}"


def test_resubmitting_the_same_question_never_runs_it_twice():
    """The fix for duplicated answers.

    A double click, a retry after a dead connection, and a reloaded tab re-dispatching
    its pending message all arrive as a repeat submission. Each must attach to the run
    already in progress; starting a second one is what produced two answers to one
    question and a chat that looked like it had answered itself.
    """
    runs: list[str] = []

    async def scenario():
        service = StubAnswerService()
        registry = service.jobs

        async def work():
            runs.append("started")
            await asyncio.sleep(0.2)
            return {"response": "una sola respuesta"}

        first = await registry.submit("ana|cda|sesion1|msg-abc", work)
        # Three more submissions of the identical question while the first still runs.
        repeats = [
            await registry.submit("ana|cda|sesion1|msg-abc", work) for _ in range(3)
        ]

        for _ in range(200):
            if first.done:
                break
            await asyncio.sleep(0.01)
        return first, repeats

    first, repeats = asyncio.run(scenario())

    assert len(runs) == 1, f"the question ran {len(runs)} times; it must run once"
    assert all(job.job_id == first.job_id for job in repeats)
    assert first.result == {"response": "una sola respuesta"}


def test_a_finished_answer_survives_the_caller_disconnecting():
    """The heart of the "already answered after a refresh" bug.

    Nobody polls while the answer is being computed — the browser is gone. The work must
    still complete, and the result must still be there to collect afterwards, because
    that reconnecting browser is exactly who comes back for it.
    """

    async def scenario():
        registry = JobRegistry(retention_seconds=60.0)

        async def work():
            await asyncio.sleep(0.15)
            return {"response": "terminada sin nadie escuchando"}

        job = await registry.submit("ana|cda|sesion1|msg-1", work)
        job_id = job.job_id
        del job  # the caller is gone; nothing holds a reference to the job

        await asyncio.sleep(0.3)
        return await registry.get(job_id)

    recovered = asyncio.run(scenario())

    assert recovered is not None, "the job was dropped when its caller disappeared"
    assert recovered.status == "done"
    assert recovered.result == {"response": "terminada sin nadie escuchando"}


def test_a_failed_background_answer_reports_a_reason_instead_of_hanging():
    """A crash inside the run must become a poll payload, never an unpolled silence."""

    async def scenario():
        registry = JobRegistry(retention_seconds=60.0)

        async def work():
            raise CampbellBusyError("sin capacidad", retry_after=7)

        job = await registry.submit(
            "ana|cda|sesion1|msg-2",
            work,
            on_error=lambda exc: {
                "detail": str(exc),
                "kind": "busy",
                "retryable": True,
            },
        )
        for _ in range(200):
            if job.done:
                break
            await asyncio.sleep(0.01)
        return job

    job = asyncio.run(scenario())

    assert job.status == "error"
    assert job.error["kind"] == "busy"
    assert job.error["retryable"] is True
    assert job.as_dict()["elapsed_seconds"] >= 0


def test_a_cancelled_answer_frees_its_slot_for_someone_else():
    """Cancelling must release admission control, or the pool bleeds slots."""

    async def scenario():
        service = StubAnswerService(model_latency=5.0, cpu_work=0.0)
        job = await service.jobs.submit(
            "ana|cda|sesion1|msg-3",
            lambda: service.answer("ana|cda", "consulta larga"),
        )
        await asyncio.sleep(0.05)
        cancelled = await service.jobs.cancel(job.job_id)
        await asyncio.sleep(0.05)
        return cancelled, service.concurrency.stats()

    cancelled, stats = asyncio.run(scenario())

    assert cancelled is True
    assert stats["in_flight"] == 0, "cancelling leaked the concurrency slot"
    assert stats["active_users"] == 0


@pytest.mark.parametrize("users", [1, 3, CONCURRENT_USERS])
def test_latency_stays_flat_as_users_are_added(users):
    """Adding users must cost throughput, not per-user latency.

    The freeze users described is this curve going wrong: with serialized answers the
    fifth person waits five times as long as the first. Concurrent answers keep each
    individual wait roughly constant.
    """

    async def scenario():
        service = StubAnswerService(model_latency=0.1, cpu_work=0.05)
        started = time.monotonic()
        await asyncio.gather(
            *(
                service.answer(f"usuario{index}|cda", "consulta")
                for index in range(users)
            )
        )
        return time.monotonic() - started

    elapsed = asyncio.run(scenario())

    # One answer is ~0.25s. Even at five users the wall clock must stay in that
    # neighbourhood rather than growing with the user count.
    assert elapsed < 0.7, (
        f"{users} concurrent users took {elapsed:.2f}s; latency is growing with load"
    )


# -- several questions at once in ONE conversation ----------------------------


@pytest.fixture
def fake_api_key(monkeypatch):
    """`answer` refuses to run without a key; the stubbed Runner never uses it."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-not-a-real-key")


def _runtime_with_slow_agent(tmp_path, answer_seconds: float = 0.3):
    """A runtime whose agent run takes real time, with everything else genuine.

    Only `_build_bundle` and the gatekeeper are replaced. The session store, the locking
    and the append path are the real ones, because those are exactly what is under test.
    """
    from src.campbell_ai.agents_runtime import CampbellAgentRuntime
    from src.campbell_ai.data import DashboardDataRepository
    from src.campbell_ai.sessions import InMemorySessionStore
    from tests.test_campbell_ai import _settings

    settings = _settings(tmp_path)
    object.__setattr__(settings, "max_history_messages", 40)
    runtime = CampbellAgentRuntime(
        DashboardDataRepository(tmp_path),
        settings,
        session_store=InMemorySessionStore(ttl_seconds=1800, lock_wait_seconds=5),
    )

    class _Result:
        def __init__(self, text):
            self.final_output = text

    class _Runner:
        @staticmethod
        async def run(starting_agent=None, input=None, max_turns=None):
            question = input[-1]["content"] if isinstance(input, list) else str(input)
            await asyncio.sleep(answer_seconds)
            return _Result(f"respuesta a {question[-40:]}")

    from types import SimpleNamespace

    bundle = SimpleNamespace(head="head-agent", gatekeeper="gatekeeper-agent")
    runtime._build_bundle = lambda principal: (bundle, _Runner, [], [], [])
    # The gatekeeper is a separate model call; not what this test is about.
    runtime._gatekeeper_refusal = _noop_gatekeeper
    runtime._archive_exchange = _noop_archive
    runtime._audit = lambda response, tool_outputs, question="": _EmptyGrounding()
    return runtime


async def _noop_gatekeeper(Runner, bundle, message, deadline=None):
    return None


async def _noop_archive(principal, session_id, messages):
    return None


class _EmptyGrounding:
    def as_dict(self):
        return {}

    is_grounded = True


def test_six_questions_in_one_conversation_are_all_answered(tmp_path, fake_api_key):
    """The reported failure: one account firing several questions at once.

    The session lock used to be held for the whole agent run, so a second question in
    the same conversation waited out `queue_timeout_seconds` and was then rejected —
    however idle the service was. Six questions produced one answer and five rejections.

    Serializing a conversation is right for *writes*; it was never right for the run
    itself. Now the lock covers only the read and the append.
    """
    from src.campbell_ai.models import DashboardPrincipal

    principal = DashboardPrincipal(
        username="ana.perez", role="admin", company_id="cda", allowed_clients=["cda"]
    )

    async def scenario():
        runtime = _runtime_with_slow_agent(tmp_path, answer_seconds=0.3)
        await runtime.initialize(principal, "campbell_uno")
        started = time.monotonic()
        results = await asyncio.gather(
            *(
                runtime.answer(principal, "campbell_uno", f"consulta {index}")
                for index in range(6)
            ),
            return_exceptions=True,
        )
        elapsed = time.monotonic() - started
        history = await runtime.history(principal, "campbell_uno")
        return results, elapsed, history

    results, elapsed, history = asyncio.run(scenario())

    failures = [item for item in results if isinstance(item, BaseException)]
    assert not failures, f"questions in one conversation were rejected: {failures}"

    # Six answers of 0.3s each: concurrent is ~0.3s, serialized would be ~1.8s.
    assert elapsed < 1.0, (
        f"six questions in one conversation took {elapsed:.2f}s; they are still "
        "serialized behind the session lock"
    )

    # Nothing was lost: every question and every answer is in the thread. This is what
    # the re-read inside `_commit_exchange` protects — appending to a stale snapshot
    # would let the last writer overwrite the others.
    contents = [item.content for item in history]
    for index in range(6):
        assert f"consulta {index}" in contents, (
            f"question {index} vanished from the thread; a concurrent commit "
            "overwrote it"
        )
    assert len(history) == 12, f"expected 6 exchanges, found {len(history) // 2}"


def test_concurrent_answers_do_not_overwrite_each_other(tmp_path, fake_api_key):
    """Two answers finishing at the same instant must both survive.

    Staggered durations so they commit at genuinely different moments while both having
    started from the same snapshot — the lost-update window.
    """
    from src.campbell_ai.models import DashboardPrincipal

    principal = DashboardPrincipal(
        username="ana.perez", role="admin", company_id="cda", allowed_clients=["cda"]
    )

    async def scenario():
        runtime = _runtime_with_slow_agent(tmp_path, answer_seconds=0.1)
        await runtime.initialize(principal, "campbell_dos")
        await asyncio.gather(
            runtime.answer(principal, "campbell_dos", "primera"),
            runtime.answer(principal, "campbell_dos", "segunda"),
            runtime.answer(principal, "campbell_dos", "tercera"),
        )
        return await runtime.history(principal, "campbell_dos")

    history = asyncio.run(scenario())
    contents = [item.content for item in history]

    for question in ("primera", "segunda", "tercera"):
        assert question in contents, f"{question!r} was lost to a concurrent commit"
    # Each question is followed by its own answer.
    assert len(history) == 6
    assert sum(1 for item in history if item.role == "assistant") == 3


def test_a_later_question_still_sees_an_earlier_answer(tmp_path, fake_api_key):
    """Dropping the lock must not cost sequential conversations their context.

    Asking, waiting, then asking again has to behave exactly as before: the second
    question is answered with the first exchange in its context.
    """
    from src.campbell_ai.models import DashboardPrincipal

    principal = DashboardPrincipal(
        username="ana.perez", role="admin", company_id="cda", allowed_clients=["cda"]
    )
    seen: list[int] = []

    async def scenario():
        runtime = _runtime_with_slow_agent(tmp_path, answer_seconds=0.01)
        original = runtime._conversation_input

        def spy(messages, message):
            seen.append(len(messages))
            return original(messages, message)

        runtime._conversation_input = spy
        await runtime.initialize(principal, "campbell_tres")
        await runtime.answer(principal, "campbell_tres", "primera")
        await runtime.answer(principal, "campbell_tres", "segunda")
        return await runtime.history(principal, "campbell_tres")

    history = asyncio.run(scenario())

    assert seen == [0, 2], (
        f"the second question saw {seen[-1]} prior messages; a sequential follow-up "
        "must see the first exchange"
    )
    assert len(history) == 4
