"""Offline productive audit for the dashboard's mounted data tree.

The command is deliberately read-only.  It reports source availability and
lightweight file metadata without moving, rewriting or normalising any input
CSV/Parquet/Excel files.  Use ``--json`` to feed the result to another
diagnostic process, or the default Markdown output for a human review.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd

# Support ``python scripts/audit_dashboard.py`` from the repository root as
# well as importing this module from tests.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from src.data.catalog import CLIENTS, SourceProbe, build_client_availability, dashboard_data_root


DATE_COLUMNS = (
    "Fecha", "fecha", "Timestamp", "timestamp", "TimeStart",
    "sampleDate", "latest_sample_date", "evaluation_timestamp",
    "Ultima Fecha de Actualizacion",
)
UNIT_COLUMNS = ("Unit", "unit", "UnitId", "unit_id", "equipo", "Unidad")


def _paths_for_probe(probe: SourceProbe) -> list[Path]:
    if not probe.path:
        return []
    path = Path(probe.path)
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(p for p in path.rglob("*") if p.suffix.lower() in {".csv", ".parquet", ".xlsx"})
    return []


def _inspect_file(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {"path": str(path), "size_bytes": path.stat().st_size}
    try:
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(path, nrows=0)
            result["rows"] = int(sum(1 for _ in path.open("rb"))) - 1
        elif path.suffix.lower() == ".parquet":
            frame = pd.read_parquet(path, engine="pyarrow")
            result["rows"] = int(len(frame))
        elif path.suffix.lower() == ".xlsx":
            frame = pd.read_excel(path, nrows=0)
            result["rows"] = None
        else:
            return result
        result["columns"] = int(len(frame.columns))
        result["column_names"] = [str(column) for column in frame.columns]

        # A bounded full read is useful for local diagnostics.  It is not
        # written back and it intentionally reports only derived metadata.
        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(path)
        elif path.suffix.lower() == ".xlsx":
            frame = pd.read_excel(path)
        for column in DATE_COLUMNS:
            if column not in frame.columns:
                continue
            values = pd.to_datetime(frame[column], errors="coerce", utc=True).dropna()
            if not values.empty:
                result["date_column"] = column
                result["date_min_utc"] = values.min().isoformat()
                result["date_max_utc"] = values.max().isoformat()
                break
        for column in UNIT_COLUMNS:
            if column in frame.columns:
                result["unit_column"] = column
                result["unit_count"] = int(frame[column].dropna().astype(str).nunique())
                break
    except Exception as exc:  # diagnostics must continue across incompatible sources
        result["read_error"] = f"{type(exc).__name__}: {exc}"
    return result


def audit(root: str | None = None) -> dict[str, Any]:
    data_root = dashboard_data_root(root)
    clients: dict[str, Any] = {}
    for client in CLIENTS:
        probes = build_client_availability(client, data_root)
        sources = {}
        for source, probe in probes.items():
            item = {
                "technique": probe.technique,
                "status": probe.status,
                "path": probe.path,
                "size_bytes": probe.size_bytes,
                "modified_utc": probe.modified_utc,
                "note": probe.note,
                "files": [_inspect_file(path) for path in _paths_for_probe(probe)],
            }
            sources[source] = item
        clients[client] = {"status": _aggregate(sources), "sources": sources}
    return {"data_root": str(data_root), "clients": clients}


def _aggregate(sources: dict[str, Any]) -> str:
    statuses = {item["status"] for item in sources.values()}
    if statuses == {"available"}:
        return "available"
    if "available" in statuses or "partial" in statuses:
        return "partial"
    return "missing"


def markdown_report(payload: dict[str, Any]) -> str:
    lines = [
        "# Auditoría offline del dashboard",
        "",
        f"Raíz inspeccionada: `{payload['data_root']}`",
        "",
        "| Cliente | Estado agregado | Fuente | Estado | Tamaño | Observación |",
        "|---|---|---|---|---:|---|",
    ]
    for client, data in payload["clients"].items():
        for source, item in data["sources"].items():
            size_mb = item["size_bytes"] / (1024 * 1024) if item["size_bytes"] else 0
            note = item["note"].replace("|", "\\|")
            lines.append(f"| {client} | {data['status']} | {source} | {item['status']} | {size_mb:.1f} MB | {note} |")
    lines += [
        "",
        "Los detalles de filas, columnas, unidades y fechas quedan en la salida JSON de cada archivo.",
        "Este reporte no modifica las fuentes inspeccionadas.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Raíz de datos montada; por defecto DASHBOARD_DATA_ROOT o ./data")
    parser.add_argument("--json", action="store_true", help="Emitir JSON en vez de Markdown")
    args = parser.parse_args()
    payload = audit(args.root)
    print(json.dumps(payload, ensure_ascii=False, indent=2) if args.json else markdown_report(payload))


if __name__ == "__main__":
    main()
