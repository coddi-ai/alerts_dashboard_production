# Data Contracts - Predictive Data Product

**Version**: 2.0
**Last Updated**: September 1, 2026
**Owner**: Predictive Module Team
**Status**: Golden layer migrated from the old wide per-client CSV to a partitioned parquet
format. **The data lives locally** under `data/{tecnica}/golden/{cliente}/{componente}/{tabla}/`
— it is synced there manually from S3 (not read live over `s3fs` by the dashboard). The
dashboard-side readers (`tab_predictive_overview.py`, `tab_predictive_evidence.py`,
`predictive_config.py`) still target the **v1.0 local-CSV shape** described in the
[Change Log](#change-log) — see [§9 Migration Notes](#-migration-notes-v10--v20) for what needs to
change in this repo before this contract is fully live.

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Data Layer Architecture](#data-layer-architecture)
3. [Table Schemas](#table-schemas)
4. [Reading Pattern](#reading-pattern)
5. [Failure Mode → Signal Catalog](#failure-mode--signal-catalog)
6. [Status & Classification Rules](#status--classification-rules)
7. [Cumulative Risk Curve](#cumulative-risk-curve)
8. [Data Quality Rules](#data-quality-rules)
9. [Migration Notes (v1.0 → v2.0)](#-migration-notes-v10--v20)
10. [Change Log](#change-log)

---

## 🎯 Overview

This document defines the data contract for the **Predictive** data product: per-component
(Motor, Transmisión, ...) failure-mode risk scores combining oil (tribology) and telemetry
evidence, produced entirely by an **upstream pipeline outside this repo**. This dashboard only
reads the golden-layer output described below — it does not compute essay classifications, alert
rates, or failure-mode scores itself.

**Data Product Purpose**: Provide a weekly-refreshed, per-unit record of failure-mode risk
(0-100) so the dashboard can rank units by priority, show which failure mode is driving risk, and
generate narrative evidence.

**Primary Consumer**: Multi-Technical Alerts Dashboard, Predictivo section
(`dashboard/tabs/tab_predictive_overview.py`, `tab_predictive_evidence.py`).

**As of v2.0**, the golden layer is **partitioned parquet**, replacing the wide per-client CSV
files described in v1.0. The canonical copy is produced on S3, but this repo reads it from a
**local mirror synced there manually** — there is no runtime S3 dependency. See
[§9](#-migration-notes-v10--v20) for the full diff and what it implies for this repo's loaders.

---

## 🏗️ Data Layer Architecture

### Storage Location

**Local (what this repo actually reads):**

```
data/{tecnica}/golden/{cliente}/{componente}/{tabla}/year={YYYY}/week={WW}/part-0.parquet
```

Example (verified against this checkout):

```
data/predictive/golden/capstone/motor/risk_scores/year=2026/week=32/part-0.parquet
data/telemetry/golden/capstone/motor/signal_daily_status/year=2025/week=28/part-0.parquet
```

**Upstream origin (S3):** the same relative layout is produced at
`s3://{bucket}/MultiTechnique Alerts/{tecnica}/golden/{cliente}/{componente}/{tabla}/year=/week=/part-0.parquet`
(bucket from `ERS_S3_BUCKET`), and mirrored into `data/` **manually** — there is no `s3fs`/live-S3
read path in the dashboard. Treat S3 as the origin/backup, and the local `data/` tree under the
paths above as the actual contract this repo reads against.

- **`year=` / `week=`** are Hive-style partitions, ISO week/year (Monday–Sunday; `year` is the ISO
  year, so e.g. Dec 29, 2025 falls in `year=2026/week=1`). Readers should list available
  `(year, week)` pairs rather than assume a fixed range — see [§4](#reading-pattern).
- There are **no bronze/silver layers** for Predictive — only this golden output is read.

### Refresh Cadence

Upstream, all four tables regenerate **once per week**, one partition per run. Locally, freshness
depends on when the manual sync from S3 was last run — the local mirror can lag the upstream
partitions. Either way, a stalled/skipped run does not produce an empty partition, so readers
should use the *last available* partition rather than assume the current calendar week has data.

### Tables

| Table | Contents | Grain |
|---|---|---|
| `telemetry / signal_daily_status` | % of the day each engine/transmission signal spent in the alert band and in the critical band | unit × day × signal |
| `predictive / risk_scores` | Risk score per failure mode, plus the synthetic `ranking`, in **long format** | unit × day × mode |
| `predictive / unit_status_summary` | Snapshot of each unit's status as of the run's close | unit (one row) |
| `predictive / cumulative_risk_curve` | Cumulative lifecycle risk curve per unit, with its fleet reference band | unit × day |

`failure_mode_diagnosis` — the per-mode textual root-cause detail — is described upstream as
**still being defined and not available yet**. However, a table matching that description already
exists in the local mirror and is **not mentioned in the upstream reading guide** — see
[`analisis_inteligente.parquet`](#predictive--analisis_inteligenteparquet-undocumented-upstream)
below. Confirm with the upstream team whether this is the stable `failure_mode_diagnosis` contract
or a separate/preview artifact before building against it.

### Auto-Discovery

Unlike v1.0, components are not discovered by scanning a folder for `*.csv` files — the path
itself is parameterized by `{cliente}/{componente}`. As observed in the local mirror:

| Client | Component | `risk_scores` / `unit_status_summary` (new parquet) | `cumulative_risk_curve` | Legacy CSV still present |
|---|---|:-:|:-:|:-:|
| `capstone` | `motor` | ✅ | ✅ | ✅ (`motor.csv`) |
| `cda` | `motor` | ✅ (history back to `year=2021`) | ❌ | ✅ (`motor.csv`) |
| `cda` | `transmision` | ❌ — not migrated | ❌ | ✅ (`transmision.csv`) |

So the new layout currently only covers `componente = motor`, across at least two clients
(`capstone`, `cda`); `transmision` has **not** been migrated for either client and is still only
available as the old wide CSV. `cumulative_risk_curve` has only been observed for `capstone`.
Whether/how multi-client, multi-component discovery works against this layout (equivalent to
v1.0's `_discover_components`) is **not formally specified** — treat the table above as a snapshot
of what exists today, not a guarantee, and re-check before assuming a client/component pair is
covered.

---

## 📐 Table Schemas

### `unit_status_summary`

One row per unit — feeds the crítico/alerta/saludable fleet cards.

| Column | Type | Description |
|---|---|---|
| `Unit` | string | Unit identifier |
| `Fecha` | date | Date of **that unit's** last available reading (not necessarily the run date — see below) |
| `estado` | string | `anormal` / `alerta` / `normal` — see [§6](#status--classification-rules) |
| `estado_previo` | string | `estado` seven days earlier |
| `cambio_estado` | string | `"sí"` / `"no"` — whether `estado` changed vs. `estado_previo` |
| `ranking` | float | Synthetic risk score for the day |
| `delta_ranking` | float | Change in `ranking` over the last 7 days |
| `media_30d` | float | 30-day rolling mean of `ranking`, **precomputed upstream** |
| `dias_media_30d` | int | Number of real days the 30-day mean was actually computed over |
| `peor_modo` | string | Failure mode with the highest score |
| `peor_valor` | float | That mode's score |
| `modes_over_threshold_count` | int | Count of modes scoring ≥ 35 (note: this threshold is distinct from the 30/50/60/80 thresholds used for `estado` — see [§6](#status--classification-rules)) |
| `modos_ordenados` | string (JSON) | All 9 modes with their score, ordered highest → lowest |
| `dias_sin_datos` | int | Staleness of this unit's snapshot |

Every unit that exists is always present in the run's partition, even if it has stopped
reporting — a stale unit shows a stale `Fecha` and `dias_sin_datos > 0` rather than being absent.

`modos_ordenados` must be parsed:

```python
import json
modos = json.loads(fila["modos_ordenados"])
# {'lubrication_failure_risk': 85.3, 'blowby_risk': 70.0, ...}
```

`json.loads` preserves the highest→lowest order, so it can feed a bar chart or ranked list
directly without re-sorting.

### `risk_scores`

Long format: **10 rows per unit per day** — one per failure mode plus one row where
`failure_mode == "ranking"`.

| Column | Type | Description |
|---|---|---|
| `Unit` | string | Unit identifier |
| `Fecha` | date | Day of the record |
| `failure_mode` | string | One of the 9 modes (all end in `_risk`), or the literal value `"ranking"` |
| `risk_value` | float | Score, 0–100 |

```python
modos = riesgos[riesgos["failure_mode"] != "ranking"]
curva = riesgos[riesgos["failure_mode"] == "ranking"]
# or: riesgos[riesgos["failure_mode"].str.endswith("_risk")]
```

**Absence of a row ≠ a score of 0.0.** No row for a given unit/day/mode means no data was
available that day; `risk_value == 0.0` means an actual computed score of zero risk.

### `telemetry / signal_daily_status`

| Column | Type | Description |
|---|---|---|
| `Unit` | string | Unit identifier |
| `Fecha` | date | Day of the record |
| `signal_name` | string | Signal identifier, e.g. `oil_diff_pressure_psi`, `egt_avg_c` |
| `pct_time_alert` | float | % of the day in the alert band (0–100) |
| `pct_time_critical` | float | % of the day in the critical band (0–100) |

Same rule as `risk_scores`: a missing row means no measurement that day for that signal, not a
zero reading.

> **Oil signals do not appear to follow this shape.** `FAILURE_MODE_CONFIG["capstone"]["signals"]`
> lists a `technique` per signal (`telemetry` in the worked example), and oil (tribology) essay
> names (e.g. `Cromo`, `Hierro`, `Hollín`) also appear as `signals` entries for some failure modes
> — which could suggest an equivalent `oil/.../signal_daily_status` table. Checked against the
> local mirror: **no such table exists** (`data/oil/golden/{client}/` only has the pre-existing
> `stewart_limits*.parquet` files, unchanged). Instead, raw oil essay values plus derived 5-sample
> moving means / 30-day deltas / 90-day z-scores (`{Essay}_mm5`, `{Essay}_delta30`, `{Essay}_z90`)
> show up per-unit in `analisis_inteligente.parquet` (below). So the v1.0 static `OIL_THRESHOLDS`
> table is **not confirmed redundant** — oil classification upstream now looks closer to a
> per-unit statistical baseline (`z90`) than to the old fixed Normal/Alerta/Crítico bands, which is
> itself a change worth confirming with the upstream team before touching `OIL_THRESHOLDS` — see
> [§9](#-migration-notes-v10--v20).

### `predictive / analisis_inteligente.parquet` (undocumented upstream)

Observed locally at `data/predictive/golden/{cliente}/analisis_inteligente.parquet` (both
`capstone` and `cda`) but **not mentioned anywhere in the upstream reading guide**
(`new_predictive_data_contracts.md`) that the rest of this document is otherwise based on. Flag
its use to the upstream team before depending on it — it may be a preview/internal artifact rather
than a committed contract.

**Grain**: one row per unit — a snapshot, not partitioned by `year=`/`week=` like the other four
tables (confirmed: 50 rows for 50 distinct `Unit` values in the `capstone` copy, most-recent
`Fecha` per unit).

**Contents**: this is the closest thing observed to the `failure_mode_diagnosis` table the
upstream guide describes as "still being defined" — it carries, per unit:

| Column group | Examples | Description |
|---|---|---|
| Identifiers | `Unit`, `Fecha`, `year_week` | |
| Failure-mode scores | `abrasive_wear_risk`, ..., `ranking` | Same 9 modes as `risk_scores`, but wide (one column each) |
| Raw oil essays | `Aluminio`, `Cobre`, `Hierro`, `Viscocidad`, ... | Latest sample values |
| Oil/mode derived stats | `{col}_mm5`, `{col}_delta30`, `{col}_z90` | 5-sample moving mean, 30-day delta, 90-day z-score, per failure mode and per oil essay |
| Status | `media_30d`, `peor_riesgo`, `peor_modo`, `estado`, `rolling_risk_90d` | Same shape as `unit_status_summary` |
| **Narrative (LLM-generated)** | `observaciones` (JSON list of `{severidad, texto}`), `diagnostico`, `causa_probable`, `acciones` (JSON list), `limitacion` | Free-text diagnosis, in Spanish |
| Provenance | `analisis_fuente` (`"llm"` or `"omitida"`), `analisis_tokens`, `analisis_error` | `"omitida"` rows (seen for `normal`-status units) have no narrative fields populated — the LLM pass appears to be skipped for low-risk units, presumably to save cost |

This directly resolves two things left open by the upstream guide: the **narrative diagnosis
content does exist** for at least `capstone`/`cda`, and the **failure-mode set is 9**, matching
`risk_scores`/`unit_status_summary` (see [§5](#failure-mode--signal-catalog) for the confirmed
names).

---

## 📖 Reading Pattern

The three time-series tables (`unit_status_summary`, `risk_scores`, `signal_daily_status`) share
one reading pattern based on listing available `(year, week)` partitions and reading only the
requested ones — do not `pd.read_parquet` the whole dataset and filter in memory.

**Read from the local mirror** (`data/{tecnica}/golden/{cliente}/{componente}/{tabla}/`) — no S3
client is needed at read time, since the sync already happened:

```python
import re
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as pads

RAIZ = "data"
PARTICION = pads.partitioning(pa.schema([("year", pa.int32()), ("week", pa.int32())]), flavor="hive")

def ruta_tabla(tecnica, nombre, cliente, componente):
    return f"{RAIZ}/{tecnica}/golden/{cliente}/{componente}/{nombre}"

def semanas_disponibles(ruta):
    dset = pads.dataset(ruta, format="parquet", partitioning=PARTICION)
    return sorted({(int(y.group(1)), int(w.group(1)))
                   for r in dset.files
                   if (y := re.search(r"year=(\d+)", r)) and (w := re.search(r"week=(\d+)", r))})

def leer_ultimas_semanas(ruta, n=13):
    pares = semanas_disponibles(ruta)[-n:]
    return pd.read_parquet(ruta, filters=[[("year", "==", y), ("week", "==", w)] for y, w in pares])
```

The same functions work unmodified against the S3 origin (pass an `s3fs.S3FileSystem()` as
`filesystem=` to `pads.dataset`/`pd.read_parquet` and point `RAIZ` at the bucket path) — the
partition layout is identical, only the filesystem changes. This repo has no reason to do that
today since the local mirror is kept in sync manually.

`leer_ultimas_semanas` returns a concatenated DataFrame including the `year`/`week` columns parsed
from the path. `n=13` weeks ≈ 91 days, i.e. "last 13 available weeks", not "last 90 calendar
days" — if a week is missing (ingestion gap, or a stale local sync), the actual calendar span
covered can be wider. Filter by `Fecha` afterward if exact calendar windows matter.

`cumulative_risk_curve` does **not** use this pattern — see [§7](#cumulative-risk-curve).

`Fecha` comes back as a Python `date` object, not `datetime64` — call `pd.to_datetime` before any
date arithmetic.

---

## 🧩 Failure Mode → Signal Catalog

Same role as v1.0's `FAILURE_MODE_CONFIG`, still a Python dict imported by the dashboard, **not**
data stored in parquet — but its shape has changed (see [§9](#-migration-notes-v10--v20)): it is
now keyed by client, then by component, and each signal's own catalog entry carries its source
`technique` and display metadata.

```python
FAILURE_MODE_CONFIG["capstone"]["components"]["motor"]["blowby_risk"]
# {'label': 'Blow-by / Desgaste de Anillos',
#  'signals': ['Cromo', 'Hierro', 'Hollín', 'crankcase_pressure_inh2o', 'oil_level_pct']}

FAILURE_MODE_CONFIG["capstone"]["signals"]["crankcase_pressure_inh2o"]
# {'technique': 'telemetry', 'label': 'Presión Cárter', 'unit': 'inH2O'}
```

To render a mode's evidence: filter `signals` for the selected mode, then for each signal look up
its `technique` in the `signals` catalog to know which `signal_daily_status` table to read from.

Motor now has **9 failure modes**, confirmed directly from the local `risk_scores` and
`unit_status_summary` data (both `capstone` and `cda`):

```
abrasive_wear_risk, bearing_wear_risk, blowby_risk, combustion_risk,
coolant_contamination_risk, lubrication_failure_risk, oil_degradation_risk,
thermal_imbalance_risk, turbocharger_risk
```

The 7 already known from v1.0 carry over unchanged; the **2 new modes** are `turbocharger_risk`
("Turbocompresor") and `coolant_contamination_risk` ("Contaminación por Refrigerante") — labels
confirmed from the generated narrative text in `analisis_inteligente.parquet` (e.g. *"Desbalance
Térmico: riesgo en ascenso"*, *"El motor muestra Contaminación por Refrigerante en banda
Crítica..."*). Still confirm the exact label strings and oil/telemetry variable mapping against
`FAILURE_MODE_CONFIG["capstone"]` in code before wiring these into the dashboard — the values here
are inferred from data, not read from the config dict itself.

---

## 🚦 Status & Classification Rules

### `unit_status_summary.estado` (fleet cards)

Evaluated in this order — `anormal` wins over `alerta`:

| Status | Condition |
|---|---|
| `anormal` | `media_30d ≥ 60` **or** any mode `≥ 80` |
| `alerta` | `media_30d ≥ 30` **or** any mode `≥ 50` |
| `normal` | otherwise |

These thresholds (30/50/60/80) match v1.0's dashboard-side Saludable/Alerta/Crítica thresholds —
**this rule is now precomputed upstream**, not applied client-side (see
[§9](#-migration-notes-v10--v20)). `modes_over_threshold_count` uses a separate, unrelated
threshold of 35 and should not be confused with `estado`.

### `cumulative_risk_curve.estado` (curve zones)

Uses Title Case (`Normal` / `Alerta` / `Anormal`) and compares the accumulated curve against the
fleet reference band, **not** the same 30/50/60/80 rule above. **The two `estado` fields can
disagree for the same unit** — this mirrors a known v1.0 behavior (the classic hero status vs. the
accumulated-curve zone status could already disagree; see `project_overview.md` §"Curva Acumulada
de Riesgo"). Label them distinctly in any UI that shows both.

---

## 📈 Cumulative Risk Curve

`cumulative_risk_curve` requires its own reader — it does **not** use
[`leer_ultimas_semanas`](#reading-pattern), for two reasons: each partition already contains the
**full history** (not just that week), and the parquet file carries schema-level metadata
(`config`, `banda`, and a third key `tendencia`) that `pd.read_parquet` silently discards.

```python
import json

def leer_curva(ruta, semana=None):
    dset = pads.dataset(ruta, format="parquet", partitioning=PARTICION)
    pares = sorted({(int(y.group(1)), int(w.group(1))) for r in dset.files
                    if (y := re.search(r"year=(\d+)", r)) and (w := re.search(r"week=(\d+)", r))})
    y, w = semana or pares[-1]
    tabla = dset.to_table(filter=(pads.field("year") == y) & (pads.field("week") == w))
    df = tabla.to_pandas()
    for k, v in (tabla.schema.metadata or {}).items():
        if (nombre := k.decode()) in ("config", "banda", "tendencia"):
            df.attrs[nombre] = json.loads(v.decode())
    df["Fecha"] = pd.to_datetime(df["Fecha"])
    return df
```

(Same note as [§4](#reading-pattern): this reads the local mirror; pass `filesystem=` for S3.)

If `df.attrs["config"]`/`["banda"]` is lost (e.g. by reading with plain `pd.read_parquet`), the
plotting helper (`curva_figura.plot_curva_acumulada`, shipped as a separate module) does **not**
raise — it silently falls back to default `K_SIGMA`/`K_ALERTA` parameters and draws zone
boundaries that don't match the classification that was actually used. Always read this table with
`leer_curva`. Confirmed locally, `config` for the `capstone`/`motor` partition currently reads:

```json
{"PESO_HORAS": false, "CORREDOR_INDIVIDUAL": false, "LEAVE_ONE_OUT": true,
 "APLICAR_OFFSET": true, "REFERENCIA_SOLO_VIGENTES": false, "CALCULAR_TENDENCIA": false,
 "K_SIGMA": 2.0, "K_ALERTA": 1.0}
```

### Columns

The upstream reading guide (`new_predictive_data_contracts.md`) documents a 13-column subset; the
local parquet (`data/predictive/golden/capstone/motor/cumulative_risk_curve/...`) actually carries
**30 columns**. The full set, confirmed by direct inspection:

| Column | Type | Description |
|---|---|---|
| `Unit`, `Fecha` | string, date | Unit and day |
| `ciclo` | int | Component lifecycle number; increments on each component change |
| `curva` | string | Key for one full lifecycle, e.g. `"CA-30 - ciclo 1"` |
| `componentHours_filled` | float | Component hours that day — the chart's X axis |
| `ranking` | float | That day's non-cumulative risk |
| `ranking_acumulado` | float | Cumulative sum of `ranking` within the unit/cycle; starts near 0 |
| `offset_curva` | float | Vertical offset so the curve starts at the fleet mean |
| `ranking_acumulado_ajustado` | float | **The column that is plotted and classified against** |
| `banda_media`, `banda_umbral` | float | Fleet mean and threshold at that hour value |
| `banda_inferior` | float | *Undocumented upstream.* Lower band bound at that hour value (mirrors `banda_umbral` on the low side) |
| `banda_extrapolada` | bool | *Undocumented upstream.* Whether the band value at this point was extrapolated beyond the fitted grid |
| `tramo_flota` | float | *Undocumented upstream.* Likely a fleet-segment/bucket value at that hour — meaning not confirmed |
| `sigma_curva` | float | *Undocumented upstream.* Standard deviation of the band at that hour |
| `umbral_curva` | float | *Undocumented upstream.* Per-curve threshold, distinct from `banda_umbral` — relationship not confirmed |
| `z` | float | *Undocumented upstream.* Z-score of this point vs. the band (consistent with `K_SIGMA`/`K_ALERTA` in `config`) |
| `evaluable` | bool | *Undocumented upstream.* Whether this point had enough support to be classified |
| `estado` | string | `Normal` / `Alerta` / `Anormal`, or null if outside the band's domain |
| `nivel_medio` | float | *Undocumented upstream.* Meaning not confirmed |
| `horas_por_dia` | float | *Undocumented upstream.* Component-hours accrual rate for that unit/cycle |
| `delta_tendencia`, `tendencia` | float, string | *Undocumented upstream.* Trend delta and label; mostly null in the observed sample (`CALCULAR_TENDENCIA: false` in `config` for this partition) |
| `dias_desde_tendencia` | float | *Undocumented upstream.* Days since the trend was last computed |
| `es_vigente` | bool | `True` if this is the unit's current (active) cycle |
| `zona_final` | string | Status of the vigent curve's last point, repeated across all its rows; null for historical cycles |
| `peor_zona` | string | *Undocumented upstream.* Worst zone reached across the vigent cycle so far |
| `tendencia_final`, `peor_tendencia` | string | *Undocumented upstream.* Trend-equivalents of `zona_final`/`peor_zona` |
| `componente` | string | Observed locally as `"MOTOR DIESEL"`, not the lowercase `"motor"` the reading guide shows — **do not hardcode the lowercase form when filtering on this column** |

Two different nulls: `estado` null means "outside the reference band's domain"; `zona_final` null
means "historical cycle, not the current one" — don't conflate them. Columns marked *undocumented
upstream* are present in the data but not explained in `new_predictive_data_contracts.md`; the
descriptions above are best-effort inferences from column names and observed values — confirm with
the upstream team before building logic that depends on their exact semantics.

The X axis is component **hours**, not calendar time — wear tracks component usage, not the
calendar.

**Implication for this repo**: `componentHours_filled` now arrives already joined upstream. In
v1.0, the dashboard built this same curve itself
(`dashboard/components/accumulated_curve.py::build_accumulated_data`) by merging `ranking` from the
component CSV with `cleaned_component_hours.parquet` from the Oil module and computing
`ranking_acumulado` client-side. If this table is adopted as-is, most of that module's logic
(`fill_hours_progressive`, cycle-break detection, `build_reference_band`, `classify_curves`)
becomes redundant — see [§9](#-migration-notes-v10--v20).

---

## ✅ Data Quality Rules

- ✅ `Fecha` is present and comparable across tables for a given unit/day, but arrives as a `date`
  object per parquet, not `datetime64` — cast with `pd.to_datetime` before date arithmetic.
- ✅ `Unit` is present in `unit_status_summary` for every known unit on every run, even units that
  stopped reporting (surfaced instead via `dias_sin_datos` and a stale `Fecha`).
- ✅ `risk_value` (in `risk_scores`) and `pct_time_alert`/`pct_time_critical` (in
  `signal_daily_status`) are numeric in `[0, 100]` when present.
- ✅ **Absence of a row is the "no data" signal** in both long-format tables — do not backfill or
  interpret a missing unit/day/mode (or unit/day/signal) row as zero.
- ✅ `cumulative_risk_curve` must be read via `leer_curva`, not `pd.read_parquet`, to retain
  `config`/`banda` metadata — otherwise zone boundaries silently drift from what was actually used
  to classify the data.
- ⚠️ `failure_mode_diagnosis` as its own named/partitioned table does not exist yet, but
  `analisis_inteligente.parquet` (undocumented upstream, see [§3](#predictive--analisis_inteligenteparquet-undocumented-upstream))
  already carries equivalent narrative content locally — confirm which of the two evidence UI
  should build against.
- ⚠️ `componente` in `cumulative_risk_curve` is observed as `"MOTOR DIESEL"`, not the lowercase
  `"motor"` used elsewhere in the path/config (`{componente}` in the S3/local path, or
  `FAILURE_MODE_CONFIG[...]["components"]["motor"]`) — don't assume the casing/format is
  consistent across tables.

---

## 🔀 Migration Notes (v1.0 → v2.0)

Summary of what changed and what it implies for this repo. **None of these are implemented yet** —
this repo's Predictive tabs, callbacks, and config still read the v1.0 local-CSV shape.

| Area | v1.0 | v2.0 | Implication |
|---|---|---|---|
| Storage | Local per-client CSV, `data/predictive/golden/{client}/{component}.csv` | Partitioned parquet, mirrored locally at `data/{tecnica}/golden/{cliente}/{componente}/{tabla}/year=/week=/`, synced manually from S3 | Loaders (`_load_component_data` in both tabs) need a rewrite around `pyarrow.dataset` (local `data/` root — no live S3 client needed) plus partition-listing/caching, and a way to trigger/detect the manual sync running stale — not a `pd.read_csv` swap |
| Shape | Wide: ~250 columns, one per operational-mode × signal × rate-type, plus one column per failure mode | Long: `risk_scores` and `signal_daily_status` are unit × day × (mode\|signal) rows | Code that pattern-matches column name substrings (`create_telemetry_signal_chart`, `_analyze_telemetry_observations`) must switch to filtering rows instead |
| Failure modes (Motor) | 7, hardcoded in `predictive_config.py::FAILURE_MODE_CONFIG["motor"]` | 9 — confirmed: `abrasive_wear_risk`, `bearing_wear_risk`, `blowby_risk`, `combustion_risk`, `coolant_contamination_risk`, `lubrication_failure_risk`, `oil_degradation_risk`, `thermal_imbalance_risk`, `turbocharger_risk` | `FAILURE_MODE_CONFIG` needs the 2 new modes (`turbocharger_risk`, `coolant_contamination_risk`) added, with their label/variable mapping confirmed against the actual `FAILURE_MODE_CONFIG["capstone"]` dict in code, before the failure-mode table and priority-card driver bars are complete |
| Rolling averages | Computed client-side (`30d`/`60d`/`90d` per-`Unit` rolling means, `min_periods=1`) | `media_30d` precomputed upstream in `unit_status_summary`; no `60d`/`90d` equivalent observed | Client-side 30d rolling-window computation becomes redundant once the dashboard reads `unit_status_summary.media_30d` directly; `60d`/`90d` rolling logic likely still needs to stay client-side (or be requested from upstream) unless confirmed otherwise |
| Status classification | Applied client-side on `avg_ranking_30d`/`max_fm_30d`, duplicated in 4 call sites (`tab_predictive_overview.py`, `tab_predictive_evidence.py`, twice in `predictive_callbacks.py`) | Precomputed upstream as `unit_status_summary.estado`, same 30/50/60/80 thresholds (verified against local data) | The 4-site duplication risk goes away if the dashboard trusts `estado` directly instead of recomputing it — but the accumulated-curve's separate `estado`/`zona_final` classification stays a second, independently-computed status (unchanged behavior, still worth distinct labeling) |
| Cumulative curve | Built entirely client-side in `accumulated_curve.py` (hours-fill, cycle detection, reference band, zone classification), joined against Oil's `cleaned_component_hours.parquet` | Delivered precomputed as `cumulative_risk_curve`, including `componentHours_filled`, `zona_final`, and ~17 more columns not documented upstream (see [§7](#columns)) | Most of `accumulated_curve.py` becomes redundant if this table is adopted as-is; the `K_SIGMA=2.0`/`K_ALERTA=1.0` parameters observed locally are close to the old `EXCLUDE_FROM_REFERENCE`/`K_SIGMA=2` constants but now travel as `df.attrs["config"]`/`["banda"]`/`["tendencia"]` parquet metadata instead of hardcoded constants — the extra undocumented columns (`z`, `evaluable`, `tramo_flota`, etc.) should be clarified with upstream before being relied on |
| Oil variables & thresholds | Separate wide columns per essay (`Hierro`, `Cobre`, ...) plus a static, hardcoded `OIL_THRESHOLDS` table in `predictive_config.py` | No `oil`-technique equivalent of `signal_daily_status` found locally (`data/oil/golden/{client}/` is unchanged: still just `stewart_limits*.parquet`). Raw essay values plus `_mm5`/`_delta30`/`_z90` derived stats now appear per-unit in `analisis_inteligente.parquet` | `OIL_THRESHOLDS` is **not confirmed redundant** — the upstream classification signal looks more like a per-unit `z90` baseline than the old fixed Normal/Alerta/Crítico bands; treat this as a genuine behavior change to confirm with upstream, not just a storage-format change |
| Component-hours cross-module dependency | Predictive read Oil's `data/oil/golden/{client}/cleaned_component_hours.parquet` directly for horómetro figures on priority cards/unit banner | Not present in `unit_status_summary`/`risk_scores`; only `cumulative_risk_curve.componentHours_filled` carries hours, and only for `capstone` (no curve table for `cda` yet) | Priority-card/unit-banner horómetro display likely still needs the standalone Oil-module join for any client without a `cumulative_risk_curve` table — confirm per-client rather than assuming the new layer covers it everywhere |
| Clients/components observed | `CDA`: `motor`, `transmision` (CSV) | New parquet layout confirmed for `capstone/motor` and `cda/motor` (history back to `year=2021` for `cda`); `transmision` not migrated for either client; `cumulative_risk_curve` only observed for `capstone` | Do not assume `transmision` is available under the new layout for any client, and don't assume `cumulative_risk_curve` exists for `cda` — gate per client **and** per table, not just per client, before enabling in `predictive_allowed_clients` |
| `failure_mode_diagnosis` | N/A (didn't exist) | Described upstream as planned/not yet available, but a `analisis_inteligente.parquet` snapshot table with equivalent LLM-generated narrative content (`observaciones`, `diagnostico`, `causa_probable`, `acciones`) already exists locally for both `capstone` and `cda`, undocumented in the upstream guide | Confirm with upstream whether `analisis_inteligente.parquet` **is** the `failure_mode_diagnosis` contract (just under a different/undocumented name) before building the evidence UI's narrative panel against it — until confirmed, treat it as unstable and keep the existing rule-based insight engine (`tab_predictive_evidence.py`) as the fallback |

**Net effect**: v2.0 removes most of the client-side computation this module currently does
(rolling averages, status classification, curve construction) by shifting it upstream, and swaps
the wide/CSV shape for a long/parquet one. Adopting it is a loader + config rewrite, not a
column-mapping patch — treat it as a separate, scoped migration task rather than a drop-in change
to the existing CSV readers.

---

## 📝 Change Log

### Version 2.0 (September 1, 2026)
- Documented the new parquet golden layer (`telemetry/signal_daily_status`,
  `predictive/risk_scores`, `predictive/unit_status_summary`, `predictive/cumulative_risk_curve`),
  replacing the wide per-client CSV files described in v1.0, based on
  `new_predictive_data_contracts.md`
- Recorded the long-format schema, Hive `year=`/`week=` partitioning, weekly refresh cadence, and
  the dedicated `cumulative_risk_curve` reader (parquet metadata dependency)
- **Corrected the storage model**: the golden layer is read from a **local mirror**
  (`data/{tecnica}/golden/{cliente}/{componente}/{tabla}/`) synced manually from S3 — the
  dashboard has no live/runtime S3 dependency, contrary to how the upstream reading guide frames
  it. Reading-pattern code samples updated to target the local filesystem, with S3 noted as a
  drop-in `filesystem=` swap if ever needed.
- Verified the actual local parquet against the upstream reading guide and corrected several
  discrepancies: `cumulative_risk_curve` has 30 columns locally vs. 13 documented upstream (17
  undocumented columns listed in [§7](#columns), including `componente` being the string
  `"MOTOR DIESEL"` rather than lowercase `"motor"`); the 9 Motor failure-mode names are now listed
  explicitly (`turbocharger_risk`, `coolant_contamination_risk` are the 2 new vs. v1.0); confirmed
  no `oil`-technique `signal_daily_status`-equivalent table exists yet, so `OIL_THRESHOLDS`
  redundancy remains unconfirmed; confirmed the new layout covers `capstone/motor` and
  `cda/motor` (not `transmision`, not yet `cda`'s cumulative curve)
- Discovered and documented `analisis_inteligente.parquet`, an LLM-generated per-unit narrative
  snapshot present locally for `capstone`/`cda` that appears to be the `failure_mode_diagnosis`
  content the upstream guide describes as "not available yet" — **not mentioned in the upstream
  guide itself**; flagged for confirmation with the upstream team
- Added [§9 Migration Notes](#-migration-notes-v10--v20) enumerating control changes vs. v1.0 and
  their implications for this repo's loaders, `FAILURE_MODE_CONFIG`, rolling-average logic, status
  classification, and the accumulated-curve module — none of which have been implemented against
  this new contract yet

### Version 1.0 (July 29, 2026)
- Initial formal data contract for the Predictive module, split out from the informal processing
  notes in `RESUMEN_PROCESAMIENTO_PREDICTIVO.md` to match this repo's `project_overview.md` /
  `data_contracts.md` documentation pattern
- Documented the golden CSV schema, dashboard-side oil thresholds, and the component-hours
  cross-module dependency
