# Performance Diagnosis — Slow-Loading Tabs (EC2 + EFS deployment)

**Status**: Diagnosis only. No code changes were made. This document is meant to guide
what to check next and what fixes to prioritize.

**Scope**: This covers the dashboard app (`dashboard/`, `src/data/`, `config/`) and how it
reads from the EFS-backed `data/` mesh. It does not touch the Campbell AI sidecar's own
internals except where it competes for the same host resources.

---

## 1. Executive summary

The slowness is very unlikely to be one single cause. Three independent problems compound
each other, roughly in order of expected impact:

1. **The dashboard is served by Flask's development server with no threading/worker
   configuration**, so concurrent requests (including a single user's own tab, which fires
   several callbacks in parallel) queue up and serialize instead of running concurrently.
2. **The same large file is read from disk and re-parsed with pandas multiple times per
   tab render**, with no in-process caching in the two heaviest areas (Aceite's Reporte
   detail and Visión de Flota, Predictivo). Every one of those reads is a network round
   trip because `data/` lives on EFS, not local disk.
3. **EFS itself may be throughput/IOPS-constrained** (burst-credit General Purpose mode,
   or a mount target in a different AZ), which turns "many redundant reads" from an
   annoyance into a hard bottleneck. This can only be confirmed in the AWS console, not
   from the repo.

None of this requires a rewrite. The fixes are incremental: add caching where it's already
missing (a pattern that already exists elsewhere in the codebase), and put a real WSGI
server in front of the app.

---

## 2. What to check first (measure before optimizing)

Before changing anything, confirm which of the above is actually dominant for your
deployment:

- **Which tabs are slow?** Aceite → Visión de Flota / Detalle de Reporte and Predictivo are
  the most likely candidates based on the code (see §3). Telemetría has partial caching
  already. If it's *all* tabs equally, that points more toward infra (server/EFS) than
  code; if it's specific tabs, that points at the per-tab data-loading pattern.
- **Browser DevTools → Network tab**: open a slow tab, look at the `_dash-update-component`
  requests. If several fire and each takes seconds, it's the callback layer. If one request
  is slow and blocks everything else (including the next user's requests), that's the
  single-threaded server.
- **CloudWatch on the EC2 instance**: CPU utilization during a slow load. If you're on a
  burstable instance type (`t3.*`/`t4g.*`) and CPU Credit Balance is near zero, the
  instance itself is throttled — this alone can explain intermittent slowness that gets
  worse over the day.
- **CloudWatch on the EFS file system**: `PermittedThroughput` vs actual throughput,
  `BurstCreditBalance` (if using General Purpose bursting mode), and per-operation latency
  metrics. A shrinking burst credit balance under load is a strong signal that EFS mode
  needs to change (Provisioned Throughput or Elastic).
- **Confirm AZ alignment**: the EC2 instance and the EFS mount target it uses should be in
  the same Availability Zone. Cross-AZ NFS traffic adds latency to every single file
  operation (`open`, `stat`, `read`), which multiplies badly given how many separate reads
  some callbacks issue (see §3.2).
- **`logs/dashboard.log`**: every loader call logs at INFO level with row counts
  (`dashboard/app.py:17-24` configures `logging.FileHandler('logs/dashboard.log')`).
  Compare timestamps between consecutive "Loading X from Y" lines for a single tab render —
  this alone will show you which specific file read is slow and how many redundant reads
  happen per click, without adding any instrumentation.

---

## 3. Findings

### 3.1 No production WSGI server — biggest structural risk

`dashboard/app.py:234-238` starts the app with:

```python
app.run(host=host, port=port, debug=debug)
```

No `threaded=True`, no `processes=`, and `requirements.txt` has no `gunicorn`/`waitress`/
`gevent`. `Dockerfile:70` runs `CMD ["python", "dashboard/app.py"]` directly — so the
container is running Flask's built-in development server in production.

By default this server handles **one request at a time**. Concretely:

- If two users load the dashboard at the same moment, the second one waits for the first
  one's callback to finish before their own request even starts being processed.
- Worse: Dash's own client fires multiple callbacks per page/tab load (KPIs, table, chart,
  filters) as separate HTTP requests. Those requests queue behind each other on a
  single-threaded server instead of running concurrently, even though nothing about them
  is actually sequential.

This alone can make a tab that "should" take 1-2 seconds feel like 5-10+ seconds under any
concurrent load, and it gets worse linearly with the number of active users.

**Note for later**: `Dockerfile:41-43` already documents that `CAMPBELL_AI_SESSION_BACKEND=memory`
"is process-local and only valid for a single worker; any deployment with more than one
worker or replica must use `redis`." This means the team has already anticipated moving to
a multi-worker setup — the Campbell AI side is ready for it, the Dash side (`app.run`) is
the piece still on the dev server.

### 3.2 The same large file is read and re-parsed multiple times per tab

This is the most concrete, most fixable finding. Two Aceite (oil) callback files bypass
`src/data/loaders.py` entirely and call `safe_read_parquet` directly, with **no caching**:

- **`dashboard/callbacks/reports_callbacks.py`** (Detalle de Reporte tab) reads the same
  `classified.parquet` file (`reports_file`, via `settings.get_classified_reports_path`)
  independently in **10 different callbacks**: lines 211, 259, 311, 368, 448, 538, 679,
  736, 823, 871. Each one re-opens the file from EFS and re-runs pandas parsing from
  scratch. Depending on which UI elements are visible/change together, several of these can
  fire on a single interaction.
- **`dashboard/callbacks/machines_callbacks.py`** (Visión de Flota tab, the *default* Aceite
  view) reads `classified.parquet` independently in `update_kpis` (line 115),
  `update_component_options` (line 169), and `update_fleet_heatmap_table` (line 214), plus
  `machine_status.parquet` a second time in each of those (lines 130, 230, and again further
  down). Changing the client or a single filter re-triggers all of them.

Compare this to the pattern that already exists and works well in `src/data/loaders.py`:
`_load_alerts_data_cached`, `_load_telemetry_alerts_detail_golden_cached`, and
`_load_oil_classified_cached` (lines 457, 680, 720) all use `@lru_cache(maxsize=8)` keyed by
client, with the public function returning a defensive `.copy()`. The comment above them
(`loaders.py:29-34`) explains exactly why: "These files are read by several Dash callbacks
during a single interaction... Keep one process-local parsed copy." That reasoning applies
identically to `reports_callbacks.py` and `machines_callbacks.py`, it just wasn't applied
there.

`dashboard/callbacks/telemetry_callbacks.py` already does something similar in its own way
(`_load_recent_telemetry_signal_cached`, `lru_cache(maxsize=256)`, line 576-581), so
Telemetría is comparatively better protected — which is consistent with Aceite/Predictivo
being the more likely "slow tab" candidates if the slowness is code-driven rather than
infra-driven.

### 3.3 Predictivo: a 25MB CSV is parsed and aggregated synchronously, uncached

`data/predictive/golden/cda/motor.csv` and `transmision.csv` are **~22-25 MB each**
(confirmed by file size). `dashboard/tabs/tab_predictive_overview.py::_load_component_data`
(line 46) does, on every call:

```python
df = pd.read_csv(filepath)                      # full 25MB parse
df["Fecha"] = pd.to_datetime(df["Fecha"])
...
df_latest = df.sort_values("Fecha").groupby("Unit").last().reset_index()
df_sorted = df.sort_values(["Unit", "Fecha"]).copy()
for col in score_cols:
    grouped = df_sorted.groupby("Unit")[col]
    rolling_cols[...] = grouped.transform(...)   # rolling window per column
```

None of this is cached. Every visit to Predictivo (and every filter change that re-triggers
this loader) re-downloads the file over NFS and re-runs the full parse + two separate
sort/groupby passes + rolling-window transforms. `_discover_components` (line 29) also lists
the directory with `os.listdir` on every call — on EFS, directory listing is itself a
network round trip, not a free local syscall.

The same doc-noted pattern (`documentation/codebase_explaining.md` §Predictivo) mentions
`_discover_components` is duplicated identically across three files with no shared helper —
worth keeping in mind if you centralize the caching, since fixing one copy won't fix the
others.

### 3.4 Data volume and file layout make EFS latency more painful than it needs to be

`data/telemetry/` alone is **3.7 GB**, with individual weekly parquet files in the 13-22MB
range (e.g. `data/telemetry/silver/cda/Telemetry_Wide_With_States/Week16Year2025.parquet` at
~19MB). `data/predictive/` is 55MB (dominated by the two CSVs above). `data/oil/` is 9.4MB,
`data/mantentions/` 6.7MB — these are comparatively small and not a likely source of
slowness by themselves.

Several loaders in `src/data/loaders.py` do their own directory scans to find "the latest"
file before reading it:

- `_latest_telemetry_partition` (line 772) globs `year=*` then `week=*` subdirectories —
  two nested glob calls, each one or more NFS round trips, before the actual parquet read
  even starts.
- `load_telemetry_baselines` (line 974) and the "limits" branch of `load_telemetry_limits`
  (line 1026) each do `sorted(dir.glob(...))` to find the newest file by filename.

None of this is wrong logic — it's necessary given the partitioned file layout — but on a
network filesystem, "list a directory, then read a file" costs meaningfully more than on
local SSD/EBS. This is a case where the fix isn't "read less data" but "don't repeat the
directory-listing step on every request" (see §5).

`_load_latest_telemetry_output` (line 822) does one thing right that's worth calling out as
a good existing pattern: when a `columns` list is passed, it inspects the parquet schema via
`pyarrow.parquet.ParquetFile(...).schema.names` first and only reads the columns that are
both requested and present (lines 838-849), instead of loading the full wide table. This
column-projection pattern is **not** used in the oil (`reports_callbacks.py`,
`machines_callbacks.py`) or predictive loaders, which read every column of `classified.parquet`
/ `motor.csv` even when a given callback only needs a handful.

### 3.5 No cross-request / cross-user cache

Every `@lru_cache` in the codebase is process-local, which is fine as long as the app stays
a single process (see §3.1) — it means two users looking at the same client benefit from
each other's cache-warming. But it also means:

- Restarting the container (deploys, crashes, autoscaling events) drops the cache
  completely, and the first request after a restart pays full cost for every uncached
  loader.
- If §3.1 is fixed by moving to multiple worker processes, in-memory `lru_cache` stops being
  shared across workers — same problem the team already solved for Campbell AI sessions via
  `CAMPBELL_AI_SESSION_BACKEND=redis`. Any equivalent move for the dashboard's own data
  cache needs the same kind of shared backend (Flask-Caching with a filesystem or Redis
  backend), not just more `@lru_cache`.

### 3.6 Logging overhead (minor, but easy to rule out)

`dashboard/app.py:17-24` logs to both stdout and `logs/dashboard.log` at `INFO` level, and
essentially every loader function logs a line per call (e.g. `logger.info(f"Loaded {len(df)}
...")`). This is not a major cost by itself, but if `./logs` (mounted at `docker-compose.yml:22`)
ends up on the same EFS mount as `data/`, every log line is also a network write. Worth
ruling out via the CloudWatch/EFS check in §2 rather than assuming it's significant — it's
unlikely to be a top contributor, but it's a one-line thing to confirm.

### 3.7 Campbell AI sidecar shares the same host

`docker-compose.yml` runs the dashboard and the `campbell-api` (FastAPI/uvicorn) container
on the same Docker host. If that's the same EC2 instance referenced in this diagnosis, CPU
and memory are shared between the two. Campbell AI requests are comparatively rare and
bounded (`CAMPBELL_AI_MAX_CONCURRENT_REQUESTS=10`, `Dockerfile:56`), so this is unlikely to
be a primary cause, but it's worth a glance at CloudWatch during a slow-tab incident to rule
out a coincidental AI request spike.

---

## 4. Likely ranking (to confirm via §2, not assumed)

1. Single-threaded dev server (§3.1) — affects *every* tab, worse under concurrent users.
2. Repeated uncached reads of `classified.parquet`/`machine_status.parquet` in Aceite
   (§3.2) — specific to Visión de Flota and Detalle de Reporte.
3. Uncached 25MB CSV parse + aggregation in Predictivo (§3.3) — specific to that tab.
4. EFS throughput/IOPS mode and AZ placement (§2) — amplifies #2 and #3, can't be confirmed
   from the repo alone.
5. Directory-listing-before-read pattern for partitioned telemetry files (§3.4) — likely
   secondary, since Telemetría already has partial caching (§3.2's Telemetría note).

---

## 5. Options to consider (not applied — for discussion)

Roughly ordered by effort:

- **Put a real WSGI server in front of Dash.** Options: `gunicorn` with multiple sync
  workers (Linux-friendly, simplest), or `waitress` if you need something that also runs
  well on Windows dev machines. This directly addresses §3.1 and is likely the single
  highest-leverage change given it affects every tab, not just the ones with heavy data
  loading.
- **Cache the repeated same-file reads.** Wrap the `classified.parquet` /
  `machine_status.parquet` reads in `reports_callbacks.py` and `machines_callbacks.py`
  behind the same `@lru_cache`-per-client pattern already used in `loaders.py` (§3.2), and
  do the same for `_load_component_data` in Predictivo (§3.3). This is a small, localized
  change per file and follows a pattern the codebase already trusts.
- **Invalidate on data refresh, not just process restart.** The existing `lru_cache`
  comment says the cache boundary is "the normal data refresh boundary for the mounted data
  directory" — i.e. it assumes a container restart accompanies every data sync. If that's
  not actually guaranteed operationally, consider keying the cache off file mtime (e.g.
  cache key includes `path.stat().st_mtime`) instead of relying on restarts, so stale data
  can't linger silently.
- **Move to a shared cache backend if/when workers become multi-process.** Flask-Caching
  (filesystem or Redis backend) instead of `functools.lru_cache`, consistent with how
  Campbell AI already handles this via `CAMPBELL_AI_SESSION_BACKEND=redis`.
- **Column projection on the heavy oil/predictive reads**, mirroring what
  `_load_latest_telemetry_output` already does for telemetry (§3.4) — read only the columns
  a given callback actually uses instead of the full file.
- **EFS-level changes**, pending the CloudWatch check in §2: switch from General Purpose
  bursting mode to Provisioned Throughput or Elastic Throughput if burst credits are
  depleting under load; confirm the mount target is in the same AZ as the EC2 instance.
- **Instance sizing**, pending the CloudWatch check in §2: if on a burstable (`t3`/`t4g`)
  instance type and CPU credits are being exhausted, either move to a non-burstable type or
  enable unlimited credit mode.
- **Reduce directory-listing-then-read round trips** for partitioned telemetry files (§3.4)
  — e.g. cache the "latest partition" resolution itself (it only changes when new data
  lands), rather than re-globbing on every callback call.

---

## 6. What this diagnosis deliberately does not cover

- Frontend/browser-side rendering cost (large Plotly figures, DataTable client-side
  rendering) — worth a follow-up pass with the browser's Performance tab if server-side
  fixes don't fully close the gap.
- The upstream data pipeline that produces the Gold-layer files — out of scope per
  `documentation/codebase_explaining.md`, this repo only reads what's already produced.
- Exact EFS throughput numbers and EC2 instance type — these need to be pulled from the AWS
  console/CloudWatch, not inferred from the codebase.
