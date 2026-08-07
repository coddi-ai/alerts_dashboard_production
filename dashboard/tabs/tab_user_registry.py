"""Admin-only "Registro de usuarios" tab layout — a single login-events chart."""

from dash import html, dcc
import dash_bootstrap_components as dbc


def create_layout() -> html.Div:
    return html.Div([
        # Fires once, when this page's layout mounts (a fresh component
        # appearing with an initial 'data' value counts as a change to Dash,
        # same mechanism as tab_alerts_general.py's date-range-picker
        # defaults) - this is what triggers the chart's data-loading
        # callback reliably, unlike depending on the app-wide
        # `_pages_location` pathname, which changes in a separate callback
        # dispatch from this page's own content mounting and can race it.
        dcc.Store(id="user-registry-page-load", data=True),
        html.H4(
            [html.I(className="fas fa-user-clock me-2"), "Registro de usuarios"],
            className="text-primary mb-3 mt-4",
        ),
        dbc.Card([
            dbc.CardHeader(
                html.H5(
                    [html.I(className="fas fa-chart-bar me-2"), "Inicios de sesión por usuario"],
                    className="mb-0",
                ),
                className="bg-light",
            ),
            dbc.CardBody([
                dbc.Alert(
                    id="user-registry-load-error",
                    color="danger",
                    is_open=False,
                    className="mb-3",
                ),
                dcc.Loading(
                    dcc.Graph(
                        id="user-registry-login-events-chart",
                        config={"displayModeBar": False, "responsive": True},
                        style={"height": "calc(100vh - 260px)"},
                    ),
                    type="circle",
                ),
            ]),
        ], className="shadow-sm mb-4"),
    ])
