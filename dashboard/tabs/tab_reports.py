"""
Reports Detail tab for Multi-Technical-Alerts dashboard.

Displays sample-level analysis with evidence tables, radar charts, and time series.
"""

from dash import dcc, html
import dash_bootstrap_components as dbc


def create_reports_tab() -> dbc.Container:
    """
    Create Tab 3: Reports Detail Analysis.
    
    Features (following OIL-R requirements):
    - OIL-R-01: Sticky report identity header
    - OIL-R-02: Decision summary (status, severity, breached essays)
    - OIL-R-03: Evidence tables AND radar charts
    - OIL-R-04: Separate AI diagnosis from action
    - OIL-R-05: User-selectable time-series (with breached essays pre-selected)
    - OIL-R-06: Delta summary comparison
    
    Returns:
        Bootstrap container with tab layout
    """
    return dbc.Container([
        html.H3("Análisis Detallado de Reportes", className="mt-4 mb-3"),
        html.Hr(),
        
        # STICKY REPORT IDENTITY HEADER (OIL-R-01)
        html.Div([
            dbc.Card([
                dbc.CardBody([
                    # Filter Row
                    dbc.Row([
                        dbc.Col([
                            html.Label("Familia:", className="fw-bold mb-1", style={'fontSize': '0.9rem'}),
                            dcc.Dropdown(
                                id='reports-familia-selector',
                                placeholder='Seleccionar tipo de máquina...',
                                className="mb-2"
                            )
                        ], width=3),
                        dbc.Col([
                            html.Label("Equipo:", className="fw-bold mb-1", style={'fontSize': '0.9rem'}),
                            dcc.Dropdown(
                                id='reports-equipo-selector',
                                placeholder='Seleccionar equipo...',
                                className="mb-2"
                            )
                        ], width=3),
                        dbc.Col([
                            html.Label("Componente:", className="fw-bold mb-1", style={'fontSize': '0.9rem'}),
                            dcc.Dropdown(
                                id='reports-component-selector',
                                placeholder='Seleccionar componente...',
                                className="mb-2"
                            )
                        ], width=3),
                        dbc.Col([
                            html.Label("Fecha de Muestra:", className="fw-bold mb-1", style={'fontSize': '0.9rem'}),
                            dcc.Dropdown(
                                id='reports-date-selector',
                                placeholder='Seleccionar fecha...',
                                className="mb-2"
                            )
                        ], width=3)
                    ]),
                    # Report Identity Row (populated by callback)
                    html.Div(id='reports-identity-display')
                ])
            ], className="mb-2")
        ], style={
            'position': 'sticky',
            'top': '0',
            'zIndex': '1000',
            'backgroundColor': '#f8f9fa',
            'paddingTop': '10px',
            'paddingBottom': '10px'
        }),
        
        # DECISION SUMMARY SECTION (OIL-R-02)
        dbc.Card([
            dbc.CardHeader("🎯 Resumen de Decisión", className="fw-bold bg-primary text-white"),
            dbc.CardBody(
                html.Div(id='reports-decision-summary')
            )
        ], className="mb-4"),
        
        # AI RECOMMENDATION SECTION (OIL-R-04) - Plain text display
        dbc.Card([
            dbc.CardHeader("🤖 Análisis y Recomendación de IA", className="fw-bold bg-info text-white"),
            dbc.CardBody(
                html.Div(id='reports-ai-diagnosis')  # Single plain text display
            )
        ], className="mb-4"),
        
        # EVIDENCE ANALYSIS SECTION (OIL-R-03) - Tables AND Radar Charts
        dbc.Card([
            dbc.CardHeader("📊 Análisis de Evidencia por Ensayo", className="fw-bold"),
            dbc.CardBody([
                html.P("Evidencia agrupada por categoría de ensayo (tablas + gráficos radiales)", className="text-muted mb-3"),
                html.Div(id='reports-evidence-container')  # Contains both tables and radar charts
            ])
        ], className="mb-4"),
        
        # TIME SERIES ANALYSIS (OIL-R-05) - User-selectable
        dbc.Card([
            dbc.CardHeader("📈 Análisis de Series Temporales", className="fw-bold"),
            dbc.CardBody([
                html.P("Los ensayos fuera de límite están preseleccionados por defecto. Puede modificar la selección a continuación.", 
                       className="text-muted mb-2"),
                html.Label("Seleccionar Ensayos para Graficar:", className="fw-bold mb-2"),
                dcc.Dropdown(
                    id='reports-essays-selector',
                    multi=True,
                    placeholder='Seleccionar ensayos (hasta 6)...',
                    className="mb-3"
                ),
                dcc.Graph(id='reports-time-series-chart')
            ])
        ], className="mb-4"),
        
        # DELTA SUMMARY COMPARISON (OIL-R-06)
        dbc.Card([
            dbc.CardHeader("🔄 Análisis de Cambios vs Reporte Anterior", className="fw-bold"),
            dbc.CardBody(
                html.Div(id='reports-delta-summary')
            )
        ], className="mb-4")
        
    ], fluid=True)
        
