"""Behaviour of Campbell AI once a conversation gets long.

The production report: the assistant "se pega" when the context or the conversation
grows. The mechanism was that history was bounded by *message count* only. Twenty
messages sounds modest until you notice what an answer to a data question looks like —
a markdown table of alerts is comfortably several kilobytes — and that the whole thing
is replayed into every subsequent turn, and again into each sub-agent the head agent
hands off to.

So the prompt grew turn over turn, each turn got slower than the last, and eventually an
ordinary question crossed the timeout. The user saw a frozen page; the run kept going
and quietly persisted its answer, which is why the question looked answered after a
reload.

These tests pin the two properties that stop that: replayed context has a *size* bound,
not just a count bound, and it does not grow as the conversation does.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from src.campbell_ai.agents_runtime import CampbellAgentRuntime
from src.campbell_ai.data import DashboardDataRepository
from src.campbell_ai.errors import CampbellTimeoutError
from src.campbell_ai.models import ConversationMessage, DashboardPrincipal
from src.campbell_ai.sessions import InMemorySessionStore
from tests.test_campbell_ai import _settings


PRINCIPAL = DashboardPrincipal(
    username="ana.perez", role="admin", company_id="cda", allowed_clients=["cda"]
)


def _runtime(tmp_path, **overrides) -> CampbellAgentRuntime:
    settings = _settings(tmp_path)
    for name, value in overrides.items():
        object.__setattr__(settings, name, value)
    return CampbellAgentRuntime(
        DashboardDataRepository(tmp_path),
        settings,
        session_store=InMemorySessionStore(ttl_seconds=1800),
    )


def _fat_answer(index: int, size: int = 6000) -> str:
    """An assistant reply the size of a real tabular data answer."""
    header = f"Respuesta {index}: alertas del periodo\n\n| unidad | severidad | horas |\n"
    row = "| CAEX-01 | alta | 1234 |\n"
    return header + row * (max(1, (size - len(header)) // len(row)))


def _long_conversation(turns: int, answer_size: int = 6000) -> list[ConversationMessage]:
    messages: list[ConversationMessage] = []
    for index in range(turns):
        messages.append(
            ConversationMessage(role="user", content=f"Pregunta {index} sobre la flota")
        )
        messages.append(
            ConversationMessage(role="assistant", content=_fat_answer(index, answer_size))
        )
    return messages


def _payload_chars(payload: list[dict[str, str]]) -> int:
    return sum(len(item["content"]) for item in payload)


# -- the size bound -----------------------------------------------------------


def test_a_long_conversation_does_not_produce_an_unbounded_prompt(tmp_path):
    """Ten fat answers are ~60k characters. The replayed prompt must not be."""
    runtime = _runtime(tmp_path, max_history_messages=20, max_history_chars=24000)
    messages = _long_conversation(turns=10)

    raw_size = sum(len(item.content) for item in messages)
    payload = runtime._conversation_input(messages, "¿Y en la última semana?")

    assert raw_size > 55000, "the fixture should be genuinely large"
    # The budget plus the current question and its temporal preamble.
    assert _payload_chars(payload) < 26000, (
        f"replayed {_payload_chars(payload)} characters from a {raw_size}-character "
        "conversation; the prompt is still unbounded"
    )


def test_the_prompt_stops_growing_once_the_budget_is_reached(tmp_path):
    """The property that actually matters: latency must stop tracking chat length.

    A conversation of 4 turns and one of 40 must produce prompts of comparable size.
    While the prompt grew with the conversation, so did every turn's latency, until an
    ordinary question no longer fit in the time budget.
    """
    runtime = _runtime(tmp_path, max_history_messages=40, max_history_chars=24000)

    sizes = [
        _payload_chars(
            runtime._conversation_input(_long_conversation(turns=turns), "¿Y ahora?")
        )
        for turns in (4, 10, 20, 40)
    ]

    assert sizes[0] <= sizes[-1]
    # From 4 turns to 40 — a tenfold conversation — the prompt must be flat, not tenfold.
    assert sizes[-1] < sizes[0] * 1.5, f"prompt size still grows with the chat: {sizes}"
    assert max(sizes) < 26000


def test_the_most_recent_turns_are_the_ones_kept(tmp_path):
    """Trimming drops the oldest context, never the turn the user is following up on."""
    runtime = _runtime(tmp_path, max_history_messages=40, max_history_chars=12000)
    messages = _long_conversation(turns=10)

    payload = runtime._conversation_input(messages, "¿Y el detalle de esa última?")
    replayed = "\n".join(item["content"] for item in payload)

    assert "Pregunta 9 sobre la flota" in replayed, "the newest turn was dropped"
    assert "Respuesta 9" in replayed
    assert "Pregunta 0 sobre la flota" not in replayed, "the oldest turn should be gone"
    # The live question is always last, whatever was trimmed before it.
    assert payload[-1]["role"] == "user"
    assert "¿Y el detalle de esa última?" in payload[-1]["content"]


def test_one_enormous_answer_cannot_evict_the_whole_conversation(tmp_path):
    """A single huge message is truncated rather than allowed to consume the budget.

    Without the per-message cap, one 50k-character table would fill the budget by itself
    and every other turn in the thread would be dropped to make room for it.
    """
    runtime = _runtime(
        tmp_path,
        max_history_messages=20,
        max_history_chars=24000,
        max_history_message_chars=4000,
    )
    messages = _long_conversation(turns=4, answer_size=2000)
    messages.insert(
        4, ConversationMessage(role="assistant", content=_fat_answer(99, 50000))
    )

    payload = runtime._conversation_input(messages, "Resume lo anterior")
    replayed = "\n".join(item["content"] for item in payload)

    assert all(len(item["content"]) <= 4100 for item in payload[:-1]), (
        "a single message exceeded the per-message cap"
    )
    # Truncation is announced, so the model treats the text as partial.
    assert "recortada por longitud" in replayed
    # And the surrounding conversation survived it.
    assert "Pregunta 3 sobre la flota" in replayed
    assert "Pregunta 0 sobre la flota" in replayed


def test_a_short_conversation_is_replayed_untouched(tmp_path):
    """The bound must not disturb normal use — no truncation marks in a small chat."""
    runtime = _runtime(tmp_path, max_history_messages=20, max_history_chars=24000)
    messages = [
        ConversationMessage(role="user", content="¿Cuántas alertas hay hoy?"),
        ConversationMessage(role="assistant", content="Hay 12 alertas activas."),
    ]

    payload = runtime._conversation_input(messages, "¿Y ayer?")

    assert [item["content"] for item in payload[:-1]] == [
        "¿Cuántas alertas hay hoy?",
        "Hay 12 alertas activas.",
    ]
    assert "recortada" not in "".join(item["content"] for item in payload)


def test_at_least_the_latest_turn_survives_an_absurdly_small_budget(tmp_path):
    """Degrade to less context, never to no context."""
    runtime = _runtime(
        tmp_path, max_history_messages=20, max_history_chars=1, max_history_message_chars=1
    )
    payload = runtime._conversation_input(_long_conversation(turns=5), "¿Y ahora?")

    assert len(payload) >= 2, "trimming left the model with no conversation at all"
    assert payload[-1]["role"] == "user"


# -- the timeout that a long context used to trip ------------------------------


def test_an_answer_that_outruns_its_budget_fails_loudly_instead_of_hanging(tmp_path):
    """A run past the budget must raise, not silently keep going.

    This is the other half of the "already answered after a refresh" bug: an unbounded
    run kept working long after its caller had gone, and persisted an answer nobody was
    waiting for any more.
    """
    from src.campbell_ai.concurrency import execute_with_retry

    async def scenario():
        started = time.monotonic()

        async def never_finishes():
            await asyncio.sleep(30)

        with pytest.raises(CampbellTimeoutError):
            await execute_with_retry(
                never_finishes,
                attempts=3,
                initial_delay=0.0,
                label="la consulta a los agentes",
                deadline=time.monotonic() + 0.2,
            )
        return time.monotonic() - started

    elapsed = asyncio.run(scenario())

    # Bounded by the deadline, and crucially not by attempts × the deadline.
    assert elapsed < 1.0, f"the budget was not enforced; took {elapsed:.2f}s"


def test_retries_cannot_stretch_past_the_deadline(tmp_path):
    """Three attempts at a two-minute run must not become a six-minute run.

    Retrying the whole agent run was how a 90-second client timeout met a run that kept
    going for several minutes afterwards.
    """
    from src.campbell_ai.concurrency import execute_with_retry

    attempts_made = []

    async def scenario():
        started = time.monotonic()

        async def always_throttled():
            attempts_made.append(time.monotonic())
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
    assert len(attempts_made) < 5, "every attempt ran despite the budget being spent"


def test_a_spent_budget_is_not_itself_treated_as_retryable():
    """`CampbellTimeoutError` has "timeout" in its name; the marker list must not bite.

    The transient-failure check matches on error text. Without an explicit exemption our
    own budget error looks transient, and the retry loop would immediately re-run a
    question whose whole problem was that it had no time left.
    """
    from src.campbell_ai.concurrency import is_transient_failure

    assert is_transient_failure(CampbellTimeoutError("agotó el tiempo")) is False
    assert is_transient_failure(TimeoutError("upstream timed out")) is True


# -- end to end over a long thread --------------------------------------------


def test_many_turns_in_one_session_stay_bounded_and_responsive(tmp_path):
    """Drive 30 exchanges through the real session store and watch the bounds hold.

    Uses `record_exchange`, so no model is involved: the concern here is the storage and
    trimming path that every turn goes through, not what the agents say.
    """
    runtime = _runtime(tmp_path, max_history_messages=20, max_history_chars=24000)

    async def scenario():
        timings = []
        for index in range(30):
            started = time.monotonic()
            await runtime.record_exchange(
                PRINCIPAL,
                "campbell_largo",
                f"Pregunta {index} sobre la flota",
                _fat_answer(index, 6000),
            )
            timings.append(time.monotonic() - started)
        history = await runtime.history(PRINCIPAL, "campbell_largo")
        payload = runtime._conversation_input(history, "¿Y el resumen final?")
        return timings, history, payload

    timings, history, payload = asyncio.run(scenario())

    # The stored thread is capped by message count...
    assert len(history) == 20
    # ...and what is replayed to the model is capped by size on top of that.
    assert _payload_chars(payload) < 26000

    # Turn 30 must cost about what turn 1 did. A rising curve here is the freeze.
    first_five = sum(timings[:5]) / 5
    last_five = sum(timings[-5:]) / 5
    assert last_five < max(first_five * 5, 0.05), (
        f"per-turn cost grew from {first_five:.4f}s to {last_five:.4f}s over 30 turns"
    )
