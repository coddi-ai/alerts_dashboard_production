"""Coddi dashboard shell — CONEXIÓN ERP section.

Registers the Warning Validator and Warning Viewer as pages of one multi-page
Dash app (approximating this repo's stand-in for the real, already-existing
Coddi dashboard platform these views are meant to plug into — design.md §2
tech table: "ERP views are new tabs/pages within it").

Run: python -m dashboard.app
"""
from __future__ import annotations

import logging
import os

import dash
import dash_bootstrap_components as dbc

# LOG_LEVEL=DEBUG python -m dashboard.app for verbose per-callback tracing.
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

FONT_AWESOME = "https://use.fontawesome.com/releases/v6.4.0/css/all.css"

app = dash.Dash(
    __name__,
    use_pages=True,
    pages_folder="",
    suppress_callback_exceptions=True,
    external_stylesheets=[dbc.themes.BOOTSTRAP, FONT_AWESOME],
)

# imported after app instantiation: dash.register_page()/callback() require an app to exist first
from dashboard.erp import validator, viewer  # noqa: E402

dash.register_page("validator", path="/erp/validacion-avisos", name="Validación de Avisos", layout=validator.layout)
dash.register_page("viewer", path="/erp/seguimiento-avisos", name="Seguimiento de Avisos", layout=viewer.layout)
logger.info("Registered pages: %s", [p["path"] for p in dash.page_registry.values()])

app.layout = dbc.Container(
    [
        dbc.NavbarSimple(
            children=[
                dbc.NavLink("Validación de Avisos", href="/erp/validacion-avisos", active="exact"),
                dbc.NavLink("Seguimiento de Avisos", href="/erp/seguimiento-avisos", active="exact"),
            ],
            brand="Coddi — Conexión ERP",
            color="primary",
            dark=True,
            className="mb-0",
        ),
        dash.page_container,
    ],
    fluid=True,
    className="p-0",
)

if __name__ == "__main__":
    logger.info("Starting dashboard shell on http://127.0.0.1:8050")
    app.run(debug=True)
