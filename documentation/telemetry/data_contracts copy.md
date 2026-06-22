# Data Contracts — Telemetry Health Evaluation Framework

**Version**: 1.0.0  
**Last Updated**: June 2026  
**Component**: Data Schemas, Structures & Storage Contracts

---

## Table of Contents

1. [Overview](#overview)
2. [Medallion Architecture](#medallion-architecture)
3. [Input Data (Silver Layer)](#input-data-silver-layer)
4. [Configuration Files](#configuration-files)
5. [Output Data (Golden Layer)](#output-data-golden-layer)
6. [Data Flow Diagram](#data-flow-diagram)
7. [Schema Validation](#schema-validation)
8. [Versioning & Retention](#versioning--retention)

---

## Overview

This document defines all data schemas, file formats, storage paths, and contracts used in the Telemetry Health Evaluation Framework. Following a **medallion architecture**, data flows from Silver (cleaned input) through analytical processing into Golden (health assessments).

### Naming Conventions

- **Files**: `{entity}_{qualifier}.{extension}` (e.g., `baseline_20260225.parquet`)
- **Partitions**: `year=YYYY/week=WW/` or `year=YYYY/month=MM/day=DD/`
- **Timestamps**: ISO 8601 UTC (`2026-06-10T14:30:00Z`)
- **Column names**: `snake_case` for internal data, `PascalCase` preserved from source systems

---

## Medallion Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│                          SILVER LAYER (Input)                             │
│  Cleaned, validated telemetry data from upstream pipeline                 │
│  Location: data/telemetry/silver/{client}/                               │
│  Format: Parquet (weekly partitions)                                      │
│  Responsibility: Data engineering team (external to this framework)       │
└─────────────────────────────────┬────────────────────────────────────────┘
                                  │
                                  ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                         GOLDEN LAYER (Output)                             │
│  Analytical results, health assessments, baselines                        │
│  Location: data/telemetry/golden/{client}/                               │
│  Format: Parquet (technique-specific partitioning)                        │
│  Responsibility: This framework                                           │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Input Data (Silver Layer)

### 1. Telemetry Wide With States

**Purpose**: Primary input — minute-level telemetry readings with operational state classification.

**Location**: `data/telemetry/silver/{client}/Telemetry_Wide_With_States/`

**File Pattern**: `Week{WW}Year{YYYY}.parquet` (e.g., `Week22Year2026.parquet`)

**Schema**:

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `Unit` | string | No | Equipment identifier (e.g., "T_09", "T_15") |
| `Fecha` | datetime64[ns] | No | Timestamp (UTC, 1-minute resolution) |
| `Estado` | string | No | Operational state: "Operacional", "Ralenti", "Apagada", "ND" |
| `EngCoolTemp` | float64 | Yes | Engine coolant temperature (°C) |
| `EngOilPres` | float64 | Yes | Engine oil pressure (kPa) |
| `EngSpd` | float64 | Yes | Engine speed (RPM) |
| `TCOutTemp` | float64 | Yes | Turbocharger outlet temperature (°C) |
| `...` | float64 | Yes | Additional signals per signal_registry |

**Constraints**:
- One row per (Unit, Fecha) pair — no duplicates
- Timestamps sorted ascending within each unit
- Estado values restricted to: `["Operacional", "Ralenti", "Apagada", "ND"]`
- Signal values within physical_min/physical_max from signal_registry (soft constraint)
- Weekly file covers ISO week boundary (Monday 00:00 to Sunday 23:59)

**Data Volume** (typical per file):
- ~10,000 rows per unit per week (10,080 max = 7 days × 24h × 60min)
- ~11 units → ~100,000-110,000 rows per weekly file
- ~20-30 signal columns

**Example**:
```
Unit   | Fecha                    | Estado       | EngCoolTemp | EngOilPres | EngSpd  | ...
T_09   | 2026-06-03 00:00:00     | Apagada      | 28.4        | NaN        | 0.0     | ...
T_09   | 2026-06-03 00:01:00     | Apagada      | 28.3        | NaN        | 0.0     | ...
T_09   | 2026-06-03 06:42:00     | Ralenti      | 42.1        | 385.2      | 620.0   | ...
T_09   | 2026-06-03 06:43:00     | Operacional  | 68.7        | 412.8      | 1820.0  | ...
```

---

### 2. Pre-computed Baselines

**Purpose**: Historical percentile-based reference distributions for threshold comparison.

**Location**: `data/telemetry/silver/{client}/baselines/`

**File Pattern**: `baseline_{YYYYMMDD}.parquet`

**Schema**:

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `model_specification` | string | No | Equipment model variant (e.g., "789C", "789C_with_silencer") |
| `signal` | string | No | Signal name from signal_registry |
| `state` | string | No | Operational state |
| `P1` | float64 | No | 1st percentile |
| `P2` | float64 | No | 2nd percentile |
| `P5` | float64 | No | 5th percentile |
| `P10` | float64 | No | 10th percentile |
| `P25` | float64 | No | 25th percentile |
| `P50` | float64 | No | 50th percentile (median) |
| `P75` | float64 | No | 75th percentile |
| `P90` | float64 | No | 90th percentile |
| `P95` | float64 | No | 95th percentile |
| `P98` | float64 | No | 98th percentile |
| `P99` | float64 | No | 99th percentile |
| `mean` | float64 | No | Arithmetic mean |
| `std` | float64 | No | Standard deviation |
| `sample_count` | int64 | No | Number of valid samples |
| `training_start` | datetime64[ns] | No | Start of training window |
| `training_end` | datetime64[ns] | No | End of training window |

**Metadata File**: `baseline_metadata.json`
```json
{
  "baseline_version": "20260225",
  "created_at": "2026-02-25T15:20:38.559214",
  "evaluation_week": 50,
  "evaluation_year": 2025,
  "lookback_days": 112,
  "total_records": 932,
  "units": 11,
  "signals": 18,
  "state_specific_baselines": 932,
  "aggregate_baselines": 0
}
```

**Refresh Policy**: Monthly (first Sunday of month), rolling 90-day window.

---

### 3. Computed Limits

**Purpose**: Percentile-based thresholds derived from baselines/data, used by Deviation and Event Analysis to classify each telemetry minute into risk levels. Persisted to enable auditability, reproducibility, and downstream consumption without recomputation.

**Location**: `data/telemetry/silver/{client}/limits/`

**File Pattern**: `limits_{YYYYMMDD}.parquet`

**Schema**:

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `model_specification` | string | No | Equipment model variant (e.g., "789C", "789C_with_silencer") |
| `signal` | string | No | Signal name from signal_registry |
| `state` | string | No | Operational state: "Operacional", "Ralenti", "Apagada" |
| `P1` | float64 | No | 1st percentile |
| `P2` | float64 | No | 2nd percentile |
| `P5` | float64 | No | 5th percentile |
| `P10` | float64 | No | 10th percentile |
| `P25` | float64 | No | 25th percentile |
| `P50` | float64 | No | 50th percentile (median) |
| `P75` | float64 | No | 75th percentile |
| `P90` | float64 | No | 90th percentile |
| `P95` | float64 | No | 95th percentile |
| `P98` | float64 | No | 98th percentile |
| `P99` | float64 | No | 99th percentile |
| `sample_count` | int64 | No | Number of valid samples used for computation |
| `computation_date` | date | No | Date when limits were computed |

**Constraints**:
- One row per (model_specification, signal, state) combination
- Only includes entries with ≥ `min_unique_values` (default: 10) unique samples
- Percentile values are rounded to 2 decimal places
- State values restricted to: `["Operacional", "Ralenti", "Apagada"]` (ND excluded)

**Relationship to Baselines**:
- Baselines are the historical reference distributions (external input)
- Limits are the operational thresholds derived from data for classification
- Both co-exist in the silver layer as reference data consumed by downstream techniques

**Refresh Policy**: Recomputed each pipeline execution. Previous versions retained for audit trail.

**Example**:
```
model_specification | signal      | state        | P1    | P2    | P5    | ... | P99   | sample_count | computation_date
789C                | EngCoolTemp | Operacional  | 52.10 | 54.30 | 57.80 | ... | 98.40 | 45230        | 2026-06-10
789C                | EngCoolTemp | Ralenti      | 38.20 | 39.50 | 41.00 | ... | 72.10 | 12840        | 2026-06-10
789C_with_silencer  | EngCoolTemp | Operacional  | 53.40 | 55.60 | 58.90 | ... | 99.20 | 38100        | 2026-06-10
```

---

## Configuration Files

### 1. Signal Registry

**Purpose**: Define signal characteristics, system grouping, risk direction, and processing flags.

**Location**: `data/telemetry/config/{client}/signal_registry.yaml`

**Schema**:
```yaml
version: "1.2"
last_updated: "2026-05-28"

signals:
  - name: str              # Column name in telemetry data (required)
    display_name: str      # Human-readable name (required)
    system: str            # System grouping: "Engine", "Transmission", "Brakes", "Steering" (required)
    subsystem: str         # Subsystem: "Cooling", "Lubrication", etc. (required)
    unit: str              # Measurement unit: "°C", "kPa", "RPM" (required)
    risk_direction: str    # "high", "low", or "both" (required)
    threshold_compute: bool # Whether to include in deviation analysis (required)
    physical_min: float    # Physical lower bound (required)
    physical_max: float    # Physical upper bound (required)
    criticality: int       # 1 (safety-critical) to 3 (monitoring) (required)
    description: str       # Signal description (required)

systems:
  - name: str              # System name matching signals.system (required)
    display_name: str      # Human-readable name (required)
    criticality: int       # 1 (safety-critical) to 3 (monitoring) (required)
    description: str       # System description (required)
```

**Current Systems** (CDA client):
| System | Criticality | Signals Count |
|--------|-------------|---------------|
| Engine | 3 | ~14 signals |
| Transmission | 3 | ~6 signals |
| Brakes | 1 (safety) | 4 signals |
| Steering | 1 (safety) | 1 signal |

### 2. Equipment Registry

**Purpose**: Map unit identifiers to equipment models and hardware configurations.

**Location**: `data/telemetry/config/{client}/equipment_registry.yaml`

**Schema**:
```yaml
version: "1.0"
last_updated: "2024-06-01"

equipments:
  - name: str            # Unit identifier matching telemetry data (required)
    brand: str           # Manufacturer (required)
    model: str           # Model name: "789C", "789D" (required)
    has_silencer: bool   # Silencer hardware presence (required)
```

**Derived Field**: `model_specification` = `"{model}_with_silencer"` if `has_silencer` else `"{model}"`

### 3. Analysis Configuration

**Purpose**: Tunable parameters for all analysis techniques.

**Location**: `data/telemetry/config/{client}/analysis_config.yaml`

**Schema**:
```yaml
deviation_analysis:
  baseline_weeks: int           # Weeks of data for baseline computation (default: 12)
  percentiles: list[int]        # Percentiles to compute (default: [1,2,5,10,25,50,75,90,95,98,99])
  min_unique_values: int        # Minimum unique values for valid percentile (default: 10)

event_analysis:
  binary_thresholds:
    spike_max_minutes: int      # Max duration for spike classification (default: 5)
    anomaly_max_minutes: int    # Max duration for anomaly classification (default: 30)
  weighted_thresholds:
    spike_max_points: int       # Max points for spike (default: 10)
    anomaly_max_points: int     # Max points for anomaly (default: 30)
  severity_weights:
    alert: int                  # Points per minute for alert (default: 1)
    anormal: int                # Points per minute for anormal (default: 3)
    critical: int               # Points per minute for critical (default: 5)

trend_analysis:
  window_weeks: list[int]       # Analysis windows (default: [4, 8, 12])
  rolling_window_minutes: int   # Smoothing window (default: 30)
  p_value_threshold: float      # Significance threshold (default: 0.05)
  r2_threshold: float           # Goodness of fit threshold (default: 0.3)
  min_data_points: int          # Minimum data points (default: 10)

distribution_analysis:
  baseline_weeks: int           # Baseline period (default: 52)
  observation_weeks: list[int]  # Observation windows (default: [4, 8, 12])
  p_value_threshold: float      # Significance threshold (default: 0.05)
  min_baseline_samples: int     # Minimum baseline samples (default: 100)
  min_observation_samples: int  # Minimum observation samples (default: 30)

anomaly_detection:
  sequence_length: int          # LSTM sequence length in minutes (default: 30)
  quality_threshold: float      # Max imputation ratio (default: 0.10)
  encoding_dim: int             # Latent space dimension (default: 32)
  epochs: int                   # Training epochs (default: 50)
  batch_size: int               # Training batch size (default: 32)
  validation_split: float       # Validation fraction (default: 0.2)
  early_stopping_patience: int  # Early stopping patience (default: 10)

aggregation:
  validity_periods:
    autoencoder_hours: int      # AE result validity (default: 12)
    deviation_days: int         # Deviation result validity (default: 2)
    event_days: int             # Event result validity (default: 2)
    distribution_days: int      # Distribution result validity (default: 7)
    trend_weeks: int            # Trend result validity (default: 4)
  system_weights:
    max_critical: float         # Weight for max critical score (default: 0.4)
    weighted_mean: float        # Weight for weighted mean (default: 0.3)
    persistence: float          # Weight for multi-technique agreement (default: 0.2)
    trend: float                # Weight for trend penalty (default: 0.1)
  status_thresholds:
    normal_max: int             # Max score for Normal (default: 40)
    alerta_max: int             # Max score for Alerta (default: 70)

llm:
  model: str                    # OpenAI model (default: "gpt-4o-mini")
  temperature: float            # Generation temperature (default: 0.3)
  max_tokens: int               # Max response tokens (default: 1000)
  rate_limit_delay: float       # Seconds between API calls (default: 0.5)
  skip_normal_units: bool       # Skip LLM for Normal units (default: true)
```

---

## Output Data (Golden Layer)

### 1. Technique Results — Deviation Analysis

**Purpose**: Per-signal, per-day risk classification based on threshold exceedance.

**Location**: `data/telemetry/golden/{client}/technique_results/deviation/year={YYYY}/week={WW}/`

**File Pattern**: `deviation_results.parquet`

**Schema**:

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `unit` | string | No | Equipment identifier |
| `signal` | string | No | Signal name |
| `system` | string | No | System name |
| `state` | string | No | Operational state evaluated |
| `model_specification` | string | No | Equipment model variant |
| `evaluation_date` | date | No | Date of evaluation |
| `risk_score` | float64 | No | Normalized risk (0-100) |
| `confidence_score` | float64 | No | Assessment confidence (0-100) |
| `status` | string | No | "Normal", "Alerta", "Anormal", "InsufficientData" |
| `abnormal_pct` | float64 | No | % of minutes in abnormal zone |
| `alert_pct` | float64 | No | % of minutes in alert zone |
| `critical_pct` | float64 | No | % of minutes in critical zone |
| `max_deviation` | float64 | Yes | Maximum value deviation from limit |
| `total_minutes_evaluated` | int64 | No | Minutes with valid data |
| `baseline_version` | string | No | Baseline file version used |
| `execution_timestamp` | datetime64[ns] | No | When analysis ran |

---

### 2. Technique Results — Event Analysis

**Purpose**: Identified abnormal episodes with duration and severity classification.

**Location**: `data/telemetry/golden/{client}/technique_results/events/year={YYYY}/week={WW}/`

**File Pattern**: `events.parquet`

**Schema**:

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `unit` | string | No | Equipment identifier |
| `signal` | string | No | Signal name |
| `system` | string | No | System name |
| `event_id` | string | No | Unique event identifier |
| `start_time` | datetime64[ns] | No | Event start timestamp |
| `end_time` | datetime64[ns] | No | Event end timestamp |
| `duration_minutes` | int64 | No | Event duration in minutes |
| `total_severity_points` | float64 | No | Weighted severity score |
| `event_type_binary` | string | No | "spike", "anomaly", "warning" |
| `event_type_weighted` | string | No | "spike", "anomaly", "warning" |
| `max_severity` | string | No | Maximum risk level in event |
| `alert_minutes` | int64 | No | Minutes at alert level |
| `anormal_minutes` | int64 | No | Minutes at anormal level |
| `critical_minutes` | int64 | No | Minutes at critical level |
| `execution_timestamp` | datetime64[ns] | No | When analysis ran |

---

### 3. Technique Results — Trend Analysis

**Purpose**: Statistical trend detection over multiple time windows.

**Location**: `data/telemetry/golden/{client}/technique_results/trend/year={YYYY}/week={WW}/`

**File Pattern**: `trend_results.parquet`

**Schema**:

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `unit` | string | No | Equipment identifier |
| `signal` | string | No | Signal name |
| `system` | string | No | System name |
| `window_weeks` | int64 | No | Analysis window (4, 8, or 12) |
| `slope_per_day` | float64 | No | Rate of change per day |
| `r2` | float64 | No | Regression R² score |
| `p_value` | float64 | No | Statistical significance |
| `is_significant` | bool | No | p_value < threshold |
| `is_good_fit` | bool | No | r2 > threshold |
| `risk_direction` | string | No | "high", "low", "both" |
| `trend_interpretation` | string | No | "worsening", "improving", "drifting" |
| `risk_score` | float64 | No | Normalized risk (0-100) |
| `confidence_score` | float64 | No | Assessment confidence (0-100) |
| `status` | string | No | "Normal", "Alerta", "Anormal", "InsufficientData" |
| `data_points` | int64 | No | Number of data points used |
| `start_time` | datetime64[ns] | No | Window start |
| `end_time` | datetime64[ns] | No | Window end |
| `execution_timestamp` | datetime64[ns] | No | When analysis ran |

---

### 4. Technique Results — Distribution Shift

**Purpose**: Statistical distribution comparison between recent and historical data.

**Location**: `data/telemetry/golden/{client}/technique_results/distribution/year={YYYY}/week={WW}/`

**File Pattern**: `distribution_results.parquet`

**Schema**:

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `unit` | string | No | Equipment identifier |
| `signal` | string | No | Signal name |
| `system` | string | No | System name |
| `state` | string | No | Operational state |
| `observation_weeks` | int64 | No | Recent observation window (4, 8, 12) |
| `p_value` | float64 | No | Mann-Whitney U test p-value |
| `cohens_d` | float64 | No | Effect size (Cohen's d) |
| `effect_size_category` | string | No | "negligible", "small", "medium", "large" |
| `is_significant` | bool | No | p_value < 0.05 |
| `baseline_median` | float64 | No | Historical median |
| `observation_median` | float64 | No | Recent median |
| `median_pct_change` | float64 | No | Percentage change in median |
| `shift_interpretation` | string | No | "worsening", "improving", "drifting" |
| `risk_score` | float64 | No | Normalized risk (0-100) |
| `confidence_score` | float64 | No | Assessment confidence (0-100) |
| `status` | string | No | "Normal", "Alerta", "Anormal", "InsufficientData" |
| `baseline_n` | int64 | No | Baseline sample count |
| `observation_n` | int64 | No | Observation sample count |
| `execution_timestamp` | datetime64[ns] | No | When analysis ran |

---

### 5. Technique Results — Autoencoder

**Purpose**: Multivariate anomaly detection using LSTM reconstruction error.

**Location**: `data/telemetry/golden/{client}/technique_results/autoencoder/year={YYYY}/week={WW}/`

**File Pattern**: `autoencoder_results.parquet`

**Schema**:

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `unit` | string | No | Equipment identifier |
| `system` | string | No | System name (model per system) |
| `window_start` | datetime64[ns] | No | 6-hour window start |
| `window_end` | datetime64[ns] | No | 6-hour window end |
| `reconstruction_error` | float64 | No | MSE reconstruction error |
| `z_score` | float64 | No | Error z-score vs baseline |
| `percentile_score` | float64 | No | Percentile rank (0-100) |
| `severity` | string | No | "normal", "minor", "moderate", "severe" |
| `risk_score` | float64 | No | Normalized risk (0-100) |
| `confidence_score` | float64 | No | Assessment confidence (0-100) |
| `status` | string | No | "Normal", "Alerta", "Anormal", "InsufficientData" |
| `top_contributing_signals` | string | No | JSON array of top error signals |
| `data_quality_ratio` | float64 | No | Fraction of non-imputed data |
| `model_version` | string | No | Trained model version identifier |
| `execution_timestamp` | datetime64[ns] | No | When analysis ran |

---

### 6. AI Comments — Signal Level

**Purpose**: Structured AI diagnostic comments per signal, explaining what technique evidence reveals.

**Location**: `data/telemetry/golden/{client}/ai_comments/year={YYYY}/week={WW}/`

**File Pattern**: `signal_comments.parquet`

**Language**: All AI-generated text fields are in **Spanish**.

**Schema**:

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `unit` | string | No | Equipment identifier |
| `signal` | string | No | Signal name |
| `system` | string | No | System name |
| `status` | string | No | Aggregated signal status |
| `risk_score` | float64 | No | Signal risk score at time of diagnosis |
| `description` | string | No | Brief summary of what was detected (max ~20 words, Spanish) |
| `explaining` | string | No | Detailed explanation of findings and relevance (2-4 sentences, Spanish) |
| `techniques_referenced` | string | No | JSON array of technique names that informed the diagnosis |
| `evaluation_timestamp` | datetime64[ns] | No | When diagnosis was generated |
| `model_used` | string | No | LLM model identifier |

**Constraints**:
- Only signals with non-Normal status are included
- `description`: concise, max ~20 words — explains *what* was detected
- `explaining`: detailed, 2-4 sentences — explains *what was found* and *why it is relevant*
- `techniques_referenced` contains only techniques that reported non-Normal for this signal
- No `recommended_action` at signal level — actions are generated at system/unit level

---

### 7. AI Comments — System Level

**Purpose**: Synthesized AI diagnostic at system level, combining signal-level findings.

**Location**: `data/telemetry/golden/{client}/ai_comments/year={YYYY}/week={WW}/`

**File Pattern**: `system_comments.parquet`

**Language**: All AI-generated text fields are in **Spanish**.

**Schema**:

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `unit` | string | No | Equipment identifier |
| `system` | string | No | System name |
| `system_status` | string | No | System health status |
| `system_score` | float64 | No | System health score at time of diagnosis |
| `description` | string | No | Brief summary of system condition (max ~20 words, Spanish) |
| `explaining` | string | No | Detailed explanation of findings and relevance (2-4 sentences, Spanish) |
| `signals_referenced` | string | No | JSON array of signal names discussed |
| `recommended_action` | string | Yes | Suggested maintenance action (Spanish) |
| `evaluation_timestamp` | datetime64[ns] | No | When diagnosis was generated |
| `model_used` | string | No | LLM model identifier |

**Constraints**:
- Only systems with non-Normal status are included
- Uses signal-level comments as input context (bottom-up)
- `recommended_action` is a single actionable sentence, generated with full signal context

---

### 8. AI Comments — Unit Level

**Purpose**: Executive-level AI diagnostic summarizing the unit condition.

**Location**: `data/telemetry/golden/{client}/ai_comments/year={YYYY}/week={WW}/`

**File Pattern**: `unit_comments.parquet`

**Language**: All AI-generated text fields are in **Spanish**.

**Schema**:

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `unit` | string | No | Equipment identifier |
| `overall_status` | string | No | Unit overall status |
| `priority_score` | float64 | No | Unit priority score at time of diagnosis |
| `description` | string | No | Brief summary of unit condition (max ~20 words, Spanish) |
| `explaining` | string | No | Detailed executive assessment (2-4 sentences, Spanish) |
| `systems_referenced` | string | No | JSON array of system names discussed |
| `urgency` | string | No | "routine", "monitor", "schedule_inspection", "immediate" |
| `recommended_action` | string | Yes | Top-priority maintenance recommendation (Spanish) |
| `evaluation_timestamp` | datetime64[ns] | No | When diagnosis was generated |
| `model_used` | string | No | LLM model identifier |

**Constraints**:
- Only units with non-Normal status are included
- Uses system-level comments as input context (bottom-up)
- `urgency` maps priority_score ranges to action timelines
- `recommended_action` generated with full system-level context

---

### 9. System Health

**Purpose**: Aggregated system-level health assessments combining all techniques.

**Location**: `data/telemetry/golden/{client}/system_health/year={YYYY}/week={WW}/`

**File Pattern**: `system_health.parquet`

**Schema**:

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `unit` | string | No | Equipment identifier |
| `system` | string | No | System name |
| `system_score` | float64 | No | Aggregated system score (0-100) |
| `system_status` | string | No | "Normal", "Alerta", "Anormal", "InsufficientData" |
| `confidence` | float64 | No | Aggregated confidence (0-100) |
| `n_techniques_triggered` | int64 | No | Count of non-Normal techniques |
| `top_signal` | string | Yes | Highest-risk signal in system |
| `top_signal_score` | float64 | Yes | Score of top signal |
| `top_technique` | string | Yes | Technique that found highest risk |
| `explanation` | string | Yes | LLM-generated explanation |
| `evaluation_timestamp` | datetime64[ns] | No | Assessment timestamp |
| `baseline_version` | string | No | Baseline version used |

---

### 10. Unit Health

**Purpose**: Top-level fleet ranking and unit health prioritization.

**Location**: `data/telemetry/golden/{client}/unit_health/year={YYYY}/week={WW}/`

**File Pattern**: `unit_health.parquet`

**Schema**:

| Column | Type | Nullable | Description |
|--------|------|----------|-------------|
| `unit` | string | No | Equipment identifier |
| `overall_status` | string | No | "Normal", "Alerta", "Anormal", "InsufficientData" |
| `priority_score` | float64 | No | Fleet ranking score (higher = more urgent) |
| `unit_score` | float64 | No | Average system score (0-100) |
| `n_anormal_systems` | int64 | No | Count of Anormal systems |
| `n_alerta_systems` | int64 | No | Count of Alerta systems |
| `top_risk_systems` | string | No | JSON array of top risk system names |
| `executive_summary` | string | Yes | LLM-generated executive summary |
| `evaluation_timestamp` | datetime64[ns] | No | Assessment timestamp |
| `baseline_version` | string | No | Baseline version used |

---

### 11. Autoencoder Models (Artifacts)

**Purpose**: Persisted trained LSTM autoencoder models and associated scalers.

**Location**: `data/telemetry/golden/{client}/models/autoencoder/`

**File Pattern**: `{unit}_{system}_{version}/`

**Contents per model directory**:
| File | Format | Description |
|------|--------|-------------|
| `model.keras` | Keras SavedModel | Trained LSTM autoencoder |
| `scaler.pkl` | Pickle (joblib) | StandardScaler fitted on training data |
| `metadata.json` | JSON | Training metadata |

**metadata.json Schema**:
```json
{
  "unit": "T_09",
  "system": "Engine",
  "model_version": "20260610",
  "training_date": "2026-06-10T08:00:00Z",
  "n_training_sequences": 4500,
  "n_features": 18,
  "sequence_length": 30,
  "encoding_dim": 32,
  "val_loss": 0.0023,
  "baseline_mean": 0.0018,
  "baseline_std": 0.0005,
  "baseline_p95": 0.0031,
  "baseline_p99": 0.0042,
  "feature_columns": ["EngCoolTemp", "EngOilPres", "..."]
}
```

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CONFIGURATION                                   │
│  signal_registry.yaml │ equipment_registry.yaml │ analysis_config.yaml       │
└───────────┬───────────────────────┬────────────────────────┬────────────────┘
            │                       │                        │
            ▼                       ▼                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SILVER LAYER (INPUT)                                  │
│                                                                              │
│  Telemetry_Wide_With_States/    │    baselines/          │    limits/        │
│  Week{WW}Year{YYYY}.parquet     │    baseline_{date}     │    limits_{date}  │
│  [Unit|Fecha|Estado|signals...] │    .parquet            │    .parquet       │
└───────────┬─────────────────────────────────┬──────────────────┬────────────┘
            │                                 │
            ▼                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      PROCESSING (src/ modules)                               │
│                                                                              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │  Deviation  │  │    Event    │  │    Trend    │  │  Distribution    │  │
│  │  Analysis   │──│   Analysis  │  │  Analysis   │  │    Shift         │  │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘  └───────┬──────────┘  │
│         │                │                │                  │              │
│         │      ┌─────────────────┐        │                  │              │
│         └─────►│   Autoencoder   │◄───────┘──────────────────┘              │
│                │   (uses normal  │                                           │
│                │    labels)      │                                           │
│                └────────┬────────┘                                           │
│                         │                                                    │
│                         ▼                                                    │
│              ┌───────────────────┐                                           │
│              │   Aggregation     │◄── All technique results                  │
│              │  Signal→System→   │                                           │
│              │      Unit         │                                           │
│              └────────┬──────────┘                                           │
│                       │                                                      │
│                       ▼                                                      │
│              ┌───────────────────┐                                           │
│              │  LLM Explanation  │◄── OpenAI API (via .env API_KEY)          │
│              └────────┬──────────┘                                           │
└───────────────────────┼─────────────────────────────────────────────────────┘
                        │
                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         GOLDEN LAYER (OUTPUT)                                 │
│                                                                              │
│  technique_results/         │  ai_comments/      │  system_health/           │
│  ├── deviation/             │  year=YYYY/        │  year=YYYY/               │
│  ├── events/                │  week=WW/          │  week=WW/                 │
│  ├── trend/                 │  ├── signal_       │                            │
│  ├── distribution/          │  │   comments      │  unit_health/             │
│  └── autoencoder/           │  ├── system_       │  year=YYYY/               │
│                             │  │   comments      │  week=WW/                 │
│                             │  └── unit_         │                            │
│                             │      comments      │  models/autoencoder/      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Schema Validation

### Validation Functions

All data entering or leaving the pipeline must be validated against its contract:

```python
from pydantic import BaseModel, Field
from datetime import datetime, date
from typing import Optional

class TelemetryInputSchema(BaseModel):
    """Validates a row of Silver telemetry data."""
    Unit: str
    Fecha: datetime
    Estado: str = Field(pattern=r'^(Operacional|Ralenti|Apagada|ND)$')


class DeviationResultSchema(BaseModel):
    """Validates a deviation analysis result row."""
    unit: str
    signal: str
    system: str
    state: str
    model_specification: str
    evaluation_date: date
    risk_score: float = Field(ge=0, le=100)
    confidence_score: float = Field(ge=0, le=100)
    status: str = Field(pattern=r'^(Normal|Alerta|Anormal|InsufficientData)$')
    abnormal_pct: float = Field(ge=0, le=100)
    alert_pct: float = Field(ge=0, le=100)
    critical_pct: float = Field(ge=0, le=100)
    total_minutes_evaluated: int = Field(ge=0)
    baseline_version: str
    execution_timestamp: datetime


class SystemHealthSchema(BaseModel):
    """Validates a system health assessment row."""
    unit: str
    system: str
    system_score: float = Field(ge=0, le=100)
    system_status: str = Field(pattern=r'^(Normal|Alerta|Anormal|InsufficientData)$')
    confidence: float = Field(ge=0, le=100)
    n_techniques_triggered: int = Field(ge=0)
    evaluation_timestamp: datetime
    baseline_version: str
    explanation: Optional[str] = None


class UnitHealthSchema(BaseModel):
    """Validates a unit health assessment row."""
    unit: str
    overall_status: str = Field(pattern=r'^(Normal|Alerta|Anormal|InsufficientData)$')
    priority_score: float = Field(ge=0)
    unit_score: float = Field(ge=0, le=100)
    n_anormal_systems: int = Field(ge=0)
    n_alerta_systems: int = Field(ge=0)
    evaluation_timestamp: datetime
    baseline_version: str
    executive_summary: Optional[str] = None


class SignalCommentSchema(BaseModel):
    """Validates an AI signal-level comment row."""
    unit: str
    signal: str
    system: str
    status: str = Field(pattern=r'^(Alerta|Anormal|InsufficientData)$')
    risk_score: float = Field(ge=0, le=100)
    description: str = Field(min_length=1)
    explaining: str = Field(min_length=0)
    techniques_referenced: str  # JSON array
    evaluation_timestamp: datetime
    model_used: str


class SystemCommentSchema(BaseModel):
    """Validates an AI system-level comment row."""
    unit: str
    system: str
    system_status: str = Field(pattern=r'^(Alerta|Anormal|InsufficientData)$')
    system_score: float = Field(ge=0, le=100)
    description: str = Field(min_length=1)
    explaining: str = Field(min_length=0)
    signals_referenced: str  # JSON array
    recommended_action: Optional[str] = None
    evaluation_timestamp: datetime
    model_used: str


class UnitCommentSchema(BaseModel):
    """Validates an AI unit-level comment row."""
    unit: str
    overall_status: str = Field(pattern=r'^(Alerta|Anormal|InsufficientData)$')
    priority_score: float = Field(ge=0)
    description: str = Field(min_length=1)
    explaining: str = Field(min_length=0)
    systems_referenced: str  # JSON array
    urgency: str = Field(pattern=r'^(routine|monitor|schedule_inspection|immediate)$')
    recommended_action: Optional[str] = None
    evaluation_timestamp: datetime
    model_used: str
```

### Runtime Validation Pattern

```python
def validate_output(df: pd.DataFrame, schema_class: type, sample_size: int = 100) -> dict:
    """
    Validate DataFrame output against Pydantic schema.
    
    Parameters:
        - df: DataFrame to validate
        - schema_class: Pydantic model class for validation
        - sample_size: Number of rows to validate (default: 100)
        
    Returns:
        - dict: {'valid': bool, 'errors': list, 'rows_checked': int}
    """
    errors = []
    sample = df.head(sample_size)
    
    for idx, row in sample.iterrows():
        try:
            schema_class(**row.to_dict())
        except Exception as e:
            errors.append({'row': idx, 'error': str(e)})
    
    return {
        'valid': len(errors) == 0,
        'errors': errors[:10],  # First 10 errors
        'rows_checked': len(sample)
    }
```

---

## Versioning & Retention

### File Versioning

| Data Type | Version Strategy | Example |
|-----------|-----------------|---------|
| Baselines | Date-stamped files | `baseline_20260225.parquet` |
| Models | Directory with version | `T_09_Engine_20260610/` |
| Results | Partitioned by time | `year=2026/week=22/` |
| Config | YAML `version` field | `version: "1.2"` |

### Retention Policy

| Output Type | Retention | Rationale |
|-------------|-----------|-----------|
| Technique results | 1 year | Sufficient for trend backtesting |
| AI Comments | 2 years | Historical diagnostic tracking, paired with health |
| System/Unit health | 2 years | Historical tracking and comparison |
| Events | 1 year | Operational relevance window |
| Baselines | All versions | Minimal storage, full auditability |
| Models | Last 3 versions | Rollback capability |
| LLM explanations | Stored with health outputs | Paired with assessments (legacy) |

### Backward Compatibility

All output parquet files include a `schema_version` metadata field. When schemas evolve:
1. New columns are added as nullable (non-breaking)
2. Renamed columns maintain both old and new for one version cycle
3. Removed columns are documented in migration notes
4. Reader code handles missing columns gracefully

---

## Environment Configuration

### Required Environment Variables (`.env`)

```env
# OpenAI API Configuration
OPENAI_API_KEY=sk-...

# Optional: Override model for LLM explanations
OPENAI_MODEL=gpt-4o-mini

# Data paths (optional - defaults use relative paths)
SILVER_DATA_PATH=data/telemetry/silver
GOLDEN_DATA_PATH=data/telemetry/golden
CONFIG_PATH=data/telemetry/config
```

---
