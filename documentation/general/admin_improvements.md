# Admin Improvements — User Registration Log & Client Service Register

## 1. User Registration Log

### 1.1 Investigation of the previous writer (spec §1.6)

Before it was replaced, `src/utils/auth_logger.py::log_authentication()` was the only
place `authentication_register` was written:

- **Where it was created / who wrote it**: called from
  `dashboard/callbacks/auth_callbacks.py`'s `login()` callback, on both successful and
  failed login attempts. No other process touched it.
- **Upload mechanism**: `pd.read_csv` the existing local file (if present), `pd.concat`
  the new row, `df.to_csv()` back to the same local path
  (`data/auxiliar/authentication_register.csv`), then
  `s3_client.upload_file(...)` to a **fixed** S3 key
  (`MultiTechnique Alerts/auxiliar/authentication_register.csv`) with no ETag/version
  check - every upload unconditionally overwrote whatever was already in S3.
- **Concurrent executions**: yes, they could replace each other. The read-modify-write
  of the local CSV plus the subsequent upload is not atomic; two logins racing on the
  same instance could both read the same "existing" file and each append their own row,
  with the second `to_csv`/upload winning and silently dropping the first login's row.
- **Empty/incomplete local file uploaded to S3**: yes, this was the most serious failure
  mode. The local CSV lived on the container's local disk, not any persisted/shared
  volume. A freshly started or redeployed container has an empty `data/auxiliar/`
  directory, so its very next login would create a brand-new one-row CSV and
  unconditionally overwrite the S3 object that held the *entire* prior history -
  silently truncating it. Multiple app replicas behind a load balancer make this worse:
  each replica has its own local history, and whichever one logs a user in next
  overwrites the S3 object with only its own (partial) view.
- **Multiple environments sharing the same S3 key**: the S3 key was a literal fixed
  string with no per-environment segment; environments are only separated if they use
  different `BUCKET_NAME` values. `deploy_status` was recorded per row but only as a
  data column, not as part of the key, so it does not prevent a same-bucket collision
  across environments.

### 1.2 Replacement

`src/utils/auth_event_logger.py::log_authentication_event()` writes one independent
JSON object per successful login directly to S3 (`put_object`, no local file, no
read-modify-write of shared state) under
`MultiTechnique Alerts/auxiliar/authentication_register/year=YYYY/month=MM/day=DD/<timestamp>_<event_id>.json`,
keyed by a UUID so concurrent logins can never collide. `src/data/auth_events_repository.py`
reads and consolidates these objects for the admin chart, skipping any individual
malformed object without breaking the rest of the view.

### 1.3 Migration decision

No historical backfill from the old CSV/S3 object was performed (out of scope per the
requirement doc). The old file is left untouched in S3 - it simply stops being written
to, since the writer that produced it was removed.

## 2. Client Service Register

Replaces the ad hoc, per-module allow-lists that used to live in `config/settings.py`
(`predictive_allowed_clients`, still used for the `component_hours` sub-tab flag - see
below) with a single YAML-backed configuration (`config/client_services.yaml`) and one
authorization function, `config/client_services.py::is_service_enabled(client_id,
service_id)`, used everywhere access needs to be checked: the sidebar builder
(`dashboard/layout.py`), the centralized route guard
(`dashboard/callbacks/access_control_callbacks.py`), and the predictive content callback
(`dashboard/callbacks/predictive_pages_callbacks.py`).

`component_hours_allowed_clients` (`config/settings.py`) was intentionally **not**
migrated - it gates a sub-section within an existing tab (machines/oil/predictive), not
a route-level service, so it's outside this route-oriented service register's scope.

### Design notes

- Service identifiers reuse the app's existing internal nav ids (`overview-general`,
  `monitoring-alerts`, `predictive`, ...), per the requirement that identifiers match
  internal route/module identifiers.
- Sidebar visibility is computed against **any** of the logged-in user's assigned
  clients (matching the pre-existing predictive-nav behavior), while route enforcement
  checks the **currently selected** client (`client-selector`). A multi-client admin
  therefore sees a service in the sidebar if any of their clients has it enabled, but
  gets redirected away from it if they navigate there while a client without that
  service selected.
- Blocked access (disabled service, or non-admin hitting `/admin/*`) is a silent
  redirect to the user's first enabled service (or `/sin-servicios` if none) - no
  separate access-denied page, matching the app's existing predictive-module precedent
  of degrading gracefully rather than showing an explicit "denied" screen.
