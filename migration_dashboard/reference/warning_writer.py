"""Per-client, per-state Parquet warning store (design.md §3.2/§6, REQ-010/011)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from agent.envelope import Warning

STATES = ("pending", "validated", "rejected", "sent")
DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# ponytail: nested dicts don't round-trip reliably through parquet's columnar
# schema inference across heterogeneous rows, so supporting_data is stored as
# a JSON string (same approach the oil data contract uses for breached_essays).
_JSON_FIELDS = ("supporting_data",)


def _path(client_id: str, state: str) -> Path:
    if state not in STATES:
        raise ValueError(f"Unknown warning state '{state}'")
    return DATA_DIR / client_id / "warnings" / f"{state}.parquet"


def _to_row(warning: Warning) -> dict:
    row = warning.model_dump(mode="json")
    for field in _JSON_FIELDS:
        row[field] = json.dumps(row[field])
    return row


def _from_row(row: dict) -> Warning:
    row = dict(row)
    for field in _JSON_FIELDS:
        row[field] = json.loads(row[field])
    return Warning(**row)


def read(client_id: str, state: str) -> pd.DataFrame:
    """Raw DataFrame for a client's state file (supporting_data still JSON-encoded)."""
    path = _path(client_id, state)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def read_warnings(client_id: str, state: str) -> list[Warning]:
    return [_from_row(row) for row in read(client_id, state).to_dict(orient="records")]


def write(client_id: str, state: str, warning: Warning) -> None:
    """Insert `warning`, replacing any existing row with the same warning_id in this state file."""
    path = _path(client_id, state)
    path.parent.mkdir(parents=True, exist_ok=True)
    df = read(client_id, state)
    if not df.empty:
        df = df[df["warning_id"] != warning.warning_id]
    df = pd.concat([df, pd.DataFrame([_to_row(warning)])], ignore_index=True)
    df.to_parquet(path, index=False)


def find_by_id(client_id: str, warning_id: str) -> tuple[Warning, str] | None:
    """Search all state files for `warning_id`. Returns (warning, state) or None."""
    for state in STATES:
        df = read(client_id, state)
        if df.empty:
            continue
        match = df[df["warning_id"] == warning_id]
        if not match.empty:
            return _from_row(match.iloc[0].to_dict()), state
    return None


def find_by_id_any_client(warning_id: str) -> tuple[Warning, str, str] | None:
    """Search every client's warning store for `warning_id`. Returns (warning, client_id, state) or None.

    Used by API routes (`PATCH /warnings/{id}`, `POST /warnings/{id}/send`) that
    identify a warning by its UUID alone, without a client_id in the path.
    """
    if not DATA_DIR.exists():
        return None
    for client_dir in DATA_DIR.iterdir():
        if not client_dir.is_dir():
            continue
        found = find_by_id(client_dir.name, warning_id)
        if found is not None:
            warning, state = found
            return warning, client_dir.name, state
    return None


def transition(
    client_id: str, warning_id: str, from_state: str, to_state: str, **field_updates
) -> Warning:
    """Move a warning from `from_state` to `to_state`, applying field_updates.

    Writes the record into the target state before removing it from the
    source, then rewrites the source file without it — the record is never
    dropped if a write fails partway, though it may briefly exist in both
    files (REQ-011 accepts this per design.md §8, no concurrency protection).
    """
    df = read(client_id, from_state)
    match = df[df["warning_id"] == warning_id]
    if match.empty:
        raise ValueError(
            f"Warning {warning_id} not found in state '{from_state}' for client '{client_id}'"
        )
    warning = _from_row(match.iloc[0].to_dict())
    for field, value in field_updates.items():
        setattr(warning, field, value)
    warning.status = to_state

    write(client_id, to_state, warning)
    remaining = df[df["warning_id"] != warning_id]
    remaining.to_parquet(_path(client_id, from_state), index=False)
    return warning
