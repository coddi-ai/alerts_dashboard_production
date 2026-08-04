"""
Reports Detail tab for Multi-Technical-Alerts dashboard.

Updated July 2026 v2:
- Removed Evidence by Test section
- Removed radar charts
- Added detected anomaly to decision summary
- Time series: DatePickerRange instead of dropdown, only upper condemnation limit
- Added Advanced Analytics section at end
"""

from dash import dcc, html
import dash_bootstrap_components as dbc


def create_reports_tab() -> dbc.Container:
    """Create Tab: Reports Detail Analysis."""
    return dbc.Container([
        html.H3("Análisis Detallado de Reportes", className="mt-4 mb-3"),
        html.Hr(),

        # ========================================
        # STICKY REPORT IDENTITY HEADER
        # ========================================
        html.Div([
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Label("Familia:", className="fw-bold mb-1", style={'fontSize': '0.85rem'}),
                            dcc.Dropdown(id='reports-familia-selector',
                                         placeholder='Tipo de máquina...', className="mb-2")
                        ], width=3),
                        dbc.Col([
                            html.Label("Equipo:", className="fw-bold mb-1", style={'fontSize': '0.85rem'}),
                            dcc.Dropdown(id='reports-equipo-selector',
                                         placeholder='Equipo...', className="mb-2")
                        ], width=3),
                        dbc.Col([
                            html.Label("Componente:", className="fw-bold mb-1", style={'fontSize': '0.85rem'}),
                            dcc.Dropdown(id='reports-component-selector',
                                         placeholder='Componente...', className="mb-2")
                        ], width=3),
                        dbc.Col([
                            html.Label("Fecha Muestra:", className="fw-bold mb-1", style={'fontSize': '0.85rem'}),
                            dcc.Dropdown(id='reports-date-selector',
                                         placeholder='Fecha...', className="mb-2")
                        ], width=3)
                    ]),
                    html.Div(id='reports-identity-display')
                ])
            ], className="mb-2")
        ], style={
            'position': 'sticky', 'top': '80px', 'zIndex': '999',
            'backgroundColor': '#f8f9fa', 'paddingTop': '10px', 'paddingBottom': '10px'
        }),

        # ========================================
        # DECISION SUMMARY (includes anomaly type)
        # ========================================
        dbc.Card([
            dbc.CardHeader("🎯 Resumen de Decisión", className="fw-bold bg-primary text-white"),
            dbc.CardBody(
                html.Div(id='reports-decision-summary')
            )
        ], className="mb-4"),

        # ========================================
        # AI RECOMMENDATION
        # ========================================
        dbc.Card([
            dbc.CardHeader("🤖 Análisis y Recomendación de IA", className="fw-bold bg-info text-white"),
            dbc.CardBody(
                html.Div(id='reports-ai-diagnosis')
            )
        ], className="mb-4"),

        # ========================================
        # EVIDENCE BY TEST - REMOVED (July 2026 v2)
        # Kept as hidden container for callback compatibility
        # ========================================
        html.Div(id='reports-evidence-container', style={'display': 'none'}),

        # ========================================
        # TIME SERIES ANALYSIS (DatePickerRange, upper limit only)
        # ========================================
        dbc.Card([
            dbc.CardHeader("📈 Análisis de Series Temporales", className="fw-bold"),
            dbc.CardBody([
                html.P(
                    "Evolución de variables de análisis de aceite. "
                    "El rango por defecto cubre los últimos 9 meses desde el reporte más reciente.",
                    className="text-muted mb-3"
                ),
                # Dedicated filter toolbar — visually separated from the chart grid (FR-04)
                html.Div([
                    dbc.Row([
                        dbc.Col([
                            html.Label("Rango de fechas", className="fw-bold small mb-1 d-block"),
                            dcc.DatePickerRange(
                                id='reports-date-range-picker',
                                display_format='YYYY-MM-DD',
                                start_date_placeholder_text='Fecha inicio',
                                end_date_placeholder_text='Fecha fin',
                            )
                        ], width="auto"),
                    ], align="center", className="g-3"),
                ], className="p-3 mb-4", style={
                    'backgroundColor': '#f8f9fa',
                    'border': '1px solid #e9ecef',
                    'borderRadius': '6px'
                }),
                dcc.Loading(
                    html.Div(id='reports-time-series-grid'),
                    type="circle"
                ),
                # Hidden elements for backward callback compatibility
                html.Div([
                    dcc.Dropdown(id='reports-time-range-selector', value='ALL', style={'display': 'none'}),
                    dcc.Dropdown(id='reports-essays-selector', multi=True, style={'display': 'none'}),
                    dcc.Graph(id='reports-time-series-chart', style={'display': 'none'})
                ], style={'display': 'none'})
            ])
        ], className="mb-4"),

        # ========================================
        # DELTA SUMMARY (Analysis vs Previous Report)
        # ========================================
        dbc.Card([
            dbc.CardHeader("🔄 Análisis de Cambios vs Reporte Anterior", className="fw-bold"),
            dbc.CardBody(
                html.Div(id='reports-delta-summary')
            )
        ], className="mb-4"),

        # ========================================
        # COMMENT HISTORY (traceability by unit/component)
        # ========================================
        dbc.Card([
            dbc.CardHeader("💬 Historial de Comentarios", className="fw-bold"),
            dbc.CardBody([
                html.P(
                    "Historial de comentarios/recomendaciones para la unidad y componente seleccionados.",
                    className="text-muted mb-3"
                ),
                html.Div(id='reports-comment-history-container')
            ])
        ], className="mb-4"),

        # ========================================
        # ADVANCED ANALYTICS (new section)
        # ========================================
        dbc.Card([
            dbc.CardHeader("🔬 Analítica Avanzada", className="fw-bold"),
            dbc.CardBody([
                html.P(
                    "Genere un gráfico de tendencia personalizado seleccionando las variables que desea analizar.",
                    className="text-muted mb-3"
                ),
                dbc.Row([
                    dbc.Col([
                        html.Label("Variables:", className="fw-bold small"),
                        dcc.Dropdown(
                            id='advanced-analytics-variables',
                            placeholder='Seleccionar variables...',
                            multi=True,
                            className="mb-2"
                        )
                    ], md=6),
                    dbc.Col([
                        html.Label("Opciones:", className="fw-bold small"),
                        dbc.Checklist(
                            id='advanced-analytics-show-limits',
                            options=[{'label': ' Mostrar límite condenatorio', 'value': 'show'}],
                            value=['show'],
                            inline=True,
                            className="mt-1"
                        )
                    ], md=4),
                    dbc.Col([
                        html.Label("\u00a0", className="small"),
                        dbc.Button("Generar", id='advanced-analytics-generate',
                                   color="primary", size="sm", className="w-100")
                    ], md=2),
                ]),
                dcc.Loading(
                    html.Div(id='advanced-analytics-chart-container', className="mt-3"),
                    type="circle"
                )
            ])
        ], className="mb-4"),

    ], fluid=True)
