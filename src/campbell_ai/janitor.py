"""Background reclamation of cached memory, by pressure and by inactivity.

Two independent triggers, because they catch different failures:

**Pressure.** When resident memory crosses a watermark derived from the container's own
cgroup limit, every registered cache is dropped. This is the difference between a
service that sheds cache and one that gets OOM-killed: with a container in the low
hundreds of megabytes to a gigabyte and a pandas working set of over 100 MB for the
largest client, "grow until something breaks" is not a strategy. The watermark sits
below the limit, since a reclaim has to happen while there is still room to allocate
the machinery that performs it.

**Inactivity.** Overnight, or during any quiet stretch, the caches hold frames nobody is
going to ask for. Releasing them costs a single slow question later and buys back
hundreds of megabytes for the whole idle window - which is also when the kernel would
otherwise be evicting the page cache that makes those same reads fast. Idle reclamation
fires once per quiet stretch, not once per tick.

The janitor also takes a thread census on every tick. It cannot kill a thread - there is
no safe way to do that in CPython, and a request thread wedged in a socket read owns
state that a forced unwind would corrupt - but *counting* them is what turns "the API
feels slower after a day" into a number. A count that climbs monotonically means request
threads are not retiring, which is a server configuration problem rather than a cache
problem. The census is how you tell those two apart without a console.

Every action is logged as one structured line, so it stays legible in an archived log
file to someone who was not watching when it happened.

Scoped to the Campbell AI API process: it is started from the API's startup hook and
touched by its middleware. Nothing outside this package registers with it.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Any, Callable, Optional

from src.campbell_ai.resources import (
    MEGABYTE,
    memory_snapshot,
    process_rss_bytes,
    reclaim,
    watermark_from_env,
)


logger = logging.getLogger("campbell_ai.janitor")


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


class ResourceJanitor:
    """Watches memory and activity; drops caches when either says to."""

    def __init__(
        self,
        *,
        process_name: str = "campbell-api",
        interval_seconds: int = 60,
        idle_seconds: int = 600,
        rss_watermark_bytes: Optional[int] = None,
        thread_warn_threshold: int = 60,
        pressure_cooldown_seconds: Optional[int] = None,
        on_reclaim: Optional[Callable[[dict[str, Any]], None]] = None,
    ):
        self.process_name = process_name
        self.interval_seconds = max(5, int(interval_seconds))
        # Zero disables idle reclamation without disabling the watchdog.
        self.idle_seconds = max(0, int(idle_seconds))
        self.rss_watermark_bytes = rss_watermark_bytes
        self.thread_warn_threshold = max(1, int(thread_warn_threshold))
        # A reclaim that did not help must not be retried every tick: if the footprint is
        # not in the caches, repeating it only burns CPU and floods the log with identical
        # lines, hiding the one useful signal (that it never frees anything).
        self.pressure_cooldown_seconds = (
            int(pressure_cooldown_seconds)
            if pressure_cooldown_seconds is not None
            else max(120, self.interval_seconds * 3)
        )
        self._on_reclaim = on_reclaim

        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.RLock()

        now = time.monotonic()
        self._started_at = now
        self._last_activity = now
        # Activity timestamp the last idle reclaim was performed against. Idle
        # reclamation is allowed again only after new activity moves this forward.
        self._idle_reclaim_marker: Optional[float] = None
        self._last_pressure_reclaim: Optional[float] = None
        self._reclaims_pressure = 0
        self._reclaims_idle = 0
        self._last_reclaim: Optional[dict[str, Any]] = None
        self._peak_rss_bytes = 0
        self._peak_threads = 0

    # -- activity ------------------------------------------------------------

    def touch(self) -> None:
        """Record that the process just did real work. Cheap enough per request."""
        with self._lock:
            self._last_activity = time.monotonic()

    def idle_seconds_now(self) -> float:
        with self._lock:
            return time.monotonic() - self._last_activity

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> "ResourceJanitor":
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=f"campbell-janitor-{self.process_name}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "janitor started process=%s interval=%ss idle=%ss watermark=%s",
            self.process_name,
            self.interval_seconds,
            self.idle_seconds or "off",
            f"{self.rss_watermark_bytes / MEGABYTE:.0f}MB"
            if self.rss_watermark_bytes
            else "unset",
        )
        return self

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def _run(self) -> None:
        # Interruptible sleep: `Event.wait` lets shutdown be immediate instead of waiting
        # out a full interval, which matters for container stop deadlines.
        while not self._stop.wait(self.interval_seconds):
            try:
                self.tick()
            except Exception:  # pragma: no cover - a janitor must never die
                logger.exception("janitor tick failed process=%s", self.process_name)

    # -- the check ------------------------------------------------------------

    def tick(self) -> Optional[dict[str, Any]]:
        """One evaluation. Returns the reclaim report when one was performed.

        Exposed and synchronous so tests drive it directly instead of waiting on a
        thread, and so a diagnostics endpoint can force an evaluation on demand.
        """
        rss = process_rss_bytes()
        threads = threading.active_count()

        with self._lock:
            if rss is not None:
                self._peak_rss_bytes = max(self._peak_rss_bytes, rss)
            self._peak_threads = max(self._peak_threads, threads)

        if threads >= self.thread_warn_threshold:
            # Not an error and not actionable from here - see the module docstring. It is
            # logged because a rising count is the only evidence that request threads are
            # not retiring, and nobody can read `threading.enumerate()` from a browser.
            logger.warning(
                "thread census high process=%s threads=%s threshold=%s",
                self.process_name,
                threads,
                self.thread_warn_threshold,
            )

        if self._should_reclaim_for_pressure(rss):
            return self._reclaim("memory_pressure", rss=rss)

        if self._should_reclaim_for_idle():
            return self._reclaim("inactivity", rss=rss)

        return None

    def _should_reclaim_for_pressure(self, rss: Optional[int]) -> bool:
        if rss is None or not self.rss_watermark_bytes:
            return False
        if rss < self.rss_watermark_bytes:
            return False
        with self._lock:
            last = self._last_pressure_reclaim
        if last is not None and time.monotonic() - last < self.pressure_cooldown_seconds:
            return False
        return True

    def _should_reclaim_for_idle(self) -> bool:
        if not self.idle_seconds:
            return False
        with self._lock:
            if time.monotonic() - self._last_activity < self.idle_seconds:
                return False
            # Already reclaimed for this quiet stretch; wait for new activity.
            return self._idle_reclaim_marker != self._last_activity

    def _reclaim(self, reason: str, *, rss: Optional[int]) -> dict[str, Any]:
        report = reclaim(reason)
        now = time.monotonic()
        with self._lock:
            if reason == "memory_pressure":
                self._last_pressure_reclaim = now
                self._reclaims_pressure += 1
            else:
                self._idle_reclaim_marker = self._last_activity
                self._reclaims_idle += 1
            self._last_reclaim = report

        freed = report.get("freed_mb")
        logger.info(
            "reclaim process=%s reason=%s rss_before=%sMB rss_after=%sMB freed=%sMB "
            "gc_collected=%s caches=%s",
            self.process_name,
            reason,
            report.get("rss_before_mb"),
            report.get("rss_after_mb"),
            freed,
            report.get("gc_collected"),
            ",".join(sorted(report.get("caches_cleared", {}))) or "none",
        )
        if reason == "memory_pressure" and isinstance(freed, (int, float)) and freed < 16:
            # The actionable case: pressure was real, the caches were dropped, and the
            # footprint did not move. Whatever is holding memory is not a cache, so
            # raising the reclaim frequency cannot help and the next place to look is the
            # thread census and the heap.
            logger.warning(
                "reclaim freed almost nothing process=%s freed=%sMB rss=%sMB threads=%s "
                "- footprint is likely not cache-held",
                self.process_name,
                freed,
                report.get("rss_after_mb"),
                threading.active_count(),
            )

        if self._on_reclaim is not None:
            try:
                self._on_reclaim(report)
            except Exception:  # pragma: no cover - hook must not break reclamation
                logger.exception("janitor reclaim hook failed")
        return report

    def force_reclaim(self, reason: str = "manual") -> dict[str, Any]:
        """Reclaim now, ignoring watermark and cooldown. For operator endpoints."""
        return self._reclaim(reason, rss=process_rss_bytes())

    # -- reporting -----------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        with self._lock:
            uptime = time.monotonic() - self._started_at
            return {
                "process": self.process_name,
                "running": bool(self._thread is not None and self._thread.is_alive()),
                "uptime_seconds": round(uptime, 1),
                "interval_seconds": self.interval_seconds,
                "idle_seconds_threshold": self.idle_seconds,
                "idle_seconds_now": round(time.monotonic() - self._last_activity, 1),
                "rss_watermark_mb": round(self.rss_watermark_bytes / MEGABYTE, 1)
                if self.rss_watermark_bytes
                else None,
                "peak_rss_mb": round(self._peak_rss_bytes / MEGABYTE, 1)
                if self._peak_rss_bytes
                else None,
                "threads_now": threading.active_count(),
                "peak_threads": self._peak_threads,
                "thread_warn_threshold": self.thread_warn_threshold,
                "reclaims_pressure": self._reclaims_pressure,
                "reclaims_idle": self._reclaims_idle,
                "last_reclaim": self._last_reclaim,
            }


# One janitor per process. Held module-level so the API middleware can `touch()` it and
# the diagnostics endpoint can read it without threading a reference through every layer.
_JANITOR: Optional[ResourceJanitor] = None
_JANITOR_LOCK = threading.Lock()


def start_janitor(process_name: str = "campbell-api") -> Optional[ResourceJanitor]:
    """Start (or return) this process's janitor, configured from the environment.

    Returns None when disabled by ``CAMPBELL_AI_JANITOR_ENABLED=false``, so a deployment
    can turn the whole thing off without code changes if it ever misbehaves.
    """
    global _JANITOR
    with _JANITOR_LOCK:
        if _JANITOR is not None:
            return _JANITOR
        if not _env_bool("CAMPBELL_AI_JANITOR_ENABLED", True):
            logger.info("janitor disabled by CAMPBELL_AI_JANITOR_ENABLED")
            return None
        janitor = ResourceJanitor(
            process_name=process_name,
            interval_seconds=_env_int("CAMPBELL_AI_JANITOR_INTERVAL_SECONDS", 60),
            # Ten minutes: nothing here is warm-cache sensitive for a user who is not
            # currently asking a question.
            idle_seconds=_env_int("CAMPBELL_AI_JANITOR_IDLE_SECONDS", 600),
            rss_watermark_bytes=watermark_from_env("CAMPBELL_AI_RSS_LIMIT_MB"),
            thread_warn_threshold=_env_int("CAMPBELL_AI_THREAD_WARN", 60),
        )
        _JANITOR = janitor.start()
        return _JANITOR


def get_janitor() -> Optional[ResourceJanitor]:
    return _JANITOR


def touch_activity() -> None:
    """Record activity on the process janitor, if one is running."""
    janitor = _JANITOR
    if janitor is not None:
        janitor.touch()


def reset_janitor() -> None:
    """Stop and forget the process janitor. For tests and controlled reloads."""
    global _JANITOR
    with _JANITOR_LOCK:
        if _JANITOR is not None:
            _JANITOR.stop()
        _JANITOR = None


def janitor_stats() -> dict[str, Any]:
    """Janitor stats plus current memory, or a clear 'not running' payload."""
    janitor = _JANITOR
    if janitor is None:
        return {"running": False, "memory": memory_snapshot()}
    stats = janitor.stats()
    stats["memory"] = memory_snapshot()
    return stats
