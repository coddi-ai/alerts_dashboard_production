"""Persisted index of the values each dataset filter admits.

`describe_dataset` tells the agent which values a filter accepts, and to enumerate them it used
to load the whole frame: 17,6 MB of `alerts_detail` read to list the distinct values of three
columns, up to 961 ms for `oil_classified`. Twenty-four filters across ten datasets.

The index removes that read, and two design rules keep it from becoming a liability.

**It is a shortcut, never a source of truth.** Every entry carries the fingerprint of the file
it was derived from - size and mtime. Fingerprint matches, the entry is used; anything else,
the frame is read and the entry rewritten. It cannot answer from stale data because when it is
not certain it does not answer at all.

That rule is not paranoia here. The prompt tells the agent, literally, *"Si un valor no aparece
aqui, no existe en la fuente: dilo en lugar de aproximar"* - so a stale vocabulary does not
degrade gracefully, it makes the agent confidently deny data that exists. Slow is recoverable;
that is not.

**It holds derived values only** - the vocabularies themselves, no rows. An index that starts
carrying raw data stops being an index and becomes a second copy of the database.

Built lazily, on the first query per file version, and persisted. The plan this implements
proposed building it in a thread at startup instead; the measurement argued against it - warming
every client would read 200 MB on every boot to save a query that happens rarely, and would
evict the frame cache while doing it. Persisting to disk gets the same result where it matters:
the read is paid once per file version *and survives a restart*, because `logs/` is a bind mount
that outlives the container.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional

from src.campbell_ai.resources import CACHES

logger = logging.getLogger("campbell_ai.index")

DEFAULT_INDEX_DIR = "logs/campbell_ai_index"
INDEX_FILENAME = "vocabularies.json"

# Four clients times eleven datasets is 44; the ceiling exists so a bug here cannot grow
# without bound, not because the real number is near it.
_MAX_ENTRIES = 96

_LOCK = threading.Lock()
_ENTRIES: dict[str, dict[str, Any]] = {}
_LOADED = False
_STATS = {"hits": 0, "misses": 0, "stale": 0, "writes": 0, "write_errors": 0}


def index_path() -> Path:
    return Path(os.getenv("CAMPBELL_AI_INDEX_DIR", DEFAULT_INDEX_DIR)) / INDEX_FILENAME


def enabled() -> bool:
    raw = os.getenv("CAMPBELL_AI_VOCABULARY_INDEX")
    if raw is None:
        return True
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def fingerprint(path: Path) -> Optional[dict[str, int]]:
    """Size and mtime of the file an entry was derived from, or None if unreadable."""
    try:
        stat = path.stat()
    except OSError:
        return None
    return {"size": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns)}


def _key(client: str, dataset_key: str) -> str:
    return f"{str(client).strip().lower()}|{dataset_key}"


def _load_locked() -> None:
    """Read the index file once per process. A broken file is discarded, not repaired."""
    global _LOADED
    if _LOADED:
        return
    _LOADED = True
    path = index_path()
    if not path.exists():
        return
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        entries = document.get("entries")
        if isinstance(entries, dict):
            _ENTRIES.update(
                {
                    key: value
                    for key, value in entries.items()
                    if isinstance(value, dict) and "fingerprint" in value
                }
            )
    except Exception as exc:  # noqa: BLE001 - degrade to recomputing, never fail a query
        logger.warning(
            "Indice de vocabularios ilegible (%s: %s); se reconstruye al consultar",
            type(exc).__name__,
            exc,
        )


def _persist_locked() -> None:
    """Write the index atomically, so a crash mid-write cannot leave it truncated."""
    path = index_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps({"entries": _ENTRIES}, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
        os.replace(temporary, path)
        _STATS["writes"] += 1
    except OSError as exc:
        # In-memory entries still stand, so the process keeps the benefit for its own
        # lifetime and only loses it across a restart.
        _STATS["write_errors"] += 1
        logger.warning("No se pudo escribir el indice de vocabularios: %s", exc)


def lookup(client: str, dataset_key: str, path: Path) -> Optional[dict[str, Any]]:
    """The stored vocabulary, only if it was derived from exactly this file version."""
    if not enabled():
        return None
    current = fingerprint(path)
    if current is None:
        return None
    with _LOCK:
        _load_locked()
        entry = _ENTRIES.get(_key(client, dataset_key))
        if entry is None:
            _STATS["misses"] += 1
            return None
        if entry.get("fingerprint") != current:
            # The file moved on. The entry is not repaired here - the caller reads the frame
            # and overwrites it, which is the only way the new values can be right.
            _STATS["stale"] += 1
            return None
        _STATS["hits"] += 1
        vocabulary = entry.get("vocabulary")
        return dict(vocabulary) if isinstance(vocabulary, dict) else None


def store(client: str, dataset_key: str, path: Path, vocabulary: dict[str, Any]) -> None:
    """Remember a vocabulary against the fingerprint of the file it came from."""
    if not enabled():
        return
    current = fingerprint(path)
    if current is None:
        return
    with _LOCK:
        _load_locked()
        while len(_ENTRIES) >= _MAX_ENTRIES:
            _ENTRIES.pop(next(iter(_ENTRIES)), None)
        _ENTRIES[_key(client, dataset_key)] = {
            "fingerprint": current,
            "vocabulary": vocabulary,
        }
        _persist_locked()


def clear_index() -> int:
    """Forget every entry, in memory and on disk. Returns how many were dropped."""
    with _LOCK:
        dropped = len(_ENTRIES)
        _ENTRIES.clear()
        _persist_locked()
    return dropped


def index_stats() -> dict[str, Any]:
    with _LOCK:
        return {
            "file": str(index_path()),
            "enabled": enabled(),
            "entries": len(_ENTRIES),
            "max_entries": _MAX_ENTRIES,
            **_STATS,
        }


def reset() -> None:
    """Drop the in-memory state without touching the file. For tests."""
    global _LOADED
    with _LOCK:
        _ENTRIES.clear()
        _LOADED = False
        for key in _STATS:
            _STATS[key] = 0


CACHES.register("filter_vocabularies", clear_index, index_stats)
