"""Main Telemetry tab with executive fleet and unit evidence views."""

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
                    "Monitoreo de salud de la flota"
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

        # Availability notice is populated from the selected client's data.
        html.Div(id='telemetry-availability-notice', className="mb-4"),

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

        # Navigation context shared by the fleet and unit detail views.
        dcc.Store(
            id='telemetry-navigation-state',
            data={'unit': None, 'system': None, 'signal': None, 'source': None}
        ),

        # Tab content container
        html.Div(id='telemetry-health-tab-content')

    ], className="container-fluid p-4")
