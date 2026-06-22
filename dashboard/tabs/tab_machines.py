"""
Machines Overview tab for Multi-Technical-Alerts dashboard.

Redesigned following OIL-M-01 through OIL-M-06 requirements:
- Condition-first fleet summary with interactive donut
- User-facing diagnostic table columns
- Persistent master-detail flow
- Component evidence focused on condition
- Quick navigation relocated to top
- Stacked bar chart for component distribution
"""

from dash import dcc, html
import dash_bootstrap_components as dbc


def create_machines_tab() -> dbc.Container:
    """
    Create Tab: Machines Overview (Oil).
    
    Redesigned layout with:
    1. Interactive fleet status donut + priority table (OIL-M-01, OIL-M-02)
    2. Quick navigation to report detail (OIL-M-05)
    3. Persistent machine selection with component detail (OIL-M-03, OIL-M-04)
    4. Component status stacked bar chart (OIL-M-06)
    
    Returns:
        Bootstrap container with tab layout
    """
    return dbc.Container([
        html.H3("Resumen de Máquinas", className="mt-4 mb-3"),
        html.Hr(),
        
        # ========================================
        # SECTION 1: Fleet Status KPIs (Redesigned June 2026)
        # ========================================
        html.H4("📊 Resumen de Estado de Flota", className="mt-4 mb-3"),
        
        # KPI Cards Row (Clickable for filtering - June 2026)
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6("Total Máquinas", className="text-muted mb-2"),
                        html.H2(id='kpi-total-machines', children="0", className="mb-0 text-primary"),
                    ])
                ], className="text-center shadow-sm")
            ], width=3),
            dbc.Col([
                html.Div(
                    dbc.Card([
                        dbc.CardBody([
                            html.H6("Normal", className="text-muted mb-2"),
                            html.H2(id='kpi-normal-machines', children="0", className="mb-0", 
                                    style={'color': '#28a745'}),
                        ])
                    ], className="text-center shadow-sm"),
                    id='kpi-normal-card',
                    n_clicks=0,
                    style={'cursor': 'pointer'}
                )
            ], width=3),
            dbc.Col([
                html.Div(
                    dbc.Card([
                        dbc.CardBody([
                            html.H6("Alerta", className="text-muted mb-2"),
                            html.H2(id='kpi-alerta-machines', children="0", className="mb-0",
                                    style={'color': '#ffc107'}),
                        ])
                    ], className="text-center shadow-sm"),
                    id='kpi-alerta-card',
                    n_clicks=0,
                    style={'cursor': 'pointer'}
                )
            ], width=3),
            dbc.Col([
                html.Div(
                    dbc.Card([
                        dbc.CardBody([
                            html.H6("Anormal", className="text-muted mb-2"),
                            html.H2(id='kpi-anormal-machines', children="0", className="mb-0",
                                    style={'color': '#dc3545'}),
                        ])
                    ], className="text-center shadow-sm"),
                    id='kpi-anormal-card',
                    n_clicks=0,
                    style={'cursor': 'pointer'}
                )
            ], width=3),
        ], className="mb-4"),
        
        # Priority Table - Full Width (Redesigned June 2026)
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.Span("Máquinas Prioritarias", className="fw-bold"),
                        html.Span(id='table-filter-badge', className="ms-2")
                    ]),
                    dbc.CardBody(
                        html.Div(id='priority-table-container')
                    )
                ])
            ], width=12)
        ], className="mb-4"),
        
        # ========================================
        # SECTION 2: Machine Detail (OIL-M-03, OIL-M-04)
        # ========================================
        html.Hr(),
        html.H4("🔍 Detalles de Componentes de Máquina", className="mt-4 mb-3"),
        html.P("Seleccione una máquina de la tabla de prioridad o use el selector a continuación.", className="text-muted"),
        
        # Persistent machine selection indicator
        dbc.Alert(
            id='machine-selection-indicator',
            children="Ninguna máquina seleccionada",
            color="light",
            className="mb-3"
        ),
        
        # Machine selector (alternative to table selection)
        dbc.Row([
            dbc.Col([
                html.Label("O seleccione máquina manualmente:", className="fw-bold"),
                dcc.Dropdown(
                    id='machine-detail-selector',
                    placeholder='Seleccionar máquina...',
                    className="mb-3"
                )
            ], width=6)
        ]),
        
        # Component detail table
        dbc.Card([
            dbc.CardHeader("Desglose de Componentes (Ordenado de Peor a Mejor)", className="fw-bold"),
            dbc.CardBody(
                html.Div(id='machine-detail-table-container')
            )
        ], className="mb-4"),
        
        # ========================================
        # SECTION 3: Quick Navigation (OIL-M-05)
        # ========================================
        html.Hr(),
        html.H4("🧭 Navegación Rápida al Detalle de Reporte", className="mt-4 mb-3"),
        
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("Equipo:", className="fw-bold"),
                        dcc.Dropdown(
                            id='nav-equipment-selector',
                            placeholder='Seleccionar equipo...'
                        )
                    ], width=4),
                    dbc.Col([
                        html.Label("Componente:", className="fw-bold"),
                        dcc.Dropdown(
                            id='nav-component-selector',
                            placeholder='Seleccionar componente...',
                            disabled=True
                        )
                    ], width=4),
                    dbc.Col([
                        html.Div([
                            html.Label("\u00a0", className="fw-bold"),  # Spacer
                            dbc.Button(
                                "Ir al Detalle de Reporte \u2192",
                                id='nav-to-report-button',
                                color="primary",
                                className="w-100",
                                disabled=True
                            )
                        ])
                    ], width=4)
                ])
            ])
        ], className="mb-4"),
        
        # ========================================
        # SECTION 4: Component Distribution (OIL-M-06)
        # ========================================
        html.Hr(),
        html.H4("📈 Distribución de Estado de Componentes", className="mt-4 mb-3"),
        
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.Span("Estado de Componentes por Tipo", className="fw-bold"),
                        dbc.Button(
                            "Toggle Grouping",
                            id='toggle-component-grouping',
                            color="secondary",
                            size="sm",
                            className="float-end"
                        )
                    ]),
                    dbc.CardBody([
                        html.Div(id='component-grouping-indicator', className="mb-2 text-muted small"),
                        dcc.Graph(id='component-stacked-bar-chart')
                    ])
                ])
            ], width=12)
        ], className="mb-4"),
        
        # Hidden store for component grouping toggle state
        dcc.Store(id='component-grouping-state', data={'use_normalized': False})
        
    ], fluid=True)
