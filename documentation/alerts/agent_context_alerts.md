# Agent Context: Monitoring > Alerts

**Purpose of this document**: ground-truth reference for an agent working on the Alerts tab (`Monitoring > Alerts`, route `/monitoring/alerts`). It is derived from reading the actual code (`dashboard/pages/monitoring_alerts.py`, `dashboard/tabs/tab_alerts*.py`, `dashboard/callbacks/alerts_callbacks.py`, `dashboard/components/alerts_*.py`, `src/data/loaders.py`) as of 2026-08-12, not from the design docs. Where the two existing docs (`dashboard_overview.md`, `alerts_data_contracts.md`) disagree with the code, **the code wins** and the discrepancy is called out explicitly in §8 so nobody "fixes" working code to match a stale doc.

Those two docs are still useful for original intent/rationale, but treat every concrete detail (column names, constants, component list) in them as unverified until cross-checked here or in the code itself.

---

## 1. Architecture Overview

- Route: `dashboard/pages/monitoring_alerts.py` registers `/monitoring/alerts` and calls `tab_alerts.create_layout()`.
- The "General" and "Detail" views are **not separate routes** — they are two `dcc.Tab`s inside a single `dcc.Tabs(id='alerts-internal-tabs', value='general')`, with content rendered dynamically by `render_tab_content()` in `alerts_callbacks.py`.
- Layout builders (pure functions, no callbacks): `dashboard/tabs/tab_alerts.py`, `tab_alerts_general.py`, `tab_alerts_detail.py`.
- All alerts callbacks live in one file: `dashboard/callbacks/alerts_callbacks.py` (~1660 lines), imported for side effects in `dashboard/app.py` (`import dashboard.callbacks.alerts_callbacks`).
- Figure builders: `dashboard/components/alerts_charts.py`. Table/text builders: `dashboard/components/alerts_tables.py`. Pure view-model helpers (filtering, row prep, summaries): `dashboard/components/alerts_report.py`.
- Data loading: `src/data/loaders.py`, with `functools.lru_cache(maxsize=8)` (keyed by lowercased client) for the three main golden-layer reads; maintenance and oil-limits files are re-read from disk on every render.
- Client scoping: `client-selector` (global dropdown in `dashboard/layout.py`) drives almost every alerts callback via `Input('client-selector','value')`. Access to `/monitoring/alerts` itself is gated once per navigation by `access_control_callbacks.py::guard_route`, which redirects away if the alerts service isn't enabled for the selected client.

---

## 2. Data Sources (verified against code, not docs)

| Data | Path | Load fn | Cache | Key columns actually read |
|---|---|---|---|---|
| Consolidated alerts | `data/alerts/golden/{client_lower}/consolidated_alerts.csv` | `load_alerts_data(client)` | `lru_cache(8)` | `FusionID`, `Timestamp`, `UnitId`, `Trigger_type`, `TelemetryID`, `TribologyID`, `Semana_Resumen_Mantencion`, `mensaje_ia`, `sistema`/`subsistema`/`componente`, `Trigger_Var` |
| Telemetry evidence (golden, wide) | `data/telemetry/golden/{client_lower}/alerts_detail_wide_with_gps.csv` | `load_telemetry_alerts_detail_golden(client)` | `lru_cache(8)` | `AlertID`, `Unit`, `TimeStart`, `Trigger`, `GPSLat`/`GPSLon`/`GPSElevation`, `State`, `{feature}_Value`, `{feature}_Upper_Limit`/`_Lower_Limit`, `Payload_Value` |
| Oil classified reports | `data/oil/golden/{client_lower}/classified.parquet` | `load_oil_classified(client)` | `lru_cache(8)` | `sampleNumber`, `machineName`, `componentName`/`componentNameNormalized`, `oilHourRange`, `report_status`, `unitId`, `sampleDate`, `oilMeter`, essay-value columns |
| Oil four-limit thresholds (Stewart v2.8) | `settings.get_stewart_limits_four_path(client)` → `stewart_limits_four.parquet` | `load_stewart_limits_four(limits_file)` | not cached | `client`, `machine`, `component`, `essay`, `oilHourRange`, `LIC`/`LIM`/`LSM`/`LSC` |
| Essay → element group mapping | `data/oil/essays_elements.xlsx` (hardcoded path) | plain `pd.read_excel` | not cached | `ElementNameSpanish`, `GroupElement` |
| Weekly maintenance | `data/mantentions/golden/{client_lower}/{week}.csv` | `load_maintenance_week(client, week)` | not cached | `UnitId`, `Semana`, `Summary`, `Tasks_List` (JSON string) |

**Important correction vs. `alerts_data_contracts.md`**: that doc's v1.1 changelog claims the schema was renamed `Timestamp → Fecha` and `TribologyID → OilReportNumber`, and declares itself "aligned with implementation, ground truth." **This is false for the current code** — `alerts_callbacks.py`, `alerts_report.py`, `alerts_charts.py` and the loader all use `Timestamp` and `TribologyID` throughout. Either the rename was reverted or never shipped. Trust the code's actual column names: `Timestamp`, `TribologyID`.

Everything else in that doc's schema table (`FusionID`, `TelemetryID`, `Semana_Resumen_Mantencion`, `UnitId`, `Trigger_type` values `Telemetria`/`Tribologia`/`Mixto`, lowercase `sistema`/`subsistema`/`componente`, `has_telemetry`/`has_tribology` derivation) does match the code.

Legacy/dead loaders still imported but not exercised by the live alerts flow (kept for deprecated, unused chart builders): `load_telemetry_values` (silver wide parquet), `load_telemetry_states`, `load_telemetry_limits` (this one uppercases the client path segment — the sole exception to lowercasing), `load_telemetry_alerts_metadata`, `load_component_mapping`, `load_feature_names`.

---

## 3. General Tab (`tab_alerts_general.py` layout + callbacks in `alerts_callbacks.py`)

### Layout / IDs
- `alerts-selected-alert-id` (store) — `FusionID` of the row clicked in the table.
- `alerts-general-active-filters` (store, `{}`) — the real cross-filter state: keys `unit`/`week`/`system`, single value each (not lists). **Note**: `alerts-filter-store`, declared in `tab_alerts.py`, is dead/unused — don't confuse the two.
- `alerts-summary-stats` — KPI cards container.
- `alerts-date-range-picker` (`dcc.DatePickerRange`) — default range **last 27 days to today**; `alerts-date-range-clear` button resets it.
- `alerts-general-filter-summary`, `alerts-general-active-filter-badges`, `alerts-general-filter-clear-all` — filter summary text, removable chips (`{"type":"alerts-general-filter-chip","key":...}` pattern id), and a clear-all button.
- Three chart cards: `alerts-unit-distribution-chart`, `alerts-month-distribution-chart`, `alerts-system-distribution-chart`, laid out `lg=4`/`lg=4`/`lg=4` (equal ~33%/33%/33%, exact via Bootstrap's 12-column grid) with a fixed pixel height (`ALERTS_CHART_CARD_HEIGHT`/`ALERTS_CHART_CARD_BODY_HEIGHT` in `tab_alerts_general.py`) so the row height never grows with fleet size.
  - **Naming gotcha**: `alerts-month-distribution-chart` actually renders a **weekly** bar chart (`create_alerts_per_week_chart`), not a month chart. The id is a holdover from an earlier design; don't rename it casually since callbacks target it by id.
  - `alerts-unit-distribution-chart` renders responsively (no fixed pixel width, no horizontal scroll) — the whole Pareto, including the secondary axis, must fit inside the card on first render. Tick/value font size and value-label orientation scale down as unit count grows (see thresholds in `create_alerts_per_unit_chart`) so labels keep fitting instead of overlapping; per-unit hover remains the fallback for full detail at high fleet counts.
- `alerts-table-container` — hosts `alerts-datatable` (built by `create_alerts_report_table`, the live table; `create_alerts_datatable` in the same module is an unused legacy variant with different columns/page size — don't confuse them). Visible columns: `Fecha`, `Unidad`, `Sistema`, `Componente`, `Señal / variable`, `Diagnóstico`, `Acción` (the last one is present in `columns` but hidden via a `style_cell_conditional` `display:none` rule, a different mechanism than the other hidden fields below). `ID`, `Fuente`, and `Evidencia` were dropped from the visible `columns` list but **stay in each row's `data` dict** (same pattern as the pre-existing hidden `diagnostico_completo`/`causa_completa`/`accion_completa` fields) — `store_selected_alert` and `render_selected_alert_summary` in `alerts_callbacks.py` still read `row.get('ID')`/`row.get('Fuente')`/`row.get('Evidencia')` from `derived_virtual_data`, and the Mixto row-highlight (`style_data_conditional`, `filter_query: '{Fuente} = "Mixto"'`) still works because Dash's filter/selection machinery reads from `data`, not from `columns`.
- `alerts-general-selected-alert` — "decision summary" card shown below the table after a row click.

### KPI cards
`create_summary_stats_display` renders **3** cards: Total de alertas, Unidades afectadas, Alertas mixtas. It accepts `telemetry_pct`/`oil_pct` params but never renders them — the design doc's 4-card layout (with %Telemetría/%Tribología) does not exist in the running UI.

### Charts
- Unit distribution: **Pareto chart**, `create_alerts_per_unit_chart` — units on the X-axis (title "Identificador de Unidad") sorted descending by alert count (bars, primary Y-axis "Número de Alertas") plus a cumulative-percentage line (secondary Y-axis "Porcentaje Acumulado", fixed 0–100%, always ending at exactly 100%). Bars are not segmented/colored by system and there is no legend. **The two Y-axes scale independently**: the primary axis fits `1.15 × max(unit count)` (not the total alert count), so bars for fleets with many total alerts don't compress toward the bottom; the secondary axis is always the fixed `[0, 100]` with ticks at 0/20/40/60/80/100%. Both recompute from scratch on every filtered render. Density-adaptive rendering as unit count grows (thresholds in `create_alerts_per_unit_chart`): tick/value font shrinks and on-bar value text rotates vertical past 45 units; on-bar count labels are dropped entirely past 25 units (hover still always has the exact count); X-axis tick labels thin out via `tickmode='linear'`/`dtick` past 40 units; the cumulative-% line shows at most ~12 evenly-spaced percentage labels (always including the last, 100%, point) with the rest hover-only. Clicking a bar (or a point on the cumulative line, same X category) sets the `unit` cross-filter — `update_active_filters` reads `points[0]['x']` for this chart, not `'y'` (this changed when the chart went from horizontal bars to a Pareto layout).
- Week distribution: `create_alerts_per_week_chart`, rendered into the `alerts-month-distribution-chart` id. Unchanged analytically; its figure height shares the `ALERTS_CHART_HEIGHT` constant with the other two charts, axis titles are "Semana"/"Alertas", and each stacked bar segment shows its own count (blank label for zero-filled week/system combos so empty segments don't show a dangling "0"). The "Sistema" legend is conditional: hidden when the filtered data has exactly one system (redundant when every bar is the same color), shown for 2+ — recomputed on every filtered render, so e.g. filtering down to a single-system unit hides the legend even if it was visible unfiltered.
- System distribution: **treemap**, `create_system_signal_treemap(alerts_df, client=...)` — two levels, area sized by alert count. No axis labels (not applicable to a treemap). Hover shows the root dimension label/Señal-Variable/Alertas/Porcentaje via a precomputed `hovertext` array (not a shared `hovertemplate`, so the level-1 tiles' hover doesn't show a blank Señal/Variable line). Every node (root tile and its Señal/Variable leaves alike) carries its **owning system** in `customdata` regardless of which root dimension is in use, so clicking anywhere in a branch sets the `system` cross-filter; `update_active_filters` reads `points[0]['customdata']` directly (a scalar string, not `[0]`-indexed, since `customdata` was built as a flat per-node list). Plotly's native treemap click-to-zoom (with the `pathbar` breadcrumb) works independently of and doesn't interfere with this cross-filter.
  - **Root dimension is adaptive** (`update_general_tab` passes `client=client` into the chart function): with **2+ distinct systems** in the filtered data, the root is `Sistema` (outer tiles colored via `SISTEMA_COLORS`), same as before. With **exactly 1 system**, it looks up `config/features/{client.lower()}.yaml` via `_load_functional_group_map()` (cached with `@lru_cache`) and, if that config maps the alert's first signal to a `functional_group`, switches the root to `Familia` instead — a single "Sistema" root tile is useless once every alert already shares the same system, so Familia gives single-system clients (e.g. Capstone, whose CSV only ever has `sistema == 'motor'`) a meaningful top-level grouping. `_functional_group_label()` translates the config's `functional_group` id (`coolant`, `egt`, `oil_pressure`, …) to a Spanish label via `FUNCTIONAL_GROUP_LABELS_ES`, with an auto-formatted fallback for ids not yet in that table — raw snake_case identifiers must never reach the UI. Root tile colors come from `_treemap_root_colors()`: known systems keep `SISTEMA_COLORS`, unrecognized roots (Familia labels) cycle a qualitative Plotly palette so families stay visually distinct. **Generic by design, not a Capstone special-case**: any client whose `config/features/{client}.yaml` has the same `features: [{name, source_column?, derived?, functional_group}]` shape gets Familia grouping automatically once it's single-system; missing config/mapping falls back to `Sistema` (never fabricates a grouping).
  - `_load_functional_group_map()` maps every raw signal code a client's `Trigger_Var` can carry — a feature's `source_column`, its own `name`, *and* any bare identifier referenced inside a `derived` formula string (e.g. Capstone's `egt_bank_diff: "abs(egt_lb_c - egt_rb_c)"` also maps `egt_lb_c`/`egt_rb_c` to the `egt` group even though neither has its own feature entry) — to that feature's `functional_group`.
  - **`Señal/Variable` source and the "first value only" rule**: built from `Trigger_Var`, a real Golden-layer column that is populated but not uniform across clients — Capstone stores a bare scalar code, CDA/Emin store a string-serialized Python list (mixed telemetry+tribology alerts can bundle several signals in one row — ~22% of CDA's rows in the sample data). `_first_signal_key()` in `alerts_charts.py` always keeps only the *first* value and discards the rest (both for the Señal/Variable leaf and for the Familia lookup), so one alert always sizes exactly one treemap leaf — no alert is double-counted, and the treemap's total area always equals the total (filtered) alert count. `_first_signal_display()` wraps it with the `FEATURE_NAMES_ES` Spanish translation. This "first value only" rule was a deliberate, user-specified product decision (not an inference) — an earlier evaluation of the raw data had rejected any multi-value hierarchy as infeasible without fabricating an aggregation rule, until this explicit rule resolved it. Missing/unparseable `Trigger_Var` falls back to the leaf label "Sin señal registrada" (and the root label "Sin familia" in Familia mode) rather than dropping the alert.
- The previous ~20%-width horizontal-bar replacement for the donut, `create_system_distribution_bar_chart`, was fully removed (superseded by the treemap, not left as dead code). Separately, `create_trigger_distribution_treemap` (an unrelated, always-dead `Trigger_type` treemap from the original design doc) still exists in `alerts_charts.py` but remains unimported in `alerts_callbacks.py` — don't confuse it with the live `create_system_signal_treemap`.

### Filtering pipeline (`update_general_tab`)
Inputs: `client-selector.value`, date-picker start/end, `alerts-general-active-filters.data`. Combines (AND):
1. Date range via `filter_alert_rows()` (from `alerts_report.py`) — inclusive start, inclusive end-of-day.
2. `unit`/`system` cross-filters also handled inside `filter_alert_rows` (matched against `UnitId` / derived `system_display`, not raw `sistema`).
3. `week` cross-filter handled separately in the callback: `[week_start, week_start+7days)` on `Timestamp`.

`filter_alert_rows` also accepts `source`/`evidence` params, but nothing in the General tab UI currently sets them (reserved/reused elsewhere).

### Click-to-filter (`update_active_filters`)
Clicking a bar/pie segment sets `active_filters[key] = value` (`key` = `unit`/`week`/`system`); clicking the same value again removes it (toggle, not additive — only one value per key at a time). Filter chips and "Limpiar filtros" also feed this same store. **Filters silently reset to `{}` whenever `client-selector` changes** (`reset_active_filters_on_client_change`) — the date range is preserved across a client switch, but chart cross-filters are not.

### Row click → navigation
A row click does **not** jump straight to Detail. It: (a) stores the `FusionID` in `alerts-selected-alert-id`, and (b) renders a summary card (`alerts-general-selected-alert`) with full diagnóstico/causa/acción text and a single button, `general-nav-to-detail-button` ("Ver detalle de la alerta"). Only clicking that button triggers navigation. There is no separate "Navigation Card" with its own dropdown (`general-alert-selector` doesn't exist in code) — the design doc's "Method 2" section describes a control that isn't implemented; the summary-card button is the only navigation entry point.

Navigation chain: `navigate_to_detail_from_general` writes `alerts-navigation-state` (global store in `dashboard/layout.py`, not alerts-tab-local) → `switch_to_detail_tab` flips `alerts-internal-tabs.value` → `set_alert_from_navigation` sets `alert-selector-dropdown.value` once the Detail tab is active and dropdown options are populated.

---

## 4. Detail Tab (`tab_alerts_detail.py` layout + callbacks in `alerts_callbacks.py`)

### Layout / IDs
- Filters: `detail-filter-unit` (multi), `detail-filter-sistema` (multi), `detail-filter-telemetry` / `detail-filter-tribology` (single-select, values `yes`/`no`; "no filter" = cleared dropdown, there's no literal third "Todos" option value despite the doc implying one). No date filter exists on this tab.
- `alert-selector-dropdown` — searchable/clearable, options built from all alerts for the client (not date-scoped), label `"{FusionID} | {Timestamp:%Y-%m-%d %H:%M} | {UnitId} | {componente translated}"`, sorted by `Timestamp` descending.
- `alert-detail-content` — the actual rendered evidence, built dynamically by `update_detail_view`.
- `create_alert_detail_content()` in `tab_alerts_detail.py` is a **static skeleton generator that is never called** — the real content is assembled directly inside `alerts_callbacks.py`'s section builders. Similarly `create_oil_status_display()` in the same file is unused; the live oil section builds its own status badges. Don't assume these static helpers reflect the live UI — read the callback-side builders instead.

### Detail filter dropdowns
`populate_detail_filter_options` (unit/sistema options, all-time) and `filter_alert_dropdown_by_criteria` (AND-filters the dropdown's options by unit/sistema/has_telemetry/has_tribology) only narrow the dropdown's **options list** — they don't force-clear an already-selected alert if it falls outside the new filter.

### Evidence section gating (`update_detail_view`)
```python
trigger_lower = str(alert_row['Trigger_type']).lower()
show_telemetry = 'telemetria' in trigger_lower or 'mixto' in trigger_lower
show_oil       = 'tribologia' in trigger_lower or 'oil' in trigger_lower or 'mixto' in trigger_lower
show_maintenance = pd.notna(alert_row.get('Semana_Resumen_Mantencion'))
```
Note the case-insensitive substring match (not exact enum comparison), and that maintenance visibility is independent of `Trigger_type` (gated only by having a non-null maintenance week) — matches the docs' intent here.

Render order is always: alert header card → Telemetry (if shown) → Oil (if shown) → Maintenance (if shown).

A clientside callback scrolls the page to top whenever `alert-detail-content` changes (avoids the browser preserving mid-page scroll position when a large new detail render swaps in).

### Alert header card (`_alert_case_header`)
Uses `prepare_alert_rows`/`parse_ia_message_sections` (see §6) to show Unidad/Sistema/Componente/Fecha/Fuente, then a 3-column "Análisis inteligente" block: Diagnóstico / Causa probable / Acción recomendada.

---

## 5. Telemetry Evidence

- Row selection (`_select_telemetry_alert_data`): matches `AlertID ∈ {TelemetryID, FusionID}` **AND** `Unit == UnitId` (AlertID is only unique per-unit, not globally — this AND is required for correctness).
- Alert time used for windowing is `alert_row['Timestamp']`, **not** the telemetry row's `TimeStart` (comment in code: `TimeStart` is just the window start, not the actual alert moment).
- **Time window is 90 minutes before / 10 minutes after the alert** (`M1=90, M2=10`, hardcoded locally inside `create_sensor_trends_chart_golden`/`create_gps_route_map_golden` in `alerts_charts.py`). The module-level `M1=60`/`M2=10` constants at the top of `alerts_callbacks.py` are dead/unused — **the design doc's "M1=60min" is wrong; the real window is 90 minutes before.**
- Chart-panel exclusion list: `Payload`, `EngSpd`, `GroundSpd`, `EngLoad` are excluded from sensor-trend subplot panels (still used for KPI cards).
- One subplot per remaining feature, shared x-axis, line colored gray with markers colored by operational `State`; lines are gap-segmented (`_split_gap_segments`, breaks at >3× median sample interval) so real data gaps don't render as straight interpolated lines. Upper/lower limit lines drawn dashed. A red highlight box (±30s, ±1 value) marks the specific feature that triggered the alert (`Trigger` column, case-insensitive match). A vertical dotted line marks `alert_time` on every panel.
- Client-aware fallback: for Capstone clients, `engine_speed_rpm`/`engine_load_pct` canonical columns fall back to legacy CDA aliases (`EngSpd_Value`/`EngLoad_Value`) if the canonical one has no numeric data.
- GPS map: window is `[alert_time-90min, alert_time]` **only** (does not extend +10min after, unlike the sensor chart). Flat orange markers (`#ea6648`) for the route, a distinct white+red marker for the closest-to-alert point. Style `satellite-streets`, zoom 14. **No continuous Reds colorscale gradient** as the design doc describes — that's not implemented.
- Context KPIs: **4 cards** (not 3 as documented) — Elevación (gradient of before/after GPS elevation), Carga/Payload (`Payload_Value` numeric tonnage — not the categorical `EstadoCarga` "Cargado/Vacío" the doc describes; that logic only exists in unused legacy code), Carga de Motor (`EngLoad` family), Velocidad Motor (`EngSpd` family, RPM). Column fallback chains handle both Capstone-canonical and CDA-legacy column names.

---

## 6. Oil Evidence

Far more elaborate than either doc describes — read this section, not the docs, before touching oil evidence code.

- Row selection: `oil_classified[oil_classified['sampleNumber'] == alert_row['TribologyID']]` (not `OilReportNumber`).
- `machine = oil_report['machineName']`; component key falls back `componentNameNormalized` → `componentName`; `oilHourRange` used to select the age-stratified limit tier.
- **Two tabbed sub-views**, both pre-rendered, toggled client-side via CSS (`toggle_oil_evidence_view` just flips `display:block/none`, doesn't re-render):
  - **Tendencia** (default): full equipment/component history for the same `unitId`+`componentName`, reusing the shared 9-chart grid `build_oil_time_series_grid()` from `dashboard/components/oil_charts.py` — the same component used in `Monitoring > Oil > Details`. Has its own isolated date-range picker (default: latest sample date minus 12 months) that only affects this chart, via `alert-oil-tendencia-context` store.
  - **Último Ensayo**: per essay-group (`GroupElement` from `essays_elements.xlsx`, e.g. Desgaste/Aditivos first, then alphabetical) radar chart + status table, using **four-limit Stewart classification (v2.8: LIC/LIM/LSM/LSC, 5-tier status)** — not the simple 2-tier normal/alert threshold model the design doc describes. Groups with no essays that have resolvable limits are skipped entirely. Radar values are normalized 0–100 via piecewise mapping around the four limits; rings drawn at r=20/40/60/80 for LIC/LIM/LSM/LSC (or just 60/80 if no lower limits). An oil-age badge ("Aceite Fresco <1000h" / "Aceite Envejecido ≥1000h" / unknown) is shown based on `oilHourRange`.

---

## 7. Maintenance Evidence

Matches the docs reasonably well:
- Gated only by `Semana_Resumen_Mantencion` being non-null (independent of `Trigger_type`).
- Loads `data/mantentions/golden/{client}/{week}.csv` fresh every render (no cache), filters to the alert's `UnitId`.
- `create_maintenance_display` (`alerts_tables.py`): shows `Summary` text if present, then parses `Tasks_List` JSON (`{date: {SYSTEM: [tasks]}}`), matching the alert's `sistema` **case-insensitively** against the task systems; if no date matches the alert's system, shows a specific "no activities for {system}" warning rather than a generic empty message.

---

## 8. Deviations from the Existing Docs (read before trusting either doc on a specific claim)

**`dashboard_overview.md` — stale in several concrete ways:**
- 4 KPI cards documented → actually 3 (no %Telemetría/%Tribología cards rendered).
- Trigger-type treemap documented as a live chart → exists in code (`create_trigger_distribution_treemap`) but is never called; not part of the live UI.
- "Month" chart documented → actually a **weekly** chart, rendered into an id still named `alerts-month-distribution-chart`.
- Navigation "Method 1" (row click alone navigates) is wrong — a row click only opens an inline summary card; a button inside that card does the navigating. "Method 2" (separate nav-card dropdown, `general-alert-selector`) doesn't exist at all.
- Telemetry window `M1=60min` documented → actually 90 minutes.
- GPS map "Reds colorscale gradient" documented → actually flat single-color markers with one highlighted alert point.
- Context KPIs: 3 documented (incl. categorical `EstadoCarga` payload) → actually 4, with `Payload_Value` as a numeric tonnage.
- Oil evidence section is described as a simple single radar + flat status table → actual implementation has a Tendencia/Último-Ensayo tab split, per-essay-group radars, and four-limit (v2.8) Stewart classification — none of this is in the doc.
- State color map documented with 3 states → code handles many more states plus multiple text-encoding variants of each.

**`alerts_data_contracts.md` — stale on exactly two fields despite claiming "aligned with implementation, ground truth" (v1.1 changelog):**
- Doc says the timestamp column was renamed `Timestamp → Fecha`. **Code still uses `Timestamp` everywhere.**
- Doc says the oil-reference column was renamed `TribologyID → OilReportNumber`. **Code still uses `TribologyID` everywhere.**
- Every other column name/value documented there (`sistema`/`subsistema`/`componente`, `Trigger_type` enum, `has_telemetry`/`has_tribology` derivation, `Semana_Resumen_Mantencion` format) does match the code.

**Implemented but undocumented in either doc:**
- Date-range picker on the General tab (default: last 27 days) — the docs only describe chart click-filtering, not a date filter.
- Active-filter badge chips (individually removable) + "Limpiar filtros", and the auto-reset of cross-filters on client switch.
- The decision-summary card under the General table, which is the real navigation entry point.
- Scroll-to-top clientside callback on Detail-tab re-render.
- Oil Tendencia/Último-Ensayo split and the four-limit v2.8 Stewart classification system.
- Spanish label-translation layer (`translate_alert_system`/`translate_alert_component`/`_translate_signal_text`) applied to system/component names and to in-text signal references inside AI diagnosis text.
- Capstone-vs-CDA client branching throughout `alerts_charts.py` (different column aliases, different AI-message JSON vs. regex parsing in `parse_ia_message_sections`) — the docs don't acknowledge multiple client data contracts at all.
- Trigger-feature highlight box and gap-segmented line rendering in the sensor trends chart.

---

## 9. Practical Notes for an Agent Making Changes Here

- Don't trust component **names/ids** as descriptions of what they render — `alerts-month-distribution-chart` renders a weekly chart; verify against the callback output, not the id.
- Don't assume the static builder functions in `tab_alerts_detail.py` (`create_alert_detail_content`, `create_oil_status_display`) reflect current behavior — they're unused; the real Detail-tab content is built inline in `alerts_callbacks.py`.
- Two live tables exist for alerts (`create_alerts_report_table` = live, used; `create_alerts_datatable` = legacy, unused) — check which one a change actually needs to touch.
- `M1`/`M2` in `alerts_callbacks.py` are dead constants; the real telemetry window constants live inside `alerts_charts.py`'s chart-building functions.
- If a change touches column names (`Timestamp`, `TribologyID`, etc.), verify against `src/data/loaders.py` and the actual CSV/parquet, not against `alerts_data_contracts.md`.
- Both design docs need a refresh pass; if you fix something in code, consider flagging (not necessarily fixing) the corresponding stale doc section rather than silently letting drift continue.
