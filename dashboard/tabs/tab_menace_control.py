"""
Menace Control Tab Layout.

This tab provides a critical system monitoring view with:
1. General Equipment Status Table: Shows total alerts/events per equipment and system over last X days
2. Critical Systems Table: Highlights the most critical equipment-system combinations ranked by alert count
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_layout() -> html.Div:
    """
    Create layout for Menace Control tab.
    
    Returns:
        Dash HTML Div with complete menace control layout
    """
    logger.info("Creating Menace Control Tab layout")
    
    layout = html.Div([
        # Header Section
        dbc.Row([
            dbc.Col([
                html.H2([
                    html.I(className="fas fa-exclamation-triangle me-3"),
                    "Control de Amenazas"
                ], className="text-danger mb-1"),
                html.P(
                    "Monitoreo de criticidad de equipos y sistemas basado en alertas y análisis de tribología",
                    className="text-muted"
                )
            ])
        ], className="mb-4"),
        
        # Time Range Selector
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.Div([
                            html.Label([
                                html.I(className="fas fa-calendar-alt me-2"),
                                "Rango de Análisis:"
                            ], className="fw-bold me-3"),
                            dcc.Dropdown(
                                id='menace-days-selector',
                                options=[
                                    {'label': 'Últimos 30 días', 'value': 30},
                                    {'label': 'Últimos 60 días', 'value': 60},
                                    {'label': 'Últimos 90 días', 'value': 90},
                                    {'label': 'Últimos 180 días', 'value': 180},
                                    {'label': 'Último año', 'value': 365}
                                ],
                                value=90,
                                clearable=False,
                                style={'width': '250px', 'display': 'inline-block'}
                            )
                        ], className="d-flex align-items-center")
                    ])
                ], className="shadow-sm")
            ], md=12)
        ], className="mb-4"),
        
        # Summary Statistics Cards
        html.Div(id='menace-summary-cards', className="mb-4"),
        
        # Section 1: General Equipment Status Table
        html.Div([
            html.H4([
                html.I(className="fas fa-table me-2"),
                "Estado General de Equipos"
            ], className="text-primary mb-3")
        ]),
        
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-truck me-2"),
                            "Resumen de Alertas por Equipo y Sistema"
                        ], className="mb-0")
                    ], className="bg-light"),
                    dbc.CardBody([
                        html.P(
                            "Tabla que muestra el número de alertas por equipo y sistema. "
                            "Los equipos con mayor número de eventos aparecen primero.",
                            className="text-muted small mb-3"
                        ),
                        dcc.Loading(
                            id="loading-equipment-status",
                            type="circle",
                            children=[
                                html.Div(id='menace-equipment-status-table')
                            ]
                        )
                    ])
                ], className="shadow-sm mb-4")
            ], md=12)
        ]),
        
        # Section 2: Critical Systems Table
        html.Div([
            html.H4([
                html.I(className="fas fa-fire me-2"),
                "Sistemas Más Críticos"
            ], className="text-danger mb-3 mt-4")
        ]),
        
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-exclamation-circle me-2"),
                            "Ranking de Criticidad por Equipo-Sistema"
                        ], className="mb-0")
                    ], className="bg-light"),
                    dbc.CardBody([
                        html.P(
                            "Lista ordenada de los sistemas más críticos basada en el número de alertas/eventos. "
                            "Incluye información del estado de tribología más reciente.",
                            className="text-muted small mb-3"
                        ),
                        dcc.Loading(
                            id="loading-critical-systems",
                            type="circle",
                            children=[
                                html.Div(id='menace-critical-systems-table')
                            ]
                        )
                    ])
                ], className="shadow-sm mb-4")
            ], md=12)
        ]),
        
    ], className="container-fluid p-4")
    
    logger.info("Menace Control Tab layout created successfully")
    return layout
