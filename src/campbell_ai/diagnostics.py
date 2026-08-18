"""One structured snapshot of the Campbell AI API process, for operators without a console.

Everything needed to answer "why is it slow now when it was fast this morning" in a
single payload: resident memory against the container's own limit, what each cache is
holding, the thread census, how many reclaims have fired and what the last one freed,
where the logs are and how large. These are only meaningful *together* - high memory with
a full cache is a tuning problem, high memory with empty caches and a climbing thread
count is a leak somewhere else, and the same number appears in both stories.

``tail_log`` exists because a diagnostics payload nobody can act on is a poster. Reading
the last few hundred lines over HTTP is what makes this something you can debug with.

No secrets, credentials, usernames or conversation content appear in any payload here.
The endpoints that serve it are still authenticated - it is operational detail and does
not belong on the open internet - but a leaked snapshot exposes sizes and counts.
"""

from __future__ import annotations

import gc
import os
import platform
import sys
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Optional

from src.campbell_ai.janitor import janitor_stats
from src.campbell_ai.log_archive import log_archive_stats
from src.campbell_ai.progress import active_count as active_initializations
from src.campbell_ai.logging_setup import logging_description
from src.campbell_ai.resources import CACHES, MEGABYTE, memory_snapshot

# Wall-clock start of this process, captured at first import. `time.monotonic` cannot be
# compared across processes and gives no absolute date, so both are kept.
_PROCESS_STARTED_AT = time.time()
_PROCESS_STARTED_MONOTONIC = time.monotonic()

PROCESS_NAME = "campbell-api"

# A tail longer than this is a log download, not a diagnostic, and would defeat the point
# of not materializing the file.
MAX_TAIL_LINES = 2000
_TAIL_CHUNK_BYTES = 64 * 1024


# The last few initializations, broken down by phase. "Cambiar de cliente se demora un
# minuto" is a complaint; this turns it into a row that says which phase spent the minute.
# Kept here rather than only in the log because a slow initialization is reported after the
# fact, and re-reading a rotated log to find it is worse than asking the process.
#
# Deliberately short: this is the recent past, not history. Company id, never the username -
# this payload promises to carry no identities.
_RECENT_INITIALIZATIONS: deque[dict[str, Any]] = deque(maxlen=20)


def record_initialize_phases(
    company_id: str, *, resuming: bool, phases: dict[str, int]
) -> None:
    """Remember one initialization's phase timings for the diagnostics payload."""
    _RECENT_INITIALIZATIONS.append(
        {
            "at_epoch": round(time.time(), 1),
            "company": company_id,
            "resuming": bool(resuming),
            "total_ms": int(phases.get("total", 0)),
            # Copied: the caller owns its dict and this one outlives the call.
            "phase_ms": dict(phases),
        }
    )


def initialize_phases_info() -> dict[str, Any]:
    """Recent initializations, newest first, with the slowest phase called out."""
    recent = list(_RECENT_INITIALIZATIONS)
    slowest_phase = None
    if recent:
        # Which phase dominates *across* the sample, which is the actionable question. One
        # slow call can be a cold cache; the same phase leading every call is the bottleneck.
        totals: dict[str, int] = {}
        for entry in recent:
            for phase, value in entry["phase_ms"].items():
                if phase != "total":
                    totals[phase] = totals.get(phase, 0) + value
        if totals:
            name, accumulated = max(totals.items(), key=lambda item: item[1])
            slowest_phase = {"phase": name, "total_ms": accumulated}

    return {
        "count": len(recent),
        # In flight right now, per this process. Nonzero while nothing progresses is a
        # different story from zero: the first is a slow call, the second is a lost one.
        "in_flight": active_initializations(),
        "slowest_phase": slowest_phase,
        "recent": list(reversed(recent)),
    }


def process_info() -> dict[str, Any]:
    """Identity and liveness of this process."""
    threads = threading.enumerate()
    return {
        "name": PROCESS_NAME,
        "pid": os.getpid(),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "started_at_epoch": round(_PROCESS_STARTED_AT, 1),
        "uptime_seconds": round(time.monotonic() - _PROCESS_STARTED_MONOTONIC, 1),
        "uptime_hours": round((time.monotonic() - _PROCESS_STARTED_MONOTONIC) / 3600.0, 2),
        "thread_count": len(threads),
        # Names, not stacks. A climbing count of identically-named threads is the signal;
        # capturing stacks for all of them is a profiler's job.
        "thread_names": sorted({thread.name for thread in threads}),
    }


def gc_info() -> dict[str, Any]:
    """Garbage collector state. Rising uncollectable counts mean reference cycles."""
    return {
        "counts": list(gc.get_count()),
        "garbage": len(gc.garbage),
        "enabled": gc.isenabled(),
    }


def log_files_info() -> dict[str, Any]:
    """Log files on disk with sizes, so a filling volume is visible before it fills."""
    directory = Path(os.getenv("CAMPBELL_AI_LOG_DIR", "logs"))
    stem = Path(os.getenv("CAMPBELL_AI_LOG_FILE", "campbell_api.log")).stem
    if not directory.exists():
        return {"dir": str(directory), "exists": False, "files": []}

    files = []
    total = 0
    try:
        # Scoped to this package's own files: the logs/ volume is shared with the
        # dashboard, and reporting its files here would be noise at best.
        for path in sorted(directory.glob(f"{stem}.log*")):
            if not path.is_file():
                continue
            size = path.stat().st_size
            total += size
            files.append(
                {
                    "name": path.name,
                    "mb": round(size / MEGABYTE, 2),
                    "modified_epoch": round(path.stat().st_mtime, 1),
                }
            )
    except OSError as exc:
        return {"dir": str(directory), "exists": True, "error": str(exc), "files": []}

    return {
        "dir": str(directory),
        "exists": True,
        "total_mb": round(total / MEGABYTE, 2),
        "files": files,
    }


def disk_info(paths: Optional[list[str]] = None) -> dict[str, Any]:
    """Free space on the mounts that matter. A full volume mimics every other fault."""
    targets = paths or [os.getenv("CAMPBELL_AI_LOG_DIR", "logs")]
    report: dict[str, Any] = {}
    for target in targets:
        try:
            if hasattr(os, "statvfs"):
                usage = os.statvfs(target)
                total = usage.f_frsize * usage.f_blocks
                free = usage.f_frsize * usage.f_bavail
                used = total - free
            else:
                import shutil

                total, used, free = shutil.disk_usage(target)
            report[target] = {
                "total_mb": round(total / MEGABYTE, 1),
                "used_mb": round(used / MEGABYTE, 1),
                "free_mb": round(free / MEGABYTE, 1),
                "used_pct": round(used / total * 100, 1) if total else None,
            }
        except (OSError, ValueError) as exc:
            report[target] = {"error": f"{type(exc).__name__}: {exc}"}
    return report


def snapshot(*, include_disk: bool = True) -> dict[str, Any]:
    """The full diagnostic payload for this process."""
    payload: dict[str, Any] = {
        "process": process_info(),
        "memory": memory_snapshot(),
        "caches": CACHES.stats(),
        "cache_names": CACHES.names(),
        "janitor": janitor_stats(),
        "initializations": initialize_phases_info(),
        "logging": logging_description(),
        "log_files": log_files_info(),
        "log_archive": log_archive_stats(),
        "gc": gc_info(),
    }
    if include_disk:
        payload["disk"] = disk_info()
    return payload


def tail_log(lines: int = 200, log_file: Optional[Path] = None) -> dict[str, Any]:
    """Last ``lines`` lines of the API's log file, read from the end.

    Seeks backwards in chunks instead of reading the file: at
    ``CAMPBELL_AI_LOG_MAX_BYTES`` the active file can be 10 MB, and loading it to show 200
    lines inside a memory-constrained process would be its own incident.
    """
    requested = max(1, min(int(lines), MAX_TAIL_LINES))
    described = logging_description()
    path = Path(log_file) if log_file else (
        Path(described["file"]) if described.get("file") else None
    )
    if path is None:
        return {"error": "logging is not configured with a file handler", "lines": []}
    if not path.exists():
        return {"error": f"log file not found: {path}", "lines": []}

    try:
        collected: list[bytes] = []
        newlines = 0
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            position = handle.tell()
            while position > 0 and newlines <= requested:
                read_size = min(_TAIL_CHUNK_BYTES, position)
                position -= read_size
                handle.seek(position)
                chunk = handle.read(read_size)
                collected.insert(0, chunk)
                newlines += chunk.count(b"\n")
        # Chunks are contiguous and in order, so joining them yields the file's tail. A
        # chunk boundary can split the first line; slicing to `requested` at the end drops
        # it along with any surplus.
        text = b"".join(collected).decode("utf-8", errors="replace")
        tail = text.splitlines()[-requested:]
        return {
            "file": str(path),
            "size_mb": round(path.stat().st_size / MEGABYTE, 2),
            "requested_lines": requested,
            "returned_lines": len(tail),
            "lines": tail,
        }
    except OSError as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "lines": []}
