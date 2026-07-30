"""
Predictive - Motor page.

The actual content depends on the globally-selected client (client-selector
in the navbar) and must react live when the client changes, so this page
only renders a placeholder container. Its content is filled in reactively by
the pattern-matching callback in dashboard/callbacks/predictive_pages_callbacks.py.
"""

import dash
from dash import html


def layout(**kwargs):
    return html.Div(id={'type': 'predictive-page-content', 'component': 'motor'})


dash.register_page(__name__, path="/predictive/motor", title="Predictivo – Motor | Multi-Technical Alerts", layout=layout)
