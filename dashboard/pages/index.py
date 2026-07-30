"""Root route — redirects client-side (no full reload) to the default landing page."""

import dash
from dash import dcc


def layout(**kwargs):
    return dcc.Location(id="index-redirect", pathname=dash.get_relative_path("/overview/general"))


dash.register_page(__name__, path="/", layout=layout)
