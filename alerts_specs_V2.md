# 📄 Telemetry Visualization – Issue-Based Requirements

## 1. Chart Title Rendering

### Problem

* The title of the first chart is **visually overlapped and unreadable**.
* The title is **colliding with plot elements (limit lines / UI controls)**.
* There is no clear separation between:

  * Chart title
  * Plot area
  * Toolbar icons

### Requirements

* Each chart must have a **clearly visible, non-overlapping title area**.
* The title must:

  * Be fully readable without truncation
  * Not overlap with:

    * Plot traces
    * Threshold lines
    * Plotly toolbar
* A **dedicated vertical space must be reserved** for the title.
* The title must be **aligned consistently across all charts**.
* Long titles must:

  * Either wrap into multiple lines
  * Or be truncated with ellipsis and tooltip

---

## 2. Threshold (Limit) Visualization

### Problem

* Threshold lines (upper/lower limits) are:

  * Visually confusing
  * Overlapping with each other
  * Difficult to distinguish from actual sensor data
* Excessive number of dashed red lines creates **visual noise**
* No clear distinction between:

  * Upper vs lower limits
  * Different operational states (if applicable)

### Requirements

* Thresholds must be **visually distinguishable from signal data**.

### Specific constraints:

* Limit lines must:

  * Use a **consistent style across all charts**
  * Be visually lighter than the main signal (lower visual priority)
* Upper and lower limits must be:

  * Clearly differentiated (e.g., different line styles or labels)
* The number of visible threshold lines must be:

  * **Strictly limited to relevant bounds only**
  * Redundant or duplicate limits must not be displayed

---

## 3. Signal vs Threshold Priority

### Problem

* Sensor values (actual data) are **not visually dominant**
* Threshold lines visually compete with the main signal

### Visual hierarchy must ensure:

1. Signal data (highest priority)
2. Thresholds (secondary)
3. Grid / background (lowest)

---

## 4. Color Encoding Issues

### Problem

* Multiple colors (green, orange, red) are used without clear meaning
* Color usage is inconsistent and not tied to a clear semantic model

### Requirements

* Color must follow a **strict semantic mapping** using the state ass legend (one legend for the full figure on top with horizontal allignment)
* Colors must not be used arbitrarily for decoration

---


## 5. Multi-Chart Layout

### Problem

* Multiple charts are stacked vertically without strong separation
* Difficult to distinguish where one chart ends and another begins

### Requirements

* Each chart must be visually separated using:

  * Spacing
  * Borders or card containers
* Each chart must clearly communicate:

  * Which signal it represents
* Charts must be aligned consistently in width and margins


---

## 6. Telemetry Layout

### Problem

* The telemetry doesnt follow a clean layout.
* Difficult to study the data fast.

### Requirements

* The layout must be :
  * Top Section : Telemetry trends 
  * Bottom Section : KPI Cards (2x2 grid) + GPS Chart

* This layout gives the main stage to the trends while giving context in the bottom.
The gps and the kpi cards must have the same height and use the same horizontal space


---

# ✅ Acceptance Criteria

The telemetry visualization is considered correct when:

* Chart titles are fully readable and never overlap with plot elements
* Threshold lines are:

  * Clearly distinguishable
* Signal data is visually dominant
* Colors follow a consistent semantic mapping
* Charts are readable without visual clutter
* Users can immediately identify abnormal behavior without interpretation effort

