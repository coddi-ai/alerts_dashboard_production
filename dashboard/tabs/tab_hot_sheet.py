"""
Hot Sheet Tab Layout.

This tab provides a quick status overview of all units with traffic light indicators
combining alerts and tribology status.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_layout() -> html.Div:
    """
    Create layout for Hot Sheet tab.
    
    Returns:
        Dash HTML Div with hot sheet layout
    """
    logger.info("Creating Hot Sheet Tab layout")
    
    layout = html.Div([
        # Header Section
        dbc.Row([
            dbc.Col([
                html.H2([
                    html.I(className="fas fa-th me-3"),
                    "Hot Sheet - Estado de Unidades"
                ], className="text-primary mb-1"),
                html.P(
                    "Vista rápida del estado de todas las unidades basado en telemetría y tribología",
                    className="text-muted"
                )
            ])
        ], className="mb-4"),
        
        # Hot Sheet Table (sin tarjetas de resumen)
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-table me-2"),
                            "Estado por Unidad"
                        ], className="mb-0")
                    ], className="bg-light"),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-hot-sheet",
                            type="circle",
                            children=[
                                html.Div(id='hot-sheet-table')
                            ]
                        )
                    ])
                ], className="shadow-sm mb-4")
            ], md=12)
        ])
        
    ], className="container-fluid p-4")
    
    logger.info("Hot Sheet Tab layout created successfully")
    return layout
