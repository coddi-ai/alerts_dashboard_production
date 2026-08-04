"""Per-client, per-state Parquet warning store for Conexión ERP.

Ported from migration_dashboard/reference/warning_writer.py, with one fix:
the mock laid files out as `{client_id}/warnings/{state}.parquet` (client as
the top-level grouping). The real ERP pipeline instead writes
`data/warnings/{client}/{state}.parquet` — client nested under a top-level
`warnings` folder — see Settings.get_erp_warning_path.

`load_all_warnings`/`compute_kpis`/`apply_filters`/`validation_rate_trend`
are ported from the ERP team's viewer.py — read-side transforms over the
same per-client warning set, used by the Seguimiento de Avisos page.
"""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from config.settings import get_settings
from src.data.erp_schemas import Warning

STATES = ("pending", "validated", "rejected", "sent")

# supporting_data is a nested dict — doesn't round-trip reliably through
# Parquet's columnar schema inference across heterogeneous rows, so it's
# stored as a JSON string (same approach the oil data contract uses for
# breached_essays).
_JSON_FIELDS = ("supporting_data",)

TABLE_COLUMNS = [
    "warning_id",
    "asset_id",
    "source",
    "system",
    "condition_label",
    "severity",
    "status",
    "generated_at",
    "validated_by",
    "erp_reference",
]

_EMPTY_TABLE_DF = pd.DataFrame(columns=TABLE_COLUMNS + ["client_id", "validated_at"])


def _path(client_id: str, state: str) -> Path:
    if state not in STATES:
        raise ValueError(f"Unknown warning state '{state}'")
    return get_settings().get_erp_warning_path(client_id.lower(), state)


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


def transition(
    client_id: str, warning_id: str, from_state: str, to_state: str, **field_updates
) -> Warning:
    """Move a warning from `from_state` to `to_state`, applying field_updates.

    Writes the record into the target state before removing it from the
    source, then rewrites the source file without it — the record is never
    dropped if a write fails partway, though it may briefly exist in both
    files (no concurrency protection; low risk with a single operator today).
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


def load_all_warnings(client_id: str) -> pd.DataFrame:
    """Combine all 4 state files for a client into one DataFrame (one row per Warning)."""
    rows = [
        w.model_dump(mode="json")
        for state in STATES
        for w in read_warnings(client_id, state)
    ]
    if not rows:
        return _EMPTY_TABLE_DF.copy()
    df = pd.DataFrame(rows)
    # ISO8601: records vary in timestamp precision (generated_at has no
    # microseconds, validated_at/sent_at do) — plain to_datetime() infers a
    # single strptime format from the first rows and fails on the rest.
    df["generated_at"] = pd.to_datetime(df["generated_at"], format="ISO8601")
    df["validated_at"] = pd.to_datetime(df["validated_at"], format="ISO8601")
    return df


def compute_kpis(df: pd.DataFrame) -> dict:
    """Total, pending, validated & sent, rejected, avg time to validation."""
    validated_mask = df["validated_at"].notna() if "validated_at" in df else pd.Series(dtype=bool)
    if validated_mask.any():
        deltas = df.loc[validated_mask, "validated_at"] - df.loc[validated_mask, "generated_at"]
        avg_hours = round(deltas.dt.total_seconds().mean() / 3600, 1)
    else:
        avg_hours = None
    return {
        "total": len(df),
        "pending": int((df["status"] == "pending").sum()),
        "validated_and_sent": int(df["status"].isin(["validated", "sent"]).sum()),
        "rejected": int((df["status"] == "rejected").sum()),
        "avg_hours_to_validation": avg_hours,
    }


def apply_filters(
    df: pd.DataFrame,
    source: str | None = None,
    system: str | None = None,
    condition_label: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    asset_id: str | None = None,
    from_date=None,
    to_date=None,
) -> pd.DataFrame:
    """Filter by source, system, condition label, severity, status, asset, date range."""
    filtered = df
    if source:
        filtered = filtered[filtered["source"] == source]
    if system:
        filtered = filtered[filtered["system"] == system]
    if condition_label:
        filtered = filtered[filtered["condition_label"] == condition_label]
    if severity:
        filtered = filtered[filtered["severity"] == severity]
    if status:
        filtered = filtered[filtered["status"] == status]
    if asset_id:
        filtered = filtered[filtered["asset_id"] == asset_id]
    if from_date:
        filtered = filtered[filtered["generated_at"] >= pd.to_datetime(from_date)]
    if to_date:
        filtered = filtered[filtered["generated_at"] <= pd.to_datetime(to_date)]
    return filtered


def validation_rate_trend(df: pd.DataFrame) -> pd.DataFrame:
    """% sent vs rejected per day, among warnings that reached a terminal state."""
    resolved = df[df["status"].isin(["sent", "rejected"]) & df["validated_at"].notna()].copy()
    if resolved.empty:
        return pd.DataFrame(columns=["day", "outcome", "rate"])
    resolved["day"] = resolved["validated_at"].dt.date
    counts = resolved.groupby(["day", "status"]).size().reset_index(name="count")
    counts["rate"] = counts["count"] / counts.groupby("day")["count"].transform("sum") * 100
    return counts.rename(columns={"status": "outcome"})[["day", "outcome", "rate"]]
