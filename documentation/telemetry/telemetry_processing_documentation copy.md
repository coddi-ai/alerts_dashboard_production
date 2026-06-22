# Telemetry Health Evaluation Framework — Technical Documentation

**Author**: Patricio Ortiz  
**Version**: 2.0  
**Last Updated**: June 2026  
**Project Phase**: Proof of Concept

---

## Table of Contents

1. [Mission & Vision](#mission--vision)
2. [Architecture Overview](#architecture-overview)
3. [Data Pipeline](#data-pipeline)
4. [Analysis Techniques](#analysis-techniques)
   - [1. Deviation Analysis](#1-deviation-analysis)
   - [2. Event Analysis](#2-event-analysis)
   - [3. Trend Analysis](#3-trend-analysis)
   - [4. Distribution Shift Analysis](#4-distribution-shift-analysis)
   - [5. Anomaly Detection (LSTM Autoencoder)](#5-anomaly-detection-lstm-autoencoder)
5. [Multi-Technique Aggregation](#multi-technique-aggregation)
6. [AI Diagnosis](#ai-diagnosis)
7. [LLM Integration (Legacy)](#llm-integration-legacy)
8. [Scoring Methodology](#scoring-methodology)
8. [Baseline Strategy](#baseline-strategy)
9. [Pipeline Orchestration](#pipeline-orchestration)
10. [Operational Guidelines](#operational-guidelines)

---

## Mission & Vision

### What This Framework Does

Transforms **minute-level telemetry from mining equipment** into explainable, confidence-scored health assessments by orchestrating multiple independent analytical techniques operating at their natural time scales.

### Core Philosophy

| Traditional Approach | Our Approach |
|---------------------|--------------|
| Single weekly evaluation cycle | Multiple cadences (6-hourly, daily, weekly) |
| One scoring methodology for all phenomena | Technique-specific methods for different risk types |
| Black-box "anomaly score" | Explainable risk + confidence scoring |
| Dashboard-first design | Analytics-first with future dashboard consumption |

### Value Proposition

1. **Early Detection** — Identify degradation ≥3 days before failure
2. **Explainability** — Every assessment traces to specific signals and observations
3. **Prioritization** — Rank units by maintenance urgency with confidence scores
4. **Flexibility** — Add/remove techniques without redesigning the system
5. **Auditability** — Full traceability from raw data to final assessment

### Scope

**In Scope (POC)**:
- Multi-technique telemetry analytics framework
- Signal → System → Unit health aggregation
- Explainable risk and confidence scoring
- State-specific baseline generation
- Event detection, trend analysis, distribution analysis
- LSTM autoencoder multivariate anomaly detection
- LLM-powered natural language explanations
- Historical backtesting and validation
- Analytical outputs (Parquet/JSON)

**Out of Scope (POC)**:
- Dashboard/UI development
- Real-time streaming analytics
- Maintenance system integration
- Oil analysis or multi-data-source fusion
- Automated alerting workflows
- Diagnostic rules (reserved for future phase)

---

## Architecture Overview

### Medallion Data Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          SILVER LAYER (Input)                             │
│  Cleaned, validated telemetry — minute-level resolution                   │
│  Location: data/telemetry/silver/{client}/                               │
│  Format: Parquet (weekly partitions: Week{WW}Year{YYYY}.parquet)         │
└─────────────────────────────────┬────────────────────────────────────────┘
                                  │
                    ┌─────────────┼─────────────┐
                    │     Processing (src/)      │
                    └─────────────┼─────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         GOLDEN LAYER (Output)                             │
│  Analytical results, health assessments, events, models                   │
│  Location: data/telemetry/golden/{client}/                               │
│  Format: Parquet (technique-specific partitioning by year/week)           │
└──────────────────────────────────────────────────────────────────────────┘
```

### Evaluation Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│                 SIGNAL-LEVEL EVALUATION                      │
│  Each signal evaluated independently by multiple techniques  │
│  Technique-specific risk and confidence scores               │
│  State-matched baseline comparison                           │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                 SYSTEM-LEVEL AGGREGATION                     │
│  Combine techniques within a system (Engine, Brakes, etc.)   │
│  Weight by signal criticality, time-decay, persistence       │
│  Cannot average away critical findings                       │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                  UNIT-LEVEL AGGREGATION                      │
│  Aggregate systems into fleet priority ranking               │
│  Overall status driven by worst critical system              │
│  Generate executive summary via LLM                          │
└─────────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **Technique Independence** — Each technique is an autonomous module with its own cadence, window, and scoring
2. **Risk + Confidence Separation** — Every assessment produces both severity and reliability scores
3. **Explainability First** — If you can't explain a score, don't generate it
4. **State-Specific Baselines** — Compare values against the correct operational state
5. **Configuration-Driven** — All parameters tunable via YAML without code changes
6. **Fail-Safe** — Partial failures don't corrupt outputs or block other units

---

## Data Pipeline

### Input: Silver Telemetry

**Structure**: One row per (Unit, Timestamp) — 1-minute resolution.

```
Unit   | Fecha                  | Estado       | EngCoolTemp | EngOilPres | EngSpd  | ...
T_09   | 2026-06-03 06:43:00   | Operacional  | 68.7        | 412.8      | 1820.0  | ...
```

**Operational States**: `Operacional`, `Ralenti`, `Apagada`, `ND`

**File Pattern**: `Week{WW}Year{YYYY}.parquet` (~100K rows per file, ~11 units)

### Configuration

| File | Purpose |
|------|---------|
| `signal_registry.yaml` | Signal metadata (system, risk_direction, criticality, thresholds) |
| `equipment_registry.yaml` | Unit → model mapping (789C, 789D, silencer variants) |
| `analysis_config.yaml` | Tunable analysis parameters (optional, defaults in code) |

### Preprocessing

1. **Load** weekly parquet files (configurable date range)
2. **Validate** schema (required columns, timestamp ordering, missing rates)
3. **Compute model_specification** — maps units to `"{model}"` or `"{model}_with_silencer"`
4. **Drop unmapped units** — units not in equipment_registry are excluded

---

## Analysis Techniques

### 1. Deviation Analysis

**Purpose**: Detect when signals repeatedly exceed state-specific statistical normal ranges.

**Cadence**: Daily | **Lookback**: 24 hours

#### Methodology

1. Compute percentiles (P1–P99) per `model_specification × state × signal` from historical data
2. Map risk direction to thresholds:

| Risk Direction | Alert | Anormal | Critical |
|----------------|-------|---------|----------|
| `high` | P95 | P98 | P99 |
| `low` | P5 | P2 | P1 |
| `both` | [P5, P95] | [P2, P98] | [P1, P99] |

3. Classify each minute: `normal → alert → anormal → critical`
4. Compute summary metrics: `abnormal_pct`, `alert_pct`, `critical_pct`, `max_deviation`

#### Risk Score

```python
risk_score = min(abnormal_pct * 6, 100)  # 10% abnormal → 60
if critical_pct > 0:
    risk_score = min(risk_score * 1.3, 100)  # Boost for severe excursions
```

#### Requirements
- ≥10 unique values per (model, state, signal) for valid percentile computation
- ≥12 weeks of historical data for stable baseline estimates

#### Limits Persistence

Computed limits (the percentile-based thresholds per model_specification/state/signal) are **persisted to the Silver layer** at `data/telemetry/silver/{client}/limits/limits_{YYYYMMDD}.parquet`. This ensures:
- **Auditability**: Which thresholds were active when a deviation was flagged
- **Reproducibility**: Re-run event analysis without recomputing limits
- **Downstream consumption**: Other tools/dashboards can reference the exact thresholds used

Limits are recomputed and persisted on each pipeline execution. Previous versions are retained for historical traceability.

---

### 2. Event Analysis

**Purpose**: Convert point-level violations into operationally meaningful episodes with duration and severity context.

**Cadence**: Daily (runs after deviation) | **Depends on**: Deviation results

#### Methodology

Groups consecutive non-normal minutes into discrete events (new group when status changes or time gap > 1 minute).

**Two parallel classification approaches:**

| Approach | Metric | Spike | Anomaly | Warning |
|----------|--------|-------|---------|---------|
| **Binary** | Duration (minutes) | < 5 min | 5–30 min | ≥ 30 min |
| **Weighted** | Severity points | < 10 pts | 10–30 pts | ≥ 30 pts |

**Severity weights**: Alert = 1 pt/min, Anormal = 3 pts/min, Critical = 5 pts/min

**Example**: 6-minute event (2 min alert + 2 min anormal + 2 min critical) = `(2×1)+(2×3)+(2×5) = 20 points` → Anomaly (weighted)

#### Why Both Models?
- **Binary**: Simpler to explain, focuses on persistence
- **Weighted**: Better for prioritizing events with high-severity components
- **Recommendation**: Weighted for alerting, binary for trending/reporting

---

### 3. Trend Analysis

**Purpose**: Detect statistically significant progressive degradation over multiple weeks.

**Cadence**: Weekly | **Lookback**: 4, 8, and 12 weeks

#### Methodology

1. Apply **30-minute rolling mean** to smooth noise
2. Fit **linear regression** (`y = mx + b`, X = hours since window start)
3. Evaluate:
   - **p-value < 0.05** — statistically significant
   - **R² > 0.3** — good model fit
   - **Slope direction vs risk_direction** — determines worsening/improving

#### Risk Score (worsening trends only)

```python
magnitude_score = min(abs(delta_pct) * 2, 50)     # 20% delta → 40
persistence_score = min(r_squared * 50, 30)        # R²=0.8 → 24
significance_bonus = 20 if p_value < 0.01 else 0
risk_score = min(magnitude + persistence + significance, 100)
```

#### Interpretation Table

| Risk Direction | Positive Slope | Negative Slope |
|----------------|---------------|----------------|
| `high` | Worsening ⚠️ | Improving ✓ |
| `low` | Improving ✓ | Worsening ⚠️ |
| `both` | Drifting ⚡ | Drifting ⚡ |

#### Example
```
EngCoolTemp (risk_direction: high)
  4-week:  +0.3°C/day, p=0.08, R²=0.25 → Not significant
  8-week:  +0.4°C/day, p=0.02, R²=0.42 → Significant + good fit → WORSENING
  12-week: +0.5°C/day, p=0.001, R²=0.61 → Highly significant → WORSENING

→ Progressive cooling system degradation. Schedule radiator inspection.
```

---

### 4. Distribution Shift Analysis

**Purpose**: Detect changes in the **entire distribution shape** that trend analysis might miss (bimodal shifts, increased variability, intermittent issues).

**Cadence**: Weekly | **Lookback**: 4, 8, 12 weeks vs 1-year baseline

#### Methodology

1. **Test**: Mann-Whitney U (two-tailed, non-parametric)
2. **State Control**: Separate analysis per operational state
3. **Effect Size**: Cohen's d for practical significance

| Effect Size | Cohen's d | Action |
|-------------|-----------|--------|
| Negligible | < 0.2 | No action |
| Small | 0.2–0.5 | Monitor |
| Medium | 0.5–0.8 | Investigate |
| Large | > 0.8 | Immediate attention |

#### When Distribution Analysis Outperforms Trend Analysis
- Bimodal distributions (equipment switching between modes)
- Increased variability without mean change
- Non-linear sudden shifts
- Intermittent extreme values without clear linear trend

#### Minimum Requirements
- Observation period: ≥30 samples
- Baseline period: ≥100 samples
- ~10× more baseline than observation data for robust comparison

---

### 5. Anomaly Detection (LSTM Autoencoder)

**Purpose**: Detect complex **multi-signal pattern anomalies** invisible to single-signal threshold methods.

**Cadence**: Every 6 hours | **Lookback**: 6 hours (360 minutes)

#### Architecture

```
Input (30-min sequences × system features)
    │
    ▼
LSTM Encoder (64 → 32 units)
    │
    ▼
Latent Space (32-dim)
    │
    ▼
LSTM Decoder (32 → 64 units)
    │
    ▼
Reconstructed Output
    │
    ▼
Reconstruction Error → Anomaly Score
```

#### Data Preparation

- **Feature grouping by system** (Engine, Transmission, Brakes, Steering)
- **Categorical encoding**: Estado → one-hot, EngSpd → 300 RPM bins
- **Missing values**: Linear interpolation (numeric), forward-fill (categorical)
- **Quality threshold**: Only sequences with <10% imputed values used

#### Training Strategy

- **Training data**: "Normal" sequences only (identified by Deviation Analysis)
- **Minimum**: 100 sequences per (unit, system) pair
- **Validation**: 20% hold-out with early stopping (patience=10)
- **Inference**: Reconstruction error → percentile rank vs baseline errors

#### Anomaly Score Interpretation

| Percentile | Severity | Action |
|------------|----------|--------|
| 0–70 | Normal | No action |
| 70–90 | Minor | Log for trending |
| 90–95 | Moderate | Investigate if recurring |
| 95–99 | Severe | Immediate investigation |
| >99 | Critical | Urgent attention |

#### When to Use (vs Threshold Methods)
- Multi-signal coordination issues (temperature-pressure-speed relationships)
- Operator misuse patterns (rapid cycling, improper shutdown)
- Early failure signatures before individual thresholds breach
- Novel failure modes not in historical threshold data

---

## Multi-Technique Aggregation

### Purpose

Combine all technique results into a coherent, prioritized fleet view through a three-level hierarchy.

### System-Level Aggregation

Collects recent technique results for all signals within a system (e.g., Engine), respecting validity periods:

| Technique | Validity Period |
|-----------|----------------|
| Autoencoder (6h) | 12 hours |
| Deviation (daily) | 2 days |
| Events (daily) | 2 days |
| Distribution (weekly) | 7 days |
| Trend (weekly) | 4 weeks |

**Aggregation Formula:**
```python
system_score = (
    0.4 * max_recent_critical_score +    # Cannot ignore severe evidence
    0.3 * weighted_mean_score +           # Captures broad patterns
    0.2 * persistence_bonus +             # Multi-technique agreement
    0.1 * trend_penalty                   # Worsening trends add urgency
)
```

**Key rule**: Critical findings cannot be averaged away. If any technique flags `Anormal` on a high-criticality signal, the system score reflects this regardless of other signals being normal.

### Unit-Level Aggregation

**Priority Score:**
```python
priority_score = (
    100 * n_anormal_critical_systems +    # Engine, Brakes, Steering
    50 * n_anormal_other_systems +
    20 * n_alerta_critical_systems +
    10 * n_alerta_other_systems +
    unit_score                            # Average system score
)
```

**Status Logic:**
- **Anormal**: Any critical system is Anormal OR ≥2 systems Anormal
- **Alerta**: Any system is Alerta and none Anormal
- **Normal**: All systems Normal
- **InsufficientData**: Confidence too low across systems

---

## AI Diagnosis

### Purpose

Generate **structured, hierarchical diagnostic comments** by leveraging LLM intelligence against aggregated technique results. This step produces actionable natural language assessments at three levels (Signal → System → Unit), stored independently for dashboard consumption.

Unlike the legacy LLM Integration (which generates ad-hoc explanations attached to health records), AI Diagnosis is a **first-class pipeline step** with its own output schema, storage location, and diagnostic hierarchy.

### Architecture

```
Aggregated Health (system_health + unit_health)
 + Technique Results (deviation, events, trend, distribution, autoencoder)
         │
         ▼
  ┌──────────────────────────────┐
  │     AI Diagnosis Engine      │
  │                              │
  │  Level 1: Signal Diagnosis   │  ← "What is remarkable about this signal?"
  │  Level 2: System Diagnosis   │  ← "What is remarkable about this system?"
  │  Level 3: Unit Diagnosis     │  ← "What is remarkable about this unit?"
  │                              │
  └──────────────┬───────────────┘
                 │
                 ▼
  ┌──────────────────────────────┐
  │   AI Comments (Golden Layer) │
  │   Persisted as Parquet/JSON  │
  └──────────────────────────────┘
```

### Diagnostic Hierarchy

#### Level 1: Signal Diagnosis

**Input**: All technique results for a specific (unit, signal) pair.

**Question answered**: *"Based on the studies, what is remarkable about this signal (if any)?"*

**Prompt context includes**:
- Deviation status, abnormal %, critical %
- Event count, max duration, severity classification
- Trend direction, slope, significance
- Distribution shift magnitude and direction
- Signal metadata (risk_direction, criticality, physical bounds)

**Output**: A structured comment per signal explaining what the combined evidence shows, or `null` if nothing remarkable is detected (Normal across all techniques).

**Skip condition**: All techniques report Normal status for this signal.

#### Level 2: System Diagnosis

**Input**: All signal-level diagnoses within a system + system health score.

**Question answered**: *"Based on the signals status, what is remarkable about this system?"*

**Prompt context includes**:
- System health score and status
- Signal diagnoses (Level 1 outputs) for non-Normal signals
- Number of techniques triggered
- Inter-signal relationships (e.g., temperature + pressure correlations)

**Output**: A synthesis comment explaining the system condition, cross-signal patterns, and recommended actions.

**Skip condition**: System status is Normal and no signals have remarks.

#### Level 3: Unit Diagnosis

**Input**: All system-level diagnoses + unit health metrics.

**Question answered**: *"With all the prior, what is remarkable about this unit?"*

**Prompt context includes**:
- Unit overall status and priority score
- System diagnoses (Level 2 outputs) for non-Normal systems
- Fleet-relative positioning (how this unit compares)
- Maintenance urgency indicators

**Output**: An executive-level assessment summarizing the unit condition, identifying the most critical concern, and recommending next steps.

**Skip condition**: Unit status is Normal.

### Generation Strategy

| Level | When Generated | Cost Control |
|-------|---------------|--------------|
| Signal | Non-Normal signals only | Skip Normal; batch signals by system |
| System | Non-Normal systems only | Use Level 1 outputs as context (no re-analysis) |
| Unit | Non-Normal units only | Use Level 2 outputs as context (no re-analysis) |

### Configuration

```yaml
ai_comments:
  model: str                    # LLM model (default: "gpt-4o-mini")
  temperature: float            # Low for factual (default: 0.2)
  max_tokens_signal: int        # Per-signal token limit (default: 300)
  max_tokens_system: int        # Per-system token limit (default: 500)
  max_tokens_unit: int          # Per-unit token limit (default: 600)
  rate_limit_delay: float       # Seconds between API calls (default: 0.5)
  skip_normal: bool             # Skip all Normal entities (default: true)
  batch_size: int               # Signals per API call for batching (default: 5)
```

### Output Storage

**Location**: `data/telemetry/golden/{client}/ai_comments/year={YYYY}/week={WW}/`

**Files**:
- `signal_comments.parquet` — One row per (unit, signal) with non-Normal diagnosis
- `system_comments.parquet` — One row per (unit, system) with non-Normal diagnosis
- `unit_comments.parquet` — One row per unit with non-Normal diagnosis

### Relationship to Legacy LLM Integration

The legacy `LLM Integration` step (Phase 10) generates inline explanations attached directly to `system_health.explanation` and `unit_health.executive_summary`. The AI Diagnosis step replaces and supersedes this by:

1. Adding **signal-level** granularity (previously absent)
2. Storing comments **independently** (not embedded in health records)
3. Following a **bottom-up** hierarchy (Signal → System → Unit) for consistency
4. Enabling dashboard access to comments **by level** without parsing health records

The legacy LLM fields remain for backward compatibility but are no longer the primary source of AI commentary for the dashboard.

---

## LLM Integration (Legacy)

### Purpose

Transform numerical assessments into **human-readable natural language explanations** that maintenance teams can understand and act upon without interpreting statistical scores.

### Architecture

```
Technique Results + Aggregated Health
         │
         ▼
  Structured Prompt Builder
         │
         ▼
  OpenAI API (gpt-4o-mini, temperature=0.3)
         │
         ▼
  Natural Language Explanation
```

### Configuration

- API key loaded from `.env` file (`OPENAI_API_KEY`)
- Default model: `gpt-4o-mini` (low cost, consistent outputs)
- Temperature: 0.3 (factual, non-speculative)
- Rate limiting: 0.5s between calls

### Generation Strategy

| Level | When Generated | Purpose |
|-------|---------------|---------|
| System explanation | Non-Normal systems only | Technical detail for engineers |
| Unit summary | Non-Normal units only | Executive brief for planning meetings |

### Cost Management
- Skip Normal units entirely
- Use `gpt-4o-mini` for routine (reserve `gpt-4o` for complex multi-system cases)
- Cache unchanged explanations between evaluation cycles

---

## Scoring Methodology

### Risk Score (0–100)

How severe is the evidence of abnormality or degradation?

| Band | Interpretation | Action |
|------|---------------|--------|
| 0–30 | Low / Normal variation | No action required |
| 30–60 | Moderate / Elevated risk | Monitoring recommended |
| 60–80 | High / Significant risk | Inspection recommended |
| 80–100 | Critical / Severe risk | Immediate action required |

### Confidence Score (0–100)

How reliable is this assessment?

**Penalty factors:**
- **Data coverage** < 50% → large penalty
- **Baseline quality** < 500 samples → moderate penalty
- **State mismatch** (using wrong baseline) → 40-point penalty
- **Insufficient samples** (below technique minimum) → 30-point penalty

**Key principle**: Low confidence ≠ low risk. Missing data should not imply a healthy state.

### Status Classification

| Status | Criteria |
|--------|----------|
| **Normal** | risk_score < 40 |
| **Alerta** | 40 ≤ risk_score < 70 |
| **Anormal** | risk_score ≥ 70 |
| **InsufficientData** | confidence_score < 50 |

---

## Baseline Strategy

### Granularity

Baselines computed per: `model_specification × signal × operational_state`

**Why state-specific?** Engine speed at "Operacional" (~1800 RPM) vs "Ralenti" (~600 RPM) vs "Apagada" (~0 RPM) — aggregate baselines would flag normal behavior as abnormal.

### Computation

- **Training window**: 90 days (rolling)
- **Percentiles**: P1, P2, P5, P10, P25, P50, P75, P90, P95, P98, P99
- **Statistics**: mean, std
- **Minimum requirements**: ≥1000 valid samples per state, ≥60 days history

### Versioning & Refresh

| Aspect | Policy |
|--------|--------|
| File format | `baseline_{YYYYMMDD}.parquet` |
| Refresh cadence | Monthly (first Sunday) |
| Window | Rolling 90-day |
| Staleness alert | >45 days old |
| Validation | Flag if P50 shifts >20% between versions |

### Fallback Hierarchy

1. **Model + signal + state** (default POC approach)
2. **Client + signal + state** (fallback if <3 units of model type)
3. **Global + signal + state** (last resort)

### Invalidation Triggers
- Major component replacement (engine overhaul)
- Equipment reconfiguration
- Change in operational profile (new haul route)

---

## Pipeline Orchestration

### Execution Phases

```
Phase 1:  Load configuration + telemetry data
Phase 2:  Preprocess (model specification, validation)
Phase 3:  Load/compute baselines and limits (persist limits to Silver layer)
Phase 4:  Deviation Analysis (produces risk_level columns)
Phase 5:  Event Analysis (depends on Phase 4)
Phase 6:  Trend Analysis (independent)
Phase 7:  Distribution Shift Analysis (independent)
Phase 8:  Autoencoder Inference (depends on Phase 4 for training labels)
Phase 9:  Aggregation (Signal → System → Unit)
Phase 10: AI Diagnosis (Signal → System → Unit comments)
Phase 11: LLM Explanation Generation (legacy, optional)
Phase 12: Persist outputs to Golden layer
```

### Technique Dependencies

```
              Silver Data
                  │
          ┌───────┼───────┐
          ▼       ▼       ▼
    Deviation   Trend   Distribution
          │
          ▼
       Events
          │
          ▼
    Autoencoder (uses normal labels from Deviation)
          │
          ▼
    ┌─────────────┐
    │ Aggregation │ ◄── All technique results
    └──────┬──────┘
           │
           ▼
    ┌──────────────┐
    │ AI Diagnosis │ ◄── Aggregated health + all technique evidence
    │ (Signal →    │
    │  System →    │
    │  Unit)       │
    └──────┬───────┘
           │
           ▼
    ┌─────────────┐
    │ LLM Explain │ ◄── (Legacy, optional)
    └─────────────┘
```

### Execution Cadences

| Component | Cadence | Trigger |
|-----------|---------|---------|
| Baseline Refresh | Monthly | First Sunday of month |
| Deviation + Events | Daily | New day boundary |
| Autoencoder Inference | Every 6 hours | Fixed schedule |
| Trend Analysis | Weekly | End of ISO week |
| Distribution Analysis | Weekly | End of ISO week |
| Aggregation | After each technique run | Technique completion |
| AI Diagnosis | Weekly (or on status change) | Aggregation completion |
| LLM Explanations (legacy) | Weekly (or on status change) | Aggregation completion |

### Output Structure

```
data/telemetry/silver/{client}/
├── Telemetry_Wide_With_States/Week{WW}Year{YYYY}.parquet  (input)
├── baselines/baseline_{YYYYMMDD}.parquet                  (input)
└── limits/limits_{YYYYMMDD}.parquet                       (persisted during Phase 3)

data/telemetry/golden/{client}/
├── technique_results/
│   ├── deviation/year=2026/week=22/deviation_results.parquet
│   ├── events/year=2026/week=22/events.parquet
│   ├── trend/year=2026/week=22/trend_results.parquet
│   ├── distribution/year=2026/week=22/distribution_results.parquet
│   └── autoencoder/year=2026/week=22/autoencoder_results.parquet
├── ai_comments/year=2026/week=22/
│   ├── signal_comments.parquet
│   ├── system_comments.parquet
│   └── unit_comments.parquet
├── system_health/year=2026/week=22/system_health.parquet
├── unit_health/year=2026/week=22/unit_health.parquet
└── models/autoencoder/{unit}_{system}_{version}/
```

---

## Operational Guidelines

### Performance Characteristics

| Technique | Complexity | Key Bottleneck | Optimization |
|-----------|------------|----------------|--------------|
| Deviation | O(n × m × s × f) | Percentile computation | Cache limits, vectorize |
| Events | O(n × u × f) | Grouping logic | NumPy cumsum |
| Trend | O(n × u × f × w) | Linear regression | Parallelize by unit |
| Distribution | O(n log n × u × f × s × w) | Mann-Whitney U | Filter low-data pairs |
| Autoencoder | O(n × u × sys) | Model training | GPU, parallelize units |
| LLM | O(u × sys) | API latency | Batch, cache unchanged |

### Memory Management

- **< 1M rows**: Load entire dataset in memory
- **1–10M rows**: Process in weekly chunks
- **> 10M rows**: Consider Dask/Spark

### Troubleshooting

| Symptom | Likely Cause | Solution |
|---------|-------------|----------|
| No limits computed | <10 unique values per state | Check data availability, verify model mapping |
| Too many spikes | Noisy sensors or tight thresholds | Increase spike threshold, apply hysteresis |
| No significant trends | Equipment in steady-state (normal) | Lower R² threshold for exploratory analysis |
| Distribution skipped | New equipment with <1 year history | Use adaptive baseline (70% of available data) |
| Autoencoder training fails | <100 normal sequences | Need more data or relax quality threshold |
| LLM inconsistent | Temperature too high | Reduce to 0.1–0.2, validate against scores |

### Retention Policy

| Output Type | Retention |
|-------------|-----------|
| Technique results | 1 year |
| System/Unit health | 2 years |
| Events | 1 year |
| Baselines | All versions |
| Models | Last 3 versions |

---

## Related Documentation

- [Data Contracts](data_contracts.md) — Complete schema specifications for all inputs and outputs
- [Programming Rules](programming_rules.md) — Engineering standards and conventions

---
