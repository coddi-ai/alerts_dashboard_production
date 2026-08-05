# Predictive Module - Project Overview

**Version**: 1.0
**Last Updated**: July 29, 2026
**Owner**: Predictive Module Team

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [What the Module Does](#what-the-module-does)
3. [How the Model Is Assembled](#how-the-model-is-assembled)
4. [Module Access](#module-access)
5. [Dashboard Architecture](#dashboard-architecture)
6. [Processing Pipeline in the Dashboard](#processing-pipeline-in-the-dashboard)
7. [Pages and Visualizations](#pages-and-visualizations)
8. [AI Insight Engine](#ai-insight-engine)
9. [Callback Flow](#callback-flow)
10. [Relevant Files](#relevant-files)
11. [Related Documentation](#related-documentation)

---

## 🎯 Overview

The **Predictive** module estimates, per equipment component (e.g. Motor, Transmisión), the risk
of specific **failure modes** by combining oil (tribology) evidence and telemetry evidence into a
single 0-100 score per failure mode plus an overall unit ranking. Unlike the rest of this
dashboard, which reads mostly raw classified/aggregated records, Predictive reads an
**already-scored** upstream output — this repo's job is to load it, compute rolling trends,
classify fleet status, and render fleet/unit views with AI-style narrative insights.

**Key objective**: Let maintenance teams see, per component and per unit, *which* failure mode is
driving risk, *why* (which oil/telemetry variables are behind it), and *how it's trending*
— before the equipment fails.

---

## 🚀 What the Module Does

For each auto-discovered component CSV under `data/predictive/golden/{client}/`, the module
provides two views:

- **Resumen (Overview)**: fleet-wide KPIs, priority-ranked unit cards with top failure-mode
  drivers, and a sortable failure-mode table (today / 30d / 60d / 90d).
- **Evidencia (Evidence)**: per-unit deep dive — condition KPIs, fleet-position scatter, a
  comparative bar chart per failure mode vs. fleet average, an AI-style insight panel, an oil
  time series + variables table, and telemetry alert-rate charts — all scoped to the failure mode
  the user selects.

See [data_contracts.md](data_contracts.md) for the full column-level schema of the input CSVs.

---

## 🧠 How the Model Is Assembled

The risk model is a **weighted-evidence scoring system**, not a black-box ML model. Each failure
mode is defined (in `dashboard/components/predictive_config.py::FAILURE_MODE_CONFIG`) as a named
combination of:

- **Oil variables** (tribology essays, e.g. Hierro, Cobre, Viscocidad)
- **Telemetry variables** (sensor signals, e.g. EngOilPres, TrnSlip)
- A **methodology description** (`FAILURE_MODE_METHODOLOGY`) explaining, in plain language, *why*
  those variables together indicate that failure mode

**Motor** has 7 failure modes; **Transmisión** has 7 failure modes (see
[data_contracts.md §5](data_contracts.md#5-failure-mode-scores) for the full list and their
associated variables).

The actual per-row 0-100 scores for each failure mode, and the consolidated `ranking` column, are
**pre-computed upstream** (outside this repo) and arrive already populated in the golden CSV. This
dashboard does not compute the scores themselves — its "model assembly" work is entirely in the
**presentation layer**:

1. **Rolling trend aggregation** — 30d/60d/90d rolling averages per unit, per failure mode and for
   `ranking`, computed at load time (see [§6](#processing-pipeline-in-the-dashboard))
2. **Fleet status classification** — fixed-threshold rules applied to those rolling averages to
   bucket each unit into Saludable / Alerta / Crítica
3. **Driver attribution** — for the priority cards and comparative bars, the top-N failure modes
   by 30d-average score are surfaced as "why this unit is at risk"
4. **Narrative insight generation** — a rule-based (not LLM-based) engine in
   `tab_predictive_evidence.py` cross-references the failure mode's oil/telemetry variables
   against Stewart-style thresholds, trend deltas, and fleet averages to produce human-readable
   observations (see [§8](#ai-insight-engine))

**Oil thresholds** used for classification and observation text (`OIL_THRESHOLDS` in
`predictive_config.py`) are hardcoded per-essay, per-oil-age-range (`LT_1000` / `GE_1000`) values
— they are dashboard-side configuration, not part of the CSV schema, and are **not** the same
Stewart Limits used by the Oil module (they're a simplified, static threshold set specific to
Predictive).

---

## 🔐 Module Access

The Predictivo section is only shown in the sidebar to users whose client is listed in
`config/settings.py::Settings.predictive_allowed_clients` (default: **CDA, CAPSTONE**). Gating is
per-client, not per-role — an `admin` account for a non-allowed client still won't see it.

Component-hours ("Horómetro") enrichment on the KPIs/cards is a second, independent gate
(`component_hours_allowed_clients`, default **CDA, ENEX**) — it reads
`oil/golden/{client}/cleaned_component_hours.parquet` (an Oil-module golden file, reused here) via
`src.data.loaders.load_component_hours`. If the client isn't in that list, or the file/component
row is missing, the horómetro fields simply render as `—`.

---

## 🏗️ Dashboard Architecture

### Auto-Discovery

Components are **not hardcoded**. `_discover_components(client)` (duplicated identically in both
`tab_predictive_overview.py` and `tab_predictive_evidence.py`) scans
`data/predictive/golden/{client}/` for `*.csv` files and treats each filename (minus extension) as
a component key. A new component becomes available the moment a matching CSV lands in that
folder — no code change needed, provided a matching entry exists in `FAILURE_MODE_CONFIG` (falls
back to `motor`'s config if the component key is unrecognized).

### File Layout (follows the repo's tabs/callbacks/components convention)

| File | Responsibility |
|------|----------------|
| `dashboard/components/predictive_config.py` | Failure-mode → variable mapping, methodology text, oil labels/thresholds |
| `dashboard/components/predictive_charts.py` | Plotly figures: fleet scatter, comparative bars, oil time series, telemetry bars |
| `dashboard/components/predictive_tables.py` | HTML table of oil variables (current/previous/variation/velocity/status) |
| `dashboard/components/predictive_kpis.py` | Reusable KPI card/row components |
| `dashboard/tabs/tab_predictive_component.py` | Shell layout with internal Resumen/Evidencia tabs |
| `dashboard/tabs/tab_predictive_overview.py` | Resumen: load, classify, render fleet view |
| `dashboard/tabs/tab_predictive_evidence.py` | Evidencia: load, render unit KPIs + AI insight + oil/telemetry evidence |
| `dashboard/callbacks/predictive_callbacks.py` | All interactivity (see [§9](#callback-flow)) |

**Sidebar structure**: `Predictivo → {Componente} → [Resumen | Evidencia]`, one subsection per
discovered component, per client.

---

## ⚙️ Processing Pipeline in the Dashboard

`_load_component_data()` (separately implemented — with slightly different column sets — in the
overview and evidence tabs) performs:

```
CSV → DataFrame → parse Fecha → per-Unit rolling averages → latest snapshot per Unit
```

1. `pd.read_csv(filepath)`, then `Fecha` parsed to datetime
2. Per-`Unit`, per-score-column (each failure-mode column + `ranking`) rolling means over 30/60/90
   days (`min_periods=1`, so early rows still get a value from the data available so far)
3. `df_latest`: last row per `Unit`, with the corresponding rolling columns merged in
   (`avg_ranking_30d`, `avg_ranking_60d`, `ranking_acum_90d`, `{failure_mode}_30d/_60d/_90d`)
4. `max_fm_30d`: the max across all failure-mode 30d averages for that unit — the second input to
   status classification
5. `prev_ranking`: each unit's `ranking` value from the second-most-recent date present in the
   file, used to compute the priority card's delta badge

### Fleet Status Classification

Status uses **fixed thresholds** on the 30-day rolling values (not a fleet percentile):

| Status | Condition |
|--------|-----------|
| 🟢 Saludable | `avg_ranking_30d < 30` **and** `max_fm_30d < 50` |
| 🟡 Alerta | `avg_ranking_30d >= 30` **or** `max_fm_30d >= 50` |
| 🔴 Crítica | `avg_ranking_30d >= 60` **or** `max_fm_30d >= 80` |

Colors: 🟢 `#1d9e75` · 🟡 `#ef9f27` · 🔴 `#e24b4a`.

This same rule is duplicated in four places — `tab_predictive_overview.py::_render_component_overview`,
`tab_predictive_evidence.py::render_initial_content`, and twice inside
`predictive_callbacks.py` (`sort_failure_mode_table`, `update_unit_banner`) — because each renders
independently from its own callback. **If this logic ever changes, all four call sites must be
updated together.**

> Note: an earlier draft of this module's docs described status classification using a fleet
> P80 quantile of `avg_ranking_30d`. That is no longer how the shipped code works — the fixed
> thresholds above are current as of this writing. Trust this file (and the code) over older notes.

### Curva Acumulada de Riesgo

Implemented entirely in `dashboard/components/accumulated_curve.py` and inserted into the Resumen
tab by `tab_predictive_overview.py::_render_component_overview` (between the hero KPIs and the
priority cards, only when it can be built — see below). It has **no dedicated Dash `id` or
callback**: the `dcc.Graph` it returns (`config={"displayModeBar": False, "responsive": True}`) has
no `id`, so it is entirely rebuilt every time the parent Resumen content re-renders — i.e. on
`client-selector`/`user-info-store` change (`predictive_pages_callbacks.py::render_predictive_component`)
or when switching back to the Resumen internal tab (`predictive_callbacks.py::switch_internal_tab`).

**Data sources**:
- `data/predictive/golden/{client}/{component}.csv` — same file as the rest of Resumen, loaded via
  `_load_component_data()`; only `Unit`, `Fecha`, `ranking` are used here.
- `data/oil/golden/{client}/cleaned_component_hours.parquet` — loaded directly from disk by
  `_load_component_hours_if_available()` (`tab_predictive_overview.py`), **bypassing the
  `settings.get_component_hours_path()` helper** used elsewhere in this module (its own docstring
  notes this is "igual que el dashboard antiguo"). Required columns: `sampleDate`, `unitId`,
  `componentName`, `componentHours_cleaned`. If this parquet doesn't exist for the client, the
  curve is silently skipped (`_load_component_hours_if_available` returns `None`) and the classic
  KPI hero renders instead — this is the only client gate the curve itself has (see below).

**Calculation** (`build_accumulated_data`, `accumulated_curve.py`):
1. Coerce `ranking` to numeric and drop non-finite values (`np.isfinite`) — an explicit patch for
   upstream `-inf` values, noted in the code as a TODO on the upstream side, not fixed here.
2. Normalize unit ids (e.g. `T_09` → `T_9`) and merge `ranking` with hours on `(unit, Fecha)`.
3. `fill_hours_progressive()` fills missing hours per unit and detects lifecycle resets ("ciclo"):
   an hour value that drops more than 50% from the previous reading starts a new cycle; a smaller
   drop is treated as noise and held at the previous value.
4. `ranking_acumulado = groupby(["Unit", "ciclo"])["ranking"].cumsum()` — a **cumulative sum of the
   raw daily `ranking`** per unit/cycle. This is not the 30/60/90-day rolling average used
   elsewhere in Resumen/Evidencia — it is a separate, unrelated metric.

**Reference band** (`build_reference_band`): for each unit/cycle curve, computes the rate of
accumulation per component-hour, interpolates onto a 200-point grid over the component's
95th-percentile max hours, then takes the fleet mean ± `K_SIGMA = 2` standard deviations of that
rate (integrated back into a cumulative band). Requires `MIN_SUPPORT = 3` contributing curves per
grid point, else returns `None` (the curve build aborts and the classic hero is shown instead).
Units listed in the hardcoded `EXCLUDE_FROM_REFERENCE` dict (currently
`{"motor": ["T_11"], "transmision": ["T_09"]}`) are excluded only from the band statistics
("fallas conocidas… inflan sigma" per the code comment), not from the plotted curves themselves.

**Zone classification** (`classify_curves`): for each unit's most recent cycle, the last plotted
point is compared to the reference band and labeled `zona_final` = `Normal` (below the mean),
`Alerta` (between the mean and mean + 2σ), or `Anormal` (above mean + 2σ). When the curve builds
successfully, these three counts replace the classic hero with a "Estado de Flota" KPI row
(`zone_hero` in `_render_component_overview`) — **a second, independently-labeled classification
that can disagree with the classic hero's Crítica/Alerta/Saludable status** (see Fleet Status
Classification above), since one is derived from the accumulated-curve band and the other from
fixed thresholds on `avg_ranking_30d`/`max_fm_30d`.

**Time window**: none — the full available history per unit/cycle is used; the x-axis is component
hours, not calendar time.

**Empty/error handling**: `render_accumulated_section()` wraps the whole build in try/except and
renders `_empty_state(message)` for any exception, an empty result (no crossable hours), or
`fig is None` (insufficient curve support for the band). `_render_component_overview` additionally
wraps this whole block in its own try/except, so a curve failure "nunca rompe el overview" — it
just falls back to the classic hero and omits the curve section entirely.

**Relationship to the priority cards**: both read from the same `df`/`df_latest` loaded once by
`_load_component_data()`, but are computed and ordered independently — the curve groups by
unit/cycle over component hours, the cards sort by `avg_ranking_30d` descending (see below). There
is no shared calculation between them.

**Client access restrictions**: gated the same as the rest of the Predictive module by
`predictive_allowed_clients` (`config/settings.py`). `component_hours_allowed_clients` gates
*only* the horómetro text shown on priority cards/unit banner — it does not gate the curve, which
depends solely on whether `cleaned_component_hours.parquet` exists for the client.

---

## 📊 Pages and Visualizations

### Resumen (Overview)

| Element | Description |
|---------|--------------|
| **Hero KPIs** | Fleet avg ranking, count Crítica/Alerta/Saludable (or, when the accumulated curve builds successfully, replaced by zone counts Normal/Alerta/Anormal — see [Curva Acumulada de Riesgo](#curva-acumulada-de-riesgo) above) |
| **Curva Acumulada** | Cumulative-risk curve per unit/cycle vs. a fleet reference band; see [Curva Acumulada de Riesgo](#curva-acumulada-de-riesgo) above |
| **Priority cards** | One per unit, sorted by `avg_ranking_30d` desc; shows score, delta vs. previous date, top-3 failure-mode drivers as bars, and horómetro (if enabled for the client) |
| **Failure-mode table** | Unit × (Hoy/30d/60d/90d ranking + one column per failure mode), sortable via a period dropdown (`predictive-fm-sort-selector`) |

### Evidencia (Evidence), scoped to a selected unit + failure mode

| Element | Function | Chart/component |
|---------|----------|------------------|
| Unit banner | Ranking, status, horómetro | `update_unit_banner` |
| Condition KPIs | Ranking actual, riesgo acum. 90d, horas de componente, modo dominante, última evidencia | `render_initial_content` |
| Fleet scatter | Ranking actual (x) vs. ranking 90d (y), quadrant-labeled, selected unit highlighted | `create_fleet_scatter` |
| Comparative bars | Unit vs. fleet-average score, one bar pair per failure mode | `create_comparative_bars` |
| AI insight panel | Methodology + score interpretation + generated observations | `_build_insight_panel` |
| Oil evidence | Time series (max of 90 days or last 3 real samples) + variables table | `create_oil_timeseries_90d`, `create_oil_variables_table` |
| Telemetry evidence | Stacked alert/critic rate bars, one chart per associated signal | `create_telemetry_signal_chart` |

**Fleet scatter quadrants** (dividers at ranking=80 and the fleet's 30d-P80): Crítica sostenida,
Empeoró de golpe, Mejoró recientemente, Zona saludable.

---

## 🤖 AI Insight Engine

Despite the name, the "Análisis Inteligente" panel is a **deterministic, rule-based** text
generator (`tab_predictive_evidence.py`) — not an LLM call. For the selected unit + failure mode:

**Oil observations** (`_analyze_oil_observations`), per associated oil variable:
- Threshold check vs. `OIL_THRESHOLDS[var][oilHourRange]` → 🔴 critical / 🟡 warning / 🟢 normal
- Trend: % change between first and last of the last 5 real samples; flagged if `> +25%` (⬆️
  warning) or `< -25%` (⬇️ ok)
- Fleet comparison: flagged if current value is `> 40%` above the fleet mean for that variable

**Telemetry observations** (`_analyze_telemetry_observations`), per associated signal, over a
90-day window:
- 🔴 critical if avg `critic_rate > 15%`; 🟡 warning if `> 5%`
- ⚡ critical "recent spike" if last-7-day critic rate is `> 2×` the prior period's (both must
  exceed minimum thresholds to avoid noise on near-zero rates)
- 🔔 warning if avg `alert_rate > 20%`
- ✅ ok if combined alert+critic rate `< 2%`

**Fleet-percentile check**: if the failure mode's own score exceeds the fleet's 80th percentile
(and is `> 10`), an extra "above P80" warning is prepended.

Observations are sorted critical → warning → ok before rendering; if none fire, a default "no
significant anomalies" message is shown.

---

## 🔄 Callback Flow

```
predictive_callbacks.py :: register_callbacks(app)

switch_internal_tab            (Input: internal Resumen/Evidencia tab)
  ├─ Resumen  → _render_component_overview()
  └─ Evidencia → renders the interactive shell (unit selector, FM selector, empty content divs)

sort_failure_mode_table        (Input: period dropdown)      → re-renders _failure_table()
update_unit_banner             (Input: unit dropdown)        → banner with ranking/status/horómetro
update_initial_content         (Input: unit dropdown)        → render_initial_content() (KPIs + scatter + bars)
set_default_failure_mode       (Input: unit dropdown)        → picks the FM with the highest 30d score
update_detailed_evidence       (Input: unit + FM dropdowns)  → render_detailed_evidence() (AI insight + oil + telemetry)
update_oil_chart               (Input: oil-variable multi-select) → re-renders create_oil_timeseries_90d()
```

`client` and `component` are threaded through as `dcc.Store` values
(`predictive-ev-client-store`, `predictive-ev-component-store`), set once when the evidence shell
is rendered, and read as `State` by every downstream callback.

---

## 📁 Relevant Files

| File | Responsibility |
|------|-----------------|
| `dashboard/components/predictive_config.py` | Failure-mode config, oil thresholds, methodology text |
| `dashboard/components/predictive_charts.py` | Plotly figures |
| `dashboard/components/predictive_tables.py` | Oil variables HTML table |
| `dashboard/components/predictive_kpis.py` | KPI card components |
| `dashboard/components/accumulated_curve.py` | Curva Acumulada de Riesgo: build, reference band, zone classification |
| `dashboard/tabs/tab_predictive_component.py` | Unified per-component layout with internal tabs |
| `dashboard/tabs/tab_predictive_overview.py` | Resumen tab: load/classify/render |
| `dashboard/tabs/tab_predictive_evidence.py` | Evidencia tab: load/render + insight engine |
| `dashboard/callbacks/predictive_callbacks.py` | Interactivity |
| `config/settings.py` | `predictive_allowed_clients`, `component_hours_allowed_clients` |
| `src/data/loaders.py` | `load_component_hours` / `get_latest_component_hours` |
| `data/predictive/golden/{client}/{component}.csv` | Input data (see [data_contracts.md](data_contracts.md)) |

---

## 📚 Related Documentation

- [Data Contracts](data_contracts.md) — full column schema of the predictive golden CSVs
- [Codebase Explainer](../codebase_explaining.md) — repo-wide orientation (data mesh, nav gating, conventions)
- [General Dashboard Overview](../general/dashboard_overview.md) — how Predictivo fits into the whole app
- [Oil Data Contracts](../oil/oil_data_contracts.md) — `cleaned_component_hours.parquet` schema (horómetro source)
