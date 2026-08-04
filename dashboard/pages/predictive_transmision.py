"""
Predictive - Transmisión page.

See dashboard/pages/predictive_motor.py for why this is a placeholder
container filled in reactively by predictive_pages_callbacks.py.
"""

import dash
from dash import html


def layout(**kwargs):
    return html.Div(id={'type': 'predictive-page-content', 'component': 'transmision'})


dash.register_page(__name__, path="/predictive/transmision", title="Predictivo – Transmisión | Multi-Technical Alerts", layout=layout)
