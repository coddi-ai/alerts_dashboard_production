# Dashboard Proposal — Fleet Health Telemetry Monitor

**Author**: Patricio Ortiz  
**Version**: 2.0  
**Date**: June 2026  
**Tech Stack**: Dash + Plotly (Python)

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
