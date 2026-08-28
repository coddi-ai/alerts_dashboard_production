"""Memory accounting and byte-budgeted caches for the Campbell AI API process.

This service caches DataFrames so repeated questions do not re-read the same
parquet/CSV. That is the right trade until the cache is unbounded, which is what it
was: a plain dict keyed by (path, mtime) holding a full frame per dataset per client,
evicted only when the same file changed. Measured against the datasets in this
repository, loading all eleven holds 112 MB for CDA, 25 MB for ENEX, 12 MB for
CAPSTONE and 6 MB for EMIN - 155 MB once a day's traffic has touched every client, on
a container sized in the low hundreds of megabytes to a gigabyte.

The cost is not the cache lookup. It is what the cache displaces: with no page cache
left, the same reads that were instant after a restart are hitting cold storage again,
so the service degrades over hours and recovers on restart.

Three primitives, all scoped to this package:

- **Measurement.** ``process_rss_bytes`` and ``container_memory_limit_bytes`` read
  ``/proc`` and the cgroup directly, so nothing has to be installed to know how close
  this process is to being OOM-killed. Both return ``None`` off Linux, and callers
  treat that as "cannot tell" rather than "fine".
- **A cache that cannot grow past a budget.** ``FrameCache`` accounts the real
  in-memory size of each frame and evicts least-recently-used entries until it fits. A
  budget in bytes is the only bound that means anything: entry *count* says nothing
  when one CDA predictive frame outweighs every EMIN dataset combined.
- **A registry.** ``CACHES`` lets the janitor and the diagnostics endpoint drop every
  cache without knowing which caches exist.

Nothing here logs at import time or starts a thread. The janitor that acts on these
numbers lives in ``janitor.py``.
"""

from __future__ import annotations

import functools
import gc
import os
import threading
from collections import OrderedDict
from pathlib import Path
from typing import Any, Callable, Hashable, Optional

# cgroup v2 first: that is what a current Docker Engine gives a container. v1 is kept
# because plenty of hosts still run it, and reading the wrong one silently yields "no
# limit" - which would disable the watchdog exactly where it is needed.
#
# Module-level so tests can point them at fixture files. Everything in this section is
# Linux-only and therefore dead code on a developer's machine: without substitutable
# paths the parsing would first run in production, which is the one place a wrong answer
# is expensive (a misread limit silently disables the watermark).
_PROC_STATM = Path("/proc/self/statm")
_CGROUP_V2_LIMIT = Path("/sys/fs/cgroup/memory.max")
_CGROUP_V2_USAGE = Path("/sys/fs/cgroup/memory.current")
_CGROUP_V1_LIMIT = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")
_CGROUP_V1_USAGE = Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")

# An unlimited cgroup reports a sentinel near 2**63 rather than absent. Treat anything
# above a plainly impossible ceiling as "no limit configured".
_IMPLAUSIBLE_LIMIT = 1 << 55  # 32 PiB

MEGABYTE = 1024 * 1024

def _read_int(path: Path) -> Optional[int]:
    """Read a single integer out of a /proc or /sys file, or None if unreadable."""
    try:
        raw = path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        return None
    if not raw or raw == "max":
        return None
    try:
        return int(raw.split()[0])
    except (ValueError, IndexError):
        return None


def process_rss_bytes() -> Optional[int]:
    """Resident set size of this process, or None where /proc is unavailable.

    Read from ``/proc/self/statm`` rather than through psutil: this has to work in a
    slim container without adding a dependency whose only job is one number.
    """
    try:
        fields = _PROC_STATM.read_text(encoding="utf-8").split()
    except OSError:
        return None
    if len(fields) < 2:
        return None
    try:
        resident_pages = int(fields[1])
    except ValueError:
        return None
    try:
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, ValueError, OSError):
        page_size = 4096
    return resident_pages * page_size


def container_memory_limit_bytes() -> Optional[int]:
    """Memory ceiling enforced on this container, or None when there is none."""
    for path in (_CGROUP_V2_LIMIT, _CGROUP_V1_LIMIT):
        value = _read_int(path)
        if value is not None and 0 < value < _IMPLAUSIBLE_LIMIT:
            return value
    return None


def container_memory_usage_bytes() -> Optional[int]:
    """Charged usage for this container's cgroup, page cache included.

    Reported alongside RSS because they answer different questions: RSS is what this
    process holds and can be made to release, while cgroup usage is what the OOM killer
    looks at. A large gap between them is page cache, which is reclaimable and not a
    problem - it is the point of having any.
    """
    for path in (_CGROUP_V2_USAGE, _CGROUP_V1_USAGE):
        value = _read_int(path)
        if value is not None and 0 < value < _IMPLAUSIBLE_LIMIT:
            return value
    return None


def trim_malloc_arenas() -> bool:
    """Ask glibc to return free arena pages to the OS. True when it ran.

    Freeing a large frame returns its pages to the *allocator*, not necessarily to the
    kernel, so RSS can stay flat right after a cache is dropped and make the reclaim
    look like it did nothing. ``malloc_trim`` closes that gap on glibc. It is absent on
    musl and irrelevant on Windows, so failure here is normal and never an error.
    """
    try:
        import ctypes

        libc = ctypes.CDLL("libc.so.6")
        libc.malloc_trim(0)
        return True
    except Exception:
        return False


def memory_snapshot() -> dict[str, Any]:
    """Everything known about this process's memory footprint, in one dict."""
    rss = process_rss_bytes()
    limit = container_memory_limit_bytes()
    usage = container_memory_usage_bytes()
    snapshot: dict[str, Any] = {
        "rss_bytes": rss,
        "rss_mb": round(rss / MEGABYTE, 1) if rss is not None else None,
        "limit_bytes": limit,
        "limit_mb": round(limit / MEGABYTE, 1) if limit is not None else None,
        "cgroup_usage_bytes": usage,
        "cgroup_usage_mb": round(usage / MEGABYTE, 1) if usage is not None else None,
    }
    if rss is not None and limit:
        snapshot["rss_pct_of_limit"] = round(rss / limit * 100, 1)
    else:
        snapshot["rss_pct_of_limit"] = None
    return snapshot


def frame_nbytes(frame: Any) -> int:
    """Best-effort in-memory size of a pandas object, in bytes.

    ``deep=True`` is the whole point: object columns hold pointers, and a shallow
    measure reports 8 bytes for a 200-character string. Getting this wrong in the cheap
    direction is what lets a "bounded" cache overrun its budget by an order of
    magnitude. The walk costs tens of milliseconds and is paid once per cached file.
    """
    try:
        usage = frame.memory_usage(deep=True)
    except (AttributeError, TypeError):
        try:
            return int(frame.nbytes)
        except (AttributeError, TypeError):
            return 0
    try:
        return int(usage.sum())
    except (AttributeError, TypeError):
        return int(usage)


class FrameCache:
    """LRU cache for pandas objects, bounded by total measured bytes.

    Keys are opaque and hashable; callers key on (path, mtime) so a re-synced file
    becomes a miss instead of serving stale data. Two things are deliberate:

    - **Eviction is by size, not count.** See the module docstring: a count bound is not
      a memory bound when entry sizes differ by 100x.
    - **A frame larger than the whole budget is not cached at all.** Storing it would
      evict everything else and then still not fit, so it is served through and
      forgotten. ``oversized`` counts those, because a nonzero value means the budget is
      too small for the data and should be raised rather than silently defeated.
    """

    def __init__(self, budget_bytes: int, name: str = "frames"):
        self.name = name
        self.budget_bytes = max(1, int(budget_bytes))
        self._entries: "OrderedDict[Hashable, tuple[Any, int]]" = OrderedDict()
        self._bytes = 0
        self._lock = threading.RLock()
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._oversized = 0

    # -- reads ---------------------------------------------------------------

    def get(self, key: Hashable) -> Optional[Any]:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self._misses += 1
                return None
            self._entries.move_to_end(key)
            self._hits += 1
            return entry[0]

    def __contains__(self, key: Hashable) -> bool:
        with self._lock:
            return key in self._entries

    # -- writes --------------------------------------------------------------

    def put(self, key: Hashable, value: Any, nbytes: Optional[int] = None) -> None:
        size = frame_nbytes(value) if nbytes is None else max(0, int(nbytes))
        with self._lock:
            existing = self._entries.pop(key, None)
            if existing is not None:
                self._bytes -= existing[1]
            if size > self.budget_bytes:
                self._oversized += 1
                return
            self._entries[key] = (value, size)
            self._bytes += size
            self._evict_to_budget_locked()

    def _evict_to_budget_locked(self) -> None:
        while self._bytes > self.budget_bytes and self._entries:
            _, (_, size) = self._entries.popitem(last=False)
            self._bytes -= size
            self._evictions += 1

    def invalidate_where(self, predicate: Callable[[Hashable], bool]) -> int:
        """Drop every entry whose key matches. Returns how many went.

        Used to retire the previous generation of a file the moment a new mtime is seen,
        so a re-synced dataset does not keep its stale copy resident until LRU pressure
        happens to reach it.
        """
        with self._lock:
            doomed = [key for key in self._entries if predicate(key)]
            for key in doomed:
                _, size = self._entries.pop(key)
                self._bytes -= size
            return len(doomed)

    def clear(self) -> int:
        """Drop everything. Returns the bytes released."""
        with self._lock:
            released = self._bytes
            self._entries.clear()
            self._bytes = 0
            return released

    # -- reporting -----------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        with self._lock:
            return {
                "entries": len(self._entries),
                "bytes": self._bytes,
                "mb": round(self._bytes / MEGABYTE, 1),
                "budget_mb": round(self.budget_bytes / MEGABYTE, 1),
                "fill_pct": round(self._bytes / self.budget_bytes * 100, 1),
                "hits": self._hits,
                "misses": self._misses,
                "evictions": self._evictions,
                "oversized": self._oversized,
            }


class CacheRegistry:
    """Every cache in the process, so all of them can be dropped at once.

    The janitor and the diagnostics endpoint both need to act on caches they know
    nothing about. Registering a ``clear`` callable (and optionally a ``stats`` one) is
    the entire contract, which means an ``lru_cache``-decorated function and a
    ``FrameCache`` participate on equal terms.
    """

    def __init__(self) -> None:
        self._entries: dict[str, tuple[Callable[[], Any], Optional[Callable[[], Any]]]] = {}
        self._lock = threading.RLock()

    def register(
        self,
        name: str,
        clear: Callable[[], Any],
        stats: Optional[Callable[[], Any]] = None,
    ) -> None:
        with self._lock:
            self._entries[name] = (clear, stats)

    def register_cache(self, cache: FrameCache) -> FrameCache:
        """Register a FrameCache under its own name and return it, for use inline."""
        self.register(cache.name, cache.clear, cache.stats)
        return cache

    def register_lru(self, name: str, function: Any) -> Any:
        """Register an ``lru_cache``-decorated function and return it unchanged."""
        self.register(
            name,
            function.cache_clear,
            lambda: dict(function.cache_info()._asdict()),
        )
        return function

    def clear_all(self) -> dict[str, Any]:
        """Clear every registered cache. One failure never blocks the rest."""
        released: dict[str, Any] = {}
        with self._lock:
            entries = list(self._entries.items())
        for name, (clear, _) in entries:
            try:
                released[name] = clear()
            except Exception as exc:  # pragma: no cover - diagnostics must not raise
                released[name] = f"error: {type(exc).__name__}"
        return released

    def stats(self) -> dict[str, Any]:
        """Per-cache stats for whatever exposes them."""
        report: dict[str, Any] = {}
        with self._lock:
            entries = list(self._entries.items())
        for name, (_, stats) in entries:
            if stats is None:
                continue
            try:
                report[name] = stats()
            except Exception as exc:  # pragma: no cover - diagnostics must not raise
                report[name] = f"error: {type(exc).__name__}"
        return report

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._entries)


# Process-wide registry. Import and register alongside the cache being defined, so a new
# cache cannot be added without becoming reclaimable in the same edit.
CACHES = CacheRegistry()


def registered_lru_cache(
    name: str,
    maxsize: int = 8,
    *,
    env_var: Optional[str] = None,
) -> Callable[[Callable[..., Any]], Any]:
    """``lru_cache`` that registers itself as reclaimable in the same statement.

    Use this instead of ``functools.lru_cache`` for anything in this package that holds
    data. Registration as a separate line after the ``def`` is what gets forgotten, and
    a cache the registry does not know about is one the janitor cannot drop under memory
    pressure.
    """
    resolved = maxsize
    if env_var:
        raw = os.getenv(env_var, "").strip()
        if raw:
            try:
                resolved = max(1, int(float(raw)))
            except ValueError:
                resolved = maxsize

    def decorate(function: Callable[..., Any]) -> Any:
        cached = functools.lru_cache(maxsize=resolved)(function)
        CACHES.register_lru(name, cached)
        return cached

    return decorate


def reclaim(reason: str = "manual") -> dict[str, Any]:
    """Drop every registered cache, collect garbage, and report what it bought.

    Returns before/after memory so the caller can log a line that answers the only
    question worth asking about a reclaim: whether it actually released anything. A
    reclaim that frees nothing means the footprint is not cache-held, and running it
    more often cannot help.
    """
    before = memory_snapshot()
    released = CACHES.clear_all()
    collected = gc.collect()
    trimmed = trim_malloc_arenas()
    after = memory_snapshot()

    freed_mb = None
    if before["rss_bytes"] is not None and after["rss_bytes"] is not None:
        freed_mb = round((before["rss_bytes"] - after["rss_bytes"]) / MEGABYTE, 1)

    return {
        "reason": reason,
        "caches_cleared": released,
        "gc_collected": collected,
        "malloc_trimmed": trimmed,
        "rss_before_mb": before["rss_mb"],
        "rss_after_mb": after["rss_mb"],
        "freed_mb": freed_mb,
    }


def budget_from_env(variable: str, default_mb: int) -> int:
    """Resolve a cache budget in bytes from an env var expressed in MB."""
    raw = os.getenv(variable, "").strip()
    if raw:
        try:
            return max(1, int(float(raw))) * MEGABYTE
        except ValueError:
            pass
    return max(1, int(default_mb)) * MEGABYTE
