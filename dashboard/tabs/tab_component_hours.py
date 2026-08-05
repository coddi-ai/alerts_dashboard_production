"""
Component Hours (Horómetro) tab for Multi-Technical-Alerts dashboard.

Shows component operating hours evolution for each unit and component.
Available for CDA and ENEX clients.
"""

from dash import dcc, html
import dash_bootstrap_components as dbc


def create_component_hours_tab() -> dbc.Container:
    """
    Create Tab: Component Hours (Horómetro).
    
    Layout includes:
    1. Unit selector and component selector
    2. Summary table with latest hours per component
    3. Time series chart of component hours evolution
    
    Returns:
        Bootstrap container with tab layout
    """
    return dbc.Container([
        html.H3([
            html.I(className="fas fa-clock me-2"),
            "Horómetro de Componentes"
        ], className="mt-4 mb-3"),
        html.P(
            "Seguimiento de horas de operación de componentes a lo largo del tiempo. "
            "Los valores limpiados interpolan lecturas faltantes.",
            className="text-muted"
        ),
        html.Hr(),
        
        # ========================================
        # SECTION 1: Summary Table - Latest hours per component
        # ========================================
        html.H4("📊 Resumen de Horómetro por Equipo", className="mt-4 mb-3"),
        
        # Unit selector
        dbc.Row([
            dbc.Col([
                html.Label("Seleccionar Equipo:", className="fw-bold"),
                dcc.Dropdown(
                    id='comp-hours-unit-selector',
                    placeholder='Seleccionar equipo...',
                    className="mb-3"
                )
            ], width=4),
        ], className="mb-3"),
        
        # Summary table
        dbc.Card([
            dbc.CardHeader("Último Horómetro por Componente", className="fw-bold"),
            dbc.CardBody(
                html.Div(id='comp-hours-summary-table')
            )
        ], className="mb-4"),
        
        # ========================================
        # SECTION 2: Time Series Chart
        # ========================================
        html.H4("📈 Evolución de Horas de Componentes", className="mt-4 mb-3"),
        
        # Component multi-selector
        dbc.Row([
            dbc.Col([
                html.Label("Seleccionar Componentes:", className="fw-bold"),
                dcc.Dropdown(
                    id='comp-hours-component-selector',
                    placeholder='Seleccionar componentes...',
                    multi=True,
                    className="mb-3"
                )
            ], width=8),
        ], className="mb-3"),
        
        # Time series chart
        dbc.Card([
            dbc.CardBody([
                dcc.Graph(id='comp-hours-time-series')
            ])
        ], className="mb-4"),
        
    ], fluid=True)
