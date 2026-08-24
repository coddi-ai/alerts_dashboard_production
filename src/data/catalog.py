"""Read-only catalog of the data sources exposed by the dashboard.

The production data lake is intentionally treated as immutable here.  This
module only probes the mounted tree and returns derived metadata that the UI,
diagnostics and tests can consume.  Keeping path compatibility in one place
prevents individual callbacks from silently disagreeing about whether a
source exists.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Iterable


CLIENTS = ("CDA", "EMIN", "ENEX", "CAPSTONE")


@dataclass(frozen=True)
class SourceProbe:
    client: str
    technique: str
    source: str
    status: str
    path: str | None
    candidates: tuple[str, ...]
    size_bytes: int = 0
    modified_utc: str | None = None
    note: str = ""

    @property
    def available(self) -> bool:
        return self.status in {"available", "partial"}


def dashboard_data_root(explicit: str | os.PathLike[str] | None = None) -> Path:
    """Resolve the mounted data root without reading or creating anything."""

    if explicit:
        return Path(explicit).expanduser().resolve()
    configured = os.getenv("DASHBOARD_DATA_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "data"


def _file_candidates(root: Path, technique: str, client: str, filename: str) -> tuple[Path, ...]:
    client_lower = client.lower()
    if technique == "auxiliar":
        return (
            root / "auxiliar" / client_lower / filename,
            root / "auxiliar" / "golden" / client_lower / filename,
            root / "auxiliar" / "shadow" / client_lower / filename,
        )
    return (root / technique / "golden" / client_lower / filename,)


def resolve_data_file(
    technique: str,
    client: str,
    filename: str,
    root: str | os.PathLike[str] | Path | None = None,
) -> Path | None:
    """Return the first existing compatible file for a client/source."""

    for candidate in _file_candidates(dashboard_data_root(root), technique, client, filename):
        if candidate.is_file():
            return candidate
    return None


def _probe_file(
    client: str,
    technique: str,
    source: str,
    candidates: Iterable[Path],
    *,
    note: str = "",
) -> SourceProbe:
    candidates = tuple(candidates)
    match = next((path for path in candidates if path.is_file()), None)
    if match is None:
        return SourceProbe(
            client=client.upper(),
            technique=technique,
            source=source,
            status="missing",
            path=None,
            candidates=tuple(str(path) for path in candidates),
            note=note,
        )
    stat = match.stat()
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    return SourceProbe(
        client=client.upper(),
        technique=technique,
        source=source,
        status="available",
        path=str(match),
        candidates=tuple(str(path) for path in candidates),
        size_bytes=stat.st_size,
        modified_utc=modified,
        note=note,
    )


def _probe_partitioned(
    client: str,
    technique: str,
    source: str,
    candidates: Iterable[Path],
    *,
    note: str = "",
) -> SourceProbe:
    candidates = tuple(candidates)
    match = next((path for path in candidates if path.is_dir()), None)
    if match is None:
        return SourceProbe(
            client=client.upper(), technique=technique, source=source,
            status="missing", path=None,
            candidates=tuple(str(path) for path in candidates), note=note,
        )
    files = tuple(path for path in match.rglob("*") if path.is_file())
    if not files:
        return SourceProbe(
            client=client.upper(), technique=technique, source=source,
            status="partial", path=str(match),
            candidates=tuple(str(path) for path in candidates), note="Directorio sin archivos de datos.",
        )
    stat = max((path.stat() for path in files), key=lambda item: item.st_mtime)
    modified = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()
    return SourceProbe(
        client=client.upper(), technique=technique, source=source,
        status="available", path=str(match),
        candidates=tuple(str(path) for path in candidates),
        size_bytes=sum(path.stat().st_size for path in files),
        modified_utc=modified, note=note,
    )


def build_client_availability(
    client: str,
    root: str | os.PathLike[str] | Path | None = None,
) -> dict[str, SourceProbe]:
    """Probe every source used by the current dashboard pages."""

    root_path = dashboard_data_root(root)
    client = (client or "").upper()
    client_lower = client.lower()
    result: dict[str, SourceProbe] = {}

    def file_probe(technique: str, source: str, filename: str, note: str = "") -> None:
        result[source] = _probe_file(
            client, technique, source,
            _file_candidates(root_path, technique, client, filename), note=note,
        )

    file_probe("oil", "oil_classified", "classified.parquet")
    file_probe("oil", "oil_machine_status", "machine_status.parquet")
    file_probe("oil", "oil_limits", "stewart_limits.parquet")
    file_probe("oil", "oil_limits_four", "stewart_limits_four.parquet")
    file_probe("oil", "oil_component_hours", "cleaned_component_hours.parquet")
    file_probe("alerts", "alerts_consolidated", "consolidated_alerts.csv")
    file_probe("telemetry", "telemetry_alert_detail", "alerts_detail_wide_with_gps.csv")
    file_probe("auxiliar", "data_freshness", "Data_Date_Last_Update.csv")
    file_probe("predictive", "predictive_ai", "analisis_inteligente.parquet")

    telemetry_root = root_path / "telemetry" / "golden" / client_lower
    result["telemetry_unit_health"] = _probe_partitioned(
        client, "telemetry", "telemetry_unit_health",
        (telemetry_root / "unit_health",),
        note="Materialización requerida por Telemetría > Vista de Flota.",
    )
    result["telemetry_system_health"] = _probe_partitioned(
        client, "telemetry", "telemetry_system_health",
        (telemetry_root / "system_health",),
        note="Materialización requerida por Telemetría > Vista de Flota.",
    )
    result["telemetry_manifest"] = _probe_file(
        client, "telemetry", "telemetry_manifest",
        (telemetry_root / "latest.json",),
    )

    predictive_root = root_path / "predictive" / "golden" / client_lower
    predictive_files = tuple(sorted(predictive_root.glob("*.csv"))) if predictive_root.is_dir() else ()
    predictive_probe = _probe_partitioned(
        client, "predictive", "predictive_components", (predictive_root,),
        note=f"Componentes CSV detectados: {', '.join(path.stem for path in predictive_files) or 'ninguno'}.",
    )
    if predictive_probe.status == "available" and not predictive_files:
        predictive_probe = SourceProbe(
            **{
                **asdict(predictive_probe),
                "status": "partial",
                "note": "Existe la carpeta predictiva, pero no hay CSV de componentes navegables.",
            }
        )
    result["predictive_components"] = predictive_probe

    maintenance_root = root_path / "mantentions" / "golden" / client_lower
    maintenance_contract = maintenance_root / "Maintance_Labeler_Views"
    weekly_files = tuple(sorted(maintenance_root.glob("*.csv"))) if maintenance_root.is_dir() else ()
    result["maintenance_contract"] = _probe_partitioned(
        client, "mantentions", "maintenance_contract", (maintenance_contract,),
        note="Contrato Parquet de acciones/KPIs esperado por Resumen General.",
    )
    if result["maintenance_contract"].status == "missing" and weekly_files:
        result["maintenance_contract"] = SourceProbe(
            **{
                **asdict(result["maintenance_contract"]),
                "status": "partial",
                "path": str(maintenance_root),
                "note": f"Se detectaron {len(weekly_files)} CSV semanales, pero no el contrato Parquet esperado.",
            }
        )

    return result


def availability_status(probes: dict[str, SourceProbe]) -> str:
    """Summarize a source set for a client-facing status banner."""

    if not probes:
        return "missing"
    statuses = {probe.status for probe in probes.values()}
    if statuses == {"available"}:
        return "available"
    if "available" in statuses or "partial" in statuses:
        return "partial"
    return "missing"


def availability_as_dict(client: str, root: str | os.PathLike[str] | Path | None = None) -> dict:
    """Serialize the catalog for Dash stores and audit scripts."""

    probes = build_client_availability(client, root)
    return {
        "client": (client or "").upper(),
        "data_root": str(dashboard_data_root(root)),
        "status": availability_status(probes),
        "sources": {name: asdict(probe) for name, probe in probes.items()},
    }
