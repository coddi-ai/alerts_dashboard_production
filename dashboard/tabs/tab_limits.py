"""
Stewart Limits tab for Multi-Technical-Alerts dashboard.

Displays Stewart Limits thresholds with filtering capabilities.
"""

from dash import dcc, html
import dash_bootstrap_components as dbc
from dashboard.components.filters import create_machine_selector, create_component_selector
from dashboard.components.tables import create_limits_table


def create_limits_tab() -> dbc.Container:
    """
    Create Tab 1: Stewart Limits visualization.
    
    Features:
    - Machine/Component filters
    - Limits table with color-coded thresholds
    - Export functionality
    
    Returns:
        Bootstrap container with tab layout
    """
    return dbc.Container([
        html.H3("Stewart Limits", className="mt-4 mb-3"),
        html.Hr(),
        
        # Filters
        dbc.Row([
            dbc.Col([
                html.Label("Select Machine:", className="fw-bold"),
                dcc.Dropdown(
                    id='machine-selector',
                    placeholder='Select a machine...',
                    className="mb-3"
                )
            ], width=4),
            dbc.Col([
                html.Label("Select Component:", className="fw-bold"),
                dcc.Dropdown(
                    id='component-selector',
                    placeholder='Select a component...',
                    className="mb-3"
                )
            ], width=4),
            dbc.Col([
                html.Label("Search:", className="fw-bold"),
                dcc.Input(
                    id='limits-search',
                    type='text',
                    placeholder='Search essays...',
                    className="form-control mb-3"
                )
            ], width=4)
        ], className="mb-4"),
        
        # Info card
        dbc.Alert([
            html.H5("About Stewart Limits", className="alert-heading"),
            html.P([
                "Stewart Limits define the statistical thresholds for each essay (data contract v2.8): ",
                html.Br(),
                html.Strong("LIC - Inferior Condenatorio (2%): "), "Lower critical threshold — only present for essays where a lower limit applies",
                html.Br(),
                html.Strong("LIM - Inferior Marginal (5%): "), "Lower warning threshold — only present for essays where a lower limit applies",
                html.Br(),
                html.Strong("LSM - Superior Marginal (95%): "), "Upper warning threshold",
                html.Br(),
                html.Strong("LSC - Superior Condenatorio (98%): "), "Upper critical threshold"
            ])
        ], color="info", className="mb-4"),
        
        # Table container
        dbc.Card([
            dbc.CardHeader("Limits Table", className="fw-bold"),
            dbc.CardBody(
                html.Div(id='limits-table-container')
            )
        ])
        
    ], fluid=True)
