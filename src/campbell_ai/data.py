"""Read-only adapter for the dashboard's existing multi-client data layout."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.campbell_ai.errors import CampbellDataError
from src.campbell_ai.identity import normalize_client_id


@dataclass(frozen=True)
class DatasetSpec:
    key: str
    path_template: str
    label: str
    required_column_groups: tuple[tuple[str, ...], ...] = ()


DATASETS: tuple[DatasetSpec, ...] = (
    DatasetSpec(
        "alerts",
        "alerts/golden/{client}/consolidated_alerts.csv",
        "Alertas consolidadas",
        (("UnitId", "Unit", "unit_id"), ("Timestamp", "Fecha", "event_ts")),
    ),
    DatasetSpec(
        "oil_classified",
        "oil/golden/{client}/classified.parquet",
        "Muestras de aceite clasificadas",
        (("unitId", "unit_id", "UnitId"), ("sampleDate", "reportDate")),
    ),
    DatasetSpec(
        "oil_machine_status",
        "oil/golden/{client}/machine_status.parquet",
        "Estado de equipos por aceite",
        (("unit_id", "unitId", "UnitId"), ("overall_status", "report_status")),
    ),
    DatasetSpec(
        "oil_limits",
        "oil/golden/{client}/stewart_limits.parquet",
        "Limites de aceite",
    ),
    DatasetSpec(
        "telemetry_machine_status",
        "telemetry/golden/{client}/machine_status.parquet",
        "Estado de equipos por telemetria",
        (("unit_id", "unitId", "UnitId"), ("overall_status", "component_status")),
    ),
    DatasetSpec(
        "telemetry_classified",
        "telemetry/golden/{client}/classified.parquet",
        "Componentes clasificados por telemetria",
        (("unit_id", "unitId", "UnitId"), ("component_status", "overall_status")),
    ),
    DatasetSpec(
        "maintenance_actions",
        "mantentions/golden/{client}/Maintance_Labeler_Views/query_3_actions_all_equipment.parquet",
        "Acciones de mantenimiento",
        (("machine_code", "machine_id", "UnitId"), ("change_date", "event_ts")),
    ),
    DatasetSpec(
        "maintenance_summary",
        "mantentions/golden/{client}/Resumen_Semanal_Completo.csv",
        "Resumen semanal de mantenimiento",
        (("UnitId", "machine_code", "machine_id"), ("Summary", "Tasks_List")),
    ),
)

DATASET_MAP = {spec.key: spec for spec in DATASETS}


class DashboardDataRepository:
    """Access dashboard datasets in place; files are never copied or rewritten."""

    def __init__(self, data_root: Path | str):
        self.data_root = Path(data_root).expanduser().resolve()
        self._cache: dict[tuple[str, int], pd.DataFrame] = {}
        self._cache_lock = threading.RLock()

    def dataset_path(self, key: str, client: str) -> Path:
        try:
            spec = DATASET_MAP[key]
        except KeyError as exc:
            raise CampbellDataError(f"Dataset no registrado: {key}") from exc

        normalized_client = normalize_client_id(client)
        path = (self.data_root / spec.path_template.format(client=normalized_client)).resolve()
        try:
            path.relative_to(self.data_root)
        except ValueError as exc:
            raise CampbellDataError("Ruta de datos fuera del directorio autorizado") from exc
        return path

    def _read_frame(self, path: Path) -> pd.DataFrame:
        if not path.exists():
            raise CampbellDataError(f"Fuente de datos no disponible: {path.name}")
        mtime_ns = path.stat().st_mtime_ns
        cache_key = (str(path), mtime_ns)
        with self._cache_lock:
            cached = self._cache.get(cache_key)
            if cached is not None:
                return cached.copy(deep=False)

        if path.suffix.lower() == ".csv":
            frame = pd.read_csv(path, low_memory=False)
        elif path.suffix.lower() == ".parquet":
            frame = pd.read_parquet(path)
        else:
            raise CampbellDataError(f"Formato no soportado: {path.suffix}")

        with self._cache_lock:
            stale = [key for key in self._cache if key[0] == str(path) and key != cache_key]
            for key in stale:
                self._cache.pop(key, None)
            self._cache[cache_key] = frame
        return frame.copy(deep=False)

    def load(self, key: str, client: str) -> pd.DataFrame:
        return self._read_frame(self.dataset_path(key, client))

    @staticmethod
    def _resolve_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
        exact = {str(column): str(column) for column in frame.columns}
        lowered = {str(column).lower(): str(column) for column in frame.columns}
        for candidate in candidates:
            if candidate in exact:
                return exact[candidate]
            if candidate.lower() in lowered:
                return lowered[candidate.lower()]
        return None

    def _validate_columns(self, frame: pd.DataFrame, spec: DatasetSpec) -> list[str]:
        missing = []
        for alternatives in spec.required_column_groups:
            if self._resolve_column(frame, alternatives) is None:
                missing.append(" | ".join(alternatives))
        return missing

    def _manifest_status(self) -> dict[str, Any]:
        manifest_path = self.data_root / "auxiliar" / "manifest.json"
        status: dict[str, Any] = {
            "path": str(manifest_path),
            "exists": manifest_path.exists(),
            "valid": False,
        }
        if not manifest_path.exists():
            return status
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            status["valid"] = isinstance(payload, dict)
        except (OSError, json.JSONDecodeError):
            status["valid"] = False
        return status

    def validate_client(self, client: str) -> dict[str, Any]:
        normalized_client = normalize_client_id(client)
        datasets: dict[str, Any] = {}
        available_count = 0
        for spec in DATASETS:
            path = self.dataset_path(spec.key, normalized_client)
            item: dict[str, Any] = {
                "label": spec.label,
                "path": str(path),
                "exists": path.exists(),
                "valid": False,
                "missing_columns": [],
            }
            if path.exists():
                try:
                    frame = self._read_frame(path)
                    missing = self._validate_columns(frame, spec)
                    item.update(
                        {
                            "valid": not missing,
                            "missing_columns": missing,
                            "rows": int(len(frame)),
                            "columns": [str(column) for column in frame.columns],
                        }
                    )
                    if item["valid"]:
                        available_count += 1
                except Exception as exc:
                    item["error"] = type(exc).__name__
            datasets[spec.key] = item

        return {
            "company_id": normalized_client,
            "data_root": str(self.data_root),
            "data_ready": available_count > 0,
            "available_datasets": available_count,
            "manifest": self._manifest_status(),
            "datasets": datasets,
        }

    @staticmethod
    def _clamp(value: int, minimum: int, maximum: int) -> int:
        return max(minimum, min(int(value), maximum))

    def filter_date_window(
        self,
        frame: pd.DataFrame,
        date_col: str | None,
        *,
        days: int = 60,
        start_date: str = "",
        end_date: str = "",
    ) -> tuple[pd.DataFrame, pd.Series | None, dict[str, Any]]:
        """Apply an explicit or relative date window and return public window metadata."""
        if not date_col:
            if start_date or end_date:
                raise CampbellDataError("La fuente no contiene una fecha para aplicar la ventana")
            return frame, None, {"mode": "unavailable"}

        dates = pd.to_datetime(frame[date_col], errors="coerce", utc=True).dt.tz_localize(None)
        valid_dates = dates.dropna()
        if valid_dates.empty:
            raise CampbellDataError("La fuente no contiene fechas válidas")

        def parse_boundary(value: str, label: str) -> pd.Timestamp | None:
            if not str(value or "").strip():
                return None
            try:
                parsed = pd.to_datetime(value, errors="raise", utc=True)
            except (ValueError, TypeError) as exc:
                raise CampbellDataError(f"{label} no tiene un formato de fecha válido") from exc
            return pd.Timestamp(parsed).tz_convert(None)

        start = parse_boundary(start_date, "start_date")
        end = parse_boundary(end_date, "end_date")
        if start is not None and end is not None and start > end:
            raise CampbellDataError("start_date no puede ser posterior a end_date")

        if start is None and end is None:
            resolved_days = self._clamp(days, 1, 3650)
            end = valid_dates.max()
            start = end - pd.Timedelta(days=resolved_days)
            mode = "relative"
        else:
            resolved_days = None
            mode = "explicit"

        mask = dates.notna()
        if start is not None:
            mask &= dates >= start
        if end is not None:
            raw_end = str(end_date or "").strip()
            if raw_end and len(raw_end) <= 10:
                mask &= dates < end + pd.Timedelta(days=1)
            else:
                mask &= dates <= end
        filtered = frame.loc[mask].copy()
        filtered_dates = dates.loc[filtered.index]
        metadata = {
            "mode": mode,
            "start_date": start.isoformat() if start is not None else None,
            "end_date": end.isoformat() if end is not None else None,
            "days": resolved_days,
            "data_min": (
                filtered_dates.min().isoformat() if not filtered_dates.dropna().empty else None
            ),
            "data_max": (
                filtered_dates.max().isoformat() if not filtered_dates.dropna().empty else None
            ),
        }
        return filtered, filtered_dates, metadata

    @staticmethod
    def _records(frame: pd.DataFrame, columns: list[str], limit: int) -> list[dict[str, Any]]:
        selected = list(
            dict.fromkeys(
                column for column in columns if column and column in frame.columns
            )
        )
        if not selected:
            selected = [str(column) for column in frame.columns[:8]]
        subset = frame[selected].head(limit).copy()
        return json.loads(subset.to_json(orient="records", date_format="iso", force_ascii=False))

    def describe_catalog(self, client: str) -> str:
        validation = self.validate_client(client)
        compact = {
            key: {
                "available": value["exists"],
                "valid": value["valid"],
                "rows": value.get("rows", 0),
                "columns": value.get("columns", []),
            }
            for key, value in validation["datasets"].items()
        }
        return json.dumps(compact, ensure_ascii=False, default=str)

    def query_alerts(
        self,
        client: str,
        days: int = 60,
        unit_id: str = "",
        system: str = "",
        component: str = "",
        trigger_type: str = "",
        start_date: str = "",
        end_date: str = "",
        limit: int = 20,
    ) -> str:
        frame = self.load("alerts", client).copy()
        date_col = self._resolve_column(frame, ("Timestamp", "Fecha", "event_ts"))
        unit_col = self._resolve_column(frame, ("UnitId", "Unit", "unit_id"))
        system_col = self._resolve_column(frame, ("sistema", "System", "system"))
        component_col = self._resolve_column(frame, ("componente", "Component", "component"))
        trigger_col = self._resolve_column(frame, ("Trigger_type", "Trigger", "trigger_type"))
        frame, _, window = self.filter_date_window(
            frame,
            date_col,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        if unit_id and unit_col:
            frame = frame[frame[unit_col].astype(str).str.casefold() == unit_id.casefold()]
        if system and system_col:
            frame = frame[
                frame[system_col].astype(str).str.contains(system, case=False, na=False)
            ]
        if component and component_col:
            frame = frame[
                frame[component_col].astype(str).str.contains(component, case=False, na=False)
            ]
        if trigger_type and trigger_col:
            frame = frame[
                frame[trigger_col].astype(str).str.contains(trigger_type, case=False, na=False)
            ]
        if date_col:
            frame = frame.sort_values(date_col, ascending=False)

        summary: dict[str, Any] = {"total": int(len(frame)), "window": window}
        if unit_col:
            summary["by_unit"] = frame[unit_col].value_counts().head(10).to_dict()
        if system_col:
            summary["by_system"] = frame[system_col].value_counts().head(10).to_dict()
        if component_col:
            summary["by_component"] = frame[component_col].value_counts().head(10).to_dict()
        if trigger_col:
            summary["by_trigger"] = frame[trigger_col].value_counts().head(10).to_dict()
        record_columns = [
            date_col,
            unit_col,
            system_col,
            self._resolve_column(frame, ("subsistema", "Subsystem")),
            component_col,
            trigger_col,
            self._resolve_column(frame, ("mensaje_ia", "Description", "Descripcion")),
        ]
        summary["records"] = self._records(
            frame, [value for value in record_columns if value], self._clamp(limit, 1, 50)
        )
        return json.dumps(summary, ensure_ascii=False, default=str)

    def query_maintenance(
        self,
        client: str,
        unit_id: str = "",
        days: int = 60,
        system: str = "",
        component: str = "",
        action_type: str = "",
        start_date: str = "",
        end_date: str = "",
        limit: int = 20,
    ) -> str:
        frame = self.load("maintenance_actions", client).copy()
        date_col = self._resolve_column(frame, ("change_date", "event_ts", "Timestamp"))
        unit_col = self._resolve_column(frame, ("machine_code", "machine_id", "UnitId"))
        system_col = self._resolve_column(frame, ("action_system_name", "job_system_name"))
        component_col = self._resolve_column(frame, ("component_names", "componentName"))
        action_col = self._resolve_column(frame, ("action_type_name", "action_type"))
        frame, _, window = self.filter_date_window(
            frame,
            date_col,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        if unit_id and unit_col:
            frame = frame[frame[unit_col].astype(str).str.casefold() == unit_id.casefold()]
        for value, column in (
            (system, system_col),
            (component, component_col),
            (action_type, action_col),
        ):
            if value and column:
                frame = frame[
                    frame[column].astype(str).str.contains(value, case=False, na=False)
                ]
        if date_col:
            frame = frame.sort_values(date_col, ascending=False)
        columns = [
            date_col,
            unit_col,
            action_col,
            system_col,
            component_col,
            self._resolve_column(frame, ("action_detail_clean", "record_original_text")),
        ]
        payload = {
            "total": int(len(frame)),
            "window": window,
            "by_unit": frame[unit_col].value_counts().head(10).to_dict() if unit_col else {},
            "by_system": frame[system_col].value_counts().head(10).to_dict() if system_col else {},
            "by_component": (
                frame[component_col].value_counts().head(10).to_dict()
                if component_col
                else {}
            ),
            "by_action_type": (
                frame[action_col].value_counts().head(10).to_dict() if action_col else {}
            ),
            "records": self._records(
                frame, [value for value in columns if value], self._clamp(limit, 1, 50)
            ),
        }
        return json.dumps(payload, ensure_ascii=False, default=str)

    def query_oil_status(self, client: str, unit_id: str = "", limit: int = 20) -> str:
        frame = self.load("oil_machine_status", client).copy()
        unit_col = self._resolve_column(frame, ("unit_id", "unitId", "UnitId"))
        if unit_id and unit_col:
            frame = frame[frame[unit_col].astype(str).str.casefold() == unit_id.casefold()]
        priority_col = self._resolve_column(frame, ("priority_score", "machine_score"))
        if priority_col:
            frame = frame.sort_values(priority_col, ascending=False)
        columns = [
            unit_col,
            self._resolve_column(frame, ("latest_sample_date",)),
            self._resolve_column(frame, ("overall_status",)),
            self._resolve_column(frame, ("machine_score",)),
            priority_col,
            self._resolve_column(frame, ("machine_ai_recommendation",)),
        ]
        return json.dumps(
            {
                "total": int(len(frame)),
                "records": self._records(
                    frame, [value for value in columns if value], self._clamp(limit, 1, 50)
                ),
            },
            ensure_ascii=False,
            default=str,
        )

    def query_telemetry_health(
        self, client: str, unit_id: str = "", limit: int = 20
    ) -> str:
        frame = self.load("telemetry_machine_status", client).copy()
        unit_col = self._resolve_column(frame, ("unit_id", "unitId", "UnitId"))
        if unit_id and unit_col:
            frame = frame[frame[unit_col].astype(str).str.casefold() == unit_id.casefold()]
        priority_col = self._resolve_column(frame, ("priority_score", "machine_score"))
        if priority_col:
            frame = frame.sort_values(priority_col, ascending=False)
        columns = [
            unit_col,
            self._resolve_column(frame, ("evaluation_week",)),
            self._resolve_column(frame, ("evaluation_year",)),
            self._resolve_column(frame, ("overall_status",)),
            self._resolve_column(frame, ("machine_score",)),
            priority_col,
            self._resolve_column(frame, ("components_alerta",)),
            self._resolve_column(frame, ("components_anormal",)),
        ]
        return json.dumps(
            {
                "total": int(len(frame)),
                "records": self._records(
                    frame, [value for value in columns if value], self._clamp(limit, 1, 50)
                ),
            },
            ensure_ascii=False,
            default=str,
        )
