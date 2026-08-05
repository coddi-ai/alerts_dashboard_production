# Reference code — read, don't run

Everything in this folder is an exact copy of Coddi's existing backend/pipeline code (the `agent`
package in the `warning_to_erp` source repo). **It is not part of what you're building, and it is
not expected to run in your environment** — there is no `agent` package on your side, and these
files won't import successfully as-is. They're included so you can see exactly what each piece of
logic the dashboard depends on actually does, instead of having to take it on faith or go find a
separate repo.

For each file: what it's for, and what you actually need to do about it.

| File | What it does | What you need to do |
|---|---|---|
| `envelope.py` | Defines the `Warning` record (every field a warning has) and the enums/Spanish-label dicts (`Severity`, `Source`, `System`, `ConditionLabel`, `WarningStatus`, and their `*_LABELS` dicts) that the dashboard renders. | Nothing to build here — this is pure data shape. The same fields/enums are documented in `../data_contract.md` §1; that table is the actual contract to match. If it's easier, your own read/write layer can literally return objects shaped like this `Warning` class. |
| `warning_writer.py` | Reads/writes warnings to Parquet files, one file per client per lifecycle state (`pending`/`validated`/`rejected`/`sent`). `transition()` is the one that matters most: move a record from one state to another, applying field edits, in one call. | You're not implementing a Parquet store — you're replacing every call into this file with equivalent calls into your platform's existing warning storage. The two things to preserve are the *operation* each function performs (see `migration_guide.md` §4/§5) and the file-layout convention, which is wrong here — see `migration_guide.md` §2. |
| `client_config.py` | Reads a per-client YAML file (`sap.notification_type`, `sap.planning_plant`, etc. — the client's SAP org settings) needed to build an ERP payload. | You need *some* source for these same per-client SAP fields — check whether your platform already stores them (likely, if it already talks to SAP) before building a new config store. |
| `erp/sap_adapter.py` | `push_to_erp()` is what the "Aprobar y Enviar al ERP" button calls: find the warning, build the SAP payload, send it, record the result. `SAPAdapter.send()` is currently a **stub** — it doesn't call real SAP, just logs the payload and returns a fake notification number. | The exact SAP field mapping this code implements is already extracted into `../data_contract.md` §2 — that's the contract to build a real connector against, not this file. This file is here so you can see the *shape* of the orchestration (`push_to_erp`) that `write_operations.py` currently calls. |
| `erp/base.py` | An abstract interface (`build_payload`/`parse_response`) that `SAPAdapter` implements — exists so a second ERP type (Ellipse, Maximo) could be added later. | Not relevant to this handoff. Included only because `sap_adapter.py` references it. |
| `api_main.py` | A local REST API wrapping the same read/write operations `warning_writer.py`/`sap_adapter.py` expose in-process (`GET /warnings`, `PATCH /warnings/{id}`, `POST /warnings/{id}/send`). Same operations, different transport. | Useful only as a shape reference if your platform's warning read/write goes through a backend service rather than in-process calls — see `migration_guide.md` §5. |

If your platform is not a Python/Dash stack, none of these files are directly reusable regardless —
treat them purely as the executable specification of what each integration point needs to do.
