"""
Main Dash application for Multi-Technical-Alerts dashboard.

Run this file to start the dashboard server.
"""

import sys
import os
from pathlib import Path
import logging

# Add project root to Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('logs/dashboard.log')
    ]
)

logger = logging.getLogger(__name__)

import dash
import dash_bootstrap_components as dbc
from flask import request, send_from_directory
from dashboard.layout import create_app_layout
from dashboard.callbacks.auth_callbacks import register_auth_callbacks
from dashboard.callbacks.navigation_callbacks import register_navigation_callbacks
from dashboard.callbacks.limits_callbacks import register_limits_callbacks
from dashboard.callbacks.machines_callbacks import register_machines_callbacks
from dashboard.callbacks.reports_callbacks import register_reports_callbacks
from dashboard.callbacks.mantenciones_general_callbacks import register_mantenciones_general_callbacks
from dashboard.callbacks.overview_general_callbacks import register_overview_general_callbacks

# Import alerts callbacks (uses @callback decorator, auto-registered on import)
import dashboard.callbacks.alerts_callbacks

# Import telemetry health callbacks (uses @callback decorator, auto-registered on import)
import dashboard.callbacks.telemetry_callbacks

# Import oil callbacks (uses @callback decorator, auto-registered on import)
import dashboard.callbacks.oil_callbacks

# Import lab compliance callbacks (uses @callback decorator, auto-registered on import)
import dashboard.callbacks.lab_compliance_callbacks

# Import menace control callbacks (uses @callback decorator, auto-registered on import)
import dashboard.callbacks.menace_control_callbacks

# Import hot sheet callbacks (uses @callback decorator, auto-registered on import)
import dashboard.callbacks.hot_sheet_callbacks

# Import Conexión ERP callbacks (uses @callback decorator, auto-registered on import)
import dashboard.callbacks.integration_avisos_callbacks

# Import health index callbacks module
from dashboard.callbacks.health_index_callbacks import register_health_index_callbacks

# Import data freshness callbacks (uses @callback decorator, auto-registered on import)
import dashboard.callbacks.data_freshness_callbacks

# Import predictive callbacks
from dashboard.callbacks.predictive_callbacks import register_callbacks as register_predictive_callbacks
from dashboard.campbell_ai.callbacks import register_campbell_ai_callbacks
from dashboard.campbell_ai.stream import register_campbell_ai_stream
from config.settings import get_settings

# Import component hours callbacks
from dashboard.callbacks.component_hours_callbacks import register_component_hours_callbacks

# Import predictive pages callbacks (reactive content for /predictive/* pages)
from dashboard.callbacks.predictive_pages_callbacks import register_predictive_pages_callbacks

# Import admin callbacks (login events chart)
from dashboard.callbacks.admin_callbacks import register_admin_callbacks

# Import the centralized route guard (role + client-service route protection)
from dashboard.callbacks.access_control_callbacks import register_access_control_callbacks

# Import the reactive sidebar (re-renders nav when the selected client changes)
from dashboard.callbacks.sidebar_callbacks import register_sidebar_callbacks

# Validate the client service register at startup - critical structural
# errors raise (fail fast); field-level issues are logged, not fatal.
from config.client_services import validate_startup_config
validate_startup_config()


def normalize_prefix(prefix: str | None) -> str:
    """
    Normalizes a URL prefix for Dash:
    - None / empty → "/"
    - ensures leading slash
    - ensures trailing slash
    """
    if not prefix:
        return "/"

    prefix = prefix.strip()

    if not prefix.startswith("/"):
        prefix = f"/{prefix}"
    if not prefix.endswith("/"):
        prefix = f"{prefix}/"

    return prefix

PATH_PREFIX = normalize_prefix(os.getenv("DASH_PATH_PREFIX"))

# Initialize Dash app with Bootstrap theme
app = dash.Dash(
    __name__,
    use_pages=True,
    pages_folder="",  # Pages are registered explicitly below, no folder auto-discovery
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.FONT_AWESOME],
    suppress_callback_exceptions=True,
    title="Multi-Technical Alerts",
    url_base_pathname=PATH_PREFIX,
    serve_locally=True
)

# Campbell AI inherits the authenticated dashboard identity from this signed session.
app.server.secret_key = get_settings().secret_key
app.server.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true",
)

# Explicit WSGI export for Gunicorn and other production servers.
server = app.server

# Import page modules so their dash.register_page() calls run (must happen
# after the app is created since register_page() looks up the active app).
import dashboard.pages.index
import dashboard.pages.overview_general
import dashboard.pages.overview_data_freshness
import dashboard.pages.monitoring_alerts
import dashboard.pages.monitoring_telemetry
import dashboard.pages.monitoring_oil
import dashboard.pages.predictive_motor
import dashboard.pages.predictive_transmision
import dashboard.pages.agents_campbell_ai
import dashboard.pages.integration_validacion_avisos
import dashboard.pages.integration_seguimiento_avisos
import dashboard.pages.reporting_main
import dashboard.pages.admin_main
import dashboard.pages.admin_user_registry
import dashboard.pages.no_services

# Set app layout
#
# El callable, no su resultado: Dash lo invoca en cada peticion de `_dash-layout`, y eso es
# lo que le permite a `user-info-store` nacer con la identidad de la sesion de Flask activa.
# Evaluado una sola vez al importar no habria request desde el cual leerla, y toda pestana
# nueva arrancaria sin identidad. Reconstruirlo cuesta ~0.3 ms.
app.layout = create_app_layout

# Add health check endpoint for ALB
@app.server.route('/alerts-dashboard/health')
def health_check():
    return {'status': 'healthy'}, 200

# Add route to serve client logos from dashboard/logos/
@app.server.route('/logos/<path:filename>')
def serve_logo(filename):
    """
    Serve client logo files from dashboard/logos/ directory.
    
    Args:
        filename: Logo filename (e.g., 'enex.png')
    
    Returns:
        Logo file or 404 if not found
    """
    logos_dir = Path(__file__).parent / 'logos'
    logger.info(f"Serving logo file: {filename} from {logos_dir}")
    
    try:
        return send_from_directory(logos_dir, filename)
    except FileNotFoundError:
        logger.warning(f"Logo file not found: {filename}")
        # Return 404 - the callback will handle hiding the logo
        return "Logo not found", 404

# Register all callbacks
register_auth_callbacks(app)
register_navigation_callbacks(app)
register_limits_callbacks(app)
register_machines_callbacks(app)
register_reports_callbacks(app)
register_mantenciones_general_callbacks(app)
register_overview_general_callbacks(app)
register_health_index_callbacks(app)
register_predictive_callbacks(app)
register_component_hours_callbacks(app)
register_predictive_pages_callbacks(app)
register_campbell_ai_callbacks(app)
# Same-origin SSE proxy for progressive Campbell AI answers; inert unless
# CAMPBELL_AI_STREAMING is enabled.
register_campbell_ai_stream(app)
register_admin_callbacks(app)
register_access_control_callbacks(app)
register_sidebar_callbacks(app)


@app.server.after_request
def _do_not_cache_the_app_shell(response):
    """Keep the page and the callback graph out of every cache; keep assets in.

    Dash already cache-busts files under `assets/` by appending the file's mtime to
    their URL, so a deploy gives them fresh URLs. That only helps if the browser
    re-fetches the *page* carrying those URLs — and the index was going out with no
    cache headers at all, which leaves browsers and proxies free to apply heuristic
    caching. The result after an update is a stale page asking for the previous build's
    JavaScript, against a server running the new callbacks: clientside functions that no
    longer exist, callbacks wired to components that moved. It looks like the app is
    broken, and a hard reload "fixes" it, which is the tell.

    Three things must never be cached, all of them descriptions of the current build:
    the index, the layout, and the dependency graph. Everything else — the fingerprinted
    assets and the bundled component libraries — is safe to cache and worth caching,
    since those are the large files.
    """
    path = request.path or ""
    never_cache = (
        path in ("/", "")
        or path.endswith("/_dash-layout")
        or path.endswith("/_dash-dependencies")
        or path.endswith("/_dash-update-component")
        # Any page route: this is a multi-page app served from the same shell.
        or not (path.startswith("/assets/") or path.startswith("/_dash-component-suites/"))
    )
    if never_cache:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


if __name__ == '__main__':
    # Get host and port from environment or use defaults
    host = os.getenv('DASHBOARD_HOST', '0.0.0.0')
    port = int(os.getenv('DASHBOARD_PORT', '8080'))
    debug = os.getenv('DEBUG', 'False').lower() == 'true'
    
    # Check if data folder exists, sync from S3 if needed
    data_folder = project_root / 'data'
    logger.info(f"Checking data folder at: {data_folder}")
    
    if not data_folder.exists():
        logger.warning("Data folder not found. Attempting to sync from S3...")
        try:
            from src.data.s3_downloader import main as s3_sync
            logger.info("Starting S3 data synchronization...")
            s3_sync()
            logger.info("S3 synchronization completed successfully")
        except ImportError as e:
            logger.error(f"Failed to import s3_downloader: {e}")
            logger.warning("Continuing without S3 sync. Some features may not work.")
        except Exception as e:
            logger.error(f"Error during S3 synchronization: {e}")
            logger.warning("Continuing without S3 sync. Some features may not work.")
    else:
        logger.info("Data folder exists. Skipping S3 sync.")
    
    # Run server
    logger.info("Starting Multi-Technical-Alerts Dashboard...")
    logger.info(f"Dashboard accessible at http://{host}:{port}")
    
    app.run(
        host=host,
        port=port,
        debug=debug,
        threaded=True,
    )
