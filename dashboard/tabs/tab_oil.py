"""
Unified Oil Tab with Internal Tabs (Fleet Overview and Report Detail).

This tab combines the Fleet Overview (former overview > general) and
Report Detail (former monitoring > oil) views into a single navigation
entry with internal tabs for switching between views.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_layout() -> html.Div:
    """
    Create unified oil tab layout with internal tabs.

    Tab A — Fleet Overview: machine-level status, priority, component distributions.
    Tab B — Report Detail: sample-level analysis with radar charts and time series.

    Returns:
        Dash HTML Div with tabbed interface
    """
    logger.info("Creating unified Oil Tab layout with internal tabs")

    layout = html.Div([
        # Header
        dbc.Row([
            dbc.Col([
                html.H2([
                    html.I(className="fas fa-oil-can me-3"),
                    "Monitor de Aceite"
                ], className="text-primary mb-1"),
                html.P(
                    "Análisis de aceite: visión de flota y detalle de reportes",
                    className="text-muted"
                )
            ])
        ], className="mb-4"),

        # Internal Tabs
        dcc.Tabs(
            id='oil-internal-tabs',
            value='fleet-overview',
            children=[
                dcc.Tab(
                    label='Visión de Flota',
                    value='fleet-overview',
                    className='custom-tab',
                    selected_className='custom-tab--selected'
                ),
                dcc.Tab(
                    label='Detalle de Reporte',
                    value='report-detail',
                    className='custom-tab',
                    selected_className='custom-tab--selected'
                )
            ],
            className='mb-4'
        ),

        # Tab content container
        html.Div(id='oil-tab-content'),

    ], className="container-fluid p-4")

    logger.info("Unified Oil Tab layout created successfully")
    return layout
