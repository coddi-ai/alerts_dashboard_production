# Multi-Technical Alerts Dashboard - Overview

**Version**: 2.1.0  
**Last Updated**: April 10, 2026  
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

The dashboard integrates four primary data sources:

### 1. **Oil (Tribology Analysis)**
- **Purpose**: Analyze oil samples to detect component wear and contamination
- **Frequency**: Periodic sampling (weekly/monthly)
- **Key Outputs**: Essay classifications, component health status, AI recommendations
- **Status**: ✅ **Fully Implemented**

### 2. **Telemetry (Sensor Data)**
- **Purpose**: Real-time monitoring of equipment sensors and operational parameters
- **Frequency**: Continuous streaming data
- **Key Outputs**: Sensor alerts, trend analysis, operational state tracking
- **Status**: 🔄 **In Progress**

### 3. **Mantentions (Maintenance Records)**
- **Purpose**: Track maintenance activities and intervention history
- **Frequency**: Weekly reports
- **Key Outputs**: Maintenance summaries, activity tracking per system
- **Status**: 🔄 **In Progress**

### 4. **Alerts (Consolidated)**
- **Purpose**: Unified view of all alerts across techniques
- **Frequency**: Real-time aggregation
- **Key Outputs**: Consolidated alerts with AI diagnosis, cross-technique correlation, evidence sections
- **Status**: ✅ **Fully Implemented** (February 18, 2026)

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
└── alerts/
    └── golden/{client}/
```

**Path Pattern**: `data/{technique}/{layer}/{client}/{datafile}`

Where:
- **technique**: `oil`, `telemetry`, `mantentions`, `alerts`
- **layer**: `silver` (harmonized data), `golden` (analysis-ready outputs)
- **client**: Client identifier
- **datafile**: Specific data files based on data contracts

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

**Navigation Sections**:
1. **Overview** (dashboard icon)
   - General
2. **Monitoring** (chart icon)
   - Alerts
   - Telemetry
   - Health Index
   - Mantentions
   - Oil
3. **Limits** (sliders icon)
   - Oil

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

The dashboard is organized into three main sections, each serving a specific purpose:

### 1. **Overview Section**

**Purpose**: Provide a high-level summary of fleet health

**Features**:
- Overall fleet condition metrics
- Aggregated alert counts across all techniques
- Equipment availability statistics
- Key performance indicators (KPIs)

**Sub-sections**:
- **General**: Fleet-wide summary dashboard

**Data Sources**: All (Oil, Telemetry, Mantentions, Alerts)

**Status**: 🔄 In Progress

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
    - Oil evidence (radar chart with essay levels)
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

#### 2.2 **Telemetry**
- **Purpose**: Hierarchical sensor monitoring from fleet-wide health to signal-level diagnosis
- **Tabs**:
  - **Fleet Overview**: High-level fleet health snapshot
    - KPI Cards: Total Units, Normal %, Alerta %, Anormal %
    - Fleet Status Table: Sortable by priority_score, component counts
    - Status Distribution Pie Chart: Visual fleet health breakdown
  - **Machine Detail**: Component-level analysis for specific units
    - Machine selector with status badges
    - Component Status Table: Detailed component health
    - Component Radar Chart: Multi-axis visualization of component scores
    - Component Details Accordion: Expandable evidence panels
  - **Component Detail**: Signal-level evaluations with historical baselines
    - Signal Evaluation Table: Window scores, severity, weight, data quality
    - Weekly Distribution Boxplots: Historical comparison across weeks
    - Estado filter: Operacional, Ralenti, Apagada state-specific analysis
    - Signal drill-down modal: Detailed baseline comparison with P2/P5/P95/P98 thresholds
  - **Limits**: Baseline threshold management and visualization
    - Baseline Thresholds Table: Display P2, P5, P95, P98 percentiles per signal
    - Training window metadata
    - Threshold Distribution Histogram: Visualize baseline calculation
- **Data Sources**: 
  - `telemetry/golden/{client}/machine_status.parquet` (fleet-level summaries)
  - `telemetry/golden/{client}/classified.parquet` (component-level evaluations)
  - `telemetry/golden/{client}/baselines/baseline_YYYYMMDD.parquet` (percentile thresholds)
  - `telemetry/silver/{client}/Telemetry_Wide_With_States/ww-yyyy.parquet` (raw sensor data)
- **Key Features**:
  - Severity-Weighted Percentile Window Scoring methodology
  - Hierarchical drill-down navigation (Fleet → Machine → Component → Signal)
  - State-aware baseline comparisons (Operacional, Ralenti, Apagada)
  - Component criticality weighting for machine-level status
  - Weekly evaluation with multi-week historical comparison
  - JSON-based nested data structures (component_details, signals_evaluation)
- **Status**: 🔄 **In Progress** (February 26, 2026 - Prototyping Phase)

#### 2.3 **Mantentions**
- **Purpose**: Maintenance activity tracking
- **Features**:
  - Intervention history per unit
  - Maintenance frequency analysis
  - Activity breakdown by system
- **Data Source**: `mantentions/golden/{client}/ww-yyyy.csv`
- **Status**: 🔄 Planned

#### 2.4 **Oil**
- **Purpose**: Tribology analysis and component health
- **Features**:
  - Essay classifications
  - Radar charts for component analysis
  - Time series trends
  - AI recommendations
- **Data Sources**: 
  - `oil/golden/{client}/classified.parquet`
  - `oil/golden/{client}/machine_status.parquet`
- **Status**: ✅ **Fully Implemented**

---

### 3. **Limits Section**

**Purpose**: Display thresholds and triggers for alert generation

**Features**:
- Configurable limit tables
- Threshold visualization
- Statistical analysis of limits

**Sub-sections**:

#### 3.1 **Oil Limits**
- **Purpose**: Stewart Limits for essay classifications
- **Features**: 
  - Limits by machine/component/essay
  - Threshold distribution charts
  - Sample count statistics
- **Data Source**: `oil/golden/{client}/stewart_limits.parquet`
- **Status**: ✅ **Fully Implemented**

#### 3.2 **Telemetry Limits**
- **Purpose**: Baseline percentile thresholds for sensor anomaly detection
- **Features**:
  - Baseline Thresholds Table: Display P2, P5, P95, P98 percentiles per signal
  - Training window metadata: Shows baseline version and training period
  - Threshold Distribution Histogram: Visualize training data distribution with percentile lines
  - Filter by Unit, Signal, EstadoMaquina
  - State-specific thresholds (Operacional, Ralenti, Apagada)
- **Data Sources**: 
  - `telemetry/golden/{client}/baselines/baseline_YYYYMMDD.parquet`
  - `telemetry/silver/{client}/Telemetry_Wide_With_States/ww-yyyy.parquet` (for visualizations)
- **Key Concepts**:
  - P2/P98: Extreme bounds (alarm thresholds)
  - P5/P95: Alert bounds (early warning)
  - Training window: Historical data period used to compute percentiles
- **Status**: 🔄 **In Progress** (February 26, 2026 - Prototyping Phase)

---

## 🏢 Multi-Client Architecture

The dashboard is designed as a **SaaS platform** supporting multiple clients with isolated data:

### Client Isolation

- **Data Separation**: Each client has dedicated folders
- **Independent Processing**: Clients processed separately
- **Isolated Limits**: Thresholds calculated per client
- **Secure Access**: Authentication and authorization per client

### Client Selection

Users select their client context through a global dropdown that filters all dashboard views to show only relevant data.

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
