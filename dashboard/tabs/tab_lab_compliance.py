"""
Laboratory Compliance KPIs Tab for Oil Analysis.

Provides compliance view for laboratory processing times:
- KPI cards: samples within/outside deadline, average delay
- Weekly trend chart of average lab delay
- Distribution of samples outside deadline by unit
- Date range selector filtering all views
"""

from dash import dcc, html
import dash_bootstrap_components as dbc


def create_lab_compliance_tab() -> dbc.Container:
    """Create the Laboratory Compliance tab layout."""
    return dbc.Container([
        html.H3("Cumplimiento de Laboratorio", className="mt-4 mb-3"),
        html.Hr(),

        # ========================================
        # Date Range Filter
        # ========================================
        dbc.Row([
            dbc.Col([
                html.Label("Rango de Fechas (Fecha de Muestra):", className="fw-bold small"),
                dcc.DatePickerRange(
                    id='lab-compliance-date-range',
                    display_format='YYYY-MM-DD',
                    start_date_placeholder_text='Fecha inicio',
                    end_date_placeholder_text='Fecha fin',
                    className="mb-2"
                )
            ], md=6),
        ], className="mb-4 p-3 bg-light rounded"),

        # ========================================
        # KPI Cards
        # ========================================
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6("Muestras Dentro de Plazo", className="text-muted mb-1"),
                        html.H3(id='lab-compliance-within-deadline', children="—",
                                className="text-success fw-bold mb-0"),
                        html.Small("≤ 2 días", className="text-muted")
                    ])
                ], className="shadow-sm h-100")
            ], md=4),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6("Muestras Fuera de Plazo", className="text-muted mb-1"),
                        html.H3(id='lab-compliance-outside-deadline', children="—",
                                className="text-danger fw-bold mb-0"),
                        html.Small("> 2 días", className="text-muted")
                    ])
                ], className="shadow-sm h-100")
            ], md=4),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6("Demora Promedio", className="text-muted mb-1"),
                        html.H3(id='lab-compliance-avg-delay', children="—",
                                className="text-primary fw-bold mb-0"),
                        html.Small("días", className="text-muted")
                    ])
                ], className="shadow-sm h-100")
            ], md=4),
        ], className="mb-4"),

        # ========================================
        # Weekly Evolution Chart
        # ========================================
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Evolución Semanal de Demora Promedio de Laboratorio"),
                    dbc.CardBody([
                        dcc.Graph(id='lab-compliance-weekly-chart',
                                  config={'displayModeBar': False},
                                  style={'height': '350px'})
                    ])
                ], className="shadow-sm")
            ], md=12)
        ], className="mb-4"),

        # ========================================
        # Distribution by Unit Chart
        # ========================================
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Muestras Fuera de Plazo por Unidad"),
                    dbc.CardBody([
                        dcc.Graph(id='lab-compliance-unit-chart',
                                  config={'displayModeBar': False},
                                  style={'height': '400px'})
                    ])
                ], className="shadow-sm")
            ], md=12)
        ], className="mb-4"),

    ], fluid=True, className="p-0")
