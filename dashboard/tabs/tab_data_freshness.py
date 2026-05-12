"""
Data Freshness Tab Layout.

This tab provides real-time monitoring of data update status for all units,
showing telemetry and tribology data freshness with color-coded indicators.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_layout() -> html.Div:
    """
    Create layout for Data Freshness monitoring tab.
    
    Returns:
        Dash HTML Div with data freshness layout
    """
    logger.info("Creating Data Freshness Tab layout")
    
    layout = html.Div([
        # Header Section
        dbc.Row([
            dbc.Col([
                html.H2([
                    html.I(className="fas fa-sync-alt me-3"),
                    "Estado de Actualización de Datos"
                ], className="text-primary mb-1"),
                html.P(
                    "Monitoreo en tiempo real de la frescura de los datos de telemetría y tribología por unidad",
                    className="text-muted mb-2"
                ),
                html.Div([
                    html.Span("🟢 Actualizado: ", style={'fontWeight': 'bold', 'color': '#28a745'}),
                    html.Span("Telemetría <1h, Tribología <1 semana", style={'fontSize': '0.9rem', 'marginRight': '20px'}),
                    html.Span("🟡 Atención Requerida: ", style={'fontWeight': 'bold', 'color': '#ffc107'}),
                    html.Span("Telemetría <4h, Tribología <2 semanas", style={'fontSize': '0.9rem', 'marginRight': '20px'}),
                    html.Span("🔴 Crítico: ", style={'fontWeight': 'bold', 'color': '#dc3545'}),
                    html.Span("Telemetría >4h, Tribología >2 semanas", style={'fontSize': '0.9rem'})
                ], className="text-muted", style={'fontSize': '0.85rem'})
            ])
        ], className="mb-4"),
        
        # Data Freshness Table
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-table me-2"),
                            "Estado de Actualización por Unidad"
                        ], className="mb-0")
                    ], className="bg-light"),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-data-freshness",
                            type="circle",
                            children=[
                                html.Div(id='data-freshness-table')
                            ]
                        )
                    ])
                ], className="shadow-sm mb-4")
            ], md=12)
        ])
        
    ], className="container-fluid p-4")
    
    logger.info("Data Freshness Tab layout created successfully")
    return layout
