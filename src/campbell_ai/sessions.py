"""Conversation session storage for Campbell AI.

The runtime keeps one conversation per (user, company, session). With a single
FastAPI worker an in-process dict is enough, but more than one worker or replica
would strand a user's thread on whichever process happened to serve the previous
request. This module puts that state behind a small interface so the deployment
picks the backend, and the runtime does not change.

Both backends expose the same two guarantees the runtime depends on:

- reads and writes of a conversation are atomic with respect to other requests
  for the *same* session, via ``lock``;
- a session disappears after ``ttl_seconds`` of inactivity.
"""

from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import AsyncIterator

from src.campbell_ai.errors import CampbellBusyError, CampbellConfigurationError
from src.campbell_ai.models import ConversationMessage


SessionKey = tuple[str, str, str]

# How long a second request for the *same* conversation waits for the first to finish
# before giving up. Unbounded waiting is worse than a clear rejection: the user has
# already been told their message is being processed, so the second request only has to
# say "not yet" rather than silently hold a worker for the whole answer.
DEFAULT_LOCK_WAIT_SECONDS = 45


def serialize_messages(messages: list[ConversationMessage]) -> str:
    return json.dumps(
        [message.model_dump(mode="json") for message in messages], ensure_ascii=False
    )


def deserialize_messages(payload: str | bytes | None) -> list[ConversationMessage]:
    if not payload:
        return []
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    try:
        items = json.loads(payload)
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    messages: list[ConversationMessage] = []
    for item in items:
        try:
            messages.append(ConversationMessage.model_validate(item))
        except Exception:
            # A single unreadable message must not destroy the rest of the thread.
            continue
    return messages


class SessionStore(ABC):
    """Storage for per-session conversation history."""

    def __init__(
        self, ttl_seconds: int, lock_wait_seconds: int = DEFAULT_LOCK_WAIT_SECONDS
    ):
        self.ttl_seconds = max(60, int(ttl_seconds))
        self.lock_wait_seconds = max(1, int(lock_wait_seconds))

    @property
    @abstractmethod
    def backend(self) -> str:
        """Short name used by health checks and logs."""

    @abstractmethod
    async def exists(self, key: SessionKey) -> bool:
        """True when the session is present and has not expired."""

    @abstractmethod
    async def read(self, key: SessionKey) -> list[ConversationMessage]:
        """Return the conversation, refreshing its expiry."""

    @abstractmethod
    async def write(self, key: SessionKey, messages: list[ConversationMessage]) -> None:
        """Replace the conversation and refresh its expiry."""

    @abstractmethod
    async def create_if_absent(self, key: SessionKey) -> None:
        """Register an empty conversation without overwriting an existing one."""

    @abstractmethod
    def lock(self, key: SessionKey):
        """Async context manager serializing work for one session."""

    async def close(self) -> None:
        """Release backend resources; no-op unless the backend holds a client."""


@dataclass
class _Entry:
    messages: list[ConversationMessage] = field(default_factory=list)
    last_access: float = field(default_factory=time.time)


class InMemorySessionStore(SessionStore):
    """Process-local store. Correct for one worker; the default for development."""

    def __init__(
        self, ttl_seconds: int, lock_wait_seconds: int = DEFAULT_LOCK_WAIT_SECONDS
    ):
        super().__init__(ttl_seconds, lock_wait_seconds)
        self._entries: dict[SessionKey, _Entry] = {}
        self._locks: dict[SessionKey, asyncio.Lock] = {}
        self._pool_lock = asyncio.Lock()

    @property
    def backend(self) -> str:
        return "memory"

    def _evict_expired(self) -> None:
        cutoff = time.time() - self.ttl_seconds
        for key in [k for k, entry in self._entries.items() if entry.last_access < cutoff]:
            self._entries.pop(key, None)
            self._locks.pop(key, None)

    async def exists(self, key: SessionKey) -> bool:
        async with self._pool_lock:
            self._evict_expired()
            return key in self._entries

    async def read(self, key: SessionKey) -> list[ConversationMessage]:
        async with self._pool_lock:
            self._evict_expired()
            entry = self._entries.setdefault(key, _Entry())
            entry.last_access = time.time()
            return [message.model_copy(deep=True) for message in entry.messages]

    async def write(self, key: SessionKey, messages: list[ConversationMessage]) -> None:
        async with self._pool_lock:
            self._entries[key] = _Entry(
                messages=[message.model_copy(deep=True) for message in messages]
            )

    async def create_if_absent(self, key: SessionKey) -> None:
        async with self._pool_lock:
            self._evict_expired()
            self._entries.setdefault(key, _Entry())

    def lock(self, key: SessionKey):
        wait_seconds = self.lock_wait_seconds

        @asynccontextmanager
        async def _guard() -> AsyncIterator[None]:
            async with self._pool_lock:
                lock = self._locks.setdefault(key, asyncio.Lock())
            try:
                await asyncio.wait_for(lock.acquire(), timeout=wait_seconds)
            except asyncio.TimeoutError as exc:
                raise CampbellBusyError(
                    "La sesión de Campbell AI está ocupada procesando otra consulta",
                    retry_after=10,
                    scope="session",
                ) from exc
            try:
                yield
            finally:
                lock.release()

        return _guard()


class RedisSessionStore(SessionStore):
    """Shared store so any worker or replica can serve the same conversation."""

    def __init__(
        self,
        url: str,
        ttl_seconds: int,
        lock_timeout_seconds: int,
        namespace: str,
        lock_wait_seconds: int = DEFAULT_LOCK_WAIT_SECONDS,
    ):
        super().__init__(ttl_seconds, lock_wait_seconds)
        try:
            from redis.asyncio import Redis
        except ImportError as exc:  # pragma: no cover - depends on deployment extras
            raise CampbellConfigurationError(
                "CAMPBELL_AI_SESSION_BACKEND=redis requiere el paquete 'redis'"
            ) from exc
        self._redis = Redis.from_url(url, decode_responses=True)
        self._namespace = namespace.strip(":") or "campbell:sessions"
        # The lock is held across a full agent run, so its expiry must outlive the
        # slowest expected answer or a second request could interleave.
        self.lock_timeout_seconds = max(60, int(lock_timeout_seconds))

    @property
    def backend(self) -> str:
        return "redis"

    def _data_key(self, key: SessionKey) -> str:
        username, company_id, session_id = key
        return f"{self._namespace}:data:{username}:{company_id}:{session_id}"

    def _lock_key(self, key: SessionKey) -> str:
        username, company_id, session_id = key
        return f"{self._namespace}:lock:{username}:{company_id}:{session_id}"

    async def exists(self, key: SessionKey) -> bool:
        return bool(await self._redis.exists(self._data_key(key)))

    async def read(self, key: SessionKey) -> list[ConversationMessage]:
        name = self._data_key(key)
        payload = await self._redis.get(name)
        if payload is None:
            return []
        await self._redis.expire(name, self.ttl_seconds)
        return deserialize_messages(payload)

    async def write(self, key: SessionKey, messages: list[ConversationMessage]) -> None:
        await self._redis.set(
            self._data_key(key), serialize_messages(messages), ex=self.ttl_seconds
        )

    async def create_if_absent(self, key: SessionKey) -> None:
        await self._redis.set(
            self._data_key(key), serialize_messages([]), ex=self.ttl_seconds, nx=True
        )

    def lock(self, key: SessionKey):
        name = self._lock_key(key)
        redis = self._redis
        timeout = self.lock_timeout_seconds
        # Two different budgets: the key expiry must outlive the slowest answer so no
        # second request can interleave, while the *wait* is short so a queued request
        # gives the user an answer instead of holding a worker for minutes.
        wait_budget = min(self.lock_wait_seconds, timeout)

        @asynccontextmanager
        async def _guard() -> AsyncIterator[None]:
            deadline = time.monotonic() + wait_budget
            acquired = False
            while time.monotonic() < deadline:
                if await redis.set(name, "1", ex=timeout, nx=True):
                    acquired = True
                    break
                await asyncio.sleep(0.2)
            if not acquired:
                raise CampbellBusyError(
                    "La sesión de Campbell AI está ocupada procesando otra consulta",
                    retry_after=10,
                    scope="session",
                )
            try:
                yield
            finally:
                await redis.delete(name)

        return _guard()

    async def close(self) -> None:  # pragma: no cover - exercised by deployments
        await self._redis.aclose()


def build_session_store(settings) -> SessionStore:
    """Pick the session backend declared by configuration."""
    backend = str(getattr(settings, "session_backend", "memory") or "memory").strip().lower()
    lock_wait = int(
        getattr(settings, "queue_timeout_seconds", DEFAULT_LOCK_WAIT_SECONDS)
        or DEFAULT_LOCK_WAIT_SECONDS
    )
    if backend in {"memory", "inmemory", "local"}:
        return InMemorySessionStore(settings.session_ttl_seconds, lock_wait)
    if backend == "redis":
        url = str(getattr(settings, "redis_url", "") or "").strip()
        if not url:
            raise CampbellConfigurationError(
                "CAMPBELL_AI_SESSION_BACKEND=redis requiere CAMPBELL_AI_REDIS_URL"
            )
        return RedisSessionStore(
            url=url,
            ttl_seconds=settings.session_ttl_seconds,
            lock_timeout_seconds=getattr(settings, "session_lock_timeout_seconds", 300),
            namespace=getattr(settings, "redis_namespace", "campbell:sessions"),
            lock_wait_seconds=lock_wait,
        )
    raise CampbellConfigurationError(
        f"CAMPBELL_AI_SESSION_BACKEND no soportado: {backend}"
    )
