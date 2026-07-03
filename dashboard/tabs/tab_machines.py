"""
Machines Overview tab for Multi-Technical-Alerts dashboard.

Updated July 2026 v2:
- Smaller, filter-reactive KPI cards
- Merged heatmap + priority table with selectable component columns
- Machine status visually prominent
- Component Distribution removed (commented out)
- Machine recommendation in detail panel only
"""

from dash import dcc, html
import dash_bootstrap_components as dbc


def create_machines_tab() -> dbc.Container:
    """Create Tab: Machines Overview (Oil)."""
    return dbc.Container([
        html.H3("Resumen de Máquinas", className="mt-4 mb-3"),
        html.Hr(),

        # ========================================
        # SECTION 0: Fleet Filters
        # ========================================
        dbc.Row([
            dbc.Col([
                html.Label("Tipo de Equipo:", className="fw-bold small"),
                dcc.Dropdown(
                    id='fleet-machine-type-filter',
                    placeholder='Todos los tipos...',
                    multi=True,
                    className="mb-2"
                )
            ], md=4),
            dbc.Col([
                html.Label("Sitio / Área:", className="fw-bold small"),
                dcc.Dropdown(
                    id='fleet-site-filter',
                    placeholder='Todos los sitios...',
                    multi=True,
                    className="mb-2"
                )
            ], md=4),
            dbc.Col([
                html.Label("Estado:", className="fw-bold small"),
                dcc.Dropdown(
                    id='fleet-status-filter',
                    placeholder='Todos los estados...',
                    options=[
                        {'label': 'Normal', 'value': 'Normal'},
                        {'label': 'Alerta', 'value': 'Alerta'},
                        {'label': 'Anormal', 'value': 'Anormal'},
                    ],
                    multi=True,
                    className="mb-2"
                )
            ], md=4),
        ], className="mb-3 p-3 bg-light rounded"),

        # ========================================
        # SECTION 1: Fleet Status KPIs (compact, filter-reactive)
        # ========================================
        dbc.Row([
            dbc.Col(
                html.Div([
                    html.Span("Total: ", className="text-muted small"),
                    html.Span(id='kpi-total-machines', children="0", className="fw-bold")
                ], className="text-center"),
                width=3
            ),
            dbc.Col(
                html.Div([
                    html.Span("● ", style={'color': '#28a745'}),
                    html.Span(id='kpi-normal-machines', children="0", className="fw-bold"),
                    html.Span(" Normal", className="text-muted small ms-1")
                ], className="text-center"),
                width=3
            ),
            dbc.Col(
                html.Div([
                    html.Span("● ", style={'color': '#ffc107'}),
                    html.Span(id='kpi-alerta-machines', children="0", className="fw-bold"),
                    html.Span(" Alerta", className="text-muted small ms-1")
                ], className="text-center"),
                width=3
            ),
            dbc.Col(
                html.Div([
                    html.Span("● ", style={'color': '#dc3545'}),
                    html.Span(id='kpi-anormal-machines', children="0", className="fw-bold"),
                    html.Span(" Anormal", className="text-muted small ms-1")
                ], className="text-center"),
                width=3
            ),
        ], className="mb-4 py-2 border rounded"),

        # ========================================
        # SECTION 2: Fleet Heatmap Table
        # ========================================
        dbc.Card([
            dbc.CardHeader([
                dbc.Row([
                    dbc.Col([
                        html.Span("Estado por Componente y Máquina", className="fw-bold"),
                        html.Span(id='table-filter-badge', className="ms-2")
                    ], md=6),
                    dbc.Col([
                        html.Label("Componentes visibles:", className="small text-muted me-2",
                                   style={'display': 'inline-block'}),
                        dcc.Dropdown(
                            id='fleet-component-columns-selector',
                            placeholder='Seleccionar componentes...',
                            multi=True,
                            className="d-inline-block",
                            style={'minWidth': '250px', 'fontSize': '0.85rem'}
                        )
                    ], md=6, className="text-end d-flex align-items-center justify-content-end"),
                ])
            ]),
            dbc.CardBody([
                dcc.Loading(
                    html.Div(id='fleet-heatmap-table-container'),
                    type="circle"
                )
            ])
        ], className="mb-4"),

        # Hidden stores
        dcc.Store(id='heatmap-click-data', data=None),

        # ========================================
        # SECTION 3: Machine Detail
        # ========================================
        html.Hr(),
        html.H5("🔍 Detalle de Máquina", className="mt-3 mb-3"),

        dbc.Alert(
            id='machine-selection-indicator',
            children="Ninguna máquina seleccionada",
            color="light",
            className="mb-3"
        ),

        dbc.Row([
            dbc.Col([
                html.Label("O seleccione máquina:", className="fw-bold small"),
                dcc.Dropdown(
                    id='machine-detail-selector',
                    placeholder='Seleccionar máquina...',
                    className="mb-3"
                )
            ], width=4)
        ]),

        # Machine recommendation (shown when machine selected)
        html.Div(id='machine-recommendation-container', className="mb-3"),

        # Component detail table
        dbc.Card([
            dbc.CardHeader("Componentes (Ordenado de Peor a Mejor)", className="fw-bold"),
            dbc.CardBody(
                html.Div(id='machine-detail-table-container')
            )
        ], className="mb-4"),

        # ========================================
        # SECTION 4: Quick Navigation
        # ========================================
        html.Hr(),
        html.H5("🧭 Navegación Rápida al Detalle de Reporte", className="mt-3 mb-3"),

        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("Equipo:", className="fw-bold small"),
                        dcc.Dropdown(id='nav-equipment-selector', placeholder='Seleccionar equipo...')
                    ], width=4),
                    dbc.Col([
                        html.Label("Componente:", className="fw-bold small"),
                        dcc.Dropdown(id='nav-component-selector', placeholder='Seleccionar componente...', disabled=True)
                    ], width=4),
                    dbc.Col([
                        html.Div([
                            html.Label("\u00a0", className="fw-bold small"),
                            dbc.Button("Ir al Detalle →", id='nav-to-report-button',
                                       color="primary", className="w-100", disabled=True)
                        ])
                    ], width=4)
                ])
            ])
        ], className="mb-4"),

        # ========================================
        # SECTION 5: Component Distribution - COMMENTED OUT
        # ========================================
        # html.Hr(),
        # html.H4("📈 Distribución de Estado de Componentes", className="mt-4 mb-3"),
        # ...

        # Hidden elements for callback compatibility
        dcc.Store(id='component-grouping-state', data={'use_normalized': False}),
        html.Div(id='component-stacked-bar-chart', style={'display': 'none'}),
        html.Div(id='component-grouping-indicator', style={'display': 'none'}),
        html.Div(id='toggle-component-grouping', style={'display': 'none'}),

    ], fluid=True)
