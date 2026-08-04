"""Telemetry fleet overview layout."""

from dash import html, dcc
import dash_bootstrap_components as dbc


def create_telemetry_fleet_layout() -> html.Div:
    """Create the compact fleet matrix used in weekly maintenance meetings."""
    return html.Div([
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("Modelo de equipo", className="small fw-bold"),
                        dcc.Dropdown(
                            id="telemetry-fleet-model-filter",
                            placeholder="Todos los modelos",
                            clearable=True,
                            options=[],
                        ),
                    ], md=6),
                    dbc.Col([
                        html.Label("Estado", className="small fw-bold"),
                        dcc.Dropdown(
                            id="telemetry-fleet-status-filter",
                            placeholder="Todos los estados",
                            multi=True,
                            options=[
                                {"label": "Normal", "value": "Normal"},
                                {"label": "Alerta", "value": "Alerta"},
                                {"label": "Anormal", "value": "Anormal"},
                                {"label": "Sin evidencia suficiente", "value": "InsufficientData"},
                            ],
                        ),
                    ], md=6),
                ], className="g-3"),
            ])
        ], className="shadow-sm mb-3"),
        dbc.Card([
            dbc.CardHeader([
                dbc.Row([
                    dbc.Col([
                        html.H5([
                            html.I(className="fas fa-table me-2"),
                            "Estado por Sistema y Unidad",
                        ], className="mb-0"),
                        html.Small(
                            "Las filas se ordenan por severidad. Pase sobre un sistema para consultar la acción recomendada.",
                            className="text-muted",
                        ),
                    ], md=7),
                    dbc.Col([
                        html.Label("Sistemas visibles", className="small fw-bold mb-1"),
                        dcc.Dropdown(
                            id="telemetry-fleet-system-filter",
                            placeholder="Todos los sistemas",
                            multi=True,
                            options=[],
                            value=[],
                            closeOnSelect=False,
                        ),
                    ], md=5),
                ], className="align-items-center g-2"),
            ], className="bg-light"),
            dbc.CardBody([
                dcc.Loading(
                    html.Div(id="telemetry-fleet-table-container"),
                    type="circle",
                )
            ], className="p-2"),
        ], className="shadow-sm mb-4"),
    ])
