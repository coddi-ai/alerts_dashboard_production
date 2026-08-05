"""
Root route.

Renders briefly while dashboard/callbacks/access_control_callbacks.py's
route guard resolves the client's first enabled service and redirects there
(spec 2.7's default-route resolution - it can't be hardcoded here since it
depends on which services are enabled for the logged-in user's client).
"""

import dash
from dash import html


def layout(**kwargs):
    return html.Div("Cargando...", className="text-muted text-center py-5")


dash.register_page(__name__, path="/", layout=layout)
