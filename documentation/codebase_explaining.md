# Codebase Explainer (Cold-Start Guide)

**Purpose of this file**: a fast orientation doc for anyone (human or agent) new to this repo.
Read this first, then jump to the specific doc pointed to for the area you're touching. It
explains *how the pieces fit together*, not the full detail of any one piece.

If something here ever contradicts the code, trust the code and fix this file.

---

## 1. What this repo is

**TDS / Multi-Technical Alerts Dashboard** — a Dash (Plotly) web app that lets mining-fleet
maintenance teams monitor equipment health across several monitoring techniques (oil analysis,
telemetry, maintenance records, consolidated alerts, predictive failure models) for multiple
clients (CDA, EMIN, ENEX, CAPSTONE).

**Critical mental model**: this repo is **dashboard-only**. It does not compute the analytics it
displays. An upstream data pipeline (outside this repo) produces "Gold layer" Parquet/CSV files
and uploads them to S3; this app's only jobs are:

1. Sync those files into a local `data/` folder if missing (`src/data/s3_downloader.py`, invoked
   once at startup by `dashboard/app.py` — never re-syncs while running)
2. Read `data/` and render it

There is **no `main.py`** and **no `src/processing/`** in this repo — if you see older docs or
comments referencing "run the pipeline" or `classification.py`, that logic has moved elsewhere.
Don't go looking for it here.

---

## 2. Data flow, end to end

```
Upstream data pipeline (separate repo/process)
        │  produces Gold-layer files, uploads to S3 bucket "MultiTechnique Alerts/"
        ▼
S3 bucket
        │  src/data/s3_downloader.py — pulled automatically on dashboard startup
        │  ONLY IF the local data/ folder doesn't already exist
        ▼
data/{technique}/{layer}/{client}/{file}        ← the Data Mesh (see §5)
        │  read directly by dashboard callbacks (mostly via src/data/loaders.py,
        │  src/data/maintenance_loaders.py, or ad-hoc pandas/parquet reads in callback files)
        ▼
dashboard/callbacks/*.py  →  dashboard/components/*.py (charts/tables)  →  dashboard/tabs/*.py (layout)
        ▼
Browser (Dash/React runtime)
```

If a page shows no data, the first two questions are always: (1) does `data/{technique}/golden/{client}/`
actually contain the expected file, and (2) does the logged-in user's client list include that client.

---

## 3. Top-level directory map

| Path | What it is | Should an agent edit it? |
|---|---|---|
| `dashboard/` | The Dash application itself — UI, routing, callbacks | Yes, this is the main app |
| `config/` | Runtime settings (`settings.py`) and user accounts (`users.py`) | Yes, for config/access changes |
| `src/` | Data access layer: loaders, transformers, schemas, S3 sync, logging | Yes, when data-loading logic needs to change |
| `data/` | Local copy of Gold/Silver-layer files, organized by technique/layer/client | Usually not — this is synced/mounted data, not source |
| `documentation/` | Per-technique data contracts and design docs (source of truth for data shape) | Read frequently, edit when contracts/features change |
| `ai_docs/` | Dev-authored implementation notes/specs from past feature work | Read for historical context; treat as informal, may be stale |
| `notebooks/` | Jupyter notebooks used for one-off data exploration | Don't treat as production code; not imported by the app |
| `tests/` | A handful of standalone test scripts (not a full pytest suite) | Yes, if adding tests |
| `new_dashboard/dashboard-ers/` | **A separate git submodule** — a prototype/next-gen dashboard rewrite. Not wired into this app, not deployed from here. See §7. | Only if explicitly asked to work on the new dashboard |
| `logs/` | Runtime log output (`dashboard.log`), gitignored content | No |
| `Dockerfile`, `docker-compose.yml` | Container build/run for the dashboard | Yes, for deployment changes |
| `README.md` (root) | Spanish-language quick-start/ops doc | Keep in sync with `dashboard/README.md` when either changes |

---

## 4. `dashboard/` — the app itself

### Entry point

`dashboard/app.py` is what you run (`python dashboard/app.py` or `python -m dashboard.app`).
It:
- Adds the project root to `sys.path` and configures logging to `logs/dashboard.log`
- Builds the Dash `app` with a `DASH_PATH_PREFIX` env var for mounting behind a reverse
  proxy/ALB, and exposes `<prefix>/health` for health checks
- Serves per-client logos from `dashboard/logos/` at `/logos/<file>`
- Imports every callback module (registering their `@callback`-decorated functions) and calls
  every `register_*_callbacks(app)` function
- On direct execution (`if __name__ == '__main__'`), syncs `data/` from S3 if missing, then
  calls `app.run(...)`

### The tabs / callbacks / components convention

Each feature area follows the same three-file pattern:

- `dashboard/tabs/tab_<name>.py` — pure layout (what the page looks like), often just a shell
  with an internal `dcc.Tabs` for sub-views (e.g. `tab_alerts.py` wraps
  `tab_alerts_general.py` + `tab_alerts_detail.py`)
- `dashboard/callbacks/<name>_callbacks.py` — interactivity: reads data, computes derived
  values, updates the layout. Some modules use `register_<name>_callbacks(app)` called
  explicitly from `app.py`; others use the `@callback` decorator directly and are registered
  just by being imported in `app.py` (both patterns coexist — check `app.py` to see which)
- `dashboard/components/<name>_charts.py` / `_tables.py` — reusable Plotly figures / DataTables
  used by that feature's callbacks

**Don't assume `_tables.py` holds the live table code.** For Aceite and Telemetría specifically,
the actual `dash_table.DataTable` for each feature's main "general table" is built inline inside
the callback file, not in the sibling `_tables.py`:
- Oil's fleet heatmap table (`fleet-heatmap-table`) is built in
  `dashboard/callbacks/machines_callbacks.py` (`update_fleet_heatmap_table`)
- Telemetría's fleet status table (`telemetry-fleet-status-table`) is built in
  `dashboard/callbacks/telemetry_callbacks.py` (`_fleet_status_table` / `update_fleet_overview`)

`dashboard/components/telemetry_tables.py` is dead code as of 2026-08 — its functions
(`build_fleet_priority_table`, `build_system_risk_table`, `build_signal_overview_table`,
`build_signal_kpi`) aren't imported anywhere; the live equivalents live in
`dashboard/components/telemetry_report.py` and inline in `telemetry_callbacks.py`. Grep for a
function's usage before assuming a `_tables.py`/`_charts.py` file is where the real logic lives.

The two general tables above (Oil's and Telemetría's) intentionally share the same visual
convention — header color, cell padding/font-size, status color palette, tooltip CSS — so the
tabs read as one system. If you touch one, check whether the other should be mirrored too. See
[documentation/telemetry/dashboard_proposal.md](telemetry/dashboard_proposal.md) for the as-built
notes on this.

### Alertas → Detalle specifics: the sensor trends chart isn't shared with Telemetría

Despite looking similar, `dashboard/components/alerts_charts.py::create_sensor_trends_chart_golden`
(used by Alertas → Detalle's evidence section) and
`dashboard/components/telemetry_charts.py::build_signal_timeseries_card` (used by Telemetría) are
two independent functions in two independent files — they share no chart-building code, only the
Spanish signal-label dict (`src/charts/signals.py::SIGNAL_LABELS`). Don't assume a styling/gap/
tooltip fix to one needs to touch the other, and don't go looking for a single shared "time series
chart component" in `dashboard/components/` — there isn't one for this purpose.

As of 2026-08, `create_sensor_trends_chart_golden` renders **identically for every client**. It
used to have an `is_capstone` branch that drove completely different trace styles (CDA: markers
only, one trace per `State` value; Capstone: a single continuous `lines+markers` trace with
`connectgaps=True`). That branch is gone. The only surviving `is_capstone` check resolves legacy
column aliases (`engine_speed_rpm`→`EngSpd`, `engine_load_pct`→`EngLoad`) when Capstone's canonical
column is empty — that's a data-column lookup, not rendering, so don't reintroduce client-specific
trace styling there without a strong reason.

**Gap handling**: `_split_gap_segments()` (module level, just above the golden-layer chart
functions in `alerts_charts.py`) splits a time-sorted series into contiguous chunks wherever the
gap between consecutive samples exceeds ~3x the series' median sampling interval. Both the signal
line and the upper/lower limit lines are rendered as one `go.Scatter` trace per segment instead of
one trace for the whole series, so a real data gap shows as a visible break instead of a straight
connector. This is the only gap-detection logic in the codebase — nothing else here uses
`resample`/`reindex` for this — so reuse `_split_gap_segments` rather than writing a second
implementation if another chart needs the same treatment.

**Line styling**: module-level constants `SIGNAL_LINE_COLOR` (gray), `SIGNAL_LINE_WIDTH`, and
`LIMIT_LINE_WIDTH` control the signal line and the upper/lower limit lines respectively — limit
lines are intentionally rendered heavier than the signal line so they don't blend into it.

**Alert-moment overlays**: two independent shapes are added near the end of the function — a
full-height dotted vertical line at `alert_time` on every subplot (marks *when* the alert
happened, pre-existing), and a red highlight rectangle spanning `alert_time ± 30s` ×
`alert_value ± 1` (marks *where*, added 2026-08) drawn on **only** the panel of the feature that
actually triggered the alert. Which feature that is comes from the `Trigger` column on
`alert_data` (matched case-insensitively against the loop's `feature` variable) — if a future
caller stops passing a `Trigger` column, the rectangle silently stops appearing instead of
erroring, so check that column first if the highlight seems to be missing.

### Predictivo specifics: two data sources feeding one page

Predictivo (`dashboard/tabs/tab_predictive_overview.py`, `tab_predictive_evidence.py`,
`tab_predictive_component.py`) is the one tab that routinely reads **two different techniques'
golden layers at once** — its own `predictive/golden/` CSVs plus the Oil technique's
`oil/golden/` files. Don't assume everything on this page comes from one source:

- **Own data**: `data/predictive/golden/{client}/{component}.csv` — one file per component
  (currently only `motor.csv`/`transmision.csv` for CDA, `motor.csv` for Capstone). Components are
  **auto-discovered** by scanning that folder for `*.csv` files (`_discover_components`, duplicated
  identically in `tab_predictive_overview.py`, `tab_predictive_evidence.py`, and
  `predictive_pages_callbacks.py` — there's no single shared helper). Grain is **one row per
  Unit per day**; oil variable columns (`Hierro`, `Cobre`, ...) are forward-filled across every
  daily row between real samples by the upstream pipeline, only `sampleDate` distinguishes a real
  sample from a carried-forward value. Full schema:
  [documentation/predictive/predictive_data_contracts.md](predictive/predictive_data_contracts.md).
- **Borrowed from Oil**: two separate `oil/golden/{client}/` files feed Predictivo:
  - `cleaned_component_hours.parquet` — powers the "Curva Acumulada de Riesgo" chart
    (`dashboard/components/accumulated_curve.py`, rendered via `render_accumulated_section` /
    `build_accumulated_figure`). Joined on `unitId` (normalized `T_09`→`T_9`) +
    `componentName` matching the Predictivo component key exactly (`"motor"`, `"transmision"`).
    Gated entirely on this parquet's existence per client — if it's missing, the page falls back
    to a classic KPI hero instead of the zone-classified one (`_load_component_hours_if_available`
    returns `None` and `_render_component_overview` uses `classic_hero`).
  - `classified.parquet` — powers the oil evidence time-series chart (Evidencia ▸ Evidencia
    Tribológica), via `_load_real_oil_samples` in `predictive_callbacks.py`. This reads real,
    un-forward-filled lab samples so the chart shows genuine sample-to-sample variation instead of
    a staircase. Matching is case-insensitive exact equality on `componentName` **or**
    `componentNameNormalized` — this works cleanly for CDA (`"motor"`/`"transmision"` literal in
    both files) but **not** for every client: Capstone's oil data names the engine `"MOTOR DIESEL"`
    / `"motor diesel"`, which doesn't equality-match the Predictivo key `"motor"`. When no match is
    found the chart silently falls back to the forward-filled `component.csv` column instead of
    rendering empty — check `use_real` in `update_oil_chart` before assuming every client gets the
    real-sample chart.

Because of this dual-source pattern, a "why does this chart look different for Capstone vs CDA"
question is often answered by a naming mismatch between the two golden layers, not a code bug —
check `componentName`/`componentNameNormalized` values in that client's `classified.parquet`
before assuming the matching logic itself is broken.

### Aceite specifics: three internal tabs, three callback files, two AI-text parsers

Aceite (`dashboard/tabs/tab_oil.py`) is a shell holding `dcc.Tabs(id='oil-internal-tabs')`.
`dashboard/callbacks/oil_callbacks.py::render_oil_tab_content` is the router — it switches on the
tab value and returns a different sub-tab's layout, and **each sub-tab's interactivity lives in
its own callback file**, not in `oil_callbacks.py` itself:

| Internal tab (`oil-internal-tabs` value) | Layout | Callbacks |
|---|---|---|
| `fleet-overview` (Visión de Flota, the default) | `tab_machines.py::create_machines_tab` | `machines_callbacks.py` |
| `report-detail` (Detalle de Reporte) | `tab_reports.py::create_reports_tab` | `reports_callbacks.py` |
| `lab-compliance` (Cumplimiento Laboratorio) | `tab_lab_compliance.py::create_lab_compliance_tab` | `lab_compliance_callbacks.py` |
| `component-hours` (Horómetro) | commented out in `tab_oil.py`, see §4 nav table | `tab_component_hours.py` |

**`reports_callbacks.py` is where most of Detalle de Reporte's actual rendering lives**, inline,
the same "don't assume `_tables.py`/`_charts.py` has the real logic" pattern noted above: the
sticky identity header, decision summary, evidence tables, AI diagnosis boxes, and delta-vs-previous
summary are all built as helper functions inside this one callback file
(`create_report_identity_display`, `create_ai_diagnosis_and_action`, `create_delta_summary`, etc.),
not in `oil_charts.py` or `oil_view_models.py`.

**AI comment formatting is two independent parsers, not one shared component**, despite looking
visually identical. Both Alertas and Aceite render an "Análisis Inteligente"-style block —
labeled sections in `p-3 bg-light rounded` boxes with an icon+title header — but the parsing logic
behind each is separate because the underlying text contracts differ:
- Alerts' `mensaje_ia` (`alerts_tables.py::parse_ia_message_sections`, used by
  `alerts_callbacks.py::_alert_case_header`) handles a richer contract: either a JSON payload
  (`diagnostic`/`recommended_actions`/`evidence` keys) or free-text with `DIAGNÓSTICO`/`CAUSA
  PROBABLE`/`ACCIONES` keyword markers, rendered as **3** boxes.
- Oil's `ai_recommendation` (`reports_callbacks.py::_parse_oil_ai_sections`, used by
  `create_ai_diagnosis_and_action`) handles a simpler, fixed format —
  `"Diagnóstico: ...\nAcción: ..."`, always in that order — rendered as **2** boxes (no "causa
  probable"; oil comments don't carry one).

If a comment fails to parse (unexpected format), each parser has its own fallback — don't assume
fixing one function's edge case fixes the other. When asked to change how AI text renders in one
tab, check which of these two parsers is actually in play before reusing logic from the other.

**Unit ID casing isn't consistent across Aceite's own filters.** The Equipo (unit) selector and
sticky identity display in Detalle de Reporte use `.upper()`; the Familia and Componente selectors
in the same sticky header still use `.title()`. This is intentional per current requirements (only
the Unit filter was asked to be uppercased), not an oversight — don't "fix" the others without
checking whether it was actually requested.

### Navigation: what's actually live vs. shelved

`dashboard/layout.py::create_main_dashboard` builds the sidebar from a Python list
(`navigation_items`), **not** from the filesystem — a tab file existing does not mean it's
reachable in the UI. As of this writing:

**Live in navigation:**
- Resumen → General, Estado de Datos
- Monitoreo → Alertas, Telemetría, Aceite (Aceite's internal tabs include Cumplimiento
  Laboratorio; a Component Hours internal tab exists in code but is commented out).
  Telemetría follows the same internal-tabs pattern: 'Vista de Flota' and 'Detalle de Unidad',
  routed by `dashboard/callbacks/telemetry_callbacks.py::render_telemetry_health_tab` (the
  Telemetría equivalent of Aceite's `oil_callbacks.py` internal-tab router).
- Predictivo → one subsection per auto-discovered component CSV, **only shown if the logged-in
  user's client is in `settings.predictive_allowed_clients`**
- Integración / Reportes / Administración → static "En Desarrollo" placeholders, no real content

**Exists in code but commented out of `layout.py` (shelved/in-progress, don't assume it's live):**
`tab_limits.py`, `tab_machines.py`, `tab_reports.py` (superseded by Aceite's internal tabs),
`tab_mantenciones_general.py`, `tab_health_index.py`, `tab_menace_control.py`,
`tab_hot_sheet.py`. Their callback modules may still be imported/registered in `app.py` even
though nothing routes to them — that's not a bug, just dead code kept around for later.

Before editing a tab, **grep `dashboard/layout.py` for its module name** to confirm whether it's
actually wired into navigation.

### Auth

`dashboard/auth.py` has the login/permission logic; `config/users.py` has the actual account
data (username → SHA-256 password hash, role `admin`/`client`, list of accessible clients).
There's no session/JWT system beyond Dash's browser-local `dcc.Store` — auth state lives
client-side in `user-info-store`.

More detail: [dashboard/README.md](../dashboard/README.md).

---

## 5. `data/` — the Data Mesh

Path pattern: **`data/{technique}/{layer}/{client}/{file}`**

- **technique**: `oil`, `telemetry`, `mantentions`, `alerts`, `predictive` (plus a non-conforming
  `auxiliar/{client}/` folder used only for data-freshness timestamps)
- **layer**: `bronze` (raw), `silver` (harmonized/schema-normalized), `golden` (analysis-ready,
  what the dashboard reads almost exclusively)
- **client**: lowercase client folder name (`cda`, `emin`, `enex`, `capstone`)

The dashboard reads **golden** layer almost everywhere for performance. Bronze/silver exist
mostly for the upstream pipeline's own use and for a few loaders in `src/data/loaders.py` that
predate the golden-layer optimization.

Path resolution should go through `config/settings.py::Settings` helpers
(`get_technique_path`, `get_machine_status_path`, `get_stewart_limits_four_path`,
`get_consolidated_alerts_path`, etc.) rather than hand-building path strings, so behavior stays
consistent between local dev and the Docker-mounted path. For oil, `get_stewart_limits_four_path`
(four-limit `LIC`/`LIM`/`LSM`/`LSC` output, data contract v2.8) is what all current oil-technique
dashboard logic reads; the older `get_stewart_limits_path`/`get_stewart_limits_inferior_path`
(legacy three-limit `threshold_normal`/`threshold_alert`/`threshold_critic` shape) remain for
backward compatibility only — see [documentation/oil/dashboard_documentation.md](oil/dashboard_documentation.md#-current-classification-behavior-v28).

---

## 6. `config/` and `src/`

- **`config/settings.py`** — a Pydantic `Settings` object (env-driven via `.env`) holding API
  keys, thresholds (Stewart Limits percentiles, classification cutoffs), and
  **module access-control lists** (`predictive_allowed_clients`, `component_hours_allowed_clients`)
  that gate entire nav sections per client. Accessed as a singleton via `get_settings()`. Not every
  per-client numeric threshold lives in a golden-layer parquet (like Stewart Limits do, see §5) —
  some are plain config, e.g. `lab_compliance_threshold_days_by_client` /
  `get_lab_compliance_threshold_days(client)`, which drives the compliance-window reference line on
  Aceite → Cumplimiento Laboratorio's charts and falls back to
  `lab_compliance_default_threshold_days` (2.0) for any client without an override. Same
  allow-list-style per-client pattern as the access-control lists above, just returning a value
  instead of a boolean.
- **`config/users.py`** — the user/auth database (see §4).
- **`src/data/`** — loaders (`loaders.py`, `maintenance_loaders.py`), a repository layer for
  maintenance data (`maintenance_repository.py`), Pydantic schemas mirroring the data contracts
  (`schemas.py`), transformers/validators (used by the upstream pipeline more than the
  dashboard), a view-model layer for oil data (`oil_view_models.py`), and the S3
  downloader/uploader scripts.
- **`src/utils/`** — logging setup, safe file-reading helpers (`file_utils.py`), date helpers,
  and `auth_logger.py` (appends login attempts to a parquet file and re-uploads it to S3 so the
  audit log survives data resyncs).

---

## 7. Other directories you'll encounter

- **`ai_docs/`** — informal implementation write-ups from past feature work (Hot Sheet, Menace
  Control, alerts specs v1-v3, etc.). Useful for *why* a shelved feature looks the way it does,
  but not guaranteed current — cross-check against actual code.
- **`notebooks/`** — exploration notebooks, not imported by the app. Good for understanding raw
  data shape before it's processed, not for understanding current dashboard behavior.
- **`new_dashboard/dashboard-ers/`** — a **separate git repository** wired in as a submodule. It
  is an independent prototype/rewrite effort with its own `app.py`, `Dockerfile`,
  `docker-compose.yml`, etc. It is **not** part of the running `alerts_dashboard_production` app
  and changes here don't affect it (and vice versa). Don't conflate the two when searching for
  "where is X implemented" — always confirm you're in `dashboard/`, not
  `new_dashboard/dashboard-ers/`, unless the task explicitly targets the new dashboard.
- **`tests/`** — a small number of standalone script-style tests (run directly with `python`,
  not a pytest suite with fixtures/config). Check a test file's own `if __name__` block for how
  it's meant to be invoked.

---

## 8. Documentation map — where to look for what

| Question | Look here |
|---|---|
| High-level feature overview, current nav structure, version history | [documentation/general/dashboard_overview.md](general/dashboard_overview.md) |
| How to run/deploy the dashboard, tab-by-tab feature summary | [dashboard/README.md](../dashboard/README.md) |
| Spanish quick-start / ops cheatsheet | [README.md](../README.md) (root) |
| Oil data shape/contract | [documentation/oil/](oil/) |
| Telemetry data shape/contract | [documentation/telemetry/](telemetry/) |
| Alerts data shape/contract | [documentation/alerts/](alerts/) |
| Mantentions data shape/contract | [documentation/mantentions/](mantentions/) |
| Predictive data shape/contract (golden CSV schema, component auto-discovery, oil-hours cross-dependency) | [documentation/predictive/predictive_data_contracts.md](predictive/predictive_data_contracts.md) |
| Predictive processing/pipeline background notes | [documentation/predictive/](predictive/) |
| Data freshness feature design | [documentation/general/DATA_FRESHNESS_TAB.md](general/DATA_FRESHNESS_TAB.md), [DATA_FRESHNESS_IMPLEMENTATION.md](general/DATA_FRESHNESS_IMPLEMENTATION.md) |
| Historical implementation notes for shelved features | `ai_docs/` |

**Known duplication**: `documentation/general/dashboard_overview.md` and
`documentation/alerts/dashboard_overview.md` both exist with similar names but different scope —
check the folder, not just the filename, when following a link.

---

## 9. Running it locally

```bash
pip install -r requirements.txt
# .env needs at minimum BUCKET_NAME/ACCESS_KEY/SECRET_KEY (for S3 sync) if you don't already
# have a local data/ folder; OPENAI_API_KEY and MAPBOX_TOKEN are optional (AI text, GPS maps)
python dashboard/app.py
# → http://localhost:8080 (or DASHBOARD_PORT)
```

Or via Docker: `docker-compose up -d` (builds from root `Dockerfile`, mounts `./data` read-only
plus live-reload mounts for `./dashboard`, `./config`, `./src`).

---

## 10. Gotchas worth remembering

- **`main.py` doesn't exist.** Don't look for a data-processing entry point in this repo.
- **A tab file existing ≠ a tab being reachable.** Always check `dashboard/layout.py`'s
  `navigation_items` (and, for Aceite specifically, `dashboard/callbacks/oil_callbacks.py`'s
  internal-tab router) before assuming a feature is live.
- **Module access is per-client, not per-role.** Predictive and Component Hours visibility
  depend on the *client's* entry in `config/settings.py` allow-lists, independent of whether the
  logged-in user is `admin` or `client`.
- **`new_dashboard/dashboard-ers/` is a different app.** It's a submodule, not a folder of this
  app's code.
- **Golden layer is king.** If you're adding a dashboard feature, read from `golden/`, not
  `bronze/`/`silver/`, unless there's a specific reason not to.
- **This repo doesn't process data.** If a bug looks like "the classification/AI output is
  wrong," it's very likely an upstream pipeline issue, not something fixable in this repo.
- **A function computing something ≠ that something being rendered.** Some callbacks compute
  widgets that are never returned/displayed because of an earlier `return` in the same function
  (e.g. `telemetry_callbacks.py::update_fleet_overview` builds KPI cards, a Plotly heatmap and an
  insights row, then hits `return _fleet_status_table(...)` before any of that code runs). Trace
  the actual `return` path before assuming a widget you see referenced in code is live in the UI.
- **Alertas → Detalle's sensor trends chart and Telemetría's chart are different functions in
  different files**, not a shared component, even though they look alike. As of 2026-08 that
  chart (`create_sensor_trends_chart_golden` in `alerts_charts.py`) renders identically for CDA
  and Capstone, splits traces on real time gaps via `_split_gap_segments`, and draws the
  alert-highlight rectangle only on the triggering feature's panel (from the `Trigger` column) —
  see §4's Alertas → Detalle subsection before assuming client-specific rendering exists there.
- **Alertas and Aceite each have their own AI-comment section parser** —
  `alerts_tables.py::parse_ia_message_sections` (3 sections, JSON-or-keyword contract) and
  `reports_callbacks.py::_parse_oil_ai_sections` (2 sections, fixed `Diagnóstico:`/`Acción:`
  format). They render visually the same way on purpose, but are not the same code — see §4's
  Aceite subsection before assuming a change to one applies to the other.
- **Predictivo silently mixes two techniques' golden layers** (its own `predictive/golden/` CSVs
  plus `oil/golden/cleaned_component_hours.parquet` and `oil/golden/classified.parquet`), and the
  join between them is a plain string equality on component name (`"motor"`, `"transmision"`) that
  only holds for clients whose oil data happens to use those exact names. A component/client
  combo that "has no chart" or "shows different data than another client" is often a naming
  mismatch between the two files, not a broken calculation — see §4's Predictivo subsection before
  digging into the chart code itself.
