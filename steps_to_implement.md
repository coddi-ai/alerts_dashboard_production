# Mantenciones tab — port from w34 to dev

Source: commit `141b7c1` ("feat: W34 dashboard maintenance improvements") on
branch `w34/pandas-only-no-polars`. Isolated by diffing against the branch's
merge-base with `dev` (`88bc2ab`) — every file this commit touches is
identical between `dev` and that merge-base, so it applies cleanly with no
divergence to reconcile except the JSON file noted below.

The commit's scope is entirely the Mantenciones tab and its nav wiring; no
unrelated work (Campbell AI, Centinela, the pandas/Polars refactor — the
other two commits on w34) is included here.

## What changes

1. **Filters** — Date Range, System (multi-select), Equipment (multi-select,
   cascades off System) added above the KPI row. Empty selection = full
   dataset, matching prior no-filter behavior.
2. **New chart** — "Mantenciones por Sistema" Pareto chart (bar counts +
   cumulative-% line), excluding the generic "Equipo" and "Estación del
   Operador - Cabina" systems so they don't dominate it.
3. **Repository filtering** — `MaintenanceRepository` gains `systems` /
   `equipment` / `date_start` / `date_end` params threaded through
   `get_status_counts`, `get_downtime_mtd`, `get_last_detentions`,
   `get_jobs_last_week`, `get_downtime_by_day_mtd`, plus new
   `get_available_systems`, `get_available_equipment`,
   `get_maintenance_by_system`, and private helpers `_filtered_actions`,
   `_machines_for_systems`. Status KPIs deliberately ignore the date range
   (equipment status is real-time, not historical).
4. **Page routing** — new page `dashboard/pages/monitoring_mantenciones.py`
   registers `/monitoring/mantenciones`; wired into `dashboard/app.py`'s
   explicit page imports and into `dashboard/services_registry.py` (nav
   label "Mantenciones", section "Monitoreo").
5. **Service flag** — new service id `monitoring-mantenciones` added to
   `config/client_services.py:KNOWN_SERVICE_IDS` and enabled per-client in
   `config/client_services.json`.
6. **Layout polish** — "Última actualización" moved from page footer into
   the header row; KPI cards get a `scope_label` ("Estado actual" vs.
   "Acumulado MTD"); donut chart legend de-duplicated against slice labels;
   downtime trend title shows the last plotted day.

## Files touched

| File | Change |
|---|---|
| `dashboard/pages/monitoring_mantenciones.py` | new file — page registration |
| `dashboard/app.py` | +1 import line |
| `dashboard/services_registry.py` | + nav entry (section/label/path/route) |
| `config/client_services.py` | + `monitoring-mantenciones` to `KNOWN_SERVICE_IDS` |
| `config/client_services.json` | + `monitoring-mantenciones` per client (reconciled by hand, see below) |
| `dashboard/callbacks/mantenciones_general_callbacks.py` | + filter callbacks, Pareto callback, extended `load_general_data` |
| `dashboard/tabs/tab_mantenciones_general.py` | + filters UI, Pareto chart card, `create_system_pareto_chart`, KPI scope labels |
| `src/data/maintenance_repository.py` | + filtering params/methods described above |

## `config/client_services.json` reconciliation

The working copy had an uncommitted, syntactically-broken in-progress edit
(dangling `"monitoring-"` key, plus EMIN's `monitoring-telemetry` flipped to
`false`). Per user decision:
- The broken key is fixed by completing the `monitoring-mantenciones` entry
  from the w34 commit.
- EMIN's `monitoring-telemetry: false` is **kept** (user confirmed
  intentional, not part of this port).
- `monitoring-mantenciones` enabled for: `CDA` (`dummy: false`), `EMIN`
  (`dummy: true`), `CAPSTONE` (`dummy: true`) — matches w34. Not added for
  `ENEX` or `CENTINELA` (unchanged there in the source commit).

## Steps executed

1. `git checkout 141b7c1 -- dashboard/pages/monitoring_mantenciones.py dashboard/app.py dashboard/services_registry.py config/client_services.py dashboard/callbacks/mantenciones_general_callbacks.py dashboard/tabs/tab_mantenciones_general.py src/data/maintenance_repository.py`
   (safe: dev's tree for these paths is byte-identical to the commit's
   parent, so this is a lossless, non-destructive file restore — not a
   merge or cherry-pick of history.)
2. Hand-edit `config/client_services.json` to fix the broken JSON and add
   `monitoring-mantenciones`, preserving the `CENTINELA` block and EMIN's
   telemetry flag as decided above.
3. Validate: `python -c "import json; json.load(open('config/client_services.json'))"`,
   `python -m py_compile` on each touched `.py` file, and (if available) run
   the existing test suite.
4. Leave everything **uncommitted** in the working tree for user review —
   no commit, no push, no merge/cherry-pick command run.
