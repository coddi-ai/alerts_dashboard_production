"""Tests for the pluggable Campbell AI session store.

Conversation state used to live in a plain dict inside the runtime, which stranded
a user's thread on one worker. These tests pin the contract both backends must
honour so a deployment can switch to Redis without changing the runtime.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from src.campbell_ai.errors import CampbellBusyError, CampbellConfigurationError
from src.campbell_ai.models import ConversationMessage
from src.campbell_ai.sessions import (
    InMemorySessionStore,
    build_session_store,
    deserialize_messages,
    serialize_messages,
)


class _Settings:
    """Minimal stand-in for CampbellSettings."""

    def __init__(self, **kwargs):
        self.session_ttl_seconds = 1800
        self.session_backend = "memory"
        self.redis_url = ""
        self.redis_namespace = "campbell:test"
        self.session_lock_timeout_seconds = 300
        for key, value in kwargs.items():
            setattr(self, key, value)


KEY = ("admin", "cda", "campbell_test")
OTHER = ("admin", "emin", "campbell_test")


def test_serialization_round_trips_messages_with_visualizations():
    messages = [
        ConversationMessage(role="user", content="¿Última alerta?"),
        ConversationMessage(
            role="assistant",
            content="La unidad **T_18**",
            visualizations=[
                {
                    "title": "Pareto",
                    "description": "d",
                    "dataset": "alerts",
                    "chart_type": "pareto",
                    "figure": {"data": [], "layout": {}},
                }
            ],
        ),
    ]

    restored = deserialize_messages(serialize_messages(messages))

    assert [item.role for item in restored] == ["user", "assistant"]
    assert restored[1].content == "La unidad **T_18**"
    assert restored[1].visualizations[0].chart_type == "pareto"
    assert restored[1].message_id == messages[1].message_id


def test_deserialization_survives_corrupt_payloads():
    """One unreadable message must not destroy the rest of the thread."""
    assert deserialize_messages(None) == []
    assert deserialize_messages("not json") == []
    assert deserialize_messages('{"not": "a list"}') == []
    partial = '[{"role": "user", "content": "hola"}, {"role": "???"}]'
    assert [item.content for item in deserialize_messages(partial)] == ["hola"]


def test_in_memory_store_isolates_keys_and_replaces_content():
    store = InMemorySessionStore(ttl_seconds=1800)

    async def scenario():
        assert await store.exists(KEY) is False
        await store.create_if_absent(KEY)
        assert await store.exists(KEY) is True
        await store.write(KEY, [ConversationMessage(role="user", content="uno")])
        # create_if_absent must not wipe an existing conversation.
        await store.create_if_absent(KEY)
        assert [item.content for item in await store.read(KEY)] == ["uno"]
        # A different company is a different session.
        assert await store.read(OTHER) == []
        await store.write(KEY, [ConversationMessage(role="user", content="dos")])
        return [item.content for item in await store.read(KEY)]

    assert asyncio.run(scenario()) == ["dos"]


def test_in_memory_store_returns_copies_so_callers_cannot_mutate_state():
    store = InMemorySessionStore(ttl_seconds=1800)

    async def scenario():
        await store.write(KEY, [ConversationMessage(role="user", content="original")])
        borrowed = await store.read(KEY)
        borrowed[0].content = "mutado"
        borrowed.append(ConversationMessage(role="user", content="extra"))
        return [item.content for item in await store.read(KEY)]

    assert asyncio.run(scenario()) == ["original"]


def test_in_memory_store_evicts_expired_sessions():
    store = InMemorySessionStore(ttl_seconds=60)

    async def scenario():
        await store.write(KEY, [ConversationMessage(role="user", content="uno")])
        # Age the entry past its TTL.
        store._entries[KEY].last_access -= 120
        return await store.exists(KEY)

    assert asyncio.run(scenario()) is False


def test_session_lock_serializes_concurrent_work_on_one_session():
    """The runtime holds this lock across a whole agent run."""
    store = InMemorySessionStore(ttl_seconds=1800)
    order: list[str] = []

    async def worker(name: str) -> None:
        async with store.lock(KEY):
            order.append(f"{name}:in")
            await asyncio.sleep(0.02)
            order.append(f"{name}:out")

    async def scenario():
        await asyncio.gather(worker("a"), worker("b"))

    asyncio.run(scenario())

    # Interleaving would produce a:in, b:in, ...; serialization keeps pairs together.
    assert order in (
        ["a:in", "a:out", "b:in", "b:out"],
        ["b:in", "b:out", "a:in", "a:out"],
    )


def test_locks_on_different_sessions_do_not_block_each_other():
    store = InMemorySessionStore(ttl_seconds=1800)
    started = asyncio.Event()

    async def slow() -> None:
        async with store.lock(KEY):
            started.set()
            await asyncio.sleep(0.2)

    async def fast() -> str:
        await started.wait()
        async with store.lock(OTHER):
            return "not blocked"

    async def scenario():
        slow_task = asyncio.create_task(slow())
        result = await asyncio.wait_for(fast(), timeout=0.15)
        await slow_task
        return result

    assert asyncio.run(scenario()) == "not blocked"


def test_build_session_store_selects_the_configured_backend():
    assert build_session_store(_Settings()).backend == "memory"
    assert build_session_store(_Settings(session_backend="LOCAL")).backend == "memory"

    # Redis without a URL is a misconfiguration, not a silent fallback to memory:
    # falling back would reintroduce the very bug this store exists to fix.
    with pytest.raises(CampbellConfigurationError, match="CAMPBELL_AI_REDIS_URL"):
        build_session_store(_Settings(session_backend="redis"))

    with pytest.raises(CampbellConfigurationError, match="no soportado"):
        build_session_store(_Settings(session_backend="memcached"))


def test_ttl_has_a_floor_so_a_typo_cannot_expire_sessions_instantly():
    assert InMemorySessionStore(ttl_seconds=1).ttl_seconds == 60


class _FakeRedis:
    """Enough of redis.asyncio to exercise the store without a server."""

    def __init__(self):
        self.values: dict[str, str] = {}
        self.expiries: dict[str, int] = {}

    async def get(self, name):
        return self.values.get(name)

    async def set(self, name, value, ex=None, nx=False):
        if nx and name in self.values:
            return False
        self.values[name] = value
        if ex is not None:
            self.expiries[name] = ex
        return True

    async def expire(self, name, seconds):
        if name in self.values:
            self.expiries[name] = seconds
            return True
        return False

    async def exists(self, name):
        return 1 if name in self.values else 0

    async def delete(self, name):
        self.values.pop(name, None)
        return 1


def _redis_store(fake):
    """Build a RedisSessionStore around a fake client, skipping the real connection."""
    pytest.importorskip("redis")
    from src.campbell_ai.sessions import RedisSessionStore

    store = RedisSessionStore.__new__(RedisSessionStore)
    store.ttl_seconds = 1800
    store.lock_timeout_seconds = 60
    store._redis = fake
    store._namespace = "campbell:test"
    return store


def test_redis_store_namespaces_keys_per_user_company_and_session():
    store = _redis_store(_FakeRedis())

    assert store._data_key(KEY) == "campbell:test:data:admin:cda:campbell_test"
    # Company is part of the key, so one user's two companies never share a thread.
    assert store._data_key(KEY) != store._data_key(OTHER)
    assert store._lock_key(KEY) != store._data_key(KEY)


def test_redis_store_round_trips_and_refreshes_expiry():
    fake = _FakeRedis()
    store = _redis_store(fake)

    async def scenario():
        assert await store.exists(KEY) is False
        await store.create_if_absent(KEY)
        assert await store.exists(KEY) is True
        await store.write(KEY, [ConversationMessage(role="user", content="uno")])
        # create_if_absent uses NX, so it must not clear an existing conversation.
        await store.create_if_absent(KEY)
        restored = await store.read(KEY)
        return restored, fake.expiries[store._data_key(KEY)]

    restored, ttl = asyncio.run(scenario())

    assert [item.content for item in restored] == ["uno"]
    assert ttl == 1800


def test_redis_lock_is_exclusive_and_released():
    fake = _FakeRedis()
    store = _redis_store(fake)
    lock_key = store._lock_key(KEY)

    async def scenario():
        async with store.lock(KEY):
            held = lock_key in fake.values
        return held, lock_key in fake.values

    held, released_after = asyncio.run(scenario())

    assert held is True
    assert released_after is False


def test_redis_lock_refuses_rather_than_interleaving_two_runs():
    """A second request must fail loudly instead of corrupting a conversation."""
    fake = _FakeRedis()
    store = _redis_store(fake)
    store.lock_timeout_seconds = 60
    fake.values[store._lock_key(KEY)] = "1"

    async def scenario():
        # Shorten the acquisition window so the test does not wait a minute.
        store.lock_timeout_seconds = 1
        async with store.lock(KEY):
            pass

    # Busy, not misconfigured: the caller should retry, which is what a 429 tells it.
    with pytest.raises(CampbellBusyError, match="ocupada"):
        asyncio.run(scenario())


def test_runtime_uses_the_injected_store():
    """The runtime must own no conversation state of its own."""
    from src.campbell_ai.agents_runtime import CampbellAgentRuntime
    from src.campbell_ai.data import DashboardDataRepository
    from src.campbell_ai.models import DashboardPrincipal
    from tests.test_campbell_ai import _settings

    store = InMemorySessionStore(ttl_seconds=1800)
    runtime = CampbellAgentRuntime(
        DashboardDataRepository("data"), _settings(Path("data")), session_store=store
    )
    principal = DashboardPrincipal(
        username="admin", role="admin", company_id="cda", allowed_clients=["cda"]
    )

    async def scenario():
        message_id = await runtime.record_exchange(
            principal, "campbell_test", "pregunta", "respuesta"
        )
        # The store is the only place the exchange lives.
        stored = await store.read(("admin", "cda", "campbell_test"))
        history = await runtime.history(principal, "campbell_test")
        await runtime.clear(principal, "campbell_test")
        cleared = await runtime.history(principal, "campbell_test")
        return message_id, stored, history, cleared

    message_id, stored, history, cleared = asyncio.run(scenario())

    assert [item.content for item in stored] == ["pregunta", "respuesta"]
    assert [item.content for item in history] == ["pregunta", "respuesta"]
    assert stored[1].message_id == message_id
    assert cleared == []
    assert not hasattr(runtime, "_sessions")


def test_history_is_trimmed_to_the_configured_maximum():
    from src.campbell_ai.agents_runtime import CampbellAgentRuntime
    from src.campbell_ai.data import DashboardDataRepository
    from tests.test_campbell_ai import _settings

    settings = _settings(Path("data"))
    object.__setattr__(settings, "max_history_messages", 4)
    runtime = CampbellAgentRuntime(
        DashboardDataRepository("data"),
        settings,
        session_store=InMemorySessionStore(ttl_seconds=1800),
    )

    messages = [ConversationMessage(role="user", content=str(index)) for index in range(6)]
    trimmed, message_id = runtime._appended(messages, "pregunta", "respuesta")

    assert len(trimmed) == 4
    assert [item.content for item in trimmed[-2:]] == ["pregunta", "respuesta"]
    assert trimmed[-1].message_id == message_id
