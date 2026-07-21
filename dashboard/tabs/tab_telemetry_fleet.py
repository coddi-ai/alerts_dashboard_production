"""
Telemetry Fleet Overview Tab Layout (Page 1).

Answers: "How is my fleet behaving currently?"
Shows: Fleet status KPIs, system heatmap, priority and action table.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc


def create_telemetry_fleet_layout() -> html.Div:
    """Create fleet overview tab layout."""

    return html.Div([
        # Filters shared by KPIs, heatmap and priority table.
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("Modelo de equipo", className="small fw-bold"),
                        dcc.Dropdown(
                            id='telemetry-fleet-model-filter',
                            placeholder='Todos los modelos',
                            clearable=True,
                            options=[]
                        )
                    ], md=4),
                    dbc.Col([
                        html.Label("Estado", className="small fw-bold"),
                        dcc.Dropdown(
                            id='telemetry-fleet-status-filter',
                            placeholder='Todos los estados',
                            multi=True,
                            options=[
                                {'label': 'Normal', 'value': 'Normal'},
                                {'label': 'Alerta', 'value': 'Alerta'},
                                {'label': 'Anormal', 'value': 'Anormal'},
                                {'label': 'Sin evidencia suficiente', 'value': 'InsufficientData'},
                            ]
                        )
                    ], md=4),
                    dbc.Col([
                        html.Label("Sistemas visibles", className="small fw-bold"),
                        dcc.Dropdown(
                            id='telemetry-fleet-system-filter',
                            placeholder='Todos los sistemas',
                            multi=True,
                            options=[]
                        )
                    ], md=4),
                ])
            ])
        ], className="shadow-sm mb-4"),

        # KPI Cards Row
        html.Div(id='telemetry-fleet-kpi-row'),

        # System Health Heatmap (full width, professional card)
        dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="fas fa-th me-2"),
                    "Mapa de Calor — Estado por Sistema y Unidad"
                ], className="mb-0")
            ], className="bg-light"),
            dbc.CardBody([
                html.P(
                    "Estado de cada sistema por unidad. "
                    "Las unidades se ordenan según la prioridad interna ya calculada.",
                    className="text-muted mb-3"
                ),
                # Insight KPIs above heatmap
                html.Div(id='telemetry-fleet-heatmap-insights', className="mb-3"),
                # Risk band legend
                html.Div([
                    html.Small([
                        html.Span("Normal", className="fw-bold", style={"color": "#28a745"}),
                        html.Span(" · ", className="text-muted"),
                        html.Span("Alerta", className="fw-bold", style={"color": "#856404"}),
                        html.Span(" · ", className="text-muted"),
                        html.Span("Anormal", className="fw-bold", style={"color": "#b02a37"}),
                        html.Span(" · ", className="text-muted"),
                        html.Span("Gris", className="fw-bold", style={"color": "#95a5a6"}),
                        html.Span(" sin evidencia suficiente"),
                    ])
                ], className="text-center mb-2"),
                dcc.Loading(
                    dcc.Graph(
                        id='telemetry-fleet-heatmap',
                        config={'displayModeBar': False}
                    ),
                    type='circle'
                )
            ])
        ], className="shadow-sm mb-4"),

        # Executive priority table
        html.Div([
            html.H4([
                html.I(className="fas fa-list-ol me-2"),
                "Prioridades y acciones"
            ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
            html.P(
                "Unidades ordenadas por prioridad. Seleccione una fila para ver el resumen o haga clic en ella/mapa para abrir la evidencia.",
                className="text-muted mb-3"
            )
        ]),
        dbc.Card([
            dbc.CardBody([
                dcc.Loading(
                    html.Div(id='telemetry-fleet-ai-table'),
                    type='circle'
                )
            ])
        ], className="shadow-sm mb-4"),

        html.Div(id='telemetry-fleet-selected-unit')
    ])
