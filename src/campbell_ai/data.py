"""Read-only adapter for the dashboard's existing multi-client data layout."""

from __future__ import annotations

import json
import re
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.campbell_ai.errors import CampbellDataError
from src.campbell_ai.identity import normalize_client_id
from src.charts.signals import signal_label


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
    DatasetSpec(
        "alerts_detail",
        "telemetry/golden/{client}/alerts_detail_wide_with_gps.csv",
        "Detalle de senales por alerta",
        (("AlertID",), ("Unit", "UnitId", "unit_id"), ("Trigger",)),
    ),
    DatasetSpec(
        "predictive_motor",
        "predictive/golden/{client}/motor.csv",
        "Modelo predictivo de motor",
        (("Unit", "unitId", "unit_id"), ("ranking",)),
    ),
    DatasetSpec(
        "predictive_transmission",
        "predictive/golden/{client}/transmision.csv",
        "Modelo predictivo de transmision",
        (("Unit", "unitId", "unit_id"), ("ranking",)),
    ),
)

DATASET_MAP = {spec.key: spec for spec in DATASETS}

# Which agent tool reads each dataset; surfaced by `describe_catalog` so the analyst
# escalates to the right tool instead of assuming a source is unreachable.
DATASET_TOOLS: dict[str, str] = {
    "alerts": "query_alerts",
    "alerts_detail": "query_alert_detail",
    "oil_machine_status": "query_oil_status",
    "oil_classified": "query_oil_components",
    "oil_limits": "query_oil_components (limites de referencia)",
    "telemetry_machine_status": "query_telemetry_health",
    "telemetry_classified": "query_telemetry_components",
    "maintenance_actions": "query_maintenance",
    "maintenance_summary": "query_maintenance_summary",
    "predictive_motor": "query_predictive_risk(domain='motor')",
    "predictive_transmission": "query_predictive_risk(domain='transmision')",
}

@dataclass(frozen=True)
class FilterSpec:
    """A tool parameter that filters a dataset, and the columns it resolves against."""

    parameter: str
    columns: tuple[str, ...]
    # "category" filters expose their vocabulary so a failed guess can be corrected.
    kind: str = "category"


# Declared once so the schema tool and the error hints cannot drift from the
# filters the query methods actually apply.
DATASET_FILTERS: dict[str, tuple[FilterSpec, ...]] = {
    "alerts": (
        FilterSpec("unit_id", ("UnitId", "Unit", "unit_id"), "unit"),
        FilterSpec("system", ("sistema", "System", "system")),
        FilterSpec("subsystem", ("subsistema", "SubSystem", "Subsystem")),
        FilterSpec("component", ("componente", "Component", "component")),
        FilterSpec("trigger_type", ("Trigger_type", "Trigger", "trigger_type")),
        FilterSpec("trigger_var", ("Trigger_Var", "trigger_var")),
    ),
    "alerts_detail": (
        FilterSpec("unit_id", ("Unit", "UnitId", "unit_id"), "unit"),
        FilterSpec("trigger", ("Trigger", "trigger")),
        FilterSpec("alert_id", ("AlertID", "alert_id"), "identifier"),
    ),
    "maintenance_actions": (
        FilterSpec("unit_id", ("machine_code", "machine_id", "UnitId"), "unit"),
        FilterSpec("system", ("action_system_name", "job_system_name")),
        FilterSpec("component", ("component_names", "componentName")),
        FilterSpec("action_type", ("action_type_name", "action_type")),
    ),
    "maintenance_summary": (
        FilterSpec("unit_id", ("UnitId", "machine_code", "machine_id"), "unit"),
    ),
    "oil_machine_status": (
        FilterSpec("unit_id", ("unit_id", "unitId", "UnitId"), "unit"),
    ),
    "oil_classified": (
        FilterSpec("unit_id", ("unitId", "unit_id", "UnitId"), "unit"),
        FilterSpec("component", ("componentNameNormalized", "componentName")),
        FilterSpec("status", ("report_status", "overall_status")),
    ),
    "telemetry_machine_status": (
        FilterSpec("unit_id", ("unit_id", "unitId", "UnitId"), "unit"),
    ),
    "telemetry_classified": (
        FilterSpec("unit_id", ("unit_id", "unitId", "UnitId"), "unit"),
        FilterSpec("component", ("component", "componentName")),
        FilterSpec("status", ("component_status", "overall_status")),
    ),
    "predictive_motor": (
        FilterSpec("unit_id", ("Unit", "unitId", "unit_id"), "unit"),
    ),
    "predictive_transmission": (
        FilterSpec("unit_id", ("Unit", "unitId", "unit_id"), "unit"),
    ),
}

# Which dataset each tool reads, so an error can name the source to inspect.
TOOL_DATASETS: dict[str, str] = {
    "query_alerts": "alerts",
    "query_alert_detail": "alerts_detail",
    "query_alert_signals": "alerts_detail",
    "query_maintenance": "maintenance_actions",
    "query_maintenance_summary": "maintenance_summary",
    "query_oil_status": "oil_machine_status",
    "query_oil_components": "oil_classified",
    "query_telemetry_health": "telemetry_machine_status",
    "query_telemetry_components": "telemetry_classified",
    "query_predictive_risk": "predictive_motor",
}

@dataclass(frozen=True)
class AnalysisCapability:
    """One kind of analysis, and the datasets it cannot work without."""

    key: str
    label: str
    tools: tuple[str, ...]
    requires: tuple[str, ...]
    requires_predictive_module: bool = False


# Clients do not all carry the same techniques: EMIN has no telemetry, ENEX only
# oil, capstone no maintenance. Declaring what each analysis needs lets the agent
# learn its limits up front instead of discovering them through failures.
ANALYSIS_CAPABILITIES: tuple[AnalysisCapability, ...] = (
    AnalysisCapability(
        "alerts", "Alertas consolidadas", ("query_alerts",), ("alerts",)
    ),
    AnalysisCapability(
        "alert_detail",
        "Valor medido y umbral de la señal que disparó una alerta",
        ("query_alert_detail", "query_alert_signals"),
        ("alerts_detail",),
    ),
    AnalysisCapability(
        "alert_sensor_trend",
        "Series de las senales de una alerta contra sus limites",
        ("render_dashboard_chart(alert_sensor_trend)",),
        ("alerts_detail",),
    ),
    AnalysisCapability(
        "maintenance",
        "Acciones de mantenimiento",
        ("query_maintenance",),
        ("maintenance_actions",),
    ),
    AnalysisCapability(
        "maintenance_summary",
        "Resumen semanal de mantenimiento",
        ("query_maintenance_summary",),
        ("maintenance_summary",),
    ),
    AnalysisCapability(
        "oil_fleet",
        "Condición de la flota por análisis de aceite",
        ("query_oil_status",),
        ("oil_machine_status",),
    ),
    AnalysisCapability(
        "oil_components",
        "Condición por componente y ensayos fuera de límite",
        ("query_oil_components",),
        ("oil_classified",),
    ),
    AnalysisCapability(
        "oil_limits",
        "Comparación de ensayos contra sus límites de referencia",
        ("render_dashboard_chart(oil_essay_radar)",),
        ("oil_classified", "oil_limits"),
    ),
    AnalysisCapability(
        "telemetry_fleet",
        "Condición de la flota por telemetría",
        ("query_telemetry_health",),
        ("telemetry_machine_status",),
    ),
    AnalysisCapability(
        "telemetry_components",
        "Componentes y señales disparadoras por telemetría",
        ("query_telemetry_components",),
        ("telemetry_classified",),
    ),
    AnalysisCapability(
        "predictive_motor",
        "Modelo predictivo de motor",
        ("query_predictive_risk(domain='motor')",),
        ("predictive_motor",),
        requires_predictive_module=True,
    ),
    AnalysisCapability(
        "predictive_transmission",
        "Modelo predictivo de transmisión",
        ("query_predictive_risk(domain='transmision')",),
        ("predictive_transmission",),
        requires_predictive_module=True,
    ),
)


# Shared bands so predictive ranking is read identically by every consumer.
PREDICTIVE_BANDS: tuple[tuple[float, str], ...] = (
    (35.0, "Saludable"),
    (55.0, "Monitoreo"),
    (75.0, "Prioridad alta"),
    (float("inf"), "Critico"),
)


def predictive_band(value: float) -> str:
    """Map a predictive ranking score to its health band."""
    for threshold, label in PREDICTIVE_BANDS:
        if value < threshold:
            return label
    return "Critico"


def predictive_module_allows(client: str) -> bool:
    """Honour the dashboard's Predictive module allowlist for the requested client."""
    from config.settings import get_settings

    allowed = {
        str(value).strip().lower() for value in get_settings().predictive_allowed_clients
    }
    return normalize_client_id(client) in allowed


class DashboardDataRepository:
    """Access dashboard datasets in place; files are never copied or rewritten."""

    def __init__(self, data_root: Path | str):
        self.data_root = Path(data_root).expanduser().resolve()
        self._cache: dict[tuple[str, int], pd.DataFrame] = {}
        self._probe_cache: dict[tuple[str, int], dict[str, Any]] = {}
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

    def _probe_frame(self, path: Path) -> dict[str, Any]:
        """Read only columns and row count so validation never materializes a dataset."""
        mtime_ns = path.stat().st_mtime_ns
        cache_key = (str(path), mtime_ns)
        with self._cache_lock:
            cached = self._probe_cache.get(cache_key)
            if cached is not None:
                return cached
            frame = self._cache.get(cache_key)
        if frame is not None:
            probe = {
                "columns": [str(column) for column in frame.columns],
                "rows": int(len(frame)),
            }
        elif path.suffix.lower() == ".parquet":
            import pyarrow.parquet as pq

            metadata = pq.ParquetFile(path)
            probe = {
                "columns": [str(name) for name in metadata.schema_arrow.names],
                "rows": int(metadata.metadata.num_rows),
            }
        elif path.suffix.lower() == ".csv":
            header = pd.read_csv(path, nrows=0, low_memory=False)
            columns = [str(column) for column in header.columns]
            # Parse a single column so quoted newlines are counted correctly without
            # materializing every field of a wide dataset.
            counted = pd.read_csv(path, usecols=[0], low_memory=False) if columns else header
            probe = {"columns": columns, "rows": int(len(counted))}
        else:
            raise CampbellDataError(f"Formato no soportado: {path.suffix}")

        with self._cache_lock:
            stale = [key for key in self._probe_cache if key[0] == str(path) and key != cache_key]
            for key in stale:
                self._probe_cache.pop(key, None)
            self._probe_cache[cache_key] = probe
        return probe

    @staticmethod
    def _resolve_name(columns: list[str], candidates: tuple[str, ...]) -> str | None:
        exact = {str(column): str(column) for column in columns}
        lowered = {str(column).lower(): str(column) for column in columns}
        for candidate in candidates:
            if candidate in exact:
                return exact[candidate]
            if candidate.lower() in lowered:
                return lowered[candidate.lower()]
        return None

    @classmethod
    def _resolve_column(cls, frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
        return cls._resolve_name([str(column) for column in frame.columns], candidates)

    def _validate_columns(self, columns: list[str], spec: DatasetSpec) -> list[str]:
        missing = []
        for alternatives in spec.required_column_groups:
            if self._resolve_name(columns, alternatives) is None:
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
                    probe = self._probe_frame(path)
                    missing = self._validate_columns(probe["columns"], spec)
                    item.update(
                        {
                            "valid": not missing,
                            "missing_columns": missing,
                            "rows": probe["rows"],
                            "columns": probe["columns"],
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

    _STRINGIFIED_LIST = re.compile(r"^\[\s*(.*?)\s*\]$", re.DOTALL)

    @classmethod
    def _flatten_cell(cls, value: Any) -> Any:
        """Render list-like cells (real or already stringified) as readable text."""
        if isinstance(value, (list, tuple, set, np.ndarray)):
            return ", ".join(str(item) for item in value)
        if isinstance(value, str):
            match = cls._STRINGIFIED_LIST.match(value.strip())
            if match:
                inner = match.group(1)
                if not inner:
                    return ""
                parts = [part.strip().strip("'\"") for part in inner.split(",")]
                return ", ".join(part for part in parts if part)
        return value

    @staticmethod
    def _is_textual(series: pd.Series) -> bool:
        """True for object/string columns under both pandas 2 (object) and 3 (str)."""
        dtype = series.dtype
        return not (
            pd.api.types.is_numeric_dtype(dtype)
            or pd.api.types.is_bool_dtype(dtype)
            or pd.api.types.is_datetime64_any_dtype(dtype)
        )

    @classmethod
    def _categorical(cls, series: pd.Series) -> pd.Series:
        """Make a column safe for value_counts even when cells hold lists or arrays."""
        if not cls._is_textual(series):
            return series
        return series.map(cls._flatten_cell)

    def _distribution(self, frame: pd.DataFrame, column: str | None, top: int = 10) -> dict:
        if not column or column not in frame.columns or frame.empty:
            return {}
        return {
            str(key): int(value)
            for key, value in self._categorical(frame[column])
            .value_counts()
            .head(top)
            .items()
        }

    @staticmethod
    def _normalize_unit(value: Any) -> str:
        """Normalize equipment identifiers so T_9, T_09, T-9 and T9 all compare equal."""
        text = str(value or "").strip().upper()
        if not text:
            return ""
        match = re.match(r"^([A-Z]*)[\s\-_]*0*(\d+)$", text)
        if match:
            return f"{match.group(1)}{int(match.group(2))}"
        return re.sub(r"[\s\-_]+", "", text)

    _FUSION_ID = re.compile(r"^F-(\d+)-\d+$", re.IGNORECASE)

    @classmethod
    def _normalize_alert_id(cls, alert_id: str) -> str:
        """Accept a FusionID and return the numeric id used by the detail table."""
        text = str(alert_id or "").strip()
        match = cls._FUSION_ID.match(text)
        return match.group(1) if match else text

    @staticmethod
    def _fold(value: Any) -> str:
        """Casefold and strip accents so 'Refrigeración' matches 'Refrigeracion'."""
        text = unicodedata.normalize("NFKD", str(value or ""))
        return "".join(char for char in text if not unicodedata.combining(char)).casefold()

    def _filter_contains(
        self, frame: pd.DataFrame, column: str | None, needle: str
    ) -> pd.DataFrame:
        """Substring filter that ignores case and accents, as users type either form."""
        if not needle or not column or column not in frame.columns:
            return frame
        target = self._fold(needle).strip()
        if not target:
            return frame
        folded = self._categorical(frame[column]).map(self._fold)
        return frame[folded.str.contains(re.escape(target), na=False)]

    def _filter_hints(
        self,
        frame: pd.DataFrame,
        applied: list[tuple[str, str, str]],
    ) -> dict[str, Any]:
        """When a filter empties the result, expose the values that do exist.

        Without this, a near-miss such as searching a system name that is really a
        subsystem is indistinguishable from "this never happened".
        """
        hints: dict[str, Any] = {
            "detail": (
                "Ningun registro coincide con los filtros aplicados. Revisa los valores "
                "existentes antes de concluir que el evento no ocurrio; el termino buscado "
                "puede pertenecer a otra columna."
            ),
            "applied": {name: value for name, value, _ in applied},
            "available_values": {},
        }
        for name, _, column in applied:
            if column and column in frame.columns:
                hints["available_values"][name] = list(
                    self._distribution(frame, column, top=12)
                )
        return hints

    def _filter_unit(
        self, frame: pd.DataFrame, unit_col: str | None, unit_id: str
    ) -> pd.DataFrame:
        """Filter by equipment id tolerating the id formats used across techniques."""
        if not unit_id or not unit_col:
            return frame
        target = self._normalize_unit(unit_id)
        normalized = frame[unit_col].map(self._normalize_unit)
        return frame[normalized == target]

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
            # Absolute coverage of the source, so a caller can tell "no records in the
            # window" apart from "this source simply stops earlier than the others".
            "source_coverage": {
                "first": valid_dates.min().isoformat(),
                "last": valid_dates.max().isoformat(),
            },
        }
        return filtered, filtered_dates, metadata

    @staticmethod
    def _translate_signal_list(value: Any, separators: str = ",;") -> str | None:
        """Translate one signal code or a delimited list of them into Spanish.

        Alerts and components can be triggered by more than one signal at once
        (e.g. a telemetry signal alongside a tribology variable), stored as a single
        delimited string. Each token is looked up independently so a mixed-trigger
        value like "AirFltr,Hierro" becomes "Restricción del filtro de aire, Hierro"
        instead of reaching the model as raw codes it must guess at or translate
        itself.
        """
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        text = str(value).strip()
        if not text:
            return None
        tokens = [token.strip() for token in re.split(f"[{re.escape(separators)}]", text) if token.strip()]
        if not tokens:
            return None
        return ", ".join(signal_label(token) or token for token in tokens)

    @classmethod
    def _records(cls, frame: pd.DataFrame, columns: list[str], limit: int) -> list[dict[str, Any]]:
        selected = list(
            dict.fromkeys(
                column for column in columns if column and column in frame.columns
            )
        )
        if not selected:
            selected = [str(column) for column in frame.columns[:8]]
        subset = frame[selected].head(limit).copy()
        for column in subset.columns:
            subset[column] = cls._categorical(subset[column])
        return json.loads(subset.to_json(orient="records", date_format="iso", force_ascii=False))

    @staticmethod
    def _compact_breached_essays(raw: Any, top: int = 6) -> list[dict[str, Any]] | None:
        """Reduce the verbose breached-essay payload to the fields an analyst needs."""
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            return None
        items = raw
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except json.JSONDecodeError:
                return None
        if isinstance(items, np.ndarray):
            items = items.tolist()
        if not isinstance(items, list):
            return None
        compact = [
            {
                "essay": item.get("essay"),
                "value": item.get("value"),
                "limit": item.get("limit"),
                "threshold": item.get("threshold"),
                "group": item.get("group"),
                "classifies": bool(item.get("use_for_classification")),
            }
            for item in items
            if isinstance(item, dict)
        ]
        compact.sort(key=lambda item: (not item["classifies"], -float(item.get("value") or 0)))
        return compact[:top] or None

    def describe_catalog(self, client: str) -> str:
        """Describe which sources exist, naming the tool that reads each one."""
        validation = self.validate_client(client)
        predictive_allowed = predictive_module_allows(client)
        compact = {}
        for key, value in validation["datasets"].items():
            # Do not advertise a source the active client is not allowed to read.
            if key.startswith("predictive_") and not predictive_allowed:
                continue
            columns = value.get("columns", [])
            compact[key] = {
                "available": value["exists"],
                "valid": value["valid"],
                "rows": value.get("rows", 0),
                "read_with": DATASET_TOOLS.get(key, "sin herramienta directa"),
                "columns": columns[:40],
                "columns_truncated": len(columns) > 40,
            }
        return json.dumps(compact, ensure_ascii=False, default=str)

    def client_capabilities(self, client: str) -> dict[str, Any]:
        """Which analyses are possible for this client, and why the rest are not.

        Data coverage differs per company, so an agent that assumes CDA's catalogue
        will promise analyses that cannot run. Resolving capability once, from the
        datasets that are actually present, turns those into an upfront limitation
        instead of a mid-answer failure.
        """
        normalized = normalize_client_id(client)
        validation = self.validate_client(normalized)
        datasets = validation["datasets"]
        predictive_allowed = predictive_module_allows(normalized)

        available: list[dict[str, Any]] = []
        unavailable: list[dict[str, Any]] = []
        for capability in ANALYSIS_CAPABILITIES:
            missing = [
                DATASET_MAP[key].label
                for key in capability.requires
                if not datasets.get(key, {}).get("valid")
            ]
            blocked_module = (
                capability.requires_predictive_module and not predictive_allowed
            )
            entry = {
                "key": capability.key,
                "label": capability.label,
                "tools": list(capability.tools),
            }
            if blocked_module:
                unavailable.append(
                    {
                        **entry,
                        "reason": "El módulo predictivo no está habilitado para este cliente",
                    }
                )
            elif missing:
                unavailable.append(
                    {**entry, "reason": f"Faltan fuentes: {', '.join(missing)}"}
                )
            else:
                available.append(entry)

        return {
            "company_id": normalized,
            "available": available,
            "unavailable": unavailable,
            "techniques": {
                "alertas": any(item["key"].startswith("alert") for item in available),
                "aceite": any(item["key"].startswith("oil") for item in available),
                "telemetria": any(
                    item["key"].startswith("telemetry") for item in available
                ),
                "mantenimiento": any(
                    item["key"].startswith("maintenance") for item in available
                ),
                "predictivo": any(
                    item["key"].startswith("predictive") for item in available
                ),
            },
        }

    def describe_capabilities(self, client: str) -> str:
        """Client capabilities as JSON, with instructions for the agent."""
        payload = self.client_capabilities(client)
        payload["note"] = (
            "Solo prometas los análisis listados en 'available'. Para los de "
            "'unavailable', informa la limitación con su motivo y ofrece la "
            "alternativa más cercana entre los disponibles; no los sustituyas por "
            "otra fuente ni reintentes sus herramientas."
        )
        return json.dumps(payload, ensure_ascii=False, default=str)

    def describe_dataset(self, client: str, dataset: str = "") -> str:
        """Schema plus the real filter vocabulary, so a failed guess can be corrected.

        This is the recovery step: when a query returns no rows or rejects an
        argument, the agent reads the actual values a column holds instead of
        guessing again. Values come from the data, never from a hardcoded list.
        """
        requested = str(dataset or "").strip().lower()
        if requested and requested not in DATASET_MAP:
            raise CampbellDataError(
                f"Dataset no registrado: {requested}. "
                f"Disponibles: {', '.join(sorted(DATASET_MAP))}"
            )
        keys = [requested] if requested else list(DATASET_MAP)
        predictive_allowed = predictive_module_allows(client)

        described: dict[str, Any] = {}
        for key in keys:
            if key.startswith("predictive_") and not predictive_allowed:
                continue
            path = self.dataset_path(key, client)
            entry: dict[str, Any] = {
                "label": DATASET_MAP[key].label,
                "available": path.exists(),
                "read_with": DATASET_TOOLS.get(key, "sin herramienta directa"),
            }
            if not path.exists():
                entry["detail"] = "La fuente no existe para el cliente activo"
                described[key] = entry
                continue
            try:
                probe = self._probe_frame(path)
                entry["rows"] = probe["rows"]
                entry["columns"] = probe["columns"][:60]
                entry["columns_truncated"] = len(probe["columns"]) > 60
                # Vocabulary is only read when a single dataset is requested: it needs
                # the full frame, and the whole catalogue would be needlessly heavy.
                if requested:
                    entry["filters"] = self._filter_vocabulary(key, client)
            except Exception as exc:
                entry["error"] = type(exc).__name__
            described[key] = entry

        return json.dumps(
            {
                "datasets": described,
                "note": (
                    "Usa estos nombres y valores exactos al reintentar. Los filtros de "
                    "texto ignoran mayusculas y acentos. Si un valor no aparece aqui, "
                    "no existe en la fuente: dilo en lugar de aproximar."
                ),
            },
            ensure_ascii=False,
            default=str,
        )

    def _filter_vocabulary(self, key: str, client: str) -> dict[str, Any]:
        """Allowed values for each filter parameter of one dataset."""
        specs = DATASET_FILTERS.get(key, ())
        if not specs:
            return {}
        frame = self.load(key, client)
        vocabulary: dict[str, Any] = {}
        for spec in specs:
            column = self._resolve_column(frame, spec.columns)
            if not column:
                vocabulary[spec.parameter] = {"supported": False}
                continue
            entry: dict[str, Any] = {"supported": True, "column": column}
            if spec.kind in {"category", "unit"}:
                values = list(self._distribution(frame, column, top=25))
                entry["values"] = values
                entry["values_truncated"] = len(values) >= 25
            vocabulary[spec.parameter] = entry
        return vocabulary

    def query_alerts(
        self,
        client: str,
        days: int = 60,
        unit_id: str = "",
        system: str = "",
        component: str = "",
        trigger_type: str = "",
        subsystem: str = "",
        trigger_var: str = "",
        start_date: str = "",
        end_date: str = "",
        limit: int = 20,
    ) -> str:
        frame = self.load("alerts", client).copy()
        date_col = self._resolve_column(frame, ("Timestamp", "Fecha", "event_ts"))
        unit_col = self._resolve_column(frame, ("UnitId", "Unit", "unit_id"))
        system_col = self._resolve_column(frame, ("sistema", "System", "system"))
        subsystem_col = self._resolve_column(frame, ("subsistema", "SubSystem", "Subsystem"))
        component_col = self._resolve_column(frame, ("componente", "Component", "component"))
        trigger_col = self._resolve_column(frame, ("Trigger_type", "Trigger", "trigger_type"))
        trigger_var_col = self._resolve_column(frame, ("Trigger_Var", "Trigger", "trigger_var"))
        alert_id_col = self._resolve_column(frame, ("FusionID", "AlertID", "alert_id"))
        frame, dates, window = self.filter_date_window(
            frame,
            date_col,
            days=days,
            start_date=start_date,
            end_date=end_date,
        )
        windowed = frame
        if unit_id and unit_col:
            frame = self._filter_unit(frame, unit_col, unit_id)
        filters = (
            ("system", system, system_col),
            ("subsystem", subsystem, subsystem_col),
            ("component", component, component_col),
            ("trigger_type", trigger_type, trigger_col),
            ("trigger_var", trigger_var, trigger_var_col),
        )
        for _, value, column in filters:
            if value and column:
                frame = self._filter_contains(frame, column, value)
        if date_col:
            frame = frame.sort_values(date_col, ascending=False)

        summary: dict[str, Any] = {"total": int(len(frame)), "window": window}
        if frame.empty:
            summary["filter_hints"] = self._filter_hints(
                windowed,
                [(name, value, column) for name, value, column in filters if value and column]
                + ([("unit_id", unit_id, unit_col)] if unit_id and unit_col else []),
            )
        for label, column in (
            ("by_unit", unit_col),
            ("by_system", system_col),
            ("by_subsystem", subsystem_col),
            ("by_component", component_col),
            ("by_trigger_type", trigger_col),
            ("by_trigger_var", trigger_var_col),
            ("by_source_type", self._resolve_column(frame, ("SourceType", "source_type"))),
        ):
            if column:
                summary[label] = self._distribution(frame, column)
        if trigger_var_col and summary.get("by_trigger_var"):
            # Spanish label per code, keyed the same as by_trigger_var, so the agent
            # reports "Restricción del filtro de aire" instead of the raw "AirFltr".
            summary["by_trigger_var_labels"] = {
                code: self._translate_signal_list(code) or code
                for code in summary["by_trigger_var"]
            }
        if date_col and dates is not None and not frame.empty:
            aligned = dates.loc[frame.index].dropna()
            if not aligned.empty:
                summary["by_month"] = {
                    str(key): int(value)
                    for key, value in aligned.dt.to_period("M").astype(str).value_counts().sort_index().items()
                }
        record_columns = [
            alert_id_col,
            self._resolve_column(frame, ("TelemetryID", "telemetry_id")),
            date_col,
            unit_col,
            system_col,
            subsystem_col,
            component_col,
            trigger_col,
            trigger_var_col,
            self._resolve_column(frame, ("mensaje_ia", "Description", "Descripcion")),
        ]
        summary["records"] = self._records(
            frame, [value for value in record_columns if value], self._clamp(limit, 1, 50)
        )
        if trigger_var_col:
            for record in summary["records"]:
                record["trigger_var_label"] = self._translate_signal_list(
                    record.get(trigger_var_col)
                )
        summary["note"] = (
            "records es una muestra ordenada de mas reciente a mas antigua; "
            "usa total y las distribuciones para conteos y rankings. "
            "trigger_var_label (y by_trigger_var_labels) trae el nombre en espanol "
            "de cada senal disparadora: usalo en la respuesta al usuario en vez del "
            "codigo tecnico de Trigger_Var. "
            "Para el valor medido de la senal que disparo una alerta llama a "
            "query_alert_detail pasando unit_id y, si la conoces, la variable de "
            "Trigger_Var como trigger. El identificador de union con el detalle es "
            "TelemetryID y solo es unico dentro de un mismo equipo, por lo que unit_id "
            "es obligatorio para no mezclar equipos."
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
        windowed = frame
        if unit_id and unit_col:
            frame = self._filter_unit(frame, unit_col, unit_id)
        filters = (
            ("system", system, system_col),
            ("component", component, component_col),
            ("action_type", action_type, action_col),
        )
        for _, value, column in filters:
            if value and column:
                frame = self._filter_contains(frame, column, value)
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
        payload: dict[str, Any] = {
            "total": int(len(frame)),
            "window": window,
            "by_unit": self._distribution(frame, unit_col),
            "by_system": self._distribution(frame, system_col),
            "by_component": self._distribution(frame, component_col),
            "by_action_type": self._distribution(frame, action_col),
            "records": self._records(
                frame, [value for value in columns if value], self._clamp(limit, 1, 50)
            ),
        }
        if frame.empty:
            payload["filter_hints"] = self._filter_hints(
                windowed,
                [(name, value, column) for name, value, column in filters if value and column]
                + ([("unit_id", unit_id, unit_col)] if unit_id and unit_col else []),
            )
        return json.dumps(payload, ensure_ascii=False, default=str)

    def query_oil_status(self, client: str, unit_id: str = "", limit: int = 20) -> str:
        frame = self.load("oil_machine_status", client).copy()
        unit_col = self._resolve_column(frame, ("unit_id", "unitId", "UnitId"))
        if unit_id and unit_col:
            frame = self._filter_unit(frame, unit_col, unit_id)
        priority_col = self._resolve_column(frame, ("priority_score", "machine_score"))
        status_col = self._resolve_column(frame, ("overall_status", "report_status"))
        if priority_col:
            frame = frame.sort_values(priority_col, ascending=False)
        columns = [
            unit_col,
            self._resolve_column(frame, ("latest_sample_date",)),
            status_col,
            self._resolve_column(frame, ("machine_score",)),
            priority_col,
            self._resolve_column(frame, ("components_alerta",)),
            self._resolve_column(frame, ("components_anormal",)),
            self._resolve_column(frame, ("machine_ai_recommendation",)),
        ]
        payload: dict[str, Any] = {
            "total_units": int(len(frame)),
            "by_status": self._distribution(frame, status_col, top=12),
            "records": self._records(
                frame, [value for value in columns if value], self._clamp(limit, 1, 50)
            ),
            "note": (
                "Una fila por equipo con su muestra de aceite mas reciente. Para el detalle "
                "por componente y los ensayos fuera de limite usa query_oil_components."
            ),
        }
        date_col = self._resolve_column(frame, ("latest_sample_date",))
        if date_col and not frame.empty:
            sample_dates = pd.to_datetime(frame[date_col], errors="coerce").dropna()
            if not sample_dates.empty:
                payload["sample_window"] = {
                    "oldest": sample_dates.min().isoformat(),
                    "newest": sample_dates.max().isoformat(),
                }
        return json.dumps(payload, ensure_ascii=False, default=str)

    def query_telemetry_health(
        self,
        client: str,
        unit_id: str = "",
        latest_only: bool = True,
        limit: int = 20,
    ) -> str:
        """Return telemetry machine health, by default only the latest evaluated week."""
        frame = self.load("telemetry_machine_status", client).copy()
        unit_col = self._resolve_column(frame, ("unit_id", "unitId", "UnitId"))
        week_col = self._resolve_column(frame, ("evaluation_week",))
        year_col = self._resolve_column(frame, ("evaluation_year",))
        status_col = self._resolve_column(frame, ("overall_status", "component_status"))
        priority_col = self._resolve_column(frame, ("priority_score", "machine_score"))
        if unit_id and unit_col:
            frame = self._filter_unit(frame, unit_col, unit_id)

        evaluated: dict[str, Any] = {}
        if latest_only and unit_col and week_col:
            order = [column for column in (year_col, week_col) if column]
            ranked = frame.copy()
            for column in order:
                ranked[column] = pd.to_numeric(ranked[column], errors="coerce")
            ranked = ranked.sort_values(order, ascending=True)
            frame = ranked.groupby(unit_col, dropna=False).tail(1).copy()
            if not frame.empty:
                evaluated = {
                    "latest_year": self._scalar(frame[year_col].max()) if year_col else None,
                    "latest_week": self._scalar(frame[week_col].max()) if week_col else None,
                    "weeks_present": sorted(
                        {self._scalar(value) for value in frame[week_col].dropna().unique()}
                    )[:12],
                }
        if priority_col:
            frame = frame.sort_values(priority_col, ascending=False)

        columns = [
            unit_col,
            week_col,
            year_col,
            status_col,
            self._resolve_column(frame, ("machine_score",)),
            priority_col,
            self._resolve_column(frame, ("components_alerta",)),
            self._resolve_column(frame, ("components_anormal",)),
            self._resolve_column(frame, ("components_insufficient",)),
        ]
        return json.dumps(
            {
                "total_rows": int(len(frame)),
                "scope": "ultima semana evaluada por equipo" if latest_only else "historico completo",
                "evaluation": evaluated,
                "by_status": self._distribution(frame, status_col, top=12),
                "records": self._records(
                    frame, [value for value in columns if value], self._clamp(limit, 1, 50)
                ),
                "note": (
                    "components_anormal y components_alerta son conteos. Para saber QUE "
                    "componente y QUE senal lo dispara usa query_telemetry_components."
                ),
            },
            ensure_ascii=False,
            default=str,
        )

    @staticmethod
    def _scalar(value: Any) -> Any:
        """Convert a numpy/pandas scalar into a JSON-friendly Python value."""
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return None
        if hasattr(value, "item"):
            try:
                return value.item()
            except (AttributeError, ValueError):
                return str(value)
        return value

    def query_telemetry_components(
        self,
        client: str,
        unit_id: str = "",
        component: str = "",
        status: str = "",
        latest_only: bool = True,
        limit: int = 25,
    ) -> str:
        """Component-level telemetry condition including the signals that triggered it."""
        frame = self.load("telemetry_classified", client).copy()
        unit_col = self._resolve_column(frame, ("unit_id", "unitId", "UnitId"))
        component_col = self._resolve_column(frame, ("component", "componentName"))
        status_col = self._resolve_column(frame, ("component_status", "overall_status"))
        week_col = self._resolve_column(frame, ("evaluation_week",))
        year_col = self._resolve_column(frame, ("evaluation_year",))

        if latest_only and unit_col and component_col and week_col:
            ranked = frame.copy()
            order = [column for column in (year_col, week_col) if column]
            for column in order:
                ranked[column] = pd.to_numeric(ranked[column], errors="coerce")
            frame = (
                ranked.sort_values(order, ascending=True)
                .groupby([unit_col, component_col], dropna=False)
                .tail(1)
                .copy()
            )
        if unit_id and unit_col:
            frame = self._filter_unit(frame, unit_col, unit_id)
        for value, column in ((component, component_col), (status, status_col)):
            if value and column:
                frame = self._filter_contains(frame, column, value)

        severity = {"Anormal": 0, "Alerta": 1, "Insuficiente": 2, "Normal": 3}
        if status_col and not frame.empty:
            frame = frame.assign(
                __severity=frame[status_col].map(lambda value: severity.get(str(value), 4))
            ).sort_values("__severity")
        triggering_signals_col = self._resolve_column(frame, ("triggering_signals",))
        columns = [
            unit_col,
            component_col,
            status_col,
            self._resolve_column(frame, ("component_score",)),
            self._resolve_column(frame, ("criticality",)),
            triggering_signals_col,
            self._resolve_column(frame, ("signal_coverage",)),
            week_col,
            year_col,
        ]
        payload: dict[str, Any] = {
            "total_rows": int(len(frame)),
            "scope": "ultima semana evaluada por equipo y componente" if latest_only else "historico",
            "by_status": self._distribution(frame, status_col, top=12),
            "by_component": self._distribution(frame, component_col, top=15),
            "records": self._records(
                frame, [value for value in columns if value], self._clamp(limit, 1, 60)
            ),
            "note": (
                "triggering_signals nombra, ya traducidas al espanol, las senales que "
                "llevaron el componente a ese estado; no es una lectura instantanea del "
                "sensor."
            ),
        }
        if triggering_signals_col:
            # Purely informational (never used as a filter value elsewhere), so it is
            # safe to translate in place rather than adding a sibling field.
            for record in payload["records"]:
                record[triggering_signals_col] = self._translate_signal_list(
                    record.get(triggering_signals_col)
                )
        if status_col and component_col and unit_col and not frame.empty:
            flagged = frame[frame[status_col].astype(str).isin(("Anormal", "Alerta"))]
            payload["flagged_units"] = (
                self._distribution(flagged, unit_col, top=15) if not flagged.empty else {}
            )
        return json.dumps(payload, ensure_ascii=False, default=str)

    def query_oil_components(
        self,
        client: str,
        unit_id: str = "",
        component: str = "",
        status: str = "",
        latest_only: bool = True,
        limit: int = 25,
    ) -> str:
        """Component-level oil condition with breached essays and severity."""
        frame = self.load("oil_classified", client).copy()
        unit_col = self._resolve_column(frame, ("unitId", "unit_id", "UnitId"))
        component_col = self._resolve_column(frame, ("componentName", "component"))
        normalized_col = self._resolve_column(frame, ("componentNameNormalized",))
        status_col = self._resolve_column(frame, ("report_status", "overall_status"))
        date_col = self._resolve_column(frame, ("sampleDate", "reportDate"))

        if date_col:
            frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
        if latest_only and unit_col and component_col and date_col:
            frame = (
                frame.sort_values(date_col, ascending=True)
                .groupby([unit_col, component_col], dropna=False)
                .tail(1)
                .copy()
            )
        if unit_id and unit_col:
            frame = self._filter_unit(frame, unit_col, unit_id)
        for value, column in (
            (component, normalized_col or component_col),
            (status, status_col),
        ):
            if value and column:
                frame = self._filter_contains(frame, column, value)

        severity = {"Anormal": 0, "Alerta": 1, "Normal": 2}
        if status_col and not frame.empty:
            frame = frame.assign(
                __severity=frame[status_col].map(lambda value: severity.get(str(value), 3))
            ).sort_values(["__severity", date_col] if date_col else ["__severity"])
        columns = [
            unit_col,
            component_col,
            normalized_col,
            status_col,
            date_col,
            self._resolve_column(frame, ("severity_score",)),
            self._resolve_column(frame, ("breached_essays",)),
            self._resolve_column(frame, ("anomalyType",)),
            self._resolve_column(frame, ("daysSincePrevious",)),
            self._resolve_column(frame, ("ai_recommendation",)),
        ]
        payload: dict[str, Any] = {
            "total_rows": int(len(frame)),
            "scope": "muestra mas reciente por equipo y componente" if latest_only else "historico",
            "by_status": self._distribution(frame, status_col, top=12),
            "by_component": self._distribution(frame, normalized_col or component_col, top=15),
            "records": self._records(
                frame, [value for value in columns if value], self._clamp(limit, 1, 60)
            ),
            "note": (
                "breached_essays lista los ensayos fuera de limite de esa muestra, con su "
                "valor y umbral; classifies indica si pesa en la clasificacion del estado. "
                "ai_recommendation es una recomendacion automatica, no trabajo ejecutado."
            ),
        }
        essays_col = self._resolve_column(frame, ("breached_essays",))
        if essays_col:
            source = frame[essays_col].head(self._clamp(limit, 1, 60)).tolist()
            for record, raw in zip(payload["records"], source):
                record[essays_col] = self._compact_breached_essays(raw)
        if date_col and not frame.empty:
            valid = frame[date_col].dropna()
            if not valid.empty:
                payload["sample_window"] = {
                    "oldest": valid.min().isoformat(),
                    "newest": valid.max().isoformat(),
                }
        return json.dumps(payload, ensure_ascii=False, default=str)

    def query_alert_detail(
        self,
        client: str,
        alert_id: str = "",
        unit_id: str = "",
        trigger: str = "",
        limit: int = 10,
    ) -> str:
        """Measured value and applicable limit for the signal that raised an alert."""
        frame = self.load("alerts_detail", client).copy()
        alert_col = self._resolve_column(frame, ("AlertID", "alert_id"))
        unit_col = self._resolve_column(frame, ("Unit", "UnitId", "unit_id"))
        trigger_col = self._resolve_column(frame, ("Trigger", "trigger"))
        time_col = self._resolve_column(frame, ("TimeStart", "Alert_TimeStart", "Fecha"))
        state_col = self._resolve_column(frame, ("State",))

        if not (alert_id or unit_id or trigger):
            raise CampbellDataError(
                "query_alert_detail requiere alert_id, unit_id o trigger"
            )
        if unit_id and unit_col:
            frame = self._filter_unit(frame, unit_col, unit_id)
        if alert_id and alert_col:
            # The alerts source exposes FusionID ("F-63-1783624380") while the detail table
            # keys on the numeric telemetry id, and that id repeats across units.
            resolved = self._normalize_alert_id(alert_id)
            frame = frame[frame[alert_col].astype(str).str.casefold() == resolved.casefold()]
        if trigger and trigger_col:
            frame = self._filter_contains(frame, trigger_col, trigger)
        if frame.empty:
            available = self.load("alerts_detail", client)
            if unit_id and unit_col:
                available = self._filter_unit(available, unit_col, unit_id)
            return json.dumps(
                {
                    "alerts_matched": 0,
                    "records": [],
                    "filter_hints": {
                        "detail": (
                            "Sin filas de detalle para ese filtro. El identificador de union "
                            "es TelemetryID (no FusionID) y solo es unico dentro de un equipo. "
                            "Reintenta con unit_id mas el nombre exacto de la senal."
                        ),
                        "available_triggers": list(
                            self._distribution(available, trigger_col, top=15)
                        ),
                    },
                },
                ensure_ascii=False,
            )
        if time_col:
            frame[time_col] = pd.to_datetime(frame[time_col], errors="coerce")

        # The wide detail table is a per-sample time series; summarize one row per alert
        # so the analyst reports a peak against its limit instead of raw sample noise.
        # Unit is part of the key because AlertID is only unique within a unit.
        group_keys = [column for column in (unit_col, alert_col, trigger_col) if column]
        if not group_keys:
            raise CampbellDataError("El detalle de alertas no expone AlertID ni Trigger")

        rows: list[dict[str, Any]] = []
        grouped = frame.groupby(group_keys, dropna=False, sort=False)
        for keys, chunk in grouped:
            keys = keys if isinstance(keys, tuple) else (keys,)
            mapping = dict(zip(group_keys, keys))
            signal = str(mapping.get(trigger_col, "")) if trigger_col else ""
            value_col = f"{signal}_Value" if signal else None
            upper_col = f"{signal}_Upper_Limit" if signal else None
            lower_col = f"{signal}_Lower_Limit" if signal else None

            record: dict[str, Any] = {
                "alert_id": self._scalar(mapping.get(alert_col)) if alert_col else None,
                "unit_id": (
                    self._scalar(chunk[unit_col].dropna().iloc[0])
                    if unit_col and not chunk[unit_col].dropna().empty
                    else None
                ),
                "trigger": signal or None,
                "trigger_label": self._translate_signal_list(signal),
                "samples": int(len(chunk)),
            }
            if time_col:
                valid = chunk[time_col].dropna()
                record["start"] = valid.min().isoformat() if not valid.empty else None
                record["end"] = valid.max().isoformat() if not valid.empty else None
            if state_col:
                record["machine_states"] = self._distribution(chunk, state_col, top=4)

            if value_col and value_col in chunk.columns:
                values = pd.to_numeric(chunk[value_col], errors="coerce")
                valid = values.notna()
                if valid.any():
                    peak_index = values.idxmax()
                    record.update(
                        {
                            "peak_value": round(float(values.max()), 3),
                            "min_value": round(float(values.min()), 3),
                            "mean_value": round(float(values.mean()), 3),
                        }
                    )
                    if state_col:
                        record["state_at_peak"] = self._scalar(
                            chunk.loc[peak_index, state_col]
                        )
                    # The threshold is state-dependent (a machine at idle has a lower
                    # ceiling than one operating), so each sample is compared against
                    # its own limit. Collapsing the column to its maximum reported zero
                    # exceedances for alerts that did breach their idle limit.
                    for suffix, key, comparison in (
                        ("_Upper_Limit", "upper", "above"),
                        ("_Lower_Limit", "lower", "below"),
                    ):
                        column = f"{signal}{suffix}" if signal else None
                        if not column or column not in chunk.columns:
                            continue
                        limits = pd.to_numeric(chunk[column], errors="coerce")
                        if limits.notna().sum() == 0:
                            continue
                        breaches = (
                            (values > limits) if comparison == "above" else (values < limits)
                        )
                        breaches = breaches & valid & limits.notna()
                        distinct = sorted(
                            {round(float(value), 3) for value in limits.dropna().unique()}
                        )
                        record[f"{key}_limit_at_peak"] = (
                            round(float(limits.loc[peak_index]), 3)
                            if pd.notna(limits.loc[peak_index])
                            else None
                        )
                        record[f"{key}_limit_values"] = distinct
                        record[f"samples_{comparison}_limit"] = int(breaches.sum())
                        if breaches.any():
                            worst = values[breaches]
                            margin = (values - limits)[breaches]
                            record[f"worst_{comparison}_value"] = round(
                                float(worst.max() if comparison == "above" else worst.min()),
                                3,
                            )
                            record[f"max_{comparison}_exceedance"] = round(
                                float(margin.max() if comparison == "above" else -margin.min()),
                                3,
                            )
            rows.append(record)

        rows.sort(key=lambda item: str(item.get("end") or ""), reverse=True)
        by_trigger = self._distribution(frame, trigger_col)
        payload = {
            "alerts_matched": len(rows),
            "detail_rows_scanned": int(len(frame)),
            "by_trigger": by_trigger,
            "by_trigger_labels": {
                code: self._translate_signal_list(code) or code for code in by_trigger
            },
            "records": rows[: self._clamp(limit, 1, 30)],
            "note": (
                "Una fila por alerta y senal. peak_value es la lectura maxima registrada. "
                "trigger_label (y by_trigger_labels) trae el nombre en espanol de la senal: "
                "usalo en la respuesta al usuario en vez del codigo tecnico de trigger. "
                "El umbral depende del estado de maquina: upper_limit_values lista los "
                "umbrales aplicados durante la alerta y upper_limit_at_peak el vigente en "
                "el pico. samples_above_limit compara cada muestra contra SU propio "
                "umbral, asi que puede ser mayor que cero aunque el pico no supere el "
                "umbral mas alto. Si el umbral viene vacio, no lo inventes, y no afirmes "
                "unidades de medida que la fuente no declara."
            ),
        }
        return json.dumps(payload, ensure_ascii=False, default=str)

    # Operating context rather than monitored signals; the dashboard omits them too.
    _CONTEXT_SIGNALS = ("GroundSpd", "EngLoad", "Payload")

    def alert_signal_series(
        self,
        client: str,
        alert_id: str = "",
        unit_id: str = "",
        signals: tuple[str, ...] = (),
        max_signals: int = 4,
    ) -> dict[str, Any]:
        """Per-signal time series of one alert, with the limits the source publishes.

        The wide detail table samples every sensor during an alert, so plotting all of
        them yields a dozen unreadable panels. The triggering signal is the default and
        the caller may name more; `signals_available` lists what actually has values so
        the choice is informed rather than guessed.
        """
        frame = self.load("alerts_detail", client).copy()
        alert_col = self._resolve_column(frame, ("AlertID", "alert_id"))
        unit_col = self._resolve_column(frame, ("Unit", "UnitId", "unit_id"))
        trigger_col = self._resolve_column(frame, ("Trigger", "trigger"))
        time_col = self._resolve_column(
            frame, ("TimeStart", "Alert_TimeStart", "Fecha")
        )
        if not (alert_col and time_col):
            raise CampbellDataError(
                "El detalle de alertas no expone AlertID ni una marca de tiempo"
            )
        if unit_id and unit_col:
            frame = self._filter_unit(frame, unit_col, unit_id)
        if alert_id and alert_col:
            resolved = self._normalize_alert_id(alert_id)
            frame = frame[frame[alert_col].astype(str).str.casefold() == resolved.casefold()]
        elif not unit_id:
            raise CampbellDataError(
                "alert_signal_series requiere alert_id o unit_id"
            )
        if frame.empty:
            raise CampbellDataError(
                "Sin filas de detalle para esa alerta o equipo"
            )

        # Without an explicit alert, use the most recent one for that unit.
        frame[time_col] = pd.to_datetime(frame[time_col], errors="coerce")
        if not alert_id and alert_col:
            latest_alert = (
                frame.sort_values(time_col).iloc[-1][alert_col]
            )
            frame = frame[frame[alert_col] == latest_alert]
        frame = frame.sort_values(time_col)

        catalogued = [
            str(column)[: -len("_Value")]
            for column in frame.columns
            if str(column).endswith("_Value")
        ]
        # Only signals with captured values can be plotted; a column that carries
        # limits but no readings would render an empty panel.
        with_values = [
            signal
            for signal in catalogued
            if frame[f"{signal}_Value"].notna().any()
        ]
        with_limits = [
            signal
            for signal in with_values
            if any(
                f"{signal}{suffix}" in frame.columns
                and frame[f"{signal}{suffix}"].notna().any()
                for suffix in ("_Upper_Limit", "_Lower_Limit")
            )
        ]
        trigger = ""
        if trigger_col and not frame[trigger_col].dropna().empty:
            trigger = str(frame[trigger_col].dropna().iloc[0])

        # Signal codes are fixed identifiers, so resolve them ignoring case and
        # accents: a transcription slip like "engcooltemp" should not abort the chart,
        # while a genuinely unknown signal still fails below.
        by_folded = {self._fold(signal): signal for signal in with_values}
        requested = [str(item).strip() for item in signals if str(item).strip()]
        resolved = [(item, by_folded.get(self._fold(item))) for item in requested]
        unknown = [item for item, match in resolved if match is None]
        selected = [match for _, match in resolved if match is not None]
        if requested and not selected:
            # Falling back to the trigger here would plot a different signal than the
            # one asked for, and the answer would describe the wrong series.
            raise CampbellDataError(
                f"Ninguna de las senales solicitadas ({', '.join(requested)}) tiene "
                f"valores capturados en esta alerta. Disponibles: "
                f"{', '.join(with_values)}"
            )
        if not selected:
            selected = [trigger] if trigger in with_values else []
        if not selected:
            selected = [
                signal for signal in with_limits if signal not in self._CONTEXT_SIGNALS
            ][:1] or with_values[:1]
        selected = list(dict.fromkeys(selected))[: max(1, min(int(max_signals), 6))]

        panels: list[dict[str, Any]] = []
        for signal in selected:
            values = pd.to_numeric(frame[f"{signal}_Value"], errors="coerce")
            mask = values.notna()
            if not mask.any():
                continue

            def limit(suffix: str) -> list[float] | None:
                column = f"{signal}{suffix}"
                if column not in frame.columns:
                    return None
                series = pd.to_numeric(frame.loc[mask, column], errors="coerce")
                if series.notna().sum() == 0:
                    return None
                # Limits are constant within an alert but can arrive sparse.
                return [float(value) for value in series.ffill().bfill()]

            panels.append(
                {
                    "signal": signal,
                    "times": [stamp.isoformat() for stamp in frame.loc[mask, time_col]],
                    "values": [float(value) for value in values[mask]],
                    "upper": limit("_Upper_Limit"),
                    "lower": limit("_Lower_Limit"),
                }
            )

        return {
            "alert_id": self._scalar(frame[alert_col].iloc[0]) if alert_col else None,
            "unit_id": (
                self._scalar(frame[unit_col].dropna().iloc[0])
                if unit_col and not frame[unit_col].dropna().empty
                else None
            ),
            "trigger": trigger or None,
            "samples": int(len(frame)),
            "window": {
                "start": frame[time_col].min().isoformat(),
                "end": frame[time_col].max().isoformat(),
            },
            "signals_selected": selected,
            "signals_available": with_values,
            "signals_with_limits": with_limits,
            "signals_unknown": unknown,
            "panels": panels,
        }

    def query_alert_signals(
        self, client: str, alert_id: str = "", unit_id: str = ""
    ) -> str:
        """Which signals of an alert have captured values, and which have limits."""
        payload = self.alert_signal_series(client, alert_id=alert_id, unit_id=unit_id)
        summary = {
            key: payload[key]
            for key in (
                "alert_id",
                "unit_id",
                "trigger",
                "samples",
                "window",
                "signals_available",
                "signals_with_limits",
            )
        }
        summary["trigger_label"] = self._translate_signal_list(payload.get("trigger"))
        # Parallel Spanish labels, same order as signals_available/signals_with_limits.
        # Codes stay as-is: they are still needed verbatim as the signal= argument to
        # alert_signal_series/render_dashboard_chart.
        summary["signals_available_labels"] = [
            self._translate_signal_list(code) or code for code in payload["signals_available"]
        ]
        summary["signals_with_limits_labels"] = [
            self._translate_signal_list(code) or code for code in payload["signals_with_limits"]
        ]
        summary["note"] = (
            "signals_available son las senales con valores capturados en esta alerta; "
            "sus nombres en espanol estan en signals_available_labels (mismo orden) y "
            "trigger_label traduce trigger. Usa los nombres en espanol al responder al "
            "usuario y los codigos solo como argumentos de otras herramientas. "
            "Para graficarlas usa render_dashboard_chart(alert_sensor_trend) indicando "
            "unit_id, alert_id y opcionalmente signal. GroundSpd, EngLoad y Payload son "
            "contexto de operacion, no senales monitoreadas."
        )
        return json.dumps(summary, ensure_ascii=False, default=str)

    def query_maintenance_summary(
        self, client: str, unit_id: str = "", limit: int = 10
    ) -> str:
        """Weekly natural-language maintenance summaries per unit."""
        frame = self.load("maintenance_summary", client).copy()
        unit_col = self._resolve_column(frame, ("UnitId", "machine_code", "machine_id"))
        week_col = self._resolve_column(frame, ("Semana", "Week", "week"))
        summary_col = self._resolve_column(frame, ("Summary", "Resumen"))
        tasks_col = self._resolve_column(frame, ("Tasks_List", "Tareas"))
        if unit_id and unit_col:
            frame = self._filter_unit(frame, unit_col, unit_id)
        if week_col:
            frame = frame.sort_values(week_col, ascending=False)
        columns = [value for value in (unit_col, week_col, summary_col, tasks_col) if value]
        return json.dumps(
            {
                "total_rows": int(len(frame)),
                "by_unit": (
                    self._distribution(frame, unit_col, top=15)
                ),
                "records": self._records(frame, columns, self._clamp(limit, 1, 20)),
                "note": (
                    "Resumen redactado por semana. Para conteos por tipo de accion, sistema "
                    "o fecha exacta usa query_maintenance."
                ),
            },
            ensure_ascii=False,
            default=str,
        )

    _PREDICTIVE_DATASETS = {
        "motor": "predictive_motor",
        "transmision": "predictive_transmission",
        "transmission": "predictive_transmission",
    }

    def query_predictive_risk(
        self,
        client: str,
        domain: str = "motor",
        unit_id: str = "",
        limit: int = 15,
    ) -> str:
        """Latest predictive-model ranking and failure-mode risks per unit."""
        key = self._PREDICTIVE_DATASETS.get(str(domain or "").strip().lower())
        if key is None:
            raise CampbellDataError(
                "domain de query_predictive_risk debe ser 'motor' o 'transmision'"
            )
        # Mirror the dashboard's module access control: the Predictive section is limited to
        # an allowlist of clients, so the agent must not read it for anyone else.
        if not predictive_module_allows(client):
            raise CampbellDataError(
                "El modulo predictivo no esta habilitado para el cliente activo"
            )
        frame = self.load(key, client).copy()
        unit_col = self._resolve_column(frame, ("Unit", "unitId", "unit_id"))
        date_col = self._resolve_column(frame, ("Fecha", "sampleDate"))
        ranking_col = self._resolve_column(frame, ("ranking",))
        if ranking_col is None:
            raise CampbellDataError("La fuente predictiva no expone la columna ranking")

        resolved_domain = "transmision" if key.endswith("transmission") else "motor"
        risk_columns = [
            str(column) for column in frame.columns if str(column).endswith("_risk")
        ]
        frame[ranking_col] = pd.to_numeric(frame[ranking_col], errors="coerce")
        ranked_rows = int(frame[ranking_col].notna().sum())
        if ranked_rows == 0:
            # The source exists but the model has not published a ranking for this domain.
            # Say so explicitly instead of letting a caller substitute another source.
            return json.dumps(
                {
                    "domain": resolved_domain,
                    "source_available": True,
                    "ranking_available": False,
                    "total_units": 0,
                    "risk_modes_available": risk_columns,
                    "records": [],
                    "note": (
                        "La fuente predictiva de este dominio existe pero no tiene ranking "
                        "calculado. Informalo asi al usuario y no lo sustituyas por telemetria, "
                        "aceite o alertas como si fuera un resultado predictivo."
                    ),
                },
                ensure_ascii=False,
            )
        frame = frame[frame[ranking_col].notna()]
        if date_col:
            frame[date_col] = pd.to_datetime(frame[date_col], errors="coerce")
        if unit_col and date_col:
            frame = (
                frame.sort_values(date_col, ascending=True)
                .groupby(unit_col, dropna=False)
                .tail(1)
                .copy()
            )
        if unit_id and unit_col:
            frame = self._filter_unit(frame, unit_col, unit_id)
        if frame.empty:
            return json.dumps(
                {
                    "domain": resolved_domain,
                    "source_available": True,
                    "ranking_available": True,
                    "total_units": 0,
                    "records": [],
                    "note": "Sin filas para el filtro solicitado.",
                },
                ensure_ascii=False,
            )
        frame = frame.sort_values(ranking_col, ascending=False)
        rows: list[dict[str, Any]] = []
        for _, row in frame.head(self._clamp(limit, 1, 30)).iterrows():
            score = float(row[ranking_col])
            risks = {
                column.removesuffix("_risk"): self._scalar(row.get(column))
                for column in risk_columns
                if pd.notna(row.get(column))
            }
            top_risks = {
                name: round(float(value), 1)
                for name, value in sorted(
                    (
                        (name, value)
                        for name, value in risks.items()
                        if isinstance(value, (int, float))
                    ),
                    key=lambda item: item[1],
                    reverse=True,
                )[:5]
            }
            rows.append(
                {
                    "unit_id": self._scalar(row.get(unit_col)) if unit_col else None,
                    "evaluated_at": (
                        row[date_col].isoformat()
                        if date_col and pd.notna(row.get(date_col))
                        else None
                    ),
                    "ranking": round(score, 2),
                    "band": predictive_band(score),
                    "oil_hour_range": self._scalar(row.get("oilHourRange")),
                    "top_risks": top_risks,
                }
            )

        bands: dict[str, int] = {}
        for value in frame[ranking_col]:
            bands[predictive_band(float(value))] = bands.get(predictive_band(float(value)), 0) + 1
        return json.dumps(
            {
                "domain": resolved_domain,
                "source_available": True,
                "ranking_available": True,
                "total_units": int(len(frame)),
                "ranking_direction": "mayor ranking = mayor prioridad de riesgo",
                "bands": {
                    "definicion": "<35 Saludable, 35-54.9 Monitoreo, 55-74.9 Prioridad alta, >=75 Critico",
                    "distribucion": bands,
                },
                "risk_modes_available": risk_columns,
                "records": rows,
                "note": (
                    "Salida de un modelo predictivo, no una alerta confirmada ni una medicion "
                    "directa. Requiere validacion en terreno antes de intervenir."
                ),
            },
            ensure_ascii=False,
            default=str,
        )
