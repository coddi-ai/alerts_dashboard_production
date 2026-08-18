"""Which phase an in-flight initialization is currently in, for a UI that has to wait.

`POST /initialize` is one blocking call, and a Dash callback is atomic: between "empezo" and
"listo" the browser has nothing to show. Until now the badge filled that gap with a label
chosen at the start and a stopwatch - honest, but silent about *what* is taking the time.
This module is what makes a real answer possible: the service records the phase it is
entering, and a second, cheap request can ask for it while the first one is still running.

Two properties this deliberately keeps:

- **It reports, it never drives.** Nothing in ``initialize`` waits on, branches on, or fails
  because of anything here. A failure to record progress must never fail a session, so every
  entry point swallows its own errors.
- **It says "no se" rather than guessing.** If no record exists - because the process
  restarted, because the entry expired, or because the poll reached a different replica than
  the one doing the work - the snapshot is inactive and the caller falls back to its generic
  label. A consistently inactive poll during a slow initialization is itself a finding: it
  means more than one API process is answering.

Process-local by construction. Sessions can be shared through Redis; this cannot, and should
not be - it describes what *this* process is doing right now.
"""

from __future__ import annotations

import threading
import time
from typing import Any

# Short, human labels for the badge. One or two words: this goes in a corner pill, not a
# status page. Keys are the phase names used by `CampbellAIService.initialize`, so adding a
# phase there without a label here degrades to the raw name rather than to nothing.
PHASE_LABELS: dict[str, str] = {
    "identity": "Validando acceso",
    "validate": "Leyendo datos",
    "session": "Abriendo sesion",
    "rehydrate": "Buscando conversacion",
    "capabilities": "Preparando agentes",
}

# An entry older than this is stale, not in flight: the call it described either finished
# without clearing itself (a crash between phases) or is so far past any plausible duration
# that reporting it would be misinformation. Comfortably above the worst initialization
# anyone has observed, so a genuinely slow call is still reported as running.
_MAX_AGE_SECONDS = 300.0

# Ceiling on tracked calls. One entry per user initializing concurrently; this is far above
# the admission-control limits, and exists so a leak here can never become the memory
# problem the rest of this package was hardened against.
_MAX_ENTRIES = 64

_LOCK = threading.Lock()
_ENTRIES: dict[str, dict[str, Any]] = {}


def progress_key(username: str, company_id: str) -> str:
    """Identify one user's in-flight initialization for one client."""
    return f"{str(username).strip().lower()}|{str(company_id).strip().lower()}"


def _prune(now: float) -> None:
    """Drop stale entries. Called under the lock, on write paths only."""
    for key in [
        key
        for key, entry in _ENTRIES.items()
        if now - entry["started_at"] > _MAX_AGE_SECONDS
    ]:
        _ENTRIES.pop(key, None)
    while len(_ENTRIES) > _MAX_ENTRIES:
        # Oldest first. Python keeps insertion order, and entries are inserted when their
        # call starts, so the first key is the longest-running one.
        _ENTRIES.pop(next(iter(_ENTRIES)), None)


def begin(key: str, *, resuming: bool) -> None:
    """Record that an initialization started. Replaces any earlier entry for this key."""
    now = time.monotonic()
    with _LOCK:
        _ENTRIES.pop(key, None)
        _prune(now)
        _ENTRIES[key] = {
            "started_at": now,
            "phase": "",
            "phase_started_at": now,
            "resuming": bool(resuming),
        }


def advance(key: str, phase: str) -> None:
    """Record the phase now running. Silent if the call was never registered."""
    now = time.monotonic()
    with _LOCK:
        entry = _ENTRIES.get(key)
        if entry is None:
            return
        entry["phase"] = phase
        entry["phase_started_at"] = now


def finish(key: str) -> None:
    """Forget a finished call, so a later poll reports inactive instead of a stale phase."""
    with _LOCK:
        _ENTRIES.pop(key, None)


def snapshot(key: str) -> dict[str, Any]:
    """What this key is doing right now, as the API returns it.

    ``active`` false means "nothing known here" - not "nothing is running". The caller keeps
    its own label in that case; it must never render this as an error.
    """
    now = time.monotonic()
    with _LOCK:
        entry = _ENTRIES.get(key)
        if entry is None or now - entry["started_at"] > _MAX_AGE_SECONDS:
            return {"active": False, "phase": "", "label": "", "elapsed_ms": 0}
        phase = entry["phase"]
        return {
            "active": True,
            "phase": phase,
            "label": PHASE_LABELS.get(phase, ""),
            "resuming": entry["resuming"],
            "elapsed_ms": int((now - entry["started_at"]) * 1000),
            "phase_elapsed_ms": int((now - entry["phase_started_at"]) * 1000),
        }


def active_count() -> int:
    """How many initializations this process believes are in flight. For diagnostics."""
    now = time.monotonic()
    with _LOCK:
        return sum(
            1
            for entry in _ENTRIES.values()
            if now - entry["started_at"] <= _MAX_AGE_SECONDS
        )


def reset() -> None:
    """Drop every entry. For tests."""
    with _LOCK:
        _ENTRIES.clear()
