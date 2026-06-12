"""
Telemetry Fleet Overview Tab Layout (Page 1).

Answers: "How is my fleet behaving currently?"
Shows: Fleet status donut, system heatmap, priority table, AI assessments.
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc


def create_telemetry_fleet_layout() -> html.Div:
    """Create fleet overview tab layout."""

    return html.Div([
        # KPI Cards Row
        html.Div(id='telemetry-fleet-kpi-row'),

        # System Health Heatmap + Status Donut
        dbc.Row([
            # Heatmap
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-th me-2"),
                            "Mapa de Calor — Sistemas × Unidades"
                        ], className="mb-0")
                    ], className="bg-light"),
                    dbc.CardBody([
                        dcc.Loading(
                            dcc.Graph(
                                id='telemetry-fleet-heatmap',
                                config={'displayModeBar': False}
                            ),
                            type='circle'
                        )
                    ])
                ], className="shadow-sm mb-4 h-100")
            ], lg=8),

            # Status Donut
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-chart-pie me-2"),
                            "Estado de Flota"
                        ], className="mb-0")
                    ], className="bg-light"),
                    dbc.CardBody([
                        dcc.Loading(
                            dcc.Graph(
                                id='telemetry-fleet-donut',
                                config={'displayModeBar': False}
                            ),
                            type='circle'
                        )
                    ])
                ], className="shadow-sm mb-4 h-100")
            ], lg=4)
        ], className="gx-3"),

        # Priority Table
        html.Div([
            html.H4([
                html.I(className="fas fa-sort-amount-down me-2"),
                "Ranking de Prioridad"
            ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
            html.P("Unidades ordenadas por urgencia de atención", className="text-muted mb-3")
        ]),
        dbc.Card([
            dbc.CardBody([
                dcc.Loading(
                    dash_table.DataTable(
                        id='telemetry-fleet-priority-table',
                        columns=[
                            {'name': 'Unidad', 'id': 'unit'},
                            {'name': 'Estado', 'id': 'overall_status'},
                            {'name': 'Prioridad', 'id': 'priority_score', 'type': 'numeric'},
                            {'name': 'Score', 'id': 'unit_score', 'type': 'numeric'},
                            {'name': 'Sist. Anormal', 'id': 'n_anormal_systems', 'type': 'numeric'},
                            {'name': 'Sist. Alerta', 'id': 'n_alerta_systems', 'type': 'numeric'},
                            {'name': 'Top Riesgos', 'id': 'top_risk_systems'},
                        ],
                        data=[],
                        sort_action='native',
                        filter_action='native',
                        page_size=15,
                        row_selectable='single',
                        selected_rows=[],
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
                            'fontFamily': 'Arial, sans-serif',
                            'fontSize': '14px'
                        },
                        style_data_conditional=[
                            {
                                'if': {'row_index': 'odd'},
                                'backgroundColor': '#f8f9fa'
                            },
                            {
                                'if': {'filter_query': '{overall_status} = "Anormal"'},
                                'backgroundColor': 'rgba(220, 53, 69, 0.1)',
                                'color': '#dc3545',
                                'fontWeight': 'bold'
                            },
                            {
                                'if': {'filter_query': '{overall_status} = "Alerta"'},
                                'backgroundColor': 'rgba(255, 193, 7, 0.1)',
                                'color': '#856404',
                                'fontWeight': 'bold'
                            },
                            {
                                'if': {'filter_query': '{overall_status} = "Normal"'},
                                'color': '#28a745'
                            },
                            {
                                'if': {'state': 'active'},
                                'backgroundColor': '#3498db',
                                'color': 'white',
                                'border': '2px solid #2980b9'
                            }
                        ]
                    ),
                    type='circle'
                ),
                html.Small([
                    html.I(className="fas fa-info-circle me-1"),
                    "Haga clic en una fila para navegar al detalle de la unidad"
                ], className="text-muted mt-2 d-block")
            ])
        ], className="shadow-sm mb-4"),

        # AI Assessments Table
        html.Div([
            html.H4([
                html.I(className="fas fa-robot me-2"),
                "Evaluaciones IA"
            ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
            html.P("Resumen ejecutivo generado por IA para cada unidad", className="text-muted mb-3")
        ]),
        dbc.Card([
            dbc.CardBody([
                dcc.Loading(
                    html.Div(id='telemetry-fleet-ai-table'),
                    type='circle'
                )
            ])
        ], className="shadow-sm mb-4")
    ])
