"""
Main Telemetry Tab — Fleet Health Monitor.

Two-page layout:
- Fleet Overview: Fleet status donut, system heatmap, priority table, AI assessments
- Unit Detail: System risk table, signal cards with time series + KPI tables
"""

from dash import html, dcc
import dash_bootstrap_components as dbc


def create_layout(client: str = 'cda') -> html.Div:
    """
    Create unified telemetry health monitor layout with internal tabs.
    """
    return html.Div([
        # Header
        dbc.Row([
            dbc.Col([
                html.H2([
                    html.I(className="fas fa-heartbeat me-3"),
                    "Fleet Health Monitor"
                ], className="text-primary mb-1"),
                html.P(
                    "Monitoreo de salud de flota basado en telemetría multi-técnica",
                    className="text-muted"
                )
            ]),
            dbc.Col([
                html.Div(id='telemetry-reference-date', className="text-end")
            ], width="auto", className="d-flex align-items-center")
        ], className="mb-4"),

        # Client restriction notice
        dbc.Alert([
            html.I(className="fas fa-info-circle me-2"),
            "Este módulo está disponible únicamente para el cliente CDA"
        ], color="info", className="mb-4"),

        # Internal Tabs
        dcc.Tabs(
            id='telemetry-health-tabs',
            value='fleet-overview',
            children=[
                dcc.Tab(
                    label='Vista de Flota',
                    value='fleet-overview',
                    className='custom-tab',
                    selected_className='custom-tab--selected'
                ),
                dcc.Tab(
                    label='Detalle de Unidad',
                    value='unit-detail',
                    className='custom-tab',
                    selected_className='custom-tab--selected'
                )
            ],
            className='mb-4'
        ),

        # Tab content container
        html.Div(id='telemetry-health-tab-content')

    ], className="container-fluid p-4")
