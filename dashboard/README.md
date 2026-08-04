# Multi-Technical Alerts Dashboard

Interactive Dash web application for fleet health monitoring, consolidating oil (tribology),
telemetry, maintenance, and cross-technique alerts data into a single platform.

This repository is **dashboard-only**: it reads pre-processed Gold-layer data (produced by an
upstream data pipeline) from `data/{technique}/{layer}/{client}/` and, if that folder is missing
locally, syncs it from S3 on startup. There is no data-processing pipeline in this repo.

## Features

- **Authentication**: Username/password login with per-client, role-based access (`admin` vs `client`)
- **Multi-client**: Global client selector in the header switches all views (CDA, EMIN, ENEX, CAPSTONE)
- **Resumen (Overview)**: Fleet-wide status summary and per-unit data freshness
- **Monitoreo (Monitoring)**: Alertas (consolidated alerts), Telemetría (sensor health), Aceite (oil/tribology, incl. lab compliance)
- **Predictivo (Predictive)**: Component-level failure-mode KPIs and evidence, restricted to select clients
- **Integración / Reportes / Administración**: Placeholder sections reserved for future work

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file in the project root (see `config/settings.py` for all options):

```bash
BUCKET_NAME=...          # S3 bucket holding processed data (used for auto-sync)
ACCESS_KEY=...
SECRET_KEY=...
OPENAI_API_KEY=...       # optional, for AI-generated recommendations/insights
MAPBOX_TOKEN=...         # optional, for GPS route maps in Alerts detail
```

### 3. Get Data

The dashboard expects processed data under `data/{technique}/{layer}/{client}/` (see
[Data Layer Structure](#data-layer-structure) below). On startup, if the local `data/` folder is
missing, `dashboard/app.py` automatically syncs it from S3 via `src/data/s3_downloader.py`. If you
already have a `data/` folder, it's used as-is and no sync happens.

### 4. Start Dashboard

```bash
# Option 1: Run directly
python dashboard/app.py

# Option 2: Run as module (from project root)
python -m dashboard.app
```

The dashboard will be available at: **http://localhost:8080** (or `DASHBOARD_PORT` if set).

## Login Credentials

User accounts are defined in `config/users.py`. Each user has a role (`admin` or `client`) and a
list of accessible clients. Example accounts:

| Username     | Access     | Role   |
|--------------|------------|--------|
| admin        | All clients| admin  |
| cda_user     | CDA        | client |
| emin_user    | EMIN       | client |
| enex_user    | ENEX       | client |
| capstone_user| CAPSTONE   | client |

Passwords are SHA-256 hashed in `config/users.py`; see that file for the full user list and to add
or rotate credentials.

## Dashboard Sections

Navigation is organized into sections/subsections in the left sidebar (`dashboard/layout.py`).

### Resumen (Overview)
- **General** — unified per-unit status table combining Telemetría, Alertas, Data Freshness, and
  latest Tribología result for the selected client
- **Estado de Datos** — per-unit data freshness table (🟢/🟡/🔴) for Telemetría and Tribología,
  based on `data/auxiliar/{client}/Data_Date_Last_Update.csv`

### Monitoreo (Monitoring)
- **Alertas** — consolidated cross-technique alerts
  - *Vista General*: date-filtered distribution charts (by unit, month, trigger, sistema) and an
    interactive alerts table
  - *Vista Detallada*: per-alert inspection with AI diagnosis, telemetry evidence (sensor trends,
    GPS route, KPIs), oil evidence (radar chart), and maintenance evidence
- **Telemetría** — sensor-based health monitoring
  - *Vista de Flota*: fleet matrix of unit/system status
  - *Detalle de Unidad*: unit → system → signal drill-down with AI commentary
- **Aceite** — tribology (oil) analysis
  - *Visión de Flota*: machine status distribution and priority table
  - *Detalle de Reporte*: radar chart, time series vs. Stewart Limits thresholds, AI recommendations
  - *Cumplimiento Laboratorio*: transit-time and lab-time KPIs, weekly and per-unit delay charts

### Predictivo (Predictive)
Only visible to users whose client is in `predictive_allowed_clients` (currently CDA, CAPSTONE).
Subsections are auto-discovered per component (e.g. Motor, Transmisión) from CSVs under
`data/predictive/golden/{client}/`, each with a *Resumen* (fleet KPIs, priority cards, failure-mode
table) and *Evidencia* (per-unit oil/telemetry evidence and narrative insights) tab.

### Integración / Reportes / Administración
Reserved navigation entries currently showing "En Desarrollo" placeholder content.

## Color Scheme

- **Normal**: Green (#28a745)
- **Alerta**: Yellow/Amber (#ffc107)
- **Anormal**: Red (#dc3545)

## Data Layer Structure

Data follows a **Data Mesh** pattern: `data/{technique}/{layer}/{client}/{datafile}`

```
data/
├── oil/{silver,golden}/{client}/
├── telemetry/{silver,golden}/{client}/
├── mantentions/golden/{client}/
├── alerts/golden/{client}/
├── predictive/golden/{client}/
└── auxiliar/{client}/Data_Date_Last_Update.csv
```

Paths are resolved via helpers on `config/settings.py::Settings` (e.g. `get_machine_status_path`,
`get_stewart_limits_path`, `get_consolidated_alerts_path`).

## Architecture

```
dashboard/
├── app.py                  # Main application entry point, route/health-check registration
├── auth.py                 # Login/authorization helpers (reads config/users.py)
├── layout.py                # App shell: login page, header/navbar, sidebar navigation
├── assets/                 # CSS/JS auto-loaded by Dash, logo.svg
├── logos/                  # Per-client logo images served at /logos/<file>
├── components/             # Reusable charts, tables, filters (per technique)
├── tabs/                   # Page layouts, one (or a family) per subsection — see below
└── callbacks/              # Interactive callbacks, one module per subsection/technique
```

Each monitoring technique typically has a matching trio: `tabs/tab_<name>*.py` (layout),
`callbacks/<name>_callbacks.py` (interactivity + data loading), and often a
`components/<name>_charts.py` / `_tables.py` (Plotly figures, DataTables). Some tab/callback
modules exist in the codebase but are currently commented out of navigation in `layout.py`
(shelved or in-progress features): Stewart Limits/Machines/Reports standalone tabs (now
superseded by the Aceite subsections), Mantenciones General, Health Index, Menace Control, Hot
Sheet, and the standalone Component Hours tab (its logic is still used internally by Predictivo).

## Production Deployment

```bash
docker-compose up -d
```

This builds from the root `Dockerfile` and mounts `./data` (read-only), `./logs`, `./dashboard`,
`./config`, and `./src` into the container. Environment variables are loaded from `.env`.

For a bare WSGI deployment:

```bash
gunicorn dashboard.app:server --bind 0.0.0.0:8050 --workers 4
```

### Path Prefix / Load Balancer

Set `DASH_PATH_PREFIX` (e.g. `/alerts-dashboard/`) to mount the app under a sub-path behind a
reverse proxy or ALB. A health-check endpoint is available at `<prefix>/health`
(e.g. `/alerts-dashboard/health`).

## Customization

### Change User Credentials

Edit `config/users.py` and update the `USERS` dictionary:

```python
USERS = {
    'your_user': {
        'password': hash_password('your_password'),
        'name': 'Display Name',
        'role': 'admin',       # or 'client'
        'clients': ['CDA', 'EMIN']
    }
}
```

### Modify Thresholds / Access Control

Most tunables live in `config/settings.py` (`Settings`), including Stewart Limits percentiles,
classification thresholds, and module access lists (`predictive_allowed_clients`,
`component_hours_allowed_clients`).

## Troubleshooting

### No Data Available
- Confirm `data/` exists and contains the expected `{technique}/{layer}/{client}/` structure
- If missing, verify `BUCKET_NAME`/`ACCESS_KEY`/`SECRET_KEY` are set in `.env` so the automatic S3
  sync in `dashboard/app.py` can run (only triggers when `data/` doesn't exist)

### Import Errors
- Verify all dependencies installed: `pip install -r requirements.txt`
- Check Python version: requires Python 3.11+

### Port Already in Use
- Change `DASHBOARD_PORT` in `.env`, or pass it via environment when running `dashboard/app.py`

## Support

For issues or questions, refer to:
- `documentation/general/dashboard_overview.md` — architecture and feature overview
- `documentation/general/DATA_FRESHNESS_TAB.md` / `DATA_FRESHNESS_IMPLEMENTATION.md`
