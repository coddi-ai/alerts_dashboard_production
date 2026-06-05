"""
General Overview Tab Layout.

Simplified view: one table with Unidad, Telemetría (combines telemetry + alerts + data freshness),
and Tribología (based on last oil report).
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger

logger = get_logger(__name__)


def create_layout() -> html.Div:
    """
    Create layout for General Overview tab.
    
    Returns:
        Dash HTML Div with general overview layout
    """
    logger.info("Creating General Overview Tab layout")
    
    layout = html.Div([
        # ── Hidden stores for data ──
        dcc.Store(id='store-overview-data'),
        dcc.Store(id='store-overview-timestamp'),
        
        # ── Header Section ──
        dbc.Row([
            dbc.Col([
                html.H2([
                    html.I(className="fas fa-chart-pie me-3"),
                    "Resumen General - Estado de Unidades"
                ], className="text-primary mb-1"),
                html.P(
                    "Vista rápida del estado de todas las unidades basado en telemetría y tribología",
                    className="text-muted mb-0"
                ),
                html.Small([
                    "Última actualización: ",
                    html.Span(id='overview-last-update', children='Cargando...')
                ], className="text-muted")
            ], md=12),
        ], className="mb-3"),
        # Hidden placeholder for refresh button callback
        html.Div(id='btn-refresh-overview', style={'display': 'none'}),
        
        # ── KPI Summary Cards (commented out for simplicity) ──
        # dbc.Row([
        #     dbc.Col(dbc.Card([dbc.CardBody([
        #         html.H4(id='overview-kpi-total', children='0', className='text-primary mb-0'),
        #         html.P("Total Equipos", className='text-muted mb-0 small')
        #     ])], className="text-center shadow-sm"), md=3, sm=6, className="mb-2"),
        #     dbc.Col(dbc.Card([dbc.CardBody([
        #         html.H4(id='overview-kpi-operational', children='0', className='text-success mb-0'),
        #         html.P("Operativos", className='text-muted mb-0 small')
        #     ])], className="text-center shadow-sm"), md=3, sm=6, className="mb-2"),
        #     dbc.Col(dbc.Card([dbc.CardBody([
        #         html.H4(id='overview-kpi-warning', children='0', className='text-warning mb-0'),
        #         html.P("En Alerta", className='text-muted mb-0 small')
        #     ])], className="text-center shadow-sm"), md=3, sm=6, className="mb-2"),
        #     dbc.Col(dbc.Card([dbc.CardBody([
        #         html.H4(id='overview-kpi-critical', children='0', className='text-danger mb-0'),
        #         html.P("Críticos", className='text-muted mb-0 small')
        #     ])], className="text-center shadow-sm"), md=3, sm=6, className="mb-2"),
        # ], className="mb-3"),
        # Hidden placeholders for commented-out KPI callbacks
        html.Div(id='overview-kpi-total', style={'display': 'none'}),
        html.Div(id='overview-kpi-operational', style={'display': 'none'}),
        html.Div(id='overview-kpi-warning', style={'display': 'none'}),
        html.Div(id='overview-kpi-critical', style={'display': 'none'}),
        
        # ── Main Status Table (simplified: Unidad | Telemetría | Tribología) ──
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-table me-2"),
                            "Estado por Unidad"
                        ], className="mb-0 d-inline"),
                        html.Small(
                            " (pase el mouse sobre cada estado para ver detalles)",
                            className="text-muted"
                        )
                    ], className="bg-light"),
                    dbc.CardBody([
                        dcc.Loading(
                            id="loading-overview-table",
                            type="circle",
                            children=[
                                html.Div(id='overview-oil-ranking-table')
                            ]
                        )
                    ])
                ], className="shadow-sm mb-4")
            ], md=12)
        ]),
        
        # ── Charts Row (commented out for simplicity) ──
        # Hidden placeholders for chart callbacks that still exist
        dcc.Graph(id='overview-telemetry-chart', style={'display': 'none'}),
        dcc.Graph(id='overview-maintenance-chart', style={'display': 'none'}),
        dcc.Graph(id='overview-oil-chart', style={'display': 'none'}),
        dcc.Graph(id='overview-alerts-chart', style={'display': 'none'}),
        html.Div(id='overview-telemetry-timestamp', style={'display': 'none'}),
        html.Div(id='overview-maintenance-timestamp', style={'display': 'none'}),
        html.Div(id='overview-oil-timestamp', style={'display': 'none'}),
        html.Div(id='overview-alerts-timestamp', style={'display': 'none'}),
        html.Div(id='overview-summary-table', style={'display': 'none'}),
        dcc.Dropdown(id='overview-alerts-days-filter', value=30, style={'display': 'none'}),
        
    ], className="container-fluid p-4")
    
    logger.info("General Overview Tab layout created successfully")
    return layout
