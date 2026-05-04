"""
Alerts General Tab Layout.

Displays:
- Distribution of Alerts per Unit (horizontal bar chart)
- Distribution of Alerts per Month (vertical bar chart)
- Distribution of Alert Trigger (treemap)
- Alerts Table (interactive DataTable)
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_layout() -> html.Div:
    """
    Create layout for Alerts General tab.
    
    Returns:
        Dash HTML Div with complete general tab layout
    """
    logger.info("Creating Alerts General Tab layout")
    
    layout = html.Div([
        # Summary stats at the top
        html.Div(id='alerts-summary-stats', className="mb-3"),
        
        # Analytics Section Header
        html.Div([
            html.H4([
                html.I(className="fas fa-chart-bar me-2"),
                "Análisis de Alertas"
            ], className="text-primary mb-3 mt-4")
        ]),
        
        # Top Row: 2 Analytics Charts (Unit | Month) - Removed redundant trigger distribution
        dbc.Row([
            # Distribution per Unit
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-truck me-2"),
                            "Distribución por Unidad"
                        ], className="mb-0")
                    ], className="bg-light"),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-unit-chart",
                            type="circle",
                            children=[
                                dcc.Graph(
                                    id='alerts-unit-distribution-chart',
                                    config={'displayModeBar': False},
                                    clear_on_unhover=True
                                )
                            ]
                        )
                    ])
                ], className="shadow-sm mb-4 h-100")
            ], md=6),
            
            # Distribution per Month
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-calendar-alt me-2"),
                            "Evolución Temporal"
                        ], className="mb-0")
                    ], className="bg-light"),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-month-chart",
                            type="circle",
                            children=[
                                dcc.Graph(
                                    id='alerts-month-distribution-chart',
                                    config={'displayModeBar': False},
                                    clear_on_unhover=True
                                )
                            ]
                        )
                    ])
                ], className="shadow-sm mb-4 h-100")
            ], md=6)
        ]),
        
        # Data Section Header
        html.Div([
            html.H4([
                html.I(className="fas fa-database me-2"),
                "Listado de Alertas"
            ], className="text-primary mb-3 mt-4")
        ]),
        
        # Bottom Row: Table (9 cols) | System Distribution (3 cols)
        dbc.Row([
            # Alerts Table Section
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-table me-2"),
                            "Todas las Alertas"
                        ], className="mb-0"),
                        html.Br(),
                        html.Small(
                            "💡 Haga clic en cualquier fila para ver el análisis detallado",
                            className="text-muted"
                        )
                    ], className="bg-light"),
                    dbc.CardBody([
                        # Table
                        dcc.Loading(
                            id="loading-alerts-table",
                            type="circle",
                            children=[
                                html.Div(id='alerts-table-container')
                            ]
                        )
                    ], className="p-0")
                ], className="shadow mb-4")
            ], md=9),
            
            # System Distribution Pie Chart
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-cogs me-2"),
                            "Por Sistema"
                        ], className="mb-0 text-center")
                    ], className="bg-light"),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-system-chart",
                            type="circle",
                            children=[
                                dcc.Graph(
                                    id='alerts-system-distribution-chart',
                                    config={'displayModeBar': False},
                                    clear_on_unhover=True
                                )
                            ]
                        )
                    ])
                ], className="shadow mb-4")
            ], md=3)
        ]),
        
        # Navigation Section
        html.Div([
            html.H4([
                html.I(className="fas fa-search-plus me-2"),
                "Análisis Detallado"
            ], className="text-primary mb-3 mt-4")
        ]),
        
        dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="fas fa-microscope me-2"),
                    "Explorar Alerta en Detalle"
                ], className="mb-0")
            ], className="bg-primary text-white"),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("Seleccione una alerta para análisis completo:", className="fw-bold mb-2"),
                        html.P("Acceda a evidencia de telemetría, análisis de aceite y contexto de mantenimiento", 
                               className="text-muted small mb-3"),
                        dcc.Dropdown(
                            id='general-alert-selector',
                            placeholder="Buscar por ID, unidad o sistema...",
                            clearable=True,
                            searchable=True
                        )
                    ], md=9),
                    dbc.Col([
                        html.Label(html.Br()),  # Spacer to align with dropdown
                        dbc.Button(
                            [
                                html.I(className="fas fa-arrow-circle-right me-2"),
                                "Ver Detalle"
                            ],
                            id='general-nav-to-detail-button',
                            color='primary',
                            size='lg',
                            className='w-100 mt-4'
                        )
                    ], md=3)
                ], className="g-2")
            ])
        ], className="shadow mb-4")
    ], className="p-4")
    
    logger.info("Alerts General Tab layout created successfully")
    return layout


def create_summary_stats_display(total_alerts: int, 
                                 total_units: int, 
                                 telemetry_pct: float, 
                                 oil_pct: float) -> html.Div:
    """
    Create summary statistics display with semantic colors and clear hierarchy.
    
    Args:
        total_alerts: Total number of alerts
        total_units: Total number of unique units with alerts
        telemetry_pct: Percentage of alerts with telemetry evidence
        oil_pct: Percentage of alerts with oil evidence
    
    Returns:
        HTML Div with KPI section
    """
    return html.Div([
        # Section Header
        html.Div([
            html.H4([
                html.I(className="fas fa-chart-line me-2"),
                "Resumen Ejecutivo"
            ], className="text-primary mb-3")
        ]),
        
        # KPI Cards Row
        dbc.Row([
            # Total Alerts - Primary metric
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="fas fa-exclamation-triangle fa-2x text-danger mb-2"),
                            html.H6("Total de Alertas", className="text-muted text-uppercase mb-2", 
                                   style={'fontSize': '0.85rem', 'letterSpacing': '0.5px'}),
                            html.H2(f"{total_alerts:,}", className="text-danger mb-0 fw-bold")
                        ], className="text-center")
                    ])
                ], className="shadow-sm border-0", style={'backgroundColor': '#fff5f5'})
            ], md=3),
            
            # Affected Units - Info metric
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="fas fa-truck fa-2x text-info mb-2"),
                            html.H6("Unidades Afectadas", className="text-muted text-uppercase mb-2",
                                   style={'fontSize': '0.85rem', 'letterSpacing': '0.5px'}),
                            html.H2(f"{total_units}", className="text-info mb-0 fw-bold")
                        ], className="text-center")
                    ])
                ], className="shadow-sm border-0", style={'backgroundColor': '#f0f8ff'})
            ], md=3),
            
            # Telemetry Coverage - Success metric
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="fas fa-signal fa-2x text-success mb-2"),
                            html.H6("Con Telemetría", className="text-muted text-uppercase mb-2",
                                   style={'fontSize': '0.85rem', 'letterSpacing': '0.5px'}),
                            html.H2(f"{telemetry_pct:.1f}%", className="text-success mb-0 fw-bold")
                        ], className="text-center")
                    ])
                ], className="shadow-sm border-0", style={'backgroundColor': '#f0fff4'})
            ], md=3),
            
            # Oil Analysis Coverage - Warning metric
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.I(className="fas fa-oil-can fa-2x text-warning mb-2"),
                            html.H6("Con Tribología", className="text-muted text-uppercase mb-2",
                                   style={'fontSize': '0.85rem', 'letterSpacing': '0.5px'}),
                            html.H2(f"{oil_pct:.1f}%", className="text-warning mb-0 fw-bold")
                        ], className="text-center")
                    ])
                ], className="shadow-sm border-0", style={'backgroundColor': '#fffcf0'})
            ], md=3)
        ], className="g-3 mb-4")
    ])

