"""Background execution for one Campbell AI answer.

An answer takes tens of seconds. While the caller waited for it inside the HTTP
request, three things went wrong at once, and they are the same three things users
report as "se pega la interfaz":

- the browser (or any proxy between it and us) gives up before the agents finish, and
  the request dies — but the work does not. It keeps running, finishes, and writes the
  exchange to the session store and the durable archive. Nobody is listening, so the
  answer is invisible until the page is reloaded, which is why a "stuck" question turns
  out to be already answered after a refresh;
- the Dash callback that dispatched it never returns, so the composer it disabled is
  never re-enabled, and the tab is stuck on "Pensando..." with no way out;
- the user, seeing nothing happen, sends the question again — and a second full agent
  run starts for an answer that already exists.

Separating *doing the work* from *waiting for it* fixes all three. Submitting registers
a job and returns immediately with an id; the work runs as a task owned by this
registry, not by the request that started it. The caller polls. A caller that
disconnects, reloads, or crashes changes nothing about the job: it keeps running and
its result waits to be collected.

Two properties do the heavy lifting:

**Idempotency.** Submissions carry a caller-chosen key. A repeat submission of the same
key — a double click, a retry after a dead connection, a reloaded tab re-dispatching
its pending message — attaches to the job already running instead of starting a second
one. This is what stops duplicate answers.

**Retention.** A finished job keeps its result for a while after completing, so a
browser that reconnects late still collects it.

Scope: the registry is process-local, which matches the in-process session store this
service already uses (`CAMPBELL_AI_SESSION_BACKEND=memory`). Both assume one worker. A
deployment that runs several workers needs Redis for sessions and a shared job store
here; until then, `session_backend` in the health payload is the thing to check.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


logger = logging.getLogger("campbell_ai.jobs")


# Terminal states. A job in any of these will never change again and is eligible for
# eviction once its retention window closes.
_TERMINAL = {"done", "error", "cancelled"}


@dataclass
class Job:
    """One answer being computed, or already computed and waiting to be collected."""

    job_id: str
    dedup_key: str
    status: str = "running"
    created_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    result: dict[str, Any] | None = None
    # Shaped for the API layer: a detail to show and the metadata needed to decide
    # whether retrying is worth it.
    error: dict[str, Any] | None = None
    _task: asyncio.Task | None = field(default=None, repr=False, compare=False)

    @property
    def done(self) -> bool:
        return self.status in _TERMINAL

    def elapsed_seconds(self) -> float:
        end = self.finished_at if self.finished_at is not None else time.monotonic()
        return round(end - self.created_at, 2)

    def as_dict(self) -> dict[str, Any]:
        """Poll payload. Always carries elapsed time, so the caller can decide when to
        offer the user a way out without tracking the wait itself."""
        payload: dict[str, Any] = {
            "job_id": self.job_id,
            "status": self.status,
            "elapsed_seconds": self.elapsed_seconds(),
        }
        if self.result is not None:
            payload["result"] = self.result
        if self.error is not None:
            payload["error"] = self.error
        return payload


class JobRegistry:
    """Owns running answers and keeps finished ones readable for a while."""

    def __init__(self, retention_seconds: float = 900.0, max_jobs: int = 500):
        self.retention_seconds = max(30.0, float(retention_seconds))
        # A backstop, not a tuning knob: retention already bounds the normal case, and
        # this only matters if submissions vastly outpace expiry.
        self.max_jobs = max(10, int(max_jobs))
        self._jobs: dict[str, Job] = {}
        self._by_dedup: dict[str, str] = {}
        self._lock = asyncio.Lock()

    # -- lifecycle ----------------------------------------------------------

    async def submit(
        self,
        dedup_key: str,
        operation: Callable[[], Awaitable[Any]],
        *,
        to_result: Callable[[Any], dict[str, Any]] | None = None,
        on_error: Callable[[BaseException], dict[str, Any]] | None = None,
    ) -> Job:
        """Start `operation` in the background, or return the job already running it.

        `to_result` and `on_error` translate the outcome into the JSON the caller polls
        for, and are applied inside the task so the registry never has to know what an
        answer looks like.
        """
        async with self._lock:
            self._evict_locked()
            existing_id = self._by_dedup.get(dedup_key)
            existing = self._jobs.get(existing_id) if existing_id else None
            if existing is not None and not existing.done:
                # Same question, still being answered. Attaching to it is the whole
                # point: a resubmission must never start a second agent run.
                logger.info(
                    "Campbell AI reusing in-flight job %s for a repeated submission",
                    existing.job_id,
                )
                return existing

            job = Job(job_id=f"job_{uuid.uuid4().hex}", dedup_key=dedup_key)
            self._jobs[job.job_id] = job
            self._by_dedup[dedup_key] = job.job_id

        # Created outside the lock: the task starts running immediately and would
        # otherwise contend for a lock its own creator still holds.
        job._task = asyncio.create_task(
            self._run(job, operation, to_result, on_error),
            name=f"campbell-answer-{job.job_id}",
        )
        return job

    async def _run(
        self,
        job: Job,
        operation: Callable[[], Awaitable[Any]],
        to_result: Callable[[Any], dict[str, Any]] | None,
        on_error: Callable[[BaseException], dict[str, Any]] | None,
    ) -> None:
        try:
            outcome = await operation()
        except asyncio.CancelledError:
            job.status = "cancelled"
            job.finished_at = time.monotonic()
            job.error = {"detail": "La consulta fue cancelada", "kind": "cancelled"}
            raise
        except Exception as exc:  # noqa: BLE001 - reported through the poll payload
            job.status = "error"
            job.finished_at = time.monotonic()
            job.error = (
                on_error(exc)
                if on_error
                else {"detail": str(exc) or "Error interno", "kind": "unknown"}
            )
            # Logged here because nothing re-raises this: the task is the last owner of
            # the exception, and the caller only ever sees the translated payload.
            logger.warning(
                "Campbell AI job %s failed: %s", job.job_id, type(exc).__name__
            )
        else:
            job.status = "done"
            job.finished_at = time.monotonic()
            job.result = to_result(outcome) if to_result else outcome

    async def get(self, job_id: str) -> Job | None:
        async with self._lock:
            self._evict_locked()
            return self._jobs.get(job_id)

    async def cancel(self, job_id: str) -> bool:
        """Ask a running job to stop. Returns whether there was one to stop."""
        async with self._lock:
            job = self._jobs.get(job_id)
        if job is None or job.done or job._task is None:
            return False
        job._task.cancel()
        return True

    # -- eviction -----------------------------------------------------------

    async def evict_expired(self) -> int:
        """Apply the retention rule now, without waiting for traffic. Returns jobs dropped.

        A finished job holds its whole answer - the rendered figures plus the conversation -
        and eviction only ever ran from `submit` and `get`. A burst of questions followed by
        silence therefore left all of it resident with nothing able to release it: the
        retention window needs a caller to tick it, and the janitor could not see this
        registry at all. That is memory a reclaim could not touch, which is part of why a
        reclaim under pressure could report freeing almost nothing.

        Retention is honoured rather than bypassed, and that distinction is the whole point.
        A job that finished two seconds ago is not garbage: its answer is computed and the
        browser is about to poll for it. Dropping those to free memory is precisely the
        "Consulta perdida" the retention window exists to prevent, so this makes eviction
        *reachable*, not more aggressive.

        A coroutine, not a plain function, and that is not incidental: this registry is
        guarded by an `asyncio.Lock` owned by the event loop. Reaching it from the janitor
        thread - the obvious way to hook it into a memory reclaim - cannot work, so the
        periodic caller has to live on the loop. See `prune_jobs` in `api.py`.
        """
        async with self._lock:
            before = len(self._jobs)
            self._evict_locked()
            return before - len(self._jobs)

    def _evict_locked(self) -> None:
        """Drop finished jobs past retention. Caller must hold the lock.

        Running jobs are never evicted regardless of age: the answer timeout bounds how
        long one can live, and dropping a job someone is still polling would resurrect
        the exact bug this module exists to remove.
        """
        now = time.monotonic()
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.done
            and job.finished_at is not None
            and now - job.finished_at > self.retention_seconds
        ]
        if len(self._jobs) - len(expired) > self.max_jobs:
            finished = sorted(
                (
                    job
                    for job in self._jobs.values()
                    if job.done and job.job_id not in set(expired)
                ),
                key=lambda job: job.finished_at or 0.0,
            )
            overflow = len(self._jobs) - len(expired) - self.max_jobs
            expired.extend(job.job_id for job in finished[:overflow])

        for job_id in expired:
            job = self._jobs.pop(job_id, None)
            if job is not None and self._by_dedup.get(job.dedup_key) == job_id:
                self._by_dedup.pop(job.dedup_key, None)

    def stats(self) -> dict[str, Any]:
        """Counts only, no identities — safe for the capabilities endpoint."""
        running = sum(1 for job in self._jobs.values() if not job.done)
        return {
            "tracked": len(self._jobs),
            "running": running,
            "retention_seconds": self.retention_seconds,
        }
