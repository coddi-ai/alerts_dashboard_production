"""
Tab: Overview General
Vista consolidada de resumen ejecutivo de todas las áreas técnicas.

Este módulo proporciona una vista de alto nivel integrando:
- Telemetría: Estado de flota y equipos
- Mantenciones: Equipos operativos vs detenidos con MTD
- Tribología (Oil): Análisis de aceites y equipos críticos
- Alertas: Equipos con mayor cantidad de alertas recientes
"""

import dash_bootstrap_components as dbc
from dash import html, dcc, dash_table
import plotly.graph_objects as go
import pandas as pd
from datetime import datetime
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_kpi_card(title: str, value: str, icon: str, color: str = "primary", card_id: str = None):
    """
    Create a KPI card component for overview metrics.
    
    Args:
        title: Card title/label
        value: Displayed value
        icon: FontAwesome icon class
        color: Bootstrap color theme
        card_id: Optional ID for dynamic updates
        
    Returns:
        dbc.Card component
    """
    return dbc.Card([
        dbc.CardBody([
            html.Div([
                html.I(className=f"fas {icon} fa-2x mb-2 text-{color}"),
                html.H3(
                    value, 
                    className="mb-0",
                    id=card_id if card_id else None
                ),
                html.P(title, className="text-muted mb-0 small"),
            ], className="text-center")
        ])
    ], className="shadow-sm h-100")


def create_section_header(title: str, icon: str, color: str = "primary"):
    """
    Create a section header for each technical area.
    
    Args:
        title: Section title
        icon: FontAwesome icon class
        color: Bootstrap color for the icon
        
    Returns:
        html.Div with formatted header
    """
    return html.Div([
        html.H5([
            html.I(className=f"fas {icon} me-2 text-{color}"),
            title
        ], className="mb-0")
    ], className="mb-3")


def create_overview_general_layout():
    """
    Create the Overview General tab layout.
    
    This tab provides a consolidated executive summary of all technical areas:
    - Telemetry: Fleet status visualization
    - Maintenance: Operational vs stopped equipment with MTD
    - Tribology: Oil analysis status and critical equipment ranking
    - Alerts: Equipment with highest alert frequency
    
    Compact view - everything visible in one screen without excessive scrolling.
    
    Returns:
        html.Div with complete overview layout
    """
    logger.info("Creating Overview General tab layout")
    
    return html.Div([
        # Header - Compact
        dbc.Row([
            dbc.Col([
                html.H3([
                    html.I(className="fas fa-tachometer-alt me-2"),
                    "Resumen Ejecutivo General"
                ], className="text-primary mb-0"),
            ], width=9),
            dbc.Col([
                dbc.Button([
                    html.I(className="fas fa-sync-alt me-2"),
                    "Actualizar"
                ], id="btn-refresh-overview", color="primary", size="sm", className="float-end")
            ], width=3)
        ], className="mb-3"),
        
        # Hidden stores for data caching
        dcc.Store(id="store-overview-data"),
        dcc.Store(id="store-overview-timestamp"),
        
        # Loading overlay
        dcc.Loading(
            id="loading-overview",
            type="default",
            children=[
                # Row 1: Global KPIs - Compact
                dbc.Row([
                    dbc.Col(create_kpi_card(
                        "Total Equipos",
                        "0",
                        "fa-industry",
                        "info",
                        "overview-kpi-total"
                    ), width=3),
                    dbc.Col(create_kpi_card(
                        "Equipos Operativos",
                        "0",
                        "fa-check-circle",
                        "success",
                        "overview-kpi-operational"
                    ), width=3),
                    dbc.Col(create_kpi_card(
                        "Equipos en Alerta",
                        "0",
                        "fa-exclamation-triangle",
                        "warning",
                        "overview-kpi-warning"
                    ), width=3),
                    dbc.Col(create_kpi_card(
                        "Equipos Críticos",
                        "0",
                        "fa-times-circle",
                        "danger",
                        "overview-kpi-critical"
                    ), width=3),
                ], className="mb-3"),
                
                # Row 2: 4 Technical Areas in a Grid (2x2) - Tribology & Maintenance
                dbc.Row([
                    # Tribology Section (Left)
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.Div([
                                    create_section_header("Tribología - Distribución de Estado", "fa-oil-can", "warning"),
                                    html.Small(id="overview-oil-timestamp", className="text-muted", style={'fontSize': '10px'})
                                ])
                            ], className="py-2"),
                            dbc.CardBody([
                                dcc.Graph(
                                    id='overview-oil-chart',
                                    config={'displayModeBar': False},
                                    style={'height': '220px'}
                                )
                            ], className="p-2")
                        ], className="shadow-sm h-100")
                    ], width=12, md=6),
                    
                    # Maintenance Section (Right)
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.Div([
                                    create_section_header("Mantenciones - Equipos", "fa-wrench", "success"),
                                    html.Small(id="overview-maintenance-timestamp", className="text-muted", style={'fontSize': '10px'})
                                ])
                            ], className="py-2"),
                            dbc.CardBody([
                                dcc.Graph(
                                    id='overview-maintenance-chart',
                                    config={'displayModeBar': False},
                                    style={'height': '220px'}
                                )
                            ], className="p-2")
                        ], className="shadow-sm h-100")
                    ], width=12, md=6)
                ], className="mb-3"),
                
                # Row 3: Telemetry & Alerts
                dbc.Row([
                    # Telemetry Section (Left)
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.Div([
                                    create_section_header("Telemetría - Estado Flota", "fa-satellite-dish", "info"),
                                    html.Small(id="overview-telemetry-timestamp", className="text-muted", style={'fontSize': '10px'})
                                ])
                            ], className="py-2"),
                            dbc.CardBody([
                                dcc.Graph(
                                    id='overview-telemetry-chart',
                                    config={'displayModeBar': False},
                                    style={'height': '220px'}
                                )
                            ], className="p-2")
                        ], className="shadow-sm h-100")
                    ], width=12, md=6),
                    
                    # Alerts Section (Right)
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.Div([
                                    html.Div([
                                        create_section_header("Alertas - Top Críticos", "fa-bell", "danger"),
                                        html.Small(id="overview-alerts-timestamp", className="text-muted", style={'fontSize': '10px'})
                                    ]),
                                    dcc.Dropdown(
                                        id='overview-alerts-days-filter',
                                        options=[
                                            {'label': '7d', 'value': 7},
                                            {'label': '15d', 'value': 15},
                                            {'label': '30d', 'value': 30},
                                            {'label': '60d', 'value': 60},
                                        ],
                                        value=30,
                                        clearable=False,
                                        className="mt-2",
                                        style={'fontSize': '12px'}
                                    )
                                ])
                            ], className="py-2"),
                            dbc.CardBody([
                                dcc.Graph(
                                    id='overview-alerts-chart',
                                    config={'displayModeBar': False},
                                    style={'height': '180px'}
                                )
                            ], className="p-2")
                        ], className="shadow-sm h-100")
                    ], width=12, md=6)
                ], className="mb-3"),
                
                # Row 4: Top Critical Equipment Table - Compact
                dbc.Row([
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.Div([
                                    html.I(className="fas fa-table me-2"),
                                    html.Span("Resumen de Equipos con Problemas", className="fw-bold"),
                                ], className="d-inline")
                            ], className="py-2"),
                            dbc.CardBody([
                                html.Div(id='overview-oil-ranking-table')
                            ], className="p-2")
                        ], className="shadow-sm")
                    ], width=12)
                ], className="mb-2"),
                
                # Footer with last update - Compact
                dbc.Row([
                    dbc.Col([
                        html.P([
                            html.I(className="fas fa-clock me-2"),
                            "Última actualización: ",
                            html.Span(id="overview-last-update", className="fw-bold")
                        ], className="text-muted small text-end mb-0")
                    ])
                ])
            ]
        )
    ], className="container-fluid p-3")


def create_layout():
    """
    Main entry point for Overview General tab.
    
    Returns:
        Complete layout for the overview tab
    """
    return create_overview_general_layout()
