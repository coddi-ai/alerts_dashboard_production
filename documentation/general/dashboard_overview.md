# Multi-Technical Alerts Dashboard - Overview

**Version**: 2.4.0  
**Last Updated**: August 4, 2026  
**Owner**: Technical Alerts Team

---

## 📋 Table of Contents

1. [Overview](#overview)
2. [Dashboard Purpose](#dashboard-purpose)
3. [Data Sources](#data-sources)
4. [Dashboard Architecture](#dashboard-architecture)
5. [User Interface Design](#user-interface-design)
6. [Dashboard Sections](#dashboard-sections)
7. [Multi-Client Architecture](#multi-client-architecture)

---

## 🎯 Overview

The Multi-Technical Alerts Dashboard is a comprehensive fleet monitoring platform that provides **real-time insights into equipment health** by integrating multiple data sources. The dashboard enables maintenance teams to proactively identify issues, optimize equipment availability, and make data-driven decisions.

**Key Objective**: Allow users to understand the state of the fleet based on the latest available data across all monitoring techniques.

---

## 🚀 Dashboard Purpose

The dashboard consolidates data from multiple monitoring techniques to create **contextualized alerts** that point to deficiencies in fleet machine performance. These alerts are generated through sophisticated logic applied to:

- **Sensor data** (Telemetry)
- **Tribology analysis** (Oil)
- **Maintenance records** (Mantentions)

The platform provides intuitive visualizations that help users:
- ✅ Understand overall fleet health
- ✅ Identify machines requiring attention
- ✅ Track trends and patterns over time
- ✅ Access AI-generated recommendations
- ✅ Monitor alert triggers and thresholds

---

## 📊 Data Sources

The dashboard integrates five primary data sources, all consumed as pre-processed Gold-layer
files under `data/{technique}/golden|silver/{client}/`. **This repository does not process raw
data** — it reads the output of an upstream data pipeline, syncing it from S3 on startup if the
local `data/` folder is absent (see `src/data/s3_downloader.py`).

### 1. **Oil (Tribology Analysis)**
- **Purpose**: Analyze oil samples to detect component wear and contamination
- **Frequency**: Periodic sampling (weekly/monthly)
- **Key Outputs**: Essay classifications, component health status, AI recommendations, lab
  turnaround-time compliance
- **Status**: ✅ **Fully Implemented**

### 2. **Telemetry (Sensor Data)**
- **Purpose**: Monitoring of equipment sensors and operational parameters
- **Frequency**: Weekly-aggregated silver-layer snapshots
- **Key Outputs**: Fleet/system status matrix, unit → system → signal drill-down with AI commentary
- **Status**: 🔄 **In Progress** (functional fleet + unit-detail views; a previously-planned
  signal-level baseline "Limits" UI, showing P2/P5/P95/P98 percentile thresholds per signal, is
  not currently wired into navigation)

### 3. **Mantentions (Maintenance Records)**
- **Purpose**: Track maintenance activities and intervention history
- **Frequency**: Weekly reports
- **Key Outputs**: Maintenance summaries, activity tracking per system; also feeds the Resumen
  General status table (via `src/data/maintenance_repository.py`)
- **Status**: 🔄 **In Progress** (data loaders exist and feed Overview/Predictive; there is no
  standalone Mantentions tab in navigation yet)

### 4. **Alerts (Consolidated)**
- **Purpose**: Unified view of all alerts across techniques
- **Frequency**: Real-time aggregation
- **Key Outputs**: Consolidated alerts with AI diagnosis, cross-technique correlation, evidence sections
- **Status**: ✅ **Fully Implemented** (February 18, 2026)

### 5. **Predictive (Failure-Mode KPIs)**
- **Purpose**: Component-level (e.g. Motor, Transmisión) failure-mode risk scoring combining oil
  and telemetry evidence with narrative insights
- **Frequency**: Per-component CSVs, auto-discovered per client
- **Key Outputs**: Fleet KPIs, priority cards, failure-mode table, per-unit evidence view
- **Status**: ✅ **Implemented**, restricted to clients in `predictive_allowed_clients`
  (currently CDA, CAPSTONE)

---

## 🏗️ Dashboard Architecture

### Data Layer Structure

The dashboard follows a **Data Mesh architecture** with the following structure:

```
data/
├── oil/
│   ├── silver/{client}/
│   └── golden/{client}/
├── telemetry/
│   ├── silver/{client}/
│   └── golden/{client}/
├── mantentions/
│   └── golden/{client}/
├── alerts/
│   └── golden/{client}/
├── predictive/
│   └── golden/{client}/{component}.csv
└── auxiliar/
    └── {client}/Data_Date_Last_Update.csv
```

**Path Pattern**: `data/{technique}/{layer}/{client}/{datafile}`

Where:
- **technique**: `oil`, `telemetry`, `mantentions`, `alerts`, `predictive`
- **layer**: `silver` (harmonized data), `golden` (analysis-ready outputs)
- **client**: Client identifier
- **datafile**: Specific data files based on data contracts

`auxiliar/` is a non-technique folder used by the Data Freshness view and does not follow the
`{technique}/{layer}/{client}` pattern.

### Technology Stack

- **Frontend**: Dash (Plotly)
- **Data Processing**: Python, Pandas
- **Storage**: Parquet files (columnar format)
- **Deployment**: Docker containers
- **AI Integration**: LLM-based recommendations

### User Interface Design

**Version 2.1** (April 2026) introduced a comprehensive layout redesign focused on professional appearance, improved usability, and modern web application standards.

#### Header / App Bar

The top navigation bar provides a **branded, professional entry point** with clear visual hierarchy:

**Design Features**:
- **Enhanced Logo Visibility**: Logo displayed in white container with rounded corners and subtle shadow for maximum contrast
- **Dual-Level Branding**: Platform name with secondary tagline for context
- **Integrated Client Selector**: Global client context control positioned prominently in header
- **User Profile Section**: Clean display of username, role, and logout functionality with icon support
- **Visual Styling**:
  - Fixed positioning (80px height) for persistent access
  - Dark background (#1a252f) with accent border (#3498db)
  - Professional shadow for depth and separation
  - Consistent spacing with 28px padding

**Key Elements** (left to right):
1. **Logo** (with white background treatment)
2. **Platform Title** ("Plataforma de Monitoreo Multi-Técnica")
3. **Client Context Selector** (dropdown, auto-right aligned)
4. **User Info** (username, role badge)
5. **Logout Button** (danger color, prominent)

#### Full-Height Sidebar Navigation

The left sidebar provides **persistent, hierarchical navigation** throughout the application:

**Design Features**:
- **Full Viewport Height**: Extends from header (80px) to bottom with no gaps
- **Fixed Positioning**: 260px width, always visible during scroll
- **Visual Continuity**: Connects seamlessly with header for unified shell layout
- **Hierarchical Structure**:
  - Section headers (uppercase, bold, with icons)
  - Subsection menu items (indented, with chevron indicators)
- **Interactive States**:
  - Hover: Light blue background, subtle right shift, chevron animation
  - Active: Blue accent border, darker background, bold text
  - Transition animations for smooth interactions

**Navigation Sections** (built dynamically in `dashboard/layout.py::create_main_dashboard`):
1. **Resumen / Overview** (dashboard icon)
   - General
   - Estado de Datos (Data Freshness)
2. **Monitoreo / Monitoring** (chart icon)
   - Alertas (Alerts)
   - Telemetría (Telemetry)
   - Aceite (Oil — includes the Cumplimiento Laboratorio lab-compliance view internally)
3. **Predictivo / Predictive** (brain icon) — *shown only if the logged-in user's client is in
   `predictive_allowed_clients`*
   - One subsection per auto-discovered component (e.g. Motor, Transmisión)
4. **Integración / Integration** (plug icon) — placeholder ("En Desarrollo")
5. **Reportes / Reporting** (file icon) — placeholder ("En Desarrollo")
6. **Administración / Admin** (gear icon) — placeholder ("En Desarrollo")

Several tab/callback modules exist in the codebase but are currently **commented out of
navigation** (shelved or superseded): standalone Stewart Limits, Machines Overview, and Reports
Detail tabs (superseded by the Aceite subsections), Mantenciones General, Health Index, Menace
Control, and Hot Sheet. The Component Hours ("Horómetro") tab is also commented out of the Aceite
tab bar, though its data loader is still used internally by the Predictive section.

**Styling Details**:
- Background: #2c3e50 (dark blue-gray)
- Typography: Clean sans-serif with varied weights for hierarchy
- Spacing: 24px header padding, 12px item spacing
- Icons: FontAwesome 5 for consistent iconography
- Scrollable menu area for extensibility

#### Content Area Layout

The main content area provides **optimized space for visualizations and data**:

**Design Features**:
- **Proper Margins**: Left margin (260px) + top margin (80px) to accommodate fixed header/sidebar
- **Clean Background**: Light gray (#f8f9fa) for contrast with white cards
- **Generous Padding**: 28px padding for breathing room
- **Full Viewport Usage**: min-height ensures full page coverage

#### Global Controls

**Client Context Selector**:
- **Location**: Header (between branding and user info)
- **Purpose**: Global filter affecting all dashboard views
- **Behavior**: Persistent across all sections, non-clearable
- **Styling**: White background dropdown with 200px minimum width

#### Layout Consistency

**Spacing System**:
- Header height: 80px (fixed)
- Sidebar width: 260px (fixed)
- Content padding: 28px (standard)
- Element spacing: 12px (small), 24px (medium), 32px (large)

**Color Palette**:
- Primary brand: #3498db (blue)
- Dark backgrounds: #1a252f (header), #2c3e50 (sidebar)
- Content background: #f8f9fa (light gray)
- Text: White on dark, dark on light
- Accents: rgba overlays for hover states

**Typography Scale**:
- Page titles: 1.1rem, weight 700
- Section headers: 0.95rem, weight 600, uppercase
- Menu items: 0.9rem, weight 400-600
- Body text: 0.9rem, weight 400

#### Responsive Behavior

- Fixed header maintains branding and global controls on scroll
- Sidebar remains accessible at all times
- Content area scrolls independently
- Consistent layout across different screen heights

---

## 🎨 Dashboard Sections

The dashboard is organized into the sections below (see [Dashboard Architecture](#dashboard-architecture)
for the full navigation tree):

### 1. **Resumen (Overview) Section**

**Purpose**: Provide a high-level summary of fleet health

**Sub-sections**:

#### 1.1 **General**
- Single unified per-unit status table combining Telemetría, Alertas, Data Freshness, and the
  latest Tribología (oil) result for the selected client
- **Data Sources**: `telemetry` (unit health), `mantentions` (status/downtime via
  `maintenance_repository.py`), `oil/golden/{client}/machine_status.parquet`,
  `alerts/golden/{client}/consolidated_alerts.csv`, `data/auxiliar/{client}/Data_Date_Last_Update.csv`
- **Status**: ✅ **Implemented**

#### 1.2 **Estado de Datos (Data Freshness)**
- Per-unit traffic-light table (🟢/🟡/🔴) showing how stale Telemetría and Tribología data are
  - 🟢 Telemetría < 1h / Tribología < 1 week
  - 🟡 Telemetría 1–4h / Tribología 1–2 weeks
  - 🔴 Telemetría > 4h / Tribología > 2 weeks
- Source timestamps are stored UTC and displayed converted to `America/Santiago`
- **Data Source**: `data/auxiliar/{client}/Data_Date_Last_Update.csv`
- **Status**: ✅ **Implemented** (see [DATA_FRESHNESS_TAB.md](DATA_FRESHNESS_TAB.md) and
  [DATA_FRESHNESS_IMPLEMENTATION.md](DATA_FRESHNESS_IMPLEMENTATION.md) for detailed design)

---

### 2. **Monitoring Section**

**Purpose**: Detailed monitoring and analysis per technique

**Features**:
- Technique-specific visualizations
- Drill-down capabilities for detailed analysis
- Historical trend analysis
- AI-generated insights

**Sub-sections**:

#### 2.1 **Alerts**
- **Purpose**: Unified view of all alerts across techniques
- **Tabs**:
  - **General**: Alert overview with distribution charts
    - Distribution by Unit (horizontal bar chart)
    - Distribution by Month (vertical bar chart)
    - Distribution by Trigger (treemap)
    - Distribution by Sistema (pie chart)
    - Interactive alerts table with filtering
  - **Detail**: Individual alert inspection with comprehensive evidence
    - Alert specifications with AI diagnosis
    - Telemetry evidence (sensor trends, GPS route, KPIs)
    - Oil evidence — "Análisis de Aceite" selector: **Tendencia** (default; the same time-series
      chart grid used in Aceite → Detalle de Reporte, scoped to the alert's equipment/component)
      or **Último Ensayo** (radar chart with essay levels for the alert's oil report)
    - Maintenance evidence (activity summaries)
- **Data Sources**: 
  - `alerts/golden/{client}/consolidated_alerts.csv`
  - `telemetry/golden/{client}/alerts_detail_wide_with_gps.csv`
  - `oil/golden/{client}/classified.parquet`
  - `mantentions/golden/{client}/ww-yyyy.csv`
- **Key Features**:
  - Spanish feature name mapping for sensor data
  - Standard sistema color mapping (Tren de Fuerza, Motor, Frenos, Direccion)
  - Conditional evidence display based on alert trigger type
  - Golden layer optimization for fast loading
  - Responsive charts with optimized legends
- **Status**: ✅ **Fully Implemented** (February 18, 2026)

#### 2.2 **Telemetría (Telemetry)**
- **Purpose**: Sensor-based health monitoring, from fleet-wide status down to unit/system/signal detail
- **Tabs**:
  - **Vista de Flota**: Compact fleet matrix of unit × system status, filterable by model/status/system
  - **Detalle de Unidad**: Unit → system → signal drill-down table with AI-generated commentary
- **Data Sources**:
  - `telemetry/silver/{client}/.../Week{NN}Year{YYYY}.parquet` (weekly sensor snapshots)
  - Unit-level health aggregation via `load_telemetry_unit_health` (also feeds Resumen General)
- **Status**: 🔄 **In Progress** — functional fleet + unit-detail views; the previously-planned
  signal-level baseline "Limits" sub-tab (P2/P5/P95/P98 percentile thresholds) is not yet wired
  into navigation

#### 2.3 **Mantenciones (Maintenance)**
- **Purpose**: Maintenance activity tracking
- **Current state**: No standalone tab in navigation (`tab_mantenciones_general.py` exists but is
  commented out in `dashboard/layout.py`). Maintenance status/downtime data is currently surfaced
  indirectly through the Resumen General status table via `src/data/maintenance_repository.py`
- **Data Source**: `mantentions/golden/{client}/ww-yyyy.csv`
- **Status**: 🔄 Planned

#### 2.4 **Aceite (Oil)**
- **Purpose**: Tribology analysis and component health
- **Tabs** (`dashboard/tabs/tab_oil.py`):
  - **Visión de Flota**: machine status distribution and priority table
  - **Detalle de Reporte**: evidence tables, time series vs. four-limit Stewart thresholds
    (LIC/LIM/LSM/LSC, v2.8), AI recommendations
  - **Cumplimiento Laboratorio**: transit-time (sample→lab) and lab-time (lab→report) KPIs,
    weekly grouped bar chart, per-unit delay chart
- **Data Sources**:
  - `oil/golden/{client}/classified.parquet`
  - `oil/golden/{client}/machine_status.parquet`
  - `oil/golden/{client}/stewart_limits_four.parquet` (LIC/LIM/LSM/LSC thresholds used in Detalle
    de Reporte; legacy `stewart_limits.parquet`/`stewart_limits_inferior.parquet` no longer used
    by oil-technique dashboard logic)
- **Status**: ✅ **Fully Implemented**

---

### 3. **Predictivo (Predictive) Section**

**Purpose**: Component-level failure-mode risk scoring combining oil and telemetry evidence

**Visibility**: Only shown to users whose client is listed in `predictive_allowed_clients`
(`config/settings.py`, currently CDA and CAPSTONE)

**How it works**: Components (e.g. Motor, Transmisión) are auto-discovered per client from CSVs
under `data/predictive/golden/{client}/*.csv`; each gets its own sidebar subsection and its own
KPI thresholds/failure-mode configuration (`dashboard/components/predictive_config.py`)

**Tabs per component** (`tab_predictive_component.py`):
- **Resumen**: fleet KPIs, an "Análisis de Riesgo" selector (**Prioridad Actual**, default — the
  priority cards; or **Riesgo Acumulado** — the cumulative-risk curve vs. a fleet reference band),
  and the failure-mode table (`tab_predictive_overview.py`)
- **Evidencia**: per-unit oil/telemetry evidence with narrative insights (`tab_predictive_evidence.py`)

**Data Sources**:
- `predictive/golden/{client}/{component}.csv`
- Component operating hours via `load_component_hours` for clients in
  `component_hours_allowed_clients` (CDA, ENEX)

**Status**: ✅ **Implemented**

---

### 4. **Integración / Reportes / Administración**

Reserved top-level navigation sections (`dashboard/layout.py`) that currently render a generic
"En Desarrollo" placeholder (`create_placeholder_content`). No functionality is implemented yet.

**Status**: 🔄 Planned

---

## 🏢 Multi-Client Architecture

The dashboard is designed as a **SaaS platform** supporting multiple clients with isolated data.
Active clients (`config/settings.py::Settings.clients`): **CDA, EMIN, ENEX, CAPSTONE**, each with
its own logo served from `dashboard/logos/` and its own set of user accounts in `config/users.py`.

### Client Isolation

- **Data Separation**: Each client has dedicated folders (`data/{technique}/{layer}/{client}/`)
- **Independent Processing**: Clients processed separately upstream
- **Isolated Limits**: Thresholds calculated per client
- **Secure Access**: Authentication and per-client authorization (`dashboard/auth.py`,
  `config/users.py`)
- **Module Gating**: Some sections (Predictivo, Component Hours) are restricted to a subset of
  clients via `predictive_allowed_clients` / `component_hours_allowed_clients`

### Client Selection

Users select their client context through a global dropdown in the header (`client-selector`)
that filters all dashboard views to show only relevant data.

### Scalability

The architecture supports:
- ✅ Adding new clients without code changes
- ✅ Different data sources per client
- ✅ Client-specific configurations
- ✅ Independent update schedules

---

## 📈 Alert Generation Logic

Alerts are generated through technique-specific logic:

### Oil Alerts
- Based on Stewart Limits (90th, 95th, 98th percentiles)
- Essay scoring system
- Component-level classification

### Telemetry Alerts
- Threshold-based detection
- State-aware limits (Operational, Idle, etc.)
- Trend analysis for anomaly detection

### Consolidated Alerts
- Cross-technique correlation
- AI-powered diagnosis
- System/subsystem/component mapping

### Predictive Failure Modes
- Per-component (Motor, Transmisión, …) risk scoring combining oil and telemetry evidence
- Priority ranking and narrative insights, restricted to `predictive_allowed_clients`

---

## 🎯 User Benefits

1. **Proactive Maintenance**: Identify issues before failure
2. **Reduced Downtime**: Quick identification of critical alerts
3. **Data-Driven Decisions**: AI recommendations based on multiple data sources
4. **Fleet Visibility**: Comprehensive view of all equipment
5. **Cost Optimization**: Prioritize maintenance activities efficiently

---

## 📚 Related Documentation

- **Data Contracts**:
  - [Oil Data Contracts](../oil/DATA_CONTRACTS.md)
  - [Telemetry Data Contracts](../telemetry/data_contracts.md)
  - [Mantentions Data Contracts](../mantentions/data_contracts.md)
  - [Alerts Data Contracts](../alerts/data_contracts.md)

- **Technical Documentation**:
  - [Migration Plan](migration_plan.md)
  - [Deployment Guide](../../DEPLOY_GUIDE.md)
  - [Component Granularity](../oil/COMPONENT_GRANULARITY_FIX.md)

---

## 🔄 Version History

### Version 2.4.0 (August 2026)
- **Four-Limit Stewart Migration**: All oil-technique dashboard logic (Monitoring ▸ Aceite ▸
  Detalle de Reporte, Alertas ▸ Detalle ▸ Evidencia de Aceite, and the unreachable Stewart Limits
  tab) now reads `stewart_limits_four.parquet` (`LIC`/`LIM`/`LSM`/`LSC`, data contract v2.8)
  instead of the legacy `stewart_limits.parquet`/`stewart_limits_inferior.parquet` pair
- **Five-Tier Classification**: New shared classifier
  (`dashboard/components/oil_charts.py::classify_four_limit_value`) replaces the old
  Normal/Marginal/Condenatorio/Crítico 4-tier scheme with Inferior Condenatorio/Inferior
  Marginal/Normal/Superior Marginal/Superior Condenatorio, correctly supporting null lower limits
  (`LIC`/`LIM` are null for Desgaste/Aditivo essay groups and never treated as zero)
- **Charts**: Time-series charts, the 9-chart grid, and radar charts no longer render a
  lower-limit trace/ring when `LIC`/`LIM` are null for that essay
- See [oil_data_contracts.md](../oil/oil_data_contracts.md) (v2.8) and
  [dashboard_documentation.md](../oil/dashboard_documentation.md) ("Current Classification
  Behavior (v2.8+)") for full detail

### Version 2.3.0 (August 2026)
- **Root Redirect Verified**: Confirmed the base dashboard URL (with or without `DASH_PATH_PREFIX`)
  redirects once to `/overview/general` via `dashboard/pages/index.py` — no code change needed
- **Oil Evidence Selector**: Alerts → Detail → Oil Evidence now offers **Tendencia** (default —
  the same time-series chart grid as Aceite → Detalle de Reporte, scoped to the alert's
  equipment/component) and **Último Ensayo** (the existing radar chart, unchanged). The grid
  builder was extracted to `dashboard/components/oil_charts.py` and is now shared by both views
- **Predictivo "Análisis de Riesgo" Selector**: The Resumen tab's priority cards and the
  previously-undocumented accumulated-risk curve are now presented under one selector —
  **Prioridad Actual** (default) and **Riesgo Acumulado** — instead of always stacking both;
  calculations for either are unchanged. See [Curva Acumulada de Riesgo](../predictive/project_overview.md#curva-acumulada-de-riesgo)
  for the curve's full documented behavior

### Version 2.2.0 (July 2026)
- **Predictivo Module**: New Predictive section with per-component (Motor, Transmisión) failure-mode
  KPIs, priority cards, and evidence views, auto-discovered per client and gated by
  `predictive_allowed_clients`
- **Resumen Restructure**: Overview section split into "General" (unified per-unit status table
  spanning Telemetría/Alertas/Mantenciones/Tribología) and "Estado de Datos" (data freshness
  traffic-light table)
- **Lab Compliance**: New "Cumplimiento Laboratorio" tab inside Aceite tracking sample transit
  and lab turnaround times
- **Telemetry Simplification**: Consolidated to two tabs (Vista de Flota, Detalle de Unidad);
  the previously-planned signal-level baseline/limits UI is not currently wired into navigation
- **Standalone Limits Section Removed from Nav**: The former top-level "Limits" sidebar section
  (Oil Limits, Telemetry Limits) is no longer part of navigation; Stewart Limits data is now
  surfaced contextually inside the Aceite → Detalle de Reporte view. The old standalone
  Stewart Limits/Machines/Reports tabs, Health Index, Menace Control, Hot Sheet, and Mantenciones
  General tabs remain in the codebase but are commented out of `dashboard/layout.py`
- **New Client**: Added CAPSTONE (alongside CDA, EMIN, ENEX), each with a dedicated logo
- **Expanded User Base**: Additional named admin/client accounts in `config/users.py`
- **Dashboard-Only Repository**: Data processing (`main.py`, `src/processing/classification.py`)
  moved out of this repo; the dashboard now consumes Gold-layer output directly and syncs it from
  S3 on startup if missing locally

### Version 2.1.0 (April 2026)
- **Major UI/UX Redesign**: Professional dashboard layout overhaul
- **Enhanced Header**: Improved logo visibility with white container treatment, dual-level branding
- **Global Client Selector**: Moved to header as primary control for better UX
- **Full-Height Sidebar**: Seamless navigation layout with no gaps, fixed positioning
- **Improved Navigation Styling**: Interactive states (hover, active) with smooth transitions
- **Consistent Spacing System**: Standardized margins, padding across all layout components
- **Visual Hierarchy**: Clear typography scale, color palette, and element organization
- **Unified Shell Layout**: Header, sidebar, and content area work as cohesive application framework

### Version 2.0.0 (February 2026)
- Multi-technique integration architecture
- Consolidated alerts system with full implementation
- Alerts General and Detail tabs operational
- Enhanced navigation with sections/subsections
- Scalable multi-client platform
- Golden layer optimization for performance
- Spanish translations and standard color schemes

### Version 1.0.0 (January 2026)
- Initial oil analysis dashboard
- Stewart Limits implementation
- Basic machine monitoring
