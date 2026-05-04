
# 📄 Multi-Technique Alerts Dashboard

## UI/UX & Visualization Requirements Specification

---

# 1. Objective

Redesign the existing alert dashboard to:

* Improve **visual hierarchy and readability**
* Ensure **clear interpretation of asset condition**
* Integrate **telemetry + tribology insights coherently**
* Optimize **user decision-making flow**
* Eliminate **redundant or low-value visual components**

The system must clearly answer:

> **What is happening, why, how critical it is, and what action should be taken**

---

# 2. Global Design Requirements

## 2.1 Visual System Standardization

* A unified **design system must be enforced** across the entire dashboard.
* All visual elements must adhere to:

  * A **restricted color palette**
  * A **consistent typography hierarchy**
  * A **standardized spacing system**

### Color Usage Constraints

* Colors must be **semantic**, not decorative.

* Color must only represent:

  * Severity (Normal / Alert / Critical)
  * Data source (Telemetry / Tribology / Mixed)
  * System category (Engine, Brakes, etc.)

* No component may introduce **new arbitrary colors** outside the system.

---

## 2.2 Visual Hierarchy

* The layout must clearly define:

  * Primary information (alerts status)
  * Secondary information (distribution, trends)
  * Tertiary information (supporting context)

* The user must be able to identify **priority alerts within 3 seconds**.

---

## 2.3 Layout Consistency

* All pages must follow a **grid-based layout system**.
* All components must align to a consistent structure.
* Spacing must be uniform across:

  * Cards
  * Charts
  * Tables
  * Sections

---

## 2.4 Responsiveness

* The dashboard must adapt to:

  * Standard desktop resolutions
  * Large screens (operations rooms)

* No fixed-height components that generate unused vertical space are allowed.

---

# 3. Navigation & Global Controls

## 3.1 Top-Level Navigation

* The application must have two clearly distinguishable views:

  * **General View (Overview)**
  * **Detailed View (Per Alert Analysis)**

* Active view must be visually emphasized.

---

## 3.2 Global Filter Layer

* All filters must be placed in a **dedicated global control area**.
* Filters must not be embedded within charts or visualizations.

### Required Filters

* Client
* Unit
* System
* Time range
* Data source (Telemetry / Tribology / Mixed)

---

## 3.3 Filter Behavior

* Filters must:

  * Apply globally across all components
  * Be combinable
  * Be resettable via a single action

---

# 4. Overview (General View) Requirements

## 4.1 KPI Section

* The dashboard must display a **top-level KPI summary**.

### Required KPIs

* Total number of alerts
* Number of affected units
* Percentage of alerts with telemetry
* Percentage of alerts with tribology

### Requirements

* Each KPI must include:

  * Value
  * Label
  * Context (trend or proportion)
* KPIs must not be purely decorative.

---

## 4.2 Alert Distribution by Unit

* Must display distribution of alerts per unit.

### Requirements

* Units must be sorted by number of alerts (descending).
* Visualization must support:

  * Comparison across systems
  * Identification of top problematic units

---

## 4.3 Alert Trend Over Time

* Must display evolution of alerts over time.

### Requirements

* Must allow identification of:

  * Increasing trends
  * Peaks in alert frequency
* Temporal aggregation must be consistent (e.g., weekly or monthly).

---

## 4.4 System Distribution

* Must show distribution of alerts by system.

### Requirements

* Minor categories must be grouped when necessary.
* Visualization must clearly show dominant systems.

---

## 4.5 Removal of Redundant Visualizations

* Any visualization that does not add new analytical value must be removed.

### Explicit Requirement

* The current **“distribution by source” visualization must be removed or replaced**, as it duplicates information already inferable elsewhere.

---

## 4.6 Alert Table

* A structured table must list all alerts.

### Requirements

* Must support:

  * Sorting
  * Filtering
  * Selection of a single alert
* Must visually encode severity.

### Columns must include:

* Alert ID
* Timestamp
* Unit
* System
* Source
* Severity
* AI Diagnosis (summarized)

---

## 4.7 Alert Selection Behavior

* Selecting an alert must:

  * Trigger navigation or update to the detailed view
  * Preserve current filters

---

# 5. Detailed View Requirements

## 5.1 Alert Summary Header

* A summary section must provide **high-level context** of the alert.

### Must include:

* Unit
* System
* Subsystem
* Source
* Timestamp
* Severity (visually emphasized)

---

## 5.2 AI Diagnosis Section

* AI-generated insights must be displayed in a **structured format**.

### Must be divided into:

* Diagnosis
* Probable cause
* Operational risk
* Recommended actions

### Requirements

* Each section must be clearly separated.
* Content must be readable and scannable.

---

## 5.3 Telemetry Evidence

* Telemetry data must provide **evidence of the anomaly**.

### Requirements

* Must display:

  * Signal values over time
  * Upper and lower thresholds

* Must highlight:

  * Out-of-bound values
  * Triggering signals

* Signals must be grouped logically by subsystem.

---

## 5.4 GPS Context

* Alerts must include spatial context when available.

### Requirements

* Must display:

  * Location of alert occurrence
  * Movement pattern (if relevant)

---

## 5.5 Context Indicators

* Operational context must be explicitly shown.

### Must include:

* Machine operational state
* Engine speed
* Elevation or relevant environmental indicators

---

## 5.6 Tribology Evidence

* Oil analysis must be integrated when available.

### Requirements

* Must display:

  * Element values (wear, additives, contaminants)
  * Threshold comparison (normal / alert / critical)
  * Overall oil health status

* Must include:

  * Severity score
  * Report status
  * AI recommendation

---

## 5.7 Maintenance Context

* Maintenance history must be displayed.

### Requirements

* Must include:

  * Recent interventions
  * Related activities
* Must allow correlation with alert occurrence.

---

# 6. Data Integration Requirements

## 6.1 Multi-Source Fusion

* The dashboard must integrate:

  * Telemetry data
  * Oil analysis data
  * Maintenance data

* Data must be presented as a **single coherent narrative**, not separate silos.

---

## 6.2 Consistency of Terminology

* System, component, and unit naming must be consistent across all sections.

---

## 6.3 Traceability

* Every displayed insight must be traceable to:

  * A telemetry signal
  * An oil measurement
  * Or a derived AI output

---

# 7. Interaction Requirements

## 7.1 User Flow

The dashboard must support the following flow:

1. Identify problematic units (Overview)
2. Select relevant alert
3. Analyze root cause (Detail)
4. Understand risk
5. Decide action

---

## 7.2 Performance

* All interactions must feel responsive.
* Filtering and selection must update all relevant components.

---

# 8. Usability Requirements

## 8.1 Readability

* Text must be legible at standard viewing distances.
* Charts must not require interpretation effort.

---

## 8.2 Cognitive Load

* The interface must minimize:

  * Redundant information
  * Visual clutter
  * Unnecessary interaction steps

---

## 8.3 Accessibility

* Color usage must remain interpretable without relying solely on color (icons or labels required).

---

# 9. Acceptance Criteria

The redesign is complete when:

* The user can identify the most critical alert in under 5 seconds.
* Each alert clearly communicates:

  * Condition
  * Cause
  * Risk
  * Action
* No redundant visualizations remain.
* Layout is consistent and responsive.
* Telemetry and tribology insights are presented as a unified analysis.

