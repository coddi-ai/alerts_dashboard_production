# Migration Guide — Conexión ERP Dashboard

Two new pages for the main dashboard: **Validación de Avisos** (review/approve/reject) and
**Seguimiento de Avisos** (KPIs/charts/table). Built and tested in isolation in a standalone repo;
this is the handoff for wiring them into the real platform.

## What's in this folder

```
dashboard/erp/validator.py         ← Validación de Avisos page (layout + callbacks) — port this
dashboard/erp/viewer.py            ← Seguimiento de Avisos page (layout + callbacks) — port this
dashboard/erp/write_operations.py  ← approve / reject / send-to-ERP — port this, likely your net-new work (§5)
dashboard/app.py                   ← throwaway standalone shell — do NOT port, see §1
data_contract.md                   ← Warning schema + SAP field mapping — the contract to build against
reference/                         ← Coddi backend code these pages currently call — read-only, see below
```

`validator.py`/`viewer.py`/`write_operations.py` all import from a package called `agent` (e.g.
`from agent import warning_writer`). **That package does not exist on your side, and you're not
expected to make it exist** — it's Coddi's own backend/pipeline code, included in full under
`reference/` purely so you can see what each call currently does, instead of guessing from the
function name alone. `reference/README.md` has a one-line summary of every file in there plus what
you actually need to do about it. Every section below tells you the same thing inline, so you
shouldn't need to go open `reference/` unless you want the exact current implementation.

## 1. Page registration

`dashboard/app.py` only exists because this repo has no real host app to register pages into — it
is not part of the handoff. The one thing worth keeping from it is the exact registration call,
since the file itself won't survive:

```python
dash.register_page("validator", path="/erp/validacion-avisos", name="Validación de Avisos", layout=validator.layout)
dash.register_page("viewer", path="/erp/seguimiento-avisos", name="Seguimiento de Avisos", layout=viewer.layout)
```

Register both against the real app (adjust `path`/`name` to fit your platform's URL/nav
conventions if needed), add nav entries, done.

**Runtime dependencies** (add to whatever environment hosts the real dashboard, if not already
present): `dash>=2.16`, `dash-bootstrap-components>=1.5`, `dash-ag-grid>=31.0`, `plotly>=5.20`,
`pandas>=2.2`, `pydantic>=2.6` (for the `Warning` model — see §4). No environment variables or
secrets are required by this dashboard code itself.

## 2. Known data-layout mismatch — a real bug to fix, not a style choice

The current storage layer (`reference/warning_writer.py::_path()`) lays every warning out as:

```
{client_id}/warnings/{state}.parquet      # e.g. client_a/warnings/pending.parquet
```

i.e. client is the top-level grouping, warnings nested under it. **Your platform's existing data
layer is organized the other way round — `warning/{client}/...`, warnings as the top-level
grouping with client nested underneath.** This is a genuine structural incompatibility, not
naming: every read and write currently goes through that one path convention. It matters here
because it's easy to miss — nothing in `validator.py`/`viewer.py` shows a file path directly, it's
buried one level down in code you're not even porting. When you build the real read/write layer
(§4/§5), make sure client-vs-warning nesting matches your platform's actual layout, not this one.

## 3. Client selection — build a global filter, don't port the local one

Your platform filters everything by one **global** client selector. The pages as given do not use
it: `validator.py` and `viewer.py` each have their **own independent, page-local** client dropdown,
each populated by listing config files (`validator.list_client_ids()` / the equivalent inline code
in `viewer.layout()`). Selecting a client on one page has no effect on the other, and each just
defaults to whichever client happens to sort first alphabetically.

What to implement instead:

- **Delete both dropdowns and their population logic** (`list_client_ids()` in `validator.py`, the
  glob-based list in `viewer.layout()`). Your platform's global filter replaces them entirely, not
  just their data source.
- **Wire every place that currently reads the local dropdown to read the global filter instead:**
  `validator._refresh_pending_list`, `validator._handle_action`, `viewer._refresh`, and
  `viewer._populate_asset_options` all currently take `client_id` from one of the two local
  dropdowns (via a Dash `Input`/`State`). Point all four at wherever your platform's global client
  filter already lives — a shared store, a URL param, server-side session, whatever mechanism the
  rest of the platform already uses for this.
- **The asset-id filter on the Viewer page depends on client as a second step** — right now it
  repopulates when the local client dropdown changes. Once client comes from the global filter,
  that dependency needs to be rewired to fire off the global filter changing instead, or it'll go
  stale silently when the user switches client.

## 4. What "read" needs to do

Both pages need two read operations, currently implemented against local Parquet files
(`reference/warning_writer.py`) — you're replacing the implementation, not the operation:

| Needed | Currently called as | What it must return |
|---|---|---|
| All pending warnings for a client | `list_pending(client_id)` in `validator.py` | A list of Warning records with `status = pending`, for the pending-list panel |
| Every warning for a client, all states | `load_all_warnings(client_id)` in `viewer.py` | A list/table of every Warning record regardless of status, for the KPIs/charts/table |

Point both at your platform's existing warning-read layer instead of the Parquet file store.
Whatever it returns must match the Warning shape in `data_contract.md` §1 — same fields, same
enum values — since that's what the UI code renders field-by-field. If your data already has this
shape under different names, adapt at the boundary (a thin mapping function) rather than changing
the UI code.

## 5. What "write" needs to do — this is the net-new piece

`dashboard/erp/write_operations.py` holds the **only** state-mutating logic in either page —
everything else is read/display. It's split into its own file precisely so it's the one piece to
build if your dashboard is currently read-only:

| Function | What it must do |
|---|---|
| `can_approve(title, asset_id, recommended_action) -> bool` | Pure validation, no I/O: true only if all three are non-empty. Keep as-is, no backend needed. |
| `approve_and_send(client_id, warning_id, operator_id, title, description, recommended_action, operator_notes, severity) -> Warning` | Apply the operator's edits to the warning, move its status from `pending` to `validated`, then attempt the ERP push; on success move it to `sent` with `erp_reference` set, on failure leave it `validated` with the error in `operator_notes`. |
| `reject(client_id, warning_id, operator_id, reason) -> Warning` | Move the warning's status from `pending` to `rejected`, recording `reason` and no ERP call. |

Two things currently do the heavy lifting inside those functions, both stubbed/local in this repo
and both things you need a real implementation of:

- **State transition** (`reference/warning_writer.py::transition()`) — moving a warning record from
  one status to another with field edits applied. Implement this against your platform's real
  warning store, keeping the same three function signatures above so the page code (`validator.py`)
  doesn't need to change.
- **ERP push** (`reference/erp/sap_adapter.py::push_to_erp()`) — builds a SAP payload from the
  warning and sends it. Right now this is a **stub**: it logs the payload and returns a synthetic
  notification number, it does not call real SAP. The exact field mapping it's meant to implement
  is in `data_contract.md` §2 — that's the contract to build a real connector against.

If warnings are written through an existing backend service rather than in-process, an equivalent
REST shape already exists as a reference: `PATCH /warnings/{id}`, `POST /warnings/{id}/send` (see
`reference/README.md` for where that lives) — mirror that instead of the function calls above if
it's a better fit.

Either way, **the 40-character title cap (`MAX_TITLE_LENGTH` in `write_operations.py`) must be
preserved** — it maps directly to SAP's Short Text field limit.

## 6. Fix before this goes live

- **Hardcoded operator identity.** `validator.py`'s approve/reject callback currently passes
  `operator_id="operator"` (a literal string, not a real user) into `approve_and_send`/`reject`.
  Replace with the logged-in user's ID from your auth context.
- **No authz check.** Nothing currently gates who can click approve/reject/send. Add whatever
  permission check the platform normally applies to ERP-write actions.
- **No concurrency protection.** The reference `transition()` briefly writes to the target state
  before removing the record from the source — a crash mid-transition can leave a warning in two
  states at once. Low risk with one local operator; worth hardening if your platform's write path
  supports concurrent operators on the same client.

## 7. Styling

Layouts use `dash-bootstrap-components` (`dbc.Card`/`Row`/`Col`) and Font Awesome icon classes
(`fas fa-*`). `dashboard/app.py` pulls both from a CDN only to make the standalone shell render —
don't carry that over; use the platform's existing `dbc` theme and icon library. A few literal hex
colors exist in `viewer.py` (`_LABEL_COLOR`, `_SOURCE_COLOR`, `_SYSTEM_COLOR_SEQUENCE`, KPI card
backgrounds) — swap for the platform's chart/semantic color tokens if it has them.

All UI text is hardcoded Spanish with no i18n hook — extract into your string-table system if one
exists.
