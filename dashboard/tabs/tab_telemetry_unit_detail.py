"""
Telemetry Unit Detail Tab Layout (Page 2).

Answers: "What data backs the conclusions we are presenting?"
Shows: Unit AI comment, system risk table, signal overview, signal detail cards.
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc


def create_telemetry_unit_detail_layout() -> html.Div:
    """Create unit detail tab layout."""

    return html.Div([
        # Unit Selector
        dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="fas fa-truck me-2"),
                    "Selección de Unidad"
                ], className="mb-0")
            ], className="bg-light"),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label([
                            html.I(className="fas fa-truck me-1"),
                            "Unidad"
                        ], className="fw-bold mb-2"),
                        dcc.Dropdown(
                            id='telemetry-detail-unit-selector',
                            placeholder="Seleccione una unidad...",
                            clearable=False,
                            searchable=True
                        )
                    ], md=4),
                    dbc.Col([
                        html.Label([
                            html.I(className="fas fa-cogs me-1"),
                            "Sistema"
                        ], className="fw-bold mb-2"),
                        dcc.Dropdown(
                            id='telemetry-detail-system-selector',
                            placeholder="Todos los sistemas",
                            clearable=True
                        )
                    ], md=4),
                ], className="g-3")
            ])
        ], className="shadow-sm mb-4"),

        # AI Comment on Unit
        html.Div(id='telemetry-detail-ai-comment'),

        # System Risk Table
        html.Div([
            html.H4([
                html.I(className="fas fa-cogs me-2"),
                "Sistemas — Ordenados por Riesgo"
            ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
            html.P("Estado de salud por sistema para la unidad seleccionada", className="text-muted mb-3")
        ]),
        dbc.Card([
            dbc.CardBody([
                dcc.Loading(
                    dash_table.DataTable(
                        id='telemetry-detail-system-table',
                        columns=[
                            {'name': 'Sistema', 'id': 'system'},
                            {'name': 'Risk Score', 'id': 'system_score', 'type': 'numeric'},
                            {'name': 'Estado', 'id': 'system_status'},
                            {'name': 'Técnicas Activas', 'id': 'n_techniques_triggered', 'type': 'numeric'},
                            {'name': 'Top Señal', 'id': 'top_signal'},
                            {'name': 'Top Técnica', 'id': 'top_technique'},
                        ],
                        data=[],
                        sort_action='native',
                        page_size=10,
                        style_table={'overflowX': 'auto'},
                        style_header={
                            'backgroundColor': '#2c3e50',
                            'color': 'white',
                            'fontWeight': 'bold',
                            'textAlign': 'center'
                        },
                        style_cell={
                            'textAlign': 'center',
                            'padding': '10px',
                            'fontSize': '14px'
                        },
                        style_data_conditional=[
                            {
                                'if': {'filter_query': '{system_status} = "Anormal"'},
                                'backgroundColor': 'rgba(220, 53, 69, 0.1)',
                                'color': '#dc3545',
                                'fontWeight': 'bold'
                            },
                            {
                                'if': {'filter_query': '{system_status} = "Alerta"'},
                                'backgroundColor': 'rgba(255, 193, 7, 0.1)',
                                'color': '#856404',
                                'fontWeight': 'bold'
                            },
                            {
                                'if': {'filter_query': '{system_status} = "Normal"'},
                                'color': '#28a745'
                            }
                        ]
                    ),
                    type='circle'
                )
            ])
        ], className="shadow-sm mb-4"),

        # Signal Overview Table (for selected system)
        html.Div([
            html.H4([
                html.I(className="fas fa-wave-square me-2"),
                "Señales — Detalle por Sistema"
            ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
            html.P("Evaluación de señales individuales del sistema seleccionado", className="text-muted mb-3")
        ]),
        dbc.Card([
            dbc.CardBody([
                dcc.Loading(
                    dash_table.DataTable(
                        id='telemetry-detail-signal-table',
                        columns=[
                            {'name': 'Señal', 'id': 'signal'},
                            {'name': 'Risk Score', 'id': 'risk_score', 'type': 'numeric'},
                            {'name': 'Estado', 'id': 'status'},
                            {'name': 'Anomalía %', 'id': 'abnormal_pct', 'type': 'numeric'},
                            {'name': 'Total Eventos', 'id': 'total_events', 'type': 'numeric'},
                            {'name': 'Episodio Max (min)', 'id': 'max_episode', 'type': 'numeric'},
                        ],
                        data=[],
                        sort_action='native',
                        page_size=15,
                        style_table={'overflowX': 'auto'},
                        style_header={
                            'backgroundColor': '#2c3e50',
                            'color': 'white',
                            'fontWeight': 'bold',
                            'textAlign': 'center'
                        },
                        style_cell={
                            'textAlign': 'center',
                            'padding': '10px',
                            'fontSize': '14px'
                        },
                        style_data_conditional=[
                            {
                                'if': {'filter_query': '{status} = "Anormal"'},
                                'backgroundColor': 'rgba(220, 53, 69, 0.1)',
                                'color': '#dc3545',
                                'fontWeight': 'bold'
                            },
                            {
                                'if': {'filter_query': '{status} = "Alerta"'},
                                'backgroundColor': 'rgba(255, 193, 7, 0.1)',
                                'color': '#856404',
                                'fontWeight': 'bold'
                            },
                            {
                                'if': {'filter_query': '{status} = "Normal"'},
                                'color': '#28a745'
                            }
                        ]
                    ),
                    type='circle'
                )
            ])
        ], className="shadow-sm mb-4"),

        # Signal Detail Cards Container (time series + KPI for each signal)
        html.Div([
            html.H4([
                html.I(className="fas fa-chart-line me-2"),
                "Detalle de Señales"
            ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
            html.P(
                "Series temporales con límites baseline y tendencias por señal",
                className="text-muted mb-3"
            )
        ]),
        dcc.Loading(
            html.Div(id='telemetry-detail-signal-cards'),
            type='circle'
        )
    ])
