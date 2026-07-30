# Data Contracts - Predictive Data Product

**Version**: 1.0
**Last Updated**: July 29, 2026
**Owner**: Predictive Module Team

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Data Layer Architecture](#data-layer-architecture)
3. [Golden Layer Schema](#golden-layer-schema)
4. [Failure Mode Scores](#5-failure-mode-scores)
5. [Dashboard-Side Thresholds (not part of the CSV)](#dashboard-side-thresholds-not-part-of-the-csv)
6. [External Dependency: Component Hours](#external-dependency-component-hours)
7. [Data Quality Rules](#data-quality-rules)
8. [Change Log](#change-log)

---

## 🎯 Overview

This document defines the data contract for the **Predictive** data product: per-component
(Motor, Transmisión, ...) failure-mode risk scores combining oil (tribology) and telemetry
evidence, produced entirely by an **upstream pipeline outside this repo**. This dashboard only
reads the golden-layer CSVs described below — it does not compute essay classifications, alert
rates, or failure-mode scores itself.

**Data Product Purpose**: Provide a daily, per-unit record of failure-mode risk (0-100) so the
dashboard can rank units by priority, show which failure mode is driving risk, and generate
narrative evidence.

**Primary Consumer**: Multi-Technical Alerts Dashboard, Predictivo section
(`dashboard/tabs/tab_predictive_overview.py`, `tab_predictive_evidence.py`).

---

## 🏗️ Data Layer Architecture

### Local Storage Structure

```
data/
└── predictive/
    └── golden/
        └── {client}/
            ├── motor.csv
            └── transmision.csv
```

**Path pattern**: `data/predictive/golden/{client}/{component}.csv`

Unlike other techniques in this dashboard, Predictive has **no bronze/silver layers locally** —
only the golden output is synced/read here.

### Auto-Discovery

The dashboard does **not** hardcode component names. It scans the client's golden folder for
`*.csv` files and uses each filename (minus `.csv`) as the component key
(`dashboard/tabs/tab_predictive_overview.py::_discover_components`). Adding a new component is a
matter of dropping a new CSV in the client's folder — provided a matching entry exists in
`FAILURE_MODE_CONFIG` (`dashboard/components/predictive_config.py`); an unrecognized component key
falls back to the `motor` failure-mode configuration.

### Currently Observed Files (Client: CDA)

| File | Component |
|------|-----------|
| `motor.csv` | Motor |
| `transmision.csv` | Transmisión |

### Grain

**One row per Unit per day.** Each row is a full snapshot: identifiers, telemetry rates, oil
variables (populated only on days with a new oil sample — otherwise carried/blank per the
upstream pipeline's own logic), failure-mode scores, and the consolidated `ranking`.

---

## 📐 Golden Layer Schema

### 1. Identifiers

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `Unit` | string | Unit identifier used for display/grouping in the dashboard | `T_09` |
| `Fecha` | datetime | Date of the daily record (parsed via `pd.to_datetime`) | `2026-07-15` |
| `unitId` | string | Normalized unit ID (used to join with `cleaned_component_hours.parquet`) | `T_09` |

### 2. Telemetry Rates (per operational mode × signal)

**Column name format**: `{ModoOperacional}_{Señal}_{tipo_tasa}`

**Operational modes**: `ND` (undefined), `Operacional Alto`, `Operacional Bajo`, `Ralenti`,
`Ralenti Alto`, `Ralenti Bajo`

**Rate types**: `alert_rate` (share of time in alert zone), `critic_rate` (share of time in
critical zone), `normal_rate` (share of time in normal zone)

**Telemetry signals per component**:

| Component | Signals |
|-----------|---------|
| Motor | `CnkcasePres`, `DeltaExh`, `EngOilPres`, `LtExhTemp`, `RtExhTemp` |
| Transmisión | `LckupSlip`, `TCOutTemp`, `TrnLubeTemp`, `TrnSlip`, `gear_mismatch` |

**Examples**: `Operacional Alto_CnkcasePres_alert_rate`, `Ralenti_DeltaExh_critic_rate`,
`ND_EngOilPres_normal_rate`

The dashboard reads these columns dynamically by pattern-matching `_{signal}_alert_rate` /
`_{signal}_critic_rate` substrings (`predictive_charts.py::create_telemetry_signal_chart`,
`tab_predictive_evidence.py::_analyze_telemetry_observations`) — it does not enumerate the full
operational-mode × signal cross product explicitly, so new operational-mode columns are picked up
automatically as long as the naming convention holds.

### 3. Oil (Tribology) Variables

| Column | Motor | Transmisión | Unit |
|--------|:-----:|:-----------:|------|
| `Hierro` | ✅ | ✅ | ppm |
| `Silicio` | ✅ | ✅ | ppm |
| `Plomo` | ✅ | ✅ | ppm |
| `Cromo` | ✅ | ❌ | ppm |
| `Cobre` | ✅ | ✅ | ppm |
| `Sodio` | ✅ | ✅ | ppm |
| `Hollín` | ✅ | ❌ | % |
| `Viscocidad` | ✅ | ✅ | cSt |
| `Estaño` | ❌ | ✅ | ppm |
| `Aluminio` | ❌ | ✅ | ppm |
| `Agua` | ❌ | ✅ | % |
| `Potasio` | ❌ | ✅ | ppm |
| `Boro` | ❌ | ✅ | ppm |

> Note the spelling `Viscocidad` (not `Viscosidad`) — this is the actual column name in the CSV
> and in `predictive_config.py`; only the display label says "Viscosidad".

### 4. Oil-Derived Columns

| Column | Type | Description |
|--------|------|-------------|
| `sampleDate` | date | Date the oil sample was drawn (distinct from `Fecha`, the daily record date) |
| `oilMeter` | float | Oil hours at time of sample |
| `oilHourRange` | string | `LT_1000` or `GE_1000` — selects which threshold row applies |

The dashboard deduplicates by `sampleDate` (not `Fecha`) whenever it needs "real" sample points —
e.g. the oil time series and the "previous different value" lookup in
`predictive_tables.py::create_oil_variables_table` — because the same sample value can be
forward-filled across multiple daily `Fecha` rows.

### 5. Failure Mode Scores

Each row carries one 0-100 risk score column per failure mode for that component
(`predictive_config.py::FAILURE_MODE_CONFIG`), plus a consolidated `ranking`.

**Motor** (7 failure modes):

| Column | Label | Oil Variables | Telemetry Variables |
|--------|-------|----------------|----------------------|
| `abrasive_wear_risk` | Desgaste Abrasivo | Hierro, Silicio, Cromo | — |
| `combustion_risk` | Combustión | Hollín, Viscocidad | LtExhTemp, RtExhTemp, DeltaExh |
| `thermal_imbalance_risk` | Δ T° Escape | — | LtExhTemp, RtExhTemp, DeltaExh |
| `oil_degradation_risk` | Degradación de Aceite | Viscocidad, Hollín | — |
| `lubrication_failure_risk` | Falla de Lubricación | Plomo, Cobre | EngOilPres |
| `bearing_wear_risk` | Desgaste de Cojinetes | Plomo, Cobre | EngOilPres |
| `blowby_risk` | Blow-by | Hollín | CnkcasePres |

**Transmisión** (7 failure modes):

| Column | Label | Oil Variables | Telemetry Variables |
|--------|-------|----------------|----------------------|
| `clutch_pack_risk` | Desgaste de Clutch Pack | Hierro, Cobre, Aluminio | LckupSlip, TrnSlip |
| `thermal_degradation_risk` | Degradación Térmica | Viscocidad, Agua | TCOutTemp, TrnLubeTemp |
| `planetary_gear_risk` | Desgaste de Engranajes Planetarios | Hierro, Silicio, Cobre | gear_mismatch, TrnSlip |
| `bearing_risk` | Desgaste de Rodamientos | Hierro, Cobre, Plomo, Estaño | TrnLubeTemp |
| `contamination_risk` | Contaminación | Silicio, Agua, Sodio, Potasio | — |
| `torque_converter_risk` | Convertidor de Torque | Aluminio, Cobre, Hierro | LckupSlip, TCOutTemp |
| `shift_quality_risk` | Calidad de Cambio | Viscocidad, Hierro | TrnSlip, gear_mismatch, LckupSlip |

| Column | Type | Description |
|--------|------|-------------|
| `ranking` | float (0-100) | Consolidated unit-level risk score combining all failure modes |

**Columns computed by the dashboard at load time (not present in the CSV)**: `avg_ranking_30d`,
`avg_ranking_60d`, `ranking_acum_90d`, `max_fm_30d`, and `{failure_mode}_30d/_60d/_90d` for each
failure-mode column — all derived via per-`Unit` rolling means. See
[project_overview.md §6](project_overview.md#processing-pipeline-in-the-dashboard).

---

## 🎚️ Dashboard-Side Thresholds (not part of the CSV)

`predictive_config.py::OIL_THRESHOLDS` defines static (Normal, Alerta, Crítico) triplets per oil
variable, split by `oilHourRange`. These are **dashboard configuration**, not columns in the
golden file, and are distinct from the Oil module's Stewart Limits
(`oil/golden/{client}/stewart_limits.parquet`) — Predictive uses its own simplified, hardcoded
thresholds rather than per-client/per-machine statistical percentiles.

| Variable | Normal (LT_1000) | Alerta (LT_1000) | Crítico (LT_1000) | Normal (GE_1000) | Alerta (GE_1000) | Crítico (GE_1000) |
|----------|:-:|:-:|:-:|:-:|:-:|:-:|
| Hierro | 48 | 57 | 65 | 71 | 84 | 93 |
| Cobre | 5 | 8 | 17 | 7 | 12 | 51 |
| Plomo | 3 | 5 | 8 | 4 | 5 | 6 |
| Silicio | 5 | 6 | 8 | 5 | 6 | 7 |
| Sodio | 7 | 9 | 18 | 8 | 9 | 10 |
| Viscocidad | 16 | 17 | 18 | 16 | 17 | 18 |
| Hollín | 64 | 73 | 84 | 91 | 106 | 120 |
| Cromo | 0 | 0.5 | 1.0 | 0 | 0.5 | 1.0 |

Only these 8 variables have thresholds defined; Estaño, Aluminio, Agua, Potasio, and Boro have no
threshold row and are never classified as Normal/Alerta/Crítico in the oil variables table or the
AI insight panel (they still appear in the time series chart).

---

## 🔗 External Dependency: Component Hours

The "Horómetro" (component operating hours) figures shown on Predictive's priority cards, unit
banner, and condition KPIs are **not part of this data contract** — they're read from the Oil
module's golden layer:

```
data/oil/golden/{client}/cleaned_component_hours.parquet
```

via `src.data.loaders.load_component_hours`, gated by
`config/settings.py::Settings.component_hours_allowed_clients` (default: CDA, ENEX). The join key
is `unitId` (normalized to strip leading zeros, e.g. `T_09` → `T_9`) plus `componentName` matching
the Predictive component key (`motor`, `transmision`). See the Oil module's own data contract for
that file's schema.

---

## ✅ Data Quality Rules

Since this repo only consumes the golden CSVs (produced upstream), quality assumptions the
dashboard relies on are:

- ✅ `Fecha` is parseable by `pd.to_datetime` for every row
- ✅ `Unit` is non-null and consistent across dates for the same physical unit
- ✅ `ranking` and all failure-mode score columns are numeric in `[0, 100]` (or null)
- ✅ `sampleDate` and `oilMeter`/`oilHourRange` are only populated on rows that correspond to an
  actual oil sample; the dashboard's oil evidence logic deduplicates on `sampleDate` to avoid
  treating forward-filled values as new samples
- ✅ At least one row exists per `Unit` for `df_latest` (last-row-per-unit) to be meaningful
- ⚠️ If a component's CSV is missing or empty for a client, that component's sidebar subsection
  simply renders a "no data available" message rather than erroring

---

## 📝 Change Log

### Version 1.0 (July 29, 2026)
- Initial formal data contract for the Predictive module, split out from the informal processing
  notes in `RESUMEN_PROCESAMIENTO_PREDICTIVO.md` to match this repo's `project_overview.md` /
  `data_contracts.md` documentation pattern
- Documented the golden CSV schema, dashboard-side oil thresholds, and the component-hours
  cross-module dependency
