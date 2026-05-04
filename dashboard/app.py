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

# Import telemetry callbacks (uses @callback decorator, auto-registered on import)
import dashboard.callbacks.telemetry_callbacks

# Import oil callbacks (uses @callback decorator, auto-registered on import)
import dashboard.callbacks.oil_callbacks

# Import menace control callbacks (uses @callback decorator, auto-registered on import)
import dashboard.callbacks.menace_control_callbacks

# Import hot sheet callbacks (uses @callback decorator, auto-registered on import)
import dashboard.callbacks.hot_sheet_callbacks

# Import health index callbacks module
from dashboard.callbacks.health_index_callbacks import register_health_index_callbacks


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
    external_stylesheets=[dbc.themes.BOOTSTRAP, dbc.icons.FONT_AWESOME],
    suppress_callback_exceptions=True,
    title="Multi-Technical Alerts",
    url_base_pathname=PATH_PREFIX,
    serve_locally=True
)

# Set app layout
app.layout = create_app_layout()

# Add health check endpoint for ALB
@app.server.route('/alerts-dashboard/health')
def health_check():
    return {'status': 'healthy'}, 200

# Register all callbacks
register_auth_callbacks(app)
register_navigation_callbacks(app)
register_limits_callbacks(app)
register_machines_callbacks(app)
register_reports_callbacks(app)
register_mantenciones_general_callbacks(app)
register_overview_general_callbacks(app)
register_health_index_callbacks(app)


if __name__ == '__main__':
    # Get host and port from environment or use defaults
    host = os.getenv('DASHBOARD_HOST', '0.0.0.0')
    port = int(os.getenv('DASHBOARD_PORT', '8050'))
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
        debug=debug
    )
