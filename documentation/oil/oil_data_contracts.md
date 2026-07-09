# Data Contracts - Oil Analysis Data Product

**Version**: 2.5  
**Last Updated**: July 7, 2026  
**Owner**: Oil Analysis Data Product Team

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Data Layer Architecture](#data-layer-architecture)
3. [Bronze Layer](#bronze-layer)
4. [Silver Layer](#silver-layer)
5. [Golden Layer](#golden-layer)
6. [Schema Definitions](#schema-definitions)
7. [S3 Storage](#s3-storage)
8. [Data Quality Rules](#data-quality-rules)

---

## 🎯 Overview

This document defines the data contracts for the Oil Analysis Data Product, specifying the schema, format, and location of data at each processing layer (Bronze → Silver → Golden). These contracts ensure consistent data structure for downstream consumers.

**Data Product Purpose**: Process raw oil analysis laboratory results into actionable maintenance insights with AI-powered recommendations, using oil-hour stratified statistical limits.

**Primary Consumers**:
- S3-based data consumers
- Business Intelligence tools
- Data analysts
- Fusion Service (aggregates multiple data products)

**Processing Modes**:
1. **Historical**: One-time bulk processing with Stewart Limits calculation
2. **Incremental**: Daily processing using existing Stewart Limits

**Key Enhancements (v2.5)**:
- **Three-Date Model**: sampleDate (withdrawal), labDate (arrival at lab), reportDate (diagnosis)
- **Normal Report Defaults**: Default recommendation text for Normal samples and machines
- **Site Field**: Location where the machine operates (per client source)
- **Anomaly Type Classification**: ML-predicted anomaly reason for non-Normal reports
- **Oil-Hour Stratification**: Separate limits for fresh (<1000h) vs aged (>=1000h) oil
- **Evolution Ratio Limits**: Normalized concentration per oil hour for early trend detection
- **Fallback Behavior**: Graceful degradation when stratified limits unavailable
- **Limit Traceability**: Track which limit source was used (oil_hour_stratified, fallback_global, missing)

---

## 🏗️ Data Layer Architecture

### Local Storage

```
data/
├── bronze/                       # Bronze Layer (Immutable source data)
│   ├── cda/                      # CDA client raw files
│   │   ├── T-09.xlsx             # Finning Lab format
│   │   ├── T-10.xlsx
│   │   └── ...
│   └── emin/                     # EMIN client raw files
│       ├── muestrasAlsHistoricos.parquet  # ALS Lab format
│       └── Equipamiento.parquet
│
├── silver/                       # Silver Layer (Harmonized, validated)
│   ├── CDA.parquet               # Standardized CDA data
│   └── EMIN.parquet              # Standardized EMIN data
│
├── golden/                       # Golden Layer (Analysis-ready outputs)
│   ├── cda/
│   │   ├── classified.parquet         # Classified oil analysis reports
│   │   ├── machine_status.parquet     # Aggregated machine health status
│   │   └── stewart_limits.parquet     # Statistical thresholds for CDA
│   └── emin/
│       ├── classified.parquet
│       ├── machine_status.parquet
│       └── stewart_limits.parquet
│
└── essays_elements.xlsx          # Auxiliary: Essay metadata and mappings
```

### S3 Storage (Auto-synced)

```
s3://{BUCKET_NAME}/MultiTechnique Alerts/oil/
├── silver/
│   ├── CDA.parquet
│   └── EMIN.parquet
└── golden/
    ├── cda/
    │   ├── classified.parquet
    │   ├── machine_status.parquet
    │   └── stewart_limits.parquet
    └── emin/
        ├── classified.parquet
        ├── machine_status.parquet
        └── stewart_limits.parquet
```

---

## 📥 Bronze Layer

**Purpose**: Immutable storage of raw laboratory data  
**Update Frequency**: 
- Historical: One-time bulk load
- Incremental: Daily/Weekly new files  
**Retention**: Indefinite (source of truth)  
**Format**: Original laboratory format (Excel or Parquet)

### Location

```
Local: data/bronze/{client}/
S3: Not uploaded (raw data stays local)
```

### CDA Client (Finning Laboratory)

**Format**: Excel (.xlsx)  
**Source**: Finning Laboratory reports  
**Naming**: `T-{month}.xlsx` (e.g., T-09.xlsx)

**Characteristics**:
- One file per month
- Contains multiple oil samples
- Variable essay columns (laboratory-dependent)

### EMIN Client (ALS Laboratory)

**Format**: Parquet (.parquet)  
**Source**: ALS Laboratory  
**Files**:
- `muestrasAlsHistoricos.parquet` - Oil sample results
- `Equipamiento.parquet` - Equipment metadata

**Characteristics**:
- Nested format with testName/testValue pairs
- Historical data in single file
- Machine metadata in separate file

### Contract Guarantees

✅ **Immutability**: Files never modified after ingestion  
✅ **Completeness**: All source columns preserved  
✅ **Traceability**: Original formats maintained

---

## 🔄 Silver Layer

**Purpose**: Harmonized, validated data with standardized schema  
**Update Frequency**: After each Bronze processing  
**Retention**: Keep latest + historical for trend analysis  
**Format**: Parquet (columnar, compressed)

### Location

```
Local: data/silver/{CLIENT}.parquet
S3: s3://{BUCKET}/MultiTechnique Alerts/oil/silver/{CLIENT}.parquet
```

### Files

- `CDA.parquet` - Harmonized CDA oil analysis data
- `EMIN.parquet` - Harmonized EMIN oil analysis data

### Schema

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `client` | string | Client identifier | 'CDA', 'EMIN' |
| `sampleNumber` | string | Unique sample ID | 'CDA-2024-001' |
| `sampleDate` | date | Sample collection/withdrawal date | '2024-01-15' |
| `labDate` | date | Date sample arrives at laboratory | '2024-01-16' |
| `reportDate` | date | Date sample is diagnosed/reported | '2024-01-17' |
| `site` | string | Location where the machine works | 'Área Mina' |
| `unitId` | string | Equipment unit ID | 'CAT-001' |
| `machineName` | string | Normalized machine type | 'camion', 'pala' |
| `machineModel` | string | Machine model | 'CAT 797F' |
| `machineBrand` | string | Machine brand | 'Caterpillar' |
| `machineHours` | float | Operating hours | 15420.5 |
| `machineSerialNumber` | string | Machine serial | 'ABC123' |
| `componentName` | string | Component analyzed (original with position) | 'motor diesel', 'mando final izquierdo' |
| `componentNameNormalized` | string | Component normalized for Stewart Limits | 'motor diesel', 'mando final' |
| `componentHours` | float | Component hours | 8230.0 |
| `componentSerialNumber` | string | Component serial | 'ENG456' |
| `oilMeter` | float | Oil meter reading | 1250.5 |
| `oilBrand` | string | Oil brand | 'Mobil' |
| `oilType` | string | Oil type | '15W40' |
| `oilWeight` | string | Oil weight | '15W-40' |
| `previousSampleNumber` | string | Previous sample ID | 'CDA-2023-998' |
| `previousSampleDate` | date | Previous sample date | '2023-12-20' |
| `daysSincePrevious` | int | Days between samples | 26 |
| `group_element` | string | Essay group | 'Desgaste', 'Contaminacion' |
| **Oil-Hour Stratification (v2.3)** | | | |
| `oilHourRange` | string | Oil age category | 'LT_1000', 'GE_1000', 'UNKNOWN' |
| **Essay Columns** | float | Essay values (dynamic) | |
| `Hierro` | float | Iron content (ppm) | 45.3 |
| `Cobre` | float | Copper content (ppm) | 12.1 |
| `Silicio` | float | Silicon content (ppm) | 8.7 |
| ... | float | (21 total essay columns) | |
| **Evolution Ratio Columns (v2.3)** | float | Normalized essay per oil hour | |
| `evolution_ratio_Hierro` | float | Iron per oil hour (ppm/h) | 0.036 |
| `evolution_ratio_Cobre` | float | Copper per oil hour (ppm/h) | 0.010 |
| `evolution_ratio_Silicio` | float | Silicon per oil hour (ppm/h) | 0.007 |
| ... | float | (21 total ratio columns) | |

### Oil Hour Range Categorization (v2.3)

**Logic**:
```python
if oilMeter is null:
    oilHourRange = "UNKNOWN"
elif oilMeter < 1000:
    oilHourRange = "LT_1000"  # Fresh oil
else:
    oilHourRange = "GE_1000"  # Aged oil
```

**Purpose**: Different essay behavior in fresh vs aged oil requires separate statistical limits.

### Evolution Ratio Calculation (v2.3)

**Formula**: `evolution_ratio = essay_value / oilMeter`

**Example**:
- Hierro = 80 ppm
- oilMeter = 800 hours
- evolution_ratio_Hierro = 80 / 800 = 0.10 ppm/hour

**Purpose**: Normalize concentration by oil age for early trend detection.

**Edge Cases**:
- `oilMeter` null or ≤ 0 → `evolution_ratio` = null
- Do **not** replace null ratios with zero (distorts percentile calculations)

### Site Field (v2.4)

**Source per client**:
| Client | Source | Default |
|--------|--------|---------|
| CDA | Static | "Área Mina" |
| EMIN | Static | "Área Mina" |
| ENEX | Bronze column "Site" | "Área Mina" (if null) |

### Lab Date Field (v2.5)

**Source per client** (date sample arrives at laboratory):
| Client | Bronze Column | Notes |
|--------|--------------|-------|
| CDA | N/A | Uses "Fecha de laboratorio" (same as reportDate) |
| EMIN | "dateOfEntryIntoLaboratory" | |
| ENEX | "Date Received" | |

**Format**: datetime (YYYY-MM-DD)

### Report Date Field (v2.5)

**Source per client** (date sample is diagnosed/reported):
| Client | Bronze Column |
|--------|--------------|
| CDA | "Fecha de laboratorio" |
| EMIN | "validResult_evaluationDate" |
| ENEX | "Date Diagnosed" |

**Format**: datetime (YYYY-MM-DD)

### Quality Rules

✅ Valid date formats (YYYY-MM-DD)  
✅ Essay values >= 0  
✅ Component hours <= Machine hours  
✅ No duplicate sample numbers  
✅ All essay columns present (filled with 0 if missing)

**Note on Component Names**:
- `componentName`: Preserves original granularity (e.g., "mando final izquierdo", "mando final derecho", "maza izquierda")
- `componentNameNormalized`: Grouped version for Stewart Limits calculation (e.g., "mando final", "maza")
- Golden layer reports use original `componentName` for detailed visibility
- Stewart Limits use `componentNameNormalized` to ensure sufficient sample size

---

## 🏆 Golden Layer

**Purpose**: Analysis-ready outputs with classifications, AI recommendations, and aggregations  
**Update Frequency**: After each Silver processing  
**Retention**: Keep all historical snapshots  
**Format**: Parquet (columnar, compressed)

### Location

```
Local: data/golden/{client}/
S3: s3://{BUCKET}/MultiTechnique Alerts/oil/golden/{client}/
```

### Files per Client

#### 1. Classified Reports (`classified.parquet`)

**Purpose**: Oil analysis reports with essay classifications, report status, and AI recommendations

**Schema**:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| **Base Columns** | | (All Silver layer columns including oilHourRange and evolution_ratio columns) | |
| `essay_status_{essay}` | string | Essay classification | 'Normal', 'Marginal', 'Condenatorio', 'Critico' |
| `breached_essays` | list[dict] | Essays exceeding thresholds with group info | [{'essay': 'Hierro', 'group': 'Desgaste', 'points': 5}] |
| `severity_score` | int | Total points from ALL breached essays | 14 |
| `desgaste_score` | int | Points from ONLY Desgaste essays (NEW) | 8 |
| `report_status` | string | Overall report status (based on desgaste_score) | 'Normal', 'Alerta', 'Anormal' |
| `anomalyType` | string | Predicted anomaly reason | 'Normal', 'Desgaste de Componentes', 'Contaminación Lubricante' |
| `ai_recommendation` | string | AI-generated maintenance advice (always present) | 'Se recomienda...' |
| `ai_analysis` | string | AI analysis of breached essays | 'Niveles elevados de...' |
| **Oil-Hour Stratification (v2.3)** | | | |
| `limit_source` | string | Which limit was used for classification | 'oil_hour_stratified', 'fallback_global', 'missing' |
| `ratio_limit_source` | string | Which ratio limit was used | 'oil_hour_stratified', 'fallback_global', 'not_implemented', 'missing' |

**Limit Source Values (v2.3)**:
- `oil_hour_stratified`: Exact match for oilHourRange (preferred, v2.3+)
- `backward_compatible`: Using old non-stratified limits (v2.2 format)
- `fallback_global`: Averaged across all oil hour ranges (when stratified unavailable)
- `missing`: No limits available for this machine/component/essay

**Essay Status Values**:
- `Normal`: Below 90th percentile
- `Marginal`: Between 90th-95th percentile (1 point)
- `Condenatorio`: Between 95th-98th percentile (3 points)
- `Critico`: Above 98th percentile (5 points)

**Report Status Logic** ⚠️ **HIERARCHY RULE APPLIED**:
- Only **Desgaste** (wear) essays affect report status
- Contamination, additives, and physical-chemical essays are tracked but don't change status
- `Normal`: desgaste_score < 3
- `Alerta`: 3 <= desgaste_score < 9
- `Anormal`: desgaste_score >= 9

**Desgaste Essays** (affect report status):
- Hierro, Cromo, Aluminio, Cobre, Plomo, Níquel, Plata, Estaño, Titanio, Vanadio, Manganeso

**Other Essays** (tracked but don't affect status):
- Contaminante: Silicio, Potasio, Sodio
- Aditivo: Zinc, Bario, Boro, Calcio, Molibdeno, Magnesio
- Fisico Quimico: Viscosity, TBN, etc.

**Sample Count**: ~6,000-7,000 reports per client

---

#### 2. Machine Status (`machine_status.parquet`)

**Purpose**: Aggregated current health status per equipment unit

**Schema**:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `unit_id` | string | Equipment unit ID | 'CAT-001' |
| `client` | string | Client identifier | 'CDA' |
| `latest_sample_date` | date | Most recent sample date | '2024-02-01' |
| `overall_status` | string | Machine status | 'Alerta' |
| `machine_score` | int | Weighted score for machine health | 14 |
| `total_components` | int | Total components monitored | 5 |
| `components_normal` | int | Components with Normal status | 3 |
| `components_alerta` | int | Components with Alerta status | 1 |
| `components_anormal` | int | Components with Anormal status | 1 |
| `priority_score` | int | Priority for maintenance (1=low, 10=high) | 5 |
| `component_details` | list[dict] | Component status with weights | See below |
| `machine_ai_recommendation` | string | AI-generated machine-level maintenance recommendation | 'El equipo presenta desgaste crítico en motor...' |

**Component Details Structure**:
```json
{
  "component": "motor diesel",
  "status": "Anormal",
  "severity_score": 8,
  "weight": 1.0,
  "sample_date": "2024-02-01"
}
```

**Machine Score Calculation** ⚠️ **HIERARCHY RULE APPLIED**:
- Components have different weights based on criticality:
  - **Critical** (motor, transmision): 2.0x weight
  - **Important** (convertidor, diferencial): 1.0x weight  
  - **Other** (mando final, hidraulico, etc.): 0.5x weight
- Machine score = Σ (component_status_points × component_weight)
  - Normal = 0 points, Alerta = 2 points, Anormal = 5 points
- Machine status thresholds:
  - Normal: machine_score < 6
  - Alerta: 6 <= machine_score < 10
  - Anormal: machine_score >= 10

**Machine-Level AI Recommendations** 🤖:
- Generated automatically for ALL machines regardless of status
- For 'Alerta' or 'Anormal' machines: AI-generated holistic equipment assessment
- For 'Normal' machines: Default message confirming normal operation
- Provides holistic equipment assessment considering all components
- Takes into account component criticality weights
- Recommends prioritized maintenance actions
- Uses OpenAI GPT-4o-mini with specialized mechanical engineering prompt for non-Normal machines

**Sample Count**: ~200-250 machines per client

---

#### 3. Stewart Limits (`stewart_limits.parquet`)

**Purpose**: Statistical thresholds for essay classification (per client, stratified by oil hour)

**Schema (v2.3)**:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `client` | string | Client identifier | 'CDA' |
| `machine` | string | Normalized machine name | 'camion' |
| `component` | string | Component name (normalized/grouped) | 'mando final' |
| `essay` | string | Essay name | 'Hierro' |
| `oilHourRange` | string | Oil age category | 'LT_1000', 'GE_1000', 'UNKNOWN' |
| `threshold_normal` | float | 90th percentile | 45.2 |
| `threshold_alert` | float | 95th percentile | 58.7 |
| `threshold_critic` | float | 98th percentile | 72.1 |
| `sample_count` | int | Number of samples used for calculation | 450 |
| `calculation_date` | string | ISO timestamp of calculation | '2026-05-13T10:30:00' |

**Calculation**:
- Based on historical data for each client independently
- Prevents data leakage between clients
- Recalculated in historical mode, loaded in incremental mode
- **Component Grouping**: Uses `componentNameNormalized` to group similar components
- **Oil-Hour Stratification (v2.3)**: Separate limits for LT_1000, GE_1000, UNKNOWN

**Stratification Example**:
```
Client: CDA
Machine: camion
Component: motor diesel
Essay: Hierro

LT_1000 (fresh oil):
  threshold_normal: 35.0
  threshold_alert: 45.0
  threshold_critic: 55.0

GE_1000 (aged oil):
  threshold_normal: 50.0
  threshold_alert: 65.0
  threshold_critic: 80.0
```

**Oil-Age Constraint** 🆕:
- **Rule**: `GE_1000 thresholds >= LT_1000 thresholds` for all essay/threshold combinations
- **Rationale**: Aged oil naturally accumulates more wear particles and contaminants, so thresholds should be higher (more permissive)
- **Enforcement**: Automatically applied during calculation - if calculated `GE_1000 < LT_1000`, the system adjusts `GE_1000` upward to equal `LT_1000`
- **Example**: If calculated limits show `LT_1000: 50.0` and `GE_1000: 45.0`, the system adjusts to `GE_1000: 50.0`
- **Verification**: Use `python verify_oil_age_constraint.py` to check compliance

**Sample Count**: ~900-1500 limit combinations per client (3x previous due to stratification)

---

#### 4. Stewart Limits Ratio (`stewart_limits_ratio.parquet`) 🆕 v2.3

**Purpose**: Statistical thresholds for evolution ratio classification (normalized concentration per oil hour)

**Schema**:

| Column | Type | Description | Example |
|--------|------|-------------|---------|
| `client` | string | Client identifier | 'CDA' |
| `machine` | string | Normalized machine name | 'camion' |
| `component` | string | Component name (normalized/grouped) | 'mando final' |
| `essay` | string | Essay name | 'Hierro' |
| `ratio_threshold_normal` | float | 90th percentile of evolution_ratio (4 decimals) | 0.0450 |
| `ratio_threshold_alert` | float | 95th percentile of evolution_ratio (4 decimals) | 0.0600 |
| `ratio_threshold_critic` | float | 98th percentile of evolution_ratio (4 decimals) | 0.0750 |
| `sample_count` | int | Number of samples used for calculation | 6910 |
| `calculation_date` | string | ISO timestamp of calculation | '2026-05-13T10:30:00' |

**Calculation**:
- Percentiles calculated over `evolution_ratio` values (essay_value / oilMeter)
- **NOT stratified by oilHourRange** - uses all data together for global ratio limits
- Uses decimal precision (4 decimal places) for ratio thresholds
- Only valid non-null ratios included

**Key Difference from Regular Stewart Limits**:
- Regular Stewart Limits: **Stratified** by oilHourRange (separate for LT_1000, GE_1000, UNKNOWN)
- Evolution Ratio Limits: **Not stratified** - global limits across all oil ages

**Rationale for Non-Stratification**:
- Evolution ratios already normalize for oil age (ppm/hour)
- Stratification would further fragment the data unnecessarily
- Global ratio limits provide consistent trend detection

**Purpose**:
- Early trend detection (ratio increasing → accelerating degradation)
- Normalize for oil age effects
- Complementary to absolute value limits

**Example**:
```
Client: CDA
Machine: camion
Component: motor diesel
Essay: Hierro

ratio_threshold_normal: 0.0350 ppm/hour
ratio_threshold_alert: 0.0450 ppm/hour
ratio_threshold_critic: 0.0550 ppm/hour
sample_count: 6910 (all oil ages combined)
```

**Sample Count**: ~300-500 ratio limit combinations per client

---

## ☁️ S3 Storage

### Upload Behavior

- **Automatic**: Uploads after each client completes processing
- **Independent**: CDA and EMIN upload separately
- **Resilient**: Partial failures don't block other clients

### Upload Scope

✅ **Uploaded**:
- Silver layer: `{CLIENT}.parquet`
- Golden layer: All 3 files per client

❌ **Not Uploaded**:
- Bronze layer (raw data stays local)
- Auxiliary files (`essays_elements.xlsx`)

### S3 Paths

```
s3://{BUCKET_NAME}/MultiTechnique Alerts/oil/silver/{CLIENT}.parquet
s3://{BUCKET_NAME}/MultiTechnique Alerts/oil/golden/{client}/classified.parquet
s3://{BUCKET_NAME}/MultiTechnique Alerts/oil/golden/{client}/machine_status.parquet
s3://{BUCKET_NAME}/MultiTechnique Alerts/oil/golden/{client}/stewart_limits.parquet
s3://{BUCKET_NAME}/MultiTechnique Alerts/oil/golden/{client}/stewart_limits_ratio.parquet  (NEW v2.3)
```

### Configuration

Required environment variables in `.env`:
```bash
ACCESS_KEY=your_aws_access_key
SECRET_KEY=your_aws_secret_key
BUCKET_NAME=your_bucket_name
AWS_S3_PREFIX=MultiTechnique Alerts/oil/
```

---

## ✅ Data Quality Rules

### Bronze Layer
- ❌ No validation (accept as-is from laboratories)

### Silver Layer
- ✅ All dates in ISO format (YYYY-MM-DD)
- ✅ Essay values >= 0
- ✅ Component hours <= Machine hours
- ✅ No duplicate sample numbers
- ✅ All expected essay columns present
- ✅ Machine names normalized

### Golden Layer
- ✅ Every sample has essay_status for all essays
- ✅ Every sample has report_status
- ✅ essay_score matches essay classifications
- ✅ AI recommendations present for ALL reports (default for Normal, AI-generated for others)
- ✅ Machine status aggregations match classified reports

---

## 📝 Change Log

### Version 2.5 (July 7, 2026) - DATE REFACTORING & NORMAL REPORT DEFAULTS
**Major Feature**: Three-date model and default recommendations for Normal samples/machines

#### Silver Layer Changes
- **`labDate`**: **MEANING CHANGED** — Now represents date sample arrives at laboratory (previously was date diagnosed)
  - CDA: No separate field available, uses reportDate value
  - EMIN: From bronze "dateOfEntryIntoLaboratory" (unchanged source)
  - ENEX: From bronze "Date Received" (previously used "Date Diagnosed")

- **`reportDate`**: **NEW FIELD** — Date sample is diagnosed/reported
  - CDA: From bronze "Fecha de laboratorio"
  - EMIN: From bronze "validResult_evaluationDate"
  - ENEX: From bronze "Date Diagnosed"

#### Golden Layer Changes
- **`ai_recommendation`**: Now always populated for all samples
  - Normal samples: Default text about permissible wear/contamination levels
  - Alerta/Anormal samples: AI-generated recommendation (unchanged)

- **`anomalyType`**: Unchanged — 'Normal' for Normal reports, predicted for non-Normal

- **`machine_ai_recommendation`**: Now always populated for all machines
  - Normal machines: Default text confirming normal operation
  - Alerta/Anormal machines: AI-generated recommendation (unchanged)

#### Migration Notes
- **Breaking change**: `labDate` meaning has changed. Consumers that previously used `labDate` as "diagnosis date" should now use `reportDate`
- `reportDate` is a new required column in Silver layer
- Normal samples/machines now have non-null `ai_recommendation`/`machine_ai_recommendation`

---

### Version 2.4 (July 1, 2026) - SITE, LAB DATE & ANOMALY TYPE CLASSIFICATION
**Major Feature**: New metadata fields and ML-based anomaly reason classification

#### Silver Layer Additions
- **`site`**: Location where the machine operates
  - CDA/EMIN: Default value "Área Mina"
  - ENEX: Extracted from bronze "Site" column, fallback to "Área Mina"
  
- **`labDate`**: Date the sample was processed at the laboratory
  - CDA: From bronze "Fecha de laboratorio"
  - EMIN: From bronze "dateOfEntryIntoLaboratory"
  - ENEX: From bronze "Date Diagnosed"

#### Golden Layer Additions
- **`anomalyType`**: Predicted anomaly reason for non-Normal reports
  - Values: 'Normal' (default for Normal reports), or one of:
    - 'Desgaste de Componentes'
    - 'Contaminación Lubricante'
    - 'Código ISO 4406 - Sílice'
    - 'Contaminación Sílice - Desgaste'
    - 'Contaminación Agua'
    - 'Combustión Deficiente - Desgaste'
    - 'Dilución Combustible'
  - Only predicted when `report_status` != 'Normal'
  - Uses DecisionTreeClassifier trained on external lab data
  - Model artifact: `models/anomaly_type_tree.joblib`
  - Training columns: `models/anomaly_type_columns.joblib`
  - Training script: `scripts/train_anomaly_model.py`

#### New Files
- `src/ai/anomaly_model.py`: Training and inference for anomaly type model
- `scripts/train_anomaly_model.py`: CLI script to train/retrain the model
- `models/anomaly_type_tree.joblib`: Trained model artifact
- `models/anomaly_type_columns.joblib`: Feature column alignment artifact

#### Migration Notes
- Backward compatible: Old tools can ignore new columns
- Model must be trained before running pipeline: `python scripts/train_anomaly_model.py`
- If model not found, `anomalyType` defaults to 'Normal' for all samples

---

### Version 2.3 (May 13, 2026) - OIL-HOUR STRATIFIED STEWART LIMITS + EVOLUTION RATIO LIMITS
**Major Feature**: Oil-Hour Stratification and Evolution Ratio Analysis

#### Silver Layer Additions
- **`oilHourRange`**: Categorical column for oil age grouping
  - Values: 'LT_1000' (fresh oil, <1000 hours), 'GE_1000' (aged oil, >=1000 hours), 'UNKNOWN' (missing oilMeter)
  - Purpose: Different essay behavior in fresh vs aged oil requires separate statistical limits
  
- **`evolution_ratio_{essay}`**: Normalized concentration per oil hour (21 new columns)
  - Formula: `essay_value / oilMeter`
  - Example: 80 ppm Hierro ÷ 800 hours = 0.10 ppm/hour
  - Purpose: Early trend detection normalized by oil age
  - Edge case: null or ≤0 oilMeter → null ratio (prevents division errors)

#### Golden Layer Changes

**`stewart_limits.parquet` - Schema Extended**:
- **`oilHourRange`**: Oil age category used for this limit group
- **`sample_count`**: Number of samples used in percentile calculation
- **`calculation_date`**: ISO timestamp of when limits were calculated
- Grouping changed from `[client, machine, component, essay]` to `[client, machine, component, essay, oilHourRange]`
- Sample count increased ~3x due to stratification (~900-1500 combinations per client)

**`stewart_limits_ratio.parquet` - New File**:
- Statistical limits for evolution ratios (ppm/hour)
- **Not stratified by oilHourRange** - uses all data together for global ratio limits
- Columns: client, machine, component, essay, ratio_threshold_normal/alert/critic, sample_count, calculation_date
- **No oilHourRange column** - evolution ratios already normalize for oil age
- **Decimal precision**: 4 decimal places for ratio thresholds
- Purpose: Complementary classification based on normalized degradation rate

**`classified.parquet` - New Columns**:
- **`limit_source`**: Tracks which limit was used
  - 'oil_hour_stratified': Exact match for oilHourRange (preferred)
  - 'fallback_global': Averaged across all oil hour ranges
  - 'missing': No limits available
- **`ratio_limit_source`**: Tracks ratio limit source (future use)
  - Currently: 'not_implemented'
- All `oilHourRange` and `evolution_ratio_*` columns from Silver layer preserved

#### Classification Logic Updates
- **Stratified Limit Selection**: Each sample classified using its oilHourRange-specific limits
- **Fallback Hierarchy**: 
  1. Try exact match: client + machine + component + essay + oilHourRange
  2. If missing: Average across all available oil hour ranges
  3. If still missing: Mark as 'missing' and skip classification
- **Traceability**: `limit_source` column enables debugging and quality monitoring

#### S3 Storage
- New file: `s3://{BUCKET}/MultiTechnique Alerts/oil/golden/{client}/stewart_limits_ratio.parquet`
- All other file paths unchanged

#### Benefits
- **Improved Accuracy**: Separate limits for fresh vs aged oil reduces false positives/negatives
- **Early Detection**: Evolution ratios catch accelerating degradation trends earlier
- **Transparency**: Limit source tracking enables quality monitoring and debugging
- **Graceful Degradation**: Fallback behavior ensures classification even with limited data

#### Migration Notes
- Backward compatible: Old tools can ignore new columns
- Recalculation required: Historical mode must be run to generate stratified limits
- No data loss: All Silver layer columns preserved in Golden layer

---

### Version 2.2 (April 9, 2026) - MACHINE-LEVEL AI RECOMMENDATIONS
- **Machine-Level AI**: Added `machine_ai_recommendation` field to machine_status.parquet
  - AI recommendations now generated at both sample level and machine level
  - Machine-level AI provides holistic equipment assessment across all components
  - Accounts for component criticality weights in recommendations
  - Only generated for non-Normal machines (Alerta/Anormal status)
  - Uses GPT-4o-mini with specialized mechanical engineering prompt
- Reduces need to review individual component reports for overview

### Version 2.1 (April 7, 2026) - HIERARCHY IMPROVEMENTS
- **Essay Hierarchy**: Added `desgaste_score` column to classified reports
  - Only Desgaste (wear) essays now affect report status
  - Contamination/additive essays tracked but don't trigger alerts
  - Reduces false positives by ~30-40%
- **Component Hierarchy**: Implemented weighted scoring for machine status
  - Critical components (motor, transmision): 1.0x weight
  - Important components (convertidor, diferencial): 0.5x weight
  - Other components: 0.25x weight
  - Better prioritization of maintenance resources
- Updated `breached_essays` to include essay group information
- Added `weight` field to component_details in machine_status
- See [HIERARCHY_IMPROVEMENTS.md](HIERARCHY_IMPROVEMENTS.md) for details

### Version 2.0 (February 3, 2026)
- Simplified folder structure: bronze/silver/golden
- Changed from `{client}_classified.parquet` to `golden/{client}/classified.parquet`
- Added S3 auto-upload functionality
- Split Stewart Limits per client (no more shared file)
- Removed Excel exports (Parquet only)
- Updated to use client-specific folders in golden layer

### Version 1.0 (January 2026)
- Initial data contracts
- Three-layer architecture (raw/processed/to_consume)
- Shared Stewart Limits file
