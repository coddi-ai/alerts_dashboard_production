"""
Machines Overview tab for Multi-Technical-Alerts dashboard.

Updated July 2026 v3:
- Filter order: Site → Fleet → Status (dynamic dependencies)
- Heatmap depends on fleet selection (empty if multiple fleets, no selection)
- Default components: all with ≥1 sample for selected fleet
- Machine status visually prominent
"""

from dash import dcc, html
import dash_bootstrap_components as dbc


def create_machines_tab() -> dbc.Container:
    """Create Tab: Machines Overview (Oil)."""
    return dbc.Container([
        html.H3("Resumen de Máquinas", className="mt-4 mb-3"),
        html.Hr(),

        # ========================================
        # SECTION 0: Fleet Filters (Site → Fleet → Status)
        # ========================================
        dbc.Row([
            dbc.Col([
                html.Label("Sitio / Área:", className="fw-bold small"),
                dcc.Dropdown(
                    id='fleet-site-filter',
                    placeholder='Todos los sitios...',
                    multi=False,
                    className="mb-2"
                )
            ], md=4),
            dbc.Col([
                html.Label("Flota (Tipo de Equipo):", className="fw-bold small"),
                dcc.Dropdown(
                    id='fleet-machine-type-filter',
                    placeholder='Seleccionar flota...',
                    multi=False,
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
        # SECTION 1: KPIs (compact, filter-reactive)
        # ========================================
        dbc.Row([
            dbc.Col(html.Div([
                html.Span("Total: ", className="text-muted small"),
                html.Span(id='kpi-total-machines', children="0", className="fw-bold")
            ], className="text-center"), width=3),
            dbc.Col(html.Div([
                html.Span("● ", style={'color': '#28a745'}),
                html.Span(id='kpi-normal-machines', children="0", className="fw-bold"),
                html.Span(" Normal", className="text-muted small ms-1")
            ], className="text-center"), width=3),
            dbc.Col(html.Div([
                html.Span("● ", style={'color': '#ffc107'}),
                html.Span(id='kpi-alerta-machines', children="0", className="fw-bold"),
                html.Span(" Alerta", className="text-muted small ms-1")
            ], className="text-center"), width=3),
            dbc.Col(html.Div([
                html.Span("● ", style={'color': '#dc3545'}),
                html.Span(id='kpi-anormal-machines', children="0", className="fw-bold"),
                html.Span(" Anormal", className="text-muted small ms-1")
            ], className="text-center"), width=3),
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
                    ], md=5),
                    dbc.Col([
                        html.Label("Componentes:", className="small text-muted me-2",
                                   style={'display': 'inline-block'}),
                        dcc.Dropdown(
                            id='fleet-component-columns-selector',
                            placeholder='Seleccionar componentes...',
                            multi=True,
                            style={'minWidth': '280px', 'fontSize': '0.85rem'}
                        )
                    ], md=7, className="d-flex align-items-center justify-content-end"),
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

        dbc.Alert(id='machine-selection-indicator',
                  children="Ninguna máquina seleccionada", color="light", className="mb-3"),

        dbc.Row([
            dbc.Col([
                html.Label("O seleccione máquina:", className="fw-bold small"),
                dcc.Dropdown(id='machine-detail-selector', placeholder='Seleccionar máquina...', className="mb-3")
            ], width=4)
        ]),

        html.Div(id='machine-recommendation-container', className="mb-3"),

        dbc.Card([
            dbc.CardHeader("Componentes (Ordenado de Peor a Mejor)", className="fw-bold"),
            dbc.CardBody(html.Div(id='machine-detail-table-container'))
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
                        dcc.Dropdown(id='nav-equipment-selector', placeholder='Equipo...')
                    ], width=4),
                    dbc.Col([
                        html.Label("Componente:", className="fw-bold small"),
                        dcc.Dropdown(id='nav-component-selector', placeholder='Componente...', disabled=True)
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

        # Hidden elements for callback compat
        dcc.Store(id='component-grouping-state', data={'use_normalized': False}),
        html.Div(id='component-stacked-bar-chart', style={'display': 'none'}),
        html.Div(id='component-grouping-indicator', style={'display': 'none'}),
        html.Div(id='toggle-component-grouping', style={'display': 'none'}),

    ], fluid=True)
