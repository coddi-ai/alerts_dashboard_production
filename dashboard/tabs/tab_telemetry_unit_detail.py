"""Telemetry unit detail report layout."""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc


def create_telemetry_unit_detail_layout() -> html.Div:
    """Create a report-style unit detail view with progressive evidence."""
    return html.Div([
        dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="fas fa-fingerprint me-2"),
                    "Identidad del caso"
                ], className="mb-0")
            ], className="bg-light"),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("Unidad", className="fw-bold small"),
                        dcc.Dropdown(
                            id='telemetry-detail-unit-selector',
                            placeholder="Seleccione una unidad...",
                            clearable=False,
                            searchable=True
                        )
                    ], md=4),
                    dbc.Col([
                        html.Label("Sistema", className="fw-bold small"),
                        dcc.Dropdown(
                            id='telemetry-detail-system-selector',
                            placeholder="Seleccione un sistema...",
                            clearable=False
                        )
                    ], md=4),
                    dbc.Col([
                        html.Label("Señal", className="fw-bold small"),
                        dcc.Dropdown(
                            id='telemetry-detail-signal-selector',
                            placeholder="Seleccione una señal...",
                            clearable=False
                        )
                    ], md=4),
                ]),
                html.Div(id='telemetry-detail-identity-display', className="mt-3 text-muted small")
            ])
        ], className="shadow-sm mb-4", style={'position': 'sticky', 'top': '0', 'zIndex': 1000}),

        html.Div(id='telemetry-detail-ai-comment'),

        html.Div([
            html.H4([
                html.I(className="fas fa-cogs me-2"),
                "Estado de los sistemas"
            ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
            html.P("Estado, señales con hallazgo y señal principal de cada sistema", className="text-muted mb-3")
        ]),
        dbc.Card([
            dbc.CardBody([
                dcc.Loading(
                    dash_table.DataTable(
                        id='telemetry-detail-system-table',
                        columns=[
                            {'name': 'Sistema', 'id': 'system'},
                            {'name': 'Estado', 'id': 'system_status'},
                            {'name': 'Señales con hallazgo', 'id': 'signals_in_alert', 'type': 'numeric'},
                            {'name': 'Señal Principal', 'id': 'top_signal_display'},
                        ],
                        data=[],
                        sort_action='native',
                        row_selectable='single',
                        selected_rows=[],
                        page_size=10,
                        style_table={'overflowX': 'auto'},
                        style_header={
                            'backgroundColor': '#2c3e50', 'color': 'white',
                            'fontWeight': 'bold', 'textAlign': 'center'
                        },
                        style_cell={
                            'textAlign': 'center', 'padding': '10px',
                            'fontSize': '14px', 'whiteSpace': 'normal', 'height': 'auto'
                        },
                        style_cell_conditional=[
                            {'if': {'column_id': 'system'}, 'textAlign': 'left'},
                            {'if': {'column_id': 'top_signal_display'}, 'textAlign': 'left'},
                        ],
                        style_data_conditional=[
                            {'if': {'filter_query': '{system_status} = "Anormal"'},
                             'backgroundColor': 'rgba(220, 53, 69, 0.1)', 'color': '#dc3545', 'fontWeight': 'bold'},
                            {'if': {'filter_query': '{system_status} = "Alerta"'},
                             'backgroundColor': 'rgba(255, 193, 7, 0.1)', 'color': '#856404', 'fontWeight': 'bold'},
                            {'if': {'filter_query': '{system_status} = "InsufficientData"'},
                             'backgroundColor': 'rgba(149, 165, 166, 0.15)', 'color': '#657174'},
                            {'if': {'filter_query': '{system_status} = "Normal"'}, 'color': '#28a745'},
                        ]
                    ),
                    type='circle'
                )
            ])
        ], className="shadow-sm mb-4"),

        html.Div([
            html.H4([
                html.I(className="fas fa-stethoscope me-2"),
                "Evaluación del sistema seleccionado"
            ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
            html.P(
                "Estado, explicación y acción recomendada para el sistema antes de revisar sus señales.",
                className="text-muted mb-3"
            )
        ]),
        dcc.Loading(
            html.Div(id='telemetry-detail-system-analysis'),
            type='circle'
        ),

        html.Div([
            html.H4([
                html.I(className="fas fa-wave-square me-2"),
                "Señales — Evidencia del sistema"
            ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
            html.P("Seleccione una señal para abrir su evidencia técnica", className="text-muted mb-3")
        ]),
        dbc.Card([
            dbc.CardBody([
                dcc.Loading(
                    dash_table.DataTable(
                        id='telemetry-detail-signal-table',
                        columns=[
                            {'name': 'Señal', 'id': 'signal'},
                            {'name': 'Estado', 'id': 'status'},
                            {'name': 'Fuera de rango', 'id': 'abnormal_pct_display'},
                            {'name': 'Eventos', 'id': 'total_events', 'type': 'numeric'},
                            {'name': 'Episodio Máx.', 'id': 'longest_episode', 'type': 'numeric'},
                            {'name': 'Tendencia', 'id': 'trend_direction'},
                            {'name': 'signal_raw', 'id': 'signal_raw'},
                        ],
                        data=[],
                        sort_action='native',
                        row_selectable='single',
                        selected_rows=[],
                        page_size=15,
                        style_table={'overflowX': 'auto'},
                        style_header={
                            'backgroundColor': '#2c3e50', 'color': 'white',
                            'fontWeight': 'bold', 'textAlign': 'center'
                        },
                        style_cell={
                            'textAlign': 'center', 'padding': '8px',
                            'fontSize': '13px', 'whiteSpace': 'normal', 'height': 'auto'
                        },
                        style_cell_conditional=[
                            {'if': {'column_id': 'signal'}, 'textAlign': 'left'},
                            {'if': {'column_id': 'signal_raw'}, 'display': 'none'},
                        ],
                        style_data_conditional=[
                            {'if': {'filter_query': '{status} = "Anormal"'},
                             'backgroundColor': 'rgba(220, 53, 69, 0.1)', 'color': '#dc3545', 'fontWeight': 'bold'},
                            {'if': {'filter_query': '{status} = "Alerta"'},
                             'backgroundColor': 'rgba(255, 193, 7, 0.1)', 'color': '#856404', 'fontWeight': 'bold'},
                            {'if': {'filter_query': '{status} = "InsufficientData"'},
                             'backgroundColor': 'rgba(149, 165, 166, 0.15)', 'color': '#657174'},
                            {'if': {'filter_query': '{status} = "Normal"'}, 'color': '#28a745'},
                        ]
                    ),
                    type='circle'
                )
            ])
        ], className="shadow-sm mb-4"),

        html.Div([
            html.H4([
                html.I(className="fas fa-chart-line me-2"),
                "Evidencia de la señal seleccionada"
            ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
            html.P(
                "Serie temporal con anomalías y eventos resaltados, límites de referencia, tendencia y comentario IA.",
                className="text-muted mb-3"
            )
        ]),
        dcc.Loading(
            html.Div(id='telemetry-detail-signal-cards'),
            type='circle'
        )
    ])
