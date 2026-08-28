"""
Data Freshness Tab Layout.

This tab provides real-time monitoring of data update status for all units,
showing telemetry and tribology data freshness with color-coded indicators.
"""

from dash import html, dcc
import dash_bootstrap_components as dbc
from src.utils.logger import get_logger
from dashboard.callbacks.data_freshness_callbacks import FRESHNESS_CRITERIA, FRESHNESS_STATUS_STYLE

logger = get_logger(__name__)


def _format_timedelta(td):
    """Format timedelta to human-readable Spanish string."""
    total_seconds = int(td.total_seconds())
    days = td.days
    hours = total_seconds // 3600
    if days > 0:
        return f"{days} días" if days != 1 else "1 día"
    return f"{hours}h" if hours != 1 else "1h"


def _build_legend():
    """Build legend spans dynamically from FRESHNESS_CRITERIA.

    W34-02: icon/color come from FRESHNESS_STATUS_STYLE — the same source
    the table's row/cell coloring reads — instead of a third, independently
    hand-picked palette that happened to roughly agree with the other two.
    """
    telem = FRESHNESS_CRITERIA.get('Telemetria', [])
    tribo = FRESHNESS_CRITERIA.get('Tribologia', [])

    # Map label → (telem_threshold, tribo_threshold) for display
    # Criteria are ordered: Ok (< t1), Atención (< t2), Preocupante (>= t2)
    legend_items = []

    for i, (_, label, _) in enumerate(telem):
        style = FRESHNESS_STATUS_STYLE.get(label, FRESHNESS_STATUS_STYLE['Sin Datos'])
        icon = style['icon']
        color = style['accent']
        
        # Telemetry description
        if i < len(telem) - 1:
            t_desc = f"Telemetría <{_format_timedelta(telem[i][0])}"
        else:
            t_desc = f"Telemetría >{_format_timedelta(telem[i][0])}"
        
        # Tribology description  
        if i < len(tribo):
            if i < len(tribo) - 1:
                tr_desc = f"Tribología <{_format_timedelta(tribo[i][0])}"
            else:
                tr_desc = f"Tribología >{_format_timedelta(tribo[i][0])}"
        else:
            tr_desc = ""
        
        legend_items.append(
            html.Span(f"{icon} {label}: ", style={'fontWeight': 'bold', 'color': color})
        )
        legend_items.append(
            html.Span(f"{t_desc}, {tr_desc}", style={'fontSize': '0.9rem', 'marginRight': '20px'})
        )
    
    return html.Div(legend_items, className="text-muted", style={'fontSize': '0.85rem'})


def create_layout(client: str = "cda") -> html.Div:
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
                _build_legend()
            ])
        ], className="mb-4"),
        html.Div(id="data-freshness-source-status"),
        
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
