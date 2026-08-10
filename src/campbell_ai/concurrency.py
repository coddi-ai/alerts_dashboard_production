"""Admission control for concurrent Campbell AI requests.

One answer occupies a worker for tens of seconds and issues several model calls, so a
handful of simultaneous users is enough to exhaust the event loop or the upstream model
quota. Without a bound, the failure mode is the worst one: every request slows down
together until they all time out, and nobody gets an answer.

This module bounds admission instead, on three axes:

- **global** — how many answers may be in flight at once;
- **per user** — how many of those one person may hold, so one user with several tabs
  cannot fill the pool and starve everyone else;
- **per minute** — a sliding window over the upstream quota.

A request that cannot be admitted waits briefly and then fails fast with
``CampbellBusyError``, which the API turns into ``429`` with ``Retry-After`` and the
dashboard turns into a retryable message. Failing fast is the point: a queue that grows
without bound converts an overload into a timeout, and the user has no idea whether to
wait or retry.

``execute_with_retry`` covers the other half of the problem — the upstream service
throttling *us*. Only transient failures are retried, with exponential backoff.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncIterator, Awaitable, Callable

from src.campbell_ai.errors import CampbellBusyError, CampbellTimeoutError


logger = logging.getLogger("campbell_ai.concurrency")

# Below this much time left, a retry is not worth attempting: an agent run needs at
# least a few seconds of model round trips before it can produce anything.
_MIN_RETRY_BUDGET_SECONDS = 5.0


@dataclass(frozen=True)
class ConcurrencyLimits:
    """Admission bounds. Defaults are sized for one worker on a small instance."""

    max_concurrent: int = 10
    max_concurrent_per_user: int = 2
    max_requests_per_minute: int = 200
    queue_timeout_seconds: float = 20.0
    retry_attempts: int = 3
    retry_initial_delay: float = 1.0
    retry_max_delay: float = 30.0

    @classmethod
    def from_settings(cls, settings) -> "ConcurrencyLimits":
        return cls(
            max_concurrent=max(1, int(getattr(settings, "max_concurrent_requests", 10))),
            max_concurrent_per_user=max(
                1, int(getattr(settings, "max_concurrent_per_user", 2))
            ),
            max_requests_per_minute=max(
                1, int(getattr(settings, "max_requests_per_minute", 200))
            ),
            queue_timeout_seconds=max(
                1.0, float(getattr(settings, "queue_timeout_seconds", 20.0))
            ),
            retry_attempts=max(1, int(getattr(settings, "retry_attempts", 3))),
            retry_initial_delay=max(
                0.0, float(getattr(settings, "retry_initial_delay", 1.0))
            ),
            retry_max_delay=max(1.0, float(getattr(settings, "retry_max_delay", 30.0))),
        )


class ConcurrencyGuard:
    """Bound how many answers run at once, globally and per user."""

    def __init__(self, limits: ConcurrencyLimits | None = None):
        self.limits = limits or ConcurrencyLimits()
        self._semaphore = asyncio.Semaphore(self.limits.max_concurrent)
        self._per_user: dict[str, int] = {}
        self._window: deque[float] = deque()
        self._state_lock = asyncio.Lock()
        self._admitted = 0
        self._rejected = 0
        self._in_flight = 0
        self._peak_in_flight = 0

    # -- rate limiting ------------------------------------------------------

    async def _reserve_rate_slot(self, deadline: float) -> None:
        """Hold a slot in the per-minute window, waiting only until the deadline."""
        while True:
            async with self._state_lock:
                now = time.monotonic()
                while self._window and now - self._window[0] >= 60.0:
                    self._window.popleft()
                if len(self._window) < self.limits.max_requests_per_minute:
                    self._window.append(now)
                    return
                wait_for = 60.0 - (now - self._window[0])
            remaining = deadline - time.monotonic()
            if remaining <= 0 or wait_for > remaining:
                async with self._state_lock:
                    self._rejected += 1
                raise CampbellBusyError(
                    "Campbell AI está atendiendo el máximo de consultas por minuto",
                    retry_after=max(1, int(wait_for) + 1),
                )
            await asyncio.sleep(min(wait_for, remaining, 0.5))

    async def _release_rate_slot(self) -> None:
        async with self._state_lock:
            if self._window:
                self._window.pop()

    # -- admission ----------------------------------------------------------

    @asynccontextmanager
    async def slot(self, user_key: str) -> AsyncIterator[None]:
        """Admit one request, or raise ``CampbellBusyError``.

        The per-user check comes first and does not wait: when a user already has the
        maximum in flight, queueing them would only delay a request the user is not
        waiting for anyway, while occupying a slot another user could use.
        """
        key = str(user_key or "anonimo")
        deadline = time.monotonic() + self.limits.queue_timeout_seconds

        async with self._state_lock:
            if self._per_user.get(key, 0) >= self.limits.max_concurrent_per_user:
                self._rejected += 1
                raise CampbellBusyError(
                    "Ya tienes una consulta de Campbell AI en curso; espera su "
                    "respuesta antes de enviar otra",
                    retry_after=5,
                    scope="user",
                )
            self._per_user[key] = self._per_user.get(key, 0) + 1

        rate_reserved = False
        acquired = False
        try:
            await self._reserve_rate_slot(deadline)
            rate_reserved = True
            try:
                await asyncio.wait_for(
                    self._semaphore.acquire(),
                    timeout=max(0.1, deadline - time.monotonic()),
                )
            except asyncio.TimeoutError as exc:
                async with self._state_lock:
                    self._rejected += 1
                raise CampbellBusyError(
                    "Campbell AI está atendiendo muchas consultas en este momento",
                    retry_after=10,
                    scope="global",
                ) from exc
            acquired = True
            async with self._state_lock:
                self._admitted += 1
                self._in_flight += 1
                self._peak_in_flight = max(self._peak_in_flight, self._in_flight)
            yield
        except CampbellBusyError:
            if rate_reserved:
                await self._release_rate_slot()
            raise
        finally:
            if acquired:
                self._semaphore.release()
                async with self._state_lock:
                    self._in_flight = max(0, self._in_flight - 1)
            async with self._state_lock:
                remaining = self._per_user.get(key, 0) - 1
                if remaining > 0:
                    self._per_user[key] = remaining
                else:
                    self._per_user.pop(key, None)

    def stats(self) -> dict[str, Any]:
        """Load snapshot for operators. No identities, only counts."""
        return {
            "max_concurrent": self.limits.max_concurrent,
            "max_concurrent_per_user": self.limits.max_concurrent_per_user,
            "max_requests_per_minute": self.limits.max_requests_per_minute,
            "in_flight": self._in_flight,
            "peak_in_flight": self._peak_in_flight,
            "active_users": len(self._per_user),
            "admitted": self._admitted,
            "rejected": self._rejected,
        }


# Substrings identifying a failure that a second attempt can plausibly fix. Matching on
# text is crude, but the upstream SDK raises several unrelated classes for the same
# transport-level condition, and importing them here would couple this module to it.
_TRANSIENT_MARKERS = (
    "rate limit",
    "ratelimit",
    "429",
    "500",
    "502",
    "503",
    "504",
    "timeout",
    "timed out",
    "temporarily unavailable",
    "overloaded",
    "connection reset",
    "connection aborted",
    "connection error",
    "server error",
    "bad gateway",
    "service unavailable",
)


def is_transient_failure(exc: BaseException) -> bool:
    """True when retrying the same call could succeed."""
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, CampbellBusyError):
        # Our own admission control: retrying immediately would just be rejected again.
        return False
    if isinstance(exc, CampbellTimeoutError):
        # Our own budget, already spent. Checked before the text match below, which
        # would otherwise see "timeout" in the class name and retry into the deadline.
        return False
    text = f"{type(exc).__name__} {exc}".lower()
    return any(marker in text for marker in _TRANSIENT_MARKERS)


async def execute_with_retry(
    operation: Callable[[], Awaitable[Any]],
    *,
    attempts: int = 3,
    initial_delay: float = 1.0,
    max_delay: float = 30.0,
    multiplier: float = 2.0,
    label: str = "operación",
    deadline: float | None = None,
) -> Any:
    """Run an awaitable, retrying only transient failures with exponential backoff.

    ``deadline`` is an absolute ``time.monotonic()`` instant bounding *all* attempts
    together. Without it a three-attempt retry of a two-minute agent run can occupy a
    worker for six minutes while the caller gave up after the first — the work still
    completes and is persisted, so the user sees a dead UI and then finds the question
    already answered after a refresh. With it, each attempt is capped at the time
    actually left, and a retry that could not finish in time is never started.
    """
    delay = max(0.0, initial_delay)
    last_error: BaseException | None = None

    def _remaining() -> float:
        return float("inf") if deadline is None else deadline - time.monotonic()

    for attempt in range(1, max(1, attempts) + 1):
        remaining = _remaining()
        if remaining <= 0:
            raise CampbellTimeoutError(
                f"Campbell AI agotó el tiempo disponible para {label}"
            )
        try:
            if deadline is None:
                return await operation()
            return await asyncio.wait_for(operation(), timeout=remaining)
        except asyncio.TimeoutError as exc:
            # The budget is spent. Retrying cannot help: the next attempt would have
            # even less time than the one that just ran out.
            raise CampbellTimeoutError(
                f"Campbell AI agotó el tiempo disponible para {label}"
            ) from exc
        except Exception as exc:  # noqa: BLE001 - re-raised below when not transient
            last_error = exc
            if attempt >= attempts or not is_transient_failure(exc):
                raise
            backoff = min(delay, max_delay)
            # Only sleep-and-retry when the retry has a realistic chance of finishing.
            # Burning the remaining budget on backoff just converts a transient error
            # into a timeout.
            if _remaining() - backoff <= _MIN_RETRY_BUDGET_SECONDS:
                raise
            logger.warning(
                "Campbell AI reintentará %s (intento %s/%s): %s",
                label,
                attempt,
                attempts,
                type(exc).__name__,
            )
            await asyncio.sleep(backoff)
            delay = min(delay * multiplier, max_delay) if delay else initial_delay
    # Unreachable: the loop either returns or raises.
    raise last_error if last_error else RuntimeError("execute_with_retry sin resultado")
