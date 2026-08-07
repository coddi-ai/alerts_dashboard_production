# Dashboard Proposal — Fleet Health Telemetry Monitor

**Author**: Patricio Ortiz  
**Version**: 2.0  
**Date**: June 2026  
**Tech Stack**: Dash + Plotly (Python)

> **Status note (2026-08-07)**: everything below "Objective" through "Future Enhancements" is
> the **original design proposal**, kept for its design rationale (the two-question framing,
> color system, drill-down philosophy still hold). It does **not** match the shipped code in
> several concrete ways — page structure, file layout, and some interactivity. Read
> **[As Built](#as-built-2026-08)** below first for what's actually true today; treat the rest of
> this file as historical intent, not a spec of current behavior. If something here contradicts
> the code, trust the code.

---

## As Built (2026-08)

### Real file map

The proposal's `dashboard/pages/` + `components/data_loader.py` layout was never built. The
actual structure follows this repo's standard tabs/callbacks/components convention (see
[documentation/codebase_explaining.md](../codebase_explaining.md#4-dashboard--the-app-itself)):

| File | Role |
|---|---|
| `dashboard/tabs/tab_telemetry.py` | Outer shell — header + internal `dcc.Tabs` ('Vista de Flota' / 'Detalle de Unidad') |
| `dashboard/tabs/tab_telemetry_fleet.py` | Layout only for the fleet overview page (filters + table container) |
| `dashboard/tabs/tab_telemetry_unit_detail.py` | Layout only for the unit drill-down page (unit/system/signal selectors + table containers) |
| `dashboard/callbacks/telemetry_callbacks.py` | All interactivity, including the fleet table's `dash_table.DataTable` spec itself (`_fleet_status_table`) |
| `dashboard/components/telemetry_report.py` | `TelemetrySnapshot` view-model — loads golden-layer outputs via `src/data/loaders.py` and joins/orders them for display only, no recomputation |
| `dashboard/components/telemetry_charts.py` | Plotly figure builders (fleet heatmap, signal time series), Spanish translation maps, `STATUS_COLORS` |
| `dashboard/components/telemetry_tables.py` | **Dead code** — `build_fleet_priority_table`, `build_system_risk_table`, `build_signal_overview_table`, `build_signal_kpi` are not imported anywhere; superseded by `telemetry_report.py` and inline builders in `telemetry_callbacks.py` |

### Vista de Flota (Page 1) — what's actually there

The live page is filters (equipment model, status, visible systems) plus **one**
`dash_table.DataTable` (`telemetry-fleet-status-table`, built by `_fleet_status_table` in
`telemetry_callbacks.py`): columns Unidad / Modelo / one column per visible system / Estado, rows
sorted server-side by severity then `priority_score`. There is no donut chart, no separate
heatmap graphic, no separate priority table, and no separate AI-assessment table on this page —
the mockup below overstates what's rendered.

`update_fleet_overview` (the callback behind this table) does still contain code that builds KPI
cards, a `build_fleet_heatmap` Plotly figure, and an insights row — but it hits
`return _fleet_status_table(rows, visible)` before that code executes, so none of it renders.
This is dead code, not a toggleable feature — don't build on top of it without first wiring it
into the actual return path.

**Interactivity that is live**: clicking a system-column cell (`active_cell`) navigates straight
to "Detalle de Unidad" with that unit + system pre-selected (`navigate_from_fleet`). Sorting is
native (client-side); there is no filter box on this table (matching Aceite's equivalent table,
which also has no filter). No row-selection checkboxes — Telemetría has no inline detail panel on
this page for a checkbox to drive, unlike Aceite's Fleet Overview.

**Visual styling (as of REQ-TE-01, 2026-08-07)**: this table's header color, cell padding/font
size, status color palette, tooltip CSS, and page size were aligned to match Aceite's equivalent
fleet-heatmap table (`dashboard/callbacks/machines_callbacks.py::update_fleet_heatmap_table`) so
the two "general tables" read as one system. See `_SYSTEM_STATUS_BG/_FG` and
`_OVERALL_STATUS_BG/_FG` in `telemetry_callbacks.py`, mirrored from Oil's `_STATUS_BG/_FG` and
`_MACHINE_STATUS_BG/_FG`. Interactivity was deliberately **not** touched — Telemetría's
click-to-navigate stayed as-is rather than being replaced with Aceite's checkbox row-selection,
since there's no inline detail panel here to drive with it.

### Detalle de Unidad (Page 2) — what's actually there

Broadly matches the proposal's drill-down intent (unit → system → signal, AI text at every
level), with one notable difference: **only one signal's evidence card renders at a time** (the
one currently selected in the signal table/selector), not a stacked list of cards for every
signal in the system as the mockup shows. The actual flow is:

1. Unit selector → unit-level AI decision-summary card (`_decision_summary`)
2. System status table (row-selectable) → selected-system AI analysis card (`_system_analysis_card`)
3. Signal table (row-selectable, scoped to the selected system)
4. One signal-evidence card for the selected signal: time series (`build_signal_timeseries_card`,
   with rolling mean, P2/P5/P95/P98 baseline lines, trend overlay, and materialized event/anomaly
   shading) + a KPI table, side by side

These tables (`telemetry-detail-system-table`, `telemetry-detail-signal-table`) still use the
original telemetry header color (`#34495e`) and padding — REQ-TE-01 only touched the fleet
overview table, not this page.

### Data loading — what's actually true

No 5-minute polling cache and no `dcc.Interval` exists anywhere in the telemetry tab. Instead,
`load_telemetry_snapshot` (in `telemetry_report.py`) keys an `lru_cache`-backed `TelemetrySnapshot`
off the upstream pipeline's own evaluation identity (`evaluation_year`/`evaluation_week`/
`execution_timestamp`/`baseline_version` from `data/telemetry/golden/{client}/latest.json`) — the
UI picks up a new evaluation automatically the next time any callback fires after the pipeline
publishes one, with no timer involved. Detail-only artifacts (deviation, trends, limits, signal
comments) are loaded lazily via `include_detail=True` only once a unit is opened; the event
parquet (the largest artifact) is lazier still, loaded per unit+signal only when a signal chart
is requested (`_events_for_signal_cached`).

Real golden-layer paths (via `src/data/loaders.py`), for reference against the "AI Comments
Integration" section below (which is directionally correct but not path-exact):
`data/telemetry/golden/{client}/{unit_health,system_health}/`,
`.../{deviation_summary,technique_results/deviation}`,
`.../{event_results,technique_results/events}`, `.../{trend_results,technique_results/trend}`,
`.../latest.json` (manifest), plus AI comments via `load_telemetry_ai_comments(client, level)`.
Spanish translation/registry config lives at `data/telemetry/config/{client}/signal_registry.yaml`
and `equipment_registry.yaml` — not part of the original proposal at all.

---

## Objective

Provide maintenance teams with a **fleet health monitoring dashboard** that answers two fundamental questions:

1. **Fleet Overview**: "How is my fleet behaving currently?"
2. **Unit Detail**: "What data backs the conclusions we are presenting?"

### Design Philosophy

- **Simplify for non-technical users** — Minimize statistical jargon, show clear risk levels and actionable insights
- **AI-explained** — LLM-generated natural language assessments at every level
- **Evidence-driven** — Every conclusion can be traced to specific signals and patterns
- **Progressive disclosure** — Overview first, then drill-down on demand

---

## Page 1: Fleet Overview

**Question answered**: *"How is my fleet behaving currently?"*

### Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  🏭 Fleet Health Monitor              [Last updated: 2026-06-10]     │
├─────────────────────┬────────────────────────────────────────────────┤
│                     │                                                 │
│  [Fleet Status      │  [System Health Heatmap]                        │
│   Donut Chart]      │  Units (rows) × Systems (cols)                  │
│                     │  Color: green → orange → red (0–100)            │
│  Normal: 5          │  Sorted by priority (worst at top)              │
│  Alerta: 5          │                                                 │
│  Anormal: 0         │                                                 │
│                     │                                                 │
├─────────────────────┴────────────────────────────────────────────────┤
│                                                                       │
│  [Unit Priority Table]                                                │
│  ┌──────┬────────┬──────────┬───────┬─────────────┬─────────────────┐│
│  │ Unit │ Status │ Priority │ Score │ Anormal Sys │ Top Risk        ││
│  ├──────┼────────┼──────────┼───────┼─────────────┼─────────────────┤│
│  │ T_12 │ Alerta │ 87.8     │ 27.8  │ 1           │ Trans, Engine   ││
│  │ T_13 │ Alerta │ 79.3     │ 19.3  │ 1           │ Trans, Engine   ││
│  │ ...  │        │          │       │             │                 ││
│  └──────┴────────┴──────────┴───────┴─────────────┴─────────────────┘│
│                                                                       │
├───────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  [AI Assessment Table]                                                │
│  ┌──────┬────────┬──────────────────────────────────────────────────┐│
│  │ Unit │ Status │ AI Assessment                                    ││
│  ├──────┼────────┼──────────────────────────────────────────────────┤│
│  │ T_12 │ Alerta │ Transmission showing worsening lockup slip       ││
│  │      │        │ (+0.83/day). Engine turbo pressures drifting.     ││
│  │      │        │ Schedule inspection within 48h.                   ││
│  │ T_24 │ Normal │ Operating within normal parameters.              ││
│  └──────┴────────┴──────────────────────────────────────────────────┘│
│                                                                       │
└───────────────────────────────────────────────────────────────────────┘
```

### Figures

| ID | Widget | Type | Data Source | Purpose |
|----|--------|------|-------------|---------|
| F1 | Fleet Status | Donut Chart | `unit_health.overall_status` | At-a-glance fleet distribution |
| F2 | System Heatmap | Heatmap | `system_health` (pivot) | Spot which unit+system combinations are risky |
| F3 | Priority Table | Data Table | `unit_health` (sorted) | Ranked list for action prioritization |
| F4 | AI Assessment | Data Table | `ai_comments/unit_comments.parquet` | Human-readable diagnosis per unit (from AI Diagnosis step) |

### Interactivity

- Click unit row → navigates to Page 2 (Unit Detail)
- Heatmap cells are clickable → navigate to Unit Detail with system pre-selected
- Auto-refresh every 5 minutes

---

## Page 2: Unit Detail

**Question answered**: *"What data backs the conclusions we are presenting?"*

### Layout

```
┌──────────────────────────────────────────────────────────────────────┐
│  [Filter: Unit ▼ T_12]                                               │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  [AI Comment on Unit]                                                 │
│  Source: ai_comments/unit_comments.parquet (unit-level diagnosis)      │
│  "T_12 shows elevated risk in Transmission (lockup slip trending     │
│   +0.83/day, R²=0.56) and Engine (turbo outlet pressure drifting).   │
│   Recommend transmission inspection within 48 hours."                 │
│                                                                       │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  [System Risk Table — sorted by risk]                                 │
│  ┌──────────────┬────────────┬────────┬──────────────────────┐       │
│  │ System       │ Risk Score │ Status │ Techniques Triggered │       │
│  ├──────────────┼────────────┼────────┼──────────────────────┤       │
│  │ Transmission │ 67.5       │ Alerta │ 3                    │       │
│  │ Engine       │ 43.8       │Anormal │ 2                    │       │
│  │ Brakes       │ 0.0        │ Normal │ 0                    │       │
│  │ Steering     │ 0.0        │ Normal │ 0                    │       │
│  └──────────────┴────────────┴────────┴──────────────────────┘       │
│                                                                       │
├──────────────────────────────────────────────────────────────────────┤
│  [Filter: System ▼ Transmission]                                      │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  [Signal Overview Table — sorted by risk]                             │
│  ┌──────────────┬───────┬────────┬──────────┬───────┬───────────────┐│
│  │ Signal       │ Risk  │ Status │ Abnorm % │Events │ Max Episode   ││
│  ├──────────────┼───────┼────────┼──────────┼───────┼───────────────┤│
│  │ DiffTemp     │ 78.0  │Anormal │ 12.3%    │ 3290  │ 415 min       ││
│  │ LckupSlip    │ 45.2  │ Alerta │ 5.8%     │ 1200  │ 89 min        ││
│  │ TrnSlip      │ 38.1  │ Normal │ 4.1%     │ 9510  │ 191 min       ││
│  │ ...          │       │        │          │       │               ││
│  └──────────────┴───────┴────────┴──────────┴───────┴───────────────┘│
│                                                                       │
├──────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  === Signal: DiffTemp (Differential Temperature) ===                  │
│  ┌────────────────────────────────────┬──────────────────────────────┐│
│  │                                    │  Metric          │ Value     ││
│  │  [Time Series Plot]                │  ─────────────── │ ───────── ││
│  │  • Blue line: 30-min rolling mean  │  Total Events    │ 3,290     ││
│  │  • Orange dash: P95 limit          │  Warnings        │ 693       ││
│  │  • Red dash: P99 limit             │  Longest Episode │ 415 min   ││
│  │  • Dotted: Trend regression line   │  Trend Detected  │ Yes       ││
│  │                                    │  Trend Direction │ Worsening ││
│  │                                    │  Trend Formula   │+0.12/day  ││
│  │                                    │                  │(R²=0.61)  ││
│  └────────────────────────────────────┴──────────────────────────────┘│
│                                                                       │
│  === Signal: LckupSlip (Lockup Slip) ===                              │
│  ┌────────────────────────────────────┬──────────────────────────────┐│
│  │  [Time Series Plot]                │  [KPI Table]                 ││
│  │  ...                               │  ...                         ││
│  └────────────────────────────────────┴──────────────────────────────┘│
│                                                                       │
│  (repeated for each signal in system, sorted by risk)                 │
│                                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

### Signal Time Series Plot Specification

Each signal plot contains:

| Element | Visual | Source |
|---------|--------|--------|
| Rolling mean (30 min) | Solid blue line | Raw telemetry (Silver layer) |
| P95/P99 upper limit | Dashed orange/red horizontal line | Baseline parquet |
| P5/P1 lower limit | Dashed orange/red horizontal line | Baseline (for `risk_direction: low/both`) |
| Trend regression | Dotted line (red=worsening, green=improving) | Trend analysis results |

### Signal KPI Table Specification

| Metric | Source | Description |
|--------|--------|-------------|
| Total Events | `events` (count per signal) | Number of non-normal episodes |
| Warnings | `events` (event_type_weighted == 'warning') | High-severity events |
| Longest Episode | `events` (max duration_minutes) | Worst continuous abnormal period |
| Trend Detected | `trends` (is_significant & is_good_fit) | Yes/No |
| Trend Direction | `trends.trend_interpretation` | Worsening / Improving / Drifting |
| Trend Formula | `trends` (slope + R²) | e.g., "+0.83/day (R²=0.56)" |

### Interactivity

- Unit dropdown → updates all sections below
- System dropdown → updates signal table and per-signal detail cards
- Hover on time series → shows exact value, timestamp, and state
- Signals sorted by risk score (worst first, most important at top)

---

## AI Comments Integration

The dashboard consumes structured AI diagnostic comments produced by the **AI Diagnosis** pipeline step. These comments are stored independently from health records and accessed by level.

### Data Source

```
data/telemetry/golden/{client}/ai_comments/year={YYYY}/week={WW}/
├── signal_comments.parquet   → Per-signal diagnostics
├── system_comments.parquet   → Per-system diagnostics  
└── unit_comments.parquet     → Per-unit executive diagnostics
```

### Where AI Comments Appear

| Page | Location | Comment Level | Source File |
|------|----------|---------------|-------------|
| Page 1 | AI Assessment Table (F4) | Unit | `unit_comments.parquet` |
| Page 2 | Unit header section | Unit | `unit_comments.parquet` |
| Page 2 | System Risk Table (expandable row) | System | `system_comments.parquet` |
| Page 2 | Signal detail cards (above time series) | Signal | `signal_comments.parquet` |

### Loading Pattern

```python
@lru_cache(maxsize=1)
def load_ai_comments(cache_key):
    """Load AI diagnostic comments from golden layer."""
    base = Path('data/telemetry/golden/cda/ai_comments')
    latest = sorted(base.glob('year=*/week=*/'))[-1] if list(base.glob('year=*/')) else None
    if not latest:
        return {'signal': pd.DataFrame(), 'system': pd.DataFrame(), 'unit': pd.DataFrame()}
    return {
        'signal': pd.read_parquet(latest / 'signal_comments.parquet') if (latest / 'signal_comments.parquet').exists() else pd.DataFrame(),
        'system': pd.read_parquet(latest / 'system_comments.parquet') if (latest / 'system_comments.parquet').exists() else pd.DataFrame(),
        'unit': pd.read_parquet(latest / 'unit_comments.parquet') if (latest / 'unit_comments.parquet').exists() else pd.DataFrame(),
    }
```

### Display Rules

- If no AI comment exists for an entity (Normal status), show "Operando dentro de parámetros normales."
- All AI text (`description`, `explaining`, `recommended_action`) is in **Spanish**
- `description` is shown as a headline/summary; `explaining` is shown expanded or on-demand
- Unit comments include an `urgency` field → used to style the comment card (green/orange/red border)
- System and unit comments include `recommended_action` → shown as a callout below the diagnostic text
- Signal comments show `description` inline above the time series plot; `explaining` available on expand

---

## Color System

| Status/Element | Color | Hex |
|----------------|-------|-----|
| Normal / Healthy | Green | `#2ecc71` |
| Alerta / Warning | Orange | `#f39c12` |
| Anormal / Critical | Red | `#e74c3c` |
| InsufficientData | Gray | `#95a5a6` |
| Time series line | Dark blue | `#2c3e50` |
| Trend worsening | Red dotted | `#e74c3c` |
| Trend improving | Green dotted | `#2ecc71` |
| P95 limit | Orange dashed | `#f39c12` |
| P99 limit | Red dashed | `#e74c3c` |

---

## Implementation Architecture

> Historical design sketch — the code below was never built this way. See
> **[As Built](#as-built-2026-08)** at the top of this file for the real file map, data loading,
> and callback structure.

### App Structure

```
dashboard/
├── app.py                  # Dash app initialization
├── pages/
│   ├── fleet_overview.py   # Page 1: Fleet status + AI summaries
│   └── unit_detail.py      # Page 2: Drill-down with signal cards
├── components/
│   ├── data_loader.py      # Cached Parquet + Silver data loading
│   ├── signal_card.py      # Reusable: time series + KPI table per signal
│   └── styles.py           # Color maps and layout constants
└── assets/
    └── style.css           # Custom CSS
```

### Data Loading

```python
from functools import lru_cache
import time

REFRESH_INTERVAL = 300  # 5 minutes

@lru_cache(maxsize=1)
def load_golden_data(cache_key):
    """Load all golden layer data. cache_key forces refresh."""
    base = Path('data/telemetry/golden/cda')
    return {
        'unit_health': pd.read_parquet(base / 'unit_health'),
        'system_health': pd.read_parquet(base / 'system_health'),
        'deviation': pd.read_parquet(base / 'technique_results/deviation'),
        'events': pd.read_parquet(base / 'technique_results/events'),
        'trends': pd.read_parquet(base / 'technique_results/trend'),
    }

@lru_cache(maxsize=4)
def load_raw_telemetry(unit, weeks=4):
    """Load recent raw telemetry for time series plots."""
    files = sorted(SILVER_PATH.glob('*.parquet'))[-weeks:]
    df = pd.concat([pd.read_parquet(f) for f in files])
    return df[df['Unit'] == unit]

def get_data():
    cache_key = int(time.time() // REFRESH_INTERVAL)
    return load_golden_data(cache_key)
```

### Key Callbacks

```python
# Page 2: Unit selection updates everything
@app.callback(
    [Output('unit-comment', 'children'),
     Output('system-table', 'figure'),
     Output('system-dropdown', 'options')],
    Input('unit-dropdown', 'value')
)
def update_unit_section(unit):
    data = get_data()
    # Build AI comment, system table, and system dropdown options
    ...

# Page 2: System selection updates signal cards
@app.callback(
    Output('signal-cards-container', 'children'),
    [Input('unit-dropdown', 'value'),
     Input('system-dropdown', 'value')]
)
def update_signal_cards(unit, system):
    data = get_data()
    # For each signal in system (sorted by risk):
    #   Create signal_card component (time series + KPI table)
    ...
```

### Signal Card Component

```python
def create_signal_card(unit, signal, signal_meta, raw_data, baseline, events, trends):
    """Create a Dash component with time series + KPI table for one signal."""
    
    # Left: Plotly figure with rolling mean + limits + trend
    fig = make_subplots(rows=1, cols=2, column_widths=[0.7, 0.3],
                        specs=[[{'type': 'scatter'}, {'type': 'table'}]])
    
    # ... (see notebook for implementation)
    
    return dcc.Graph(figure=fig)
```

---

## Technical Decisions

| Decision | Rationale |
|----------|-----------|
| **2 pages only** | Simpler navigation, answers exactly 2 questions |
| **Tables over complex charts** | Non-technical users understand tables immediately |
| **Rolling mean, not raw points** | Smoothed view is clearer; raw data is noisy at 1-min resolution |
| **Sorted by risk everywhere** | Most important information always at the top |
| **AI explanations prominent** | Reduces need to interpret numbers; actionable text |
| **Signal cards (plot + KPIs)** | Self-contained evidence per signal; no context-switching |
| **Limit lines from baselines** | Visual reference — user sees where "normal" ends |
| **Trend line overlay** | Shows direction without needing statistical knowledge |

---

## Deployment

| Option | Complexity | Use Case |
|--------|------------|----------|
| `python app.py` (local) | Minimal | POC / development |
| Docker container | Low | Portable team sharing |
| Azure Container Apps | Medium | Production with SSO |

---

## Future Enhancements

1. **Historical comparison** — Toggle between current and previous week's assessment
2. **Maintenance overlay** — Show when maintenance was performed on timelines
3. **Alert notifications** — Status changes trigger email/Teams alerts
4. **Export** — PDF report generation for weekly maintenance meetings
5. **Multi-client** — Client selector for multiple mining sites

---
