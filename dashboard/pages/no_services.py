import dash
from dash import html
import dash_bootstrap_components as dbc


def layout(**kwargs):
    return html.Div([
        dbc.Card([
            dbc.CardBody([
                html.Div([
                    html.I(className="fas fa-plug-circle-xmark fa-3x mb-3 text-muted"),
                    html.H3("Sin servicios activos", className="text-muted"),
                    html.P(
                        "Su cliente no tiene servicios activos actualmente.",
                        className="text-muted mb-0"
                    ),
                ], className="text-center py-5")
            ])
        ])
    ], className="mt-4")


dash.register_page(
    __name__,
    path="/sin-servicios",
    title="Sin servicios | Multi-Technical Alerts",
    layout=layout,
)
