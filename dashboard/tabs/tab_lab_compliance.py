"""
Laboratory Compliance Tab — July 2026 v3.

KPIs:
- Transit Time: labDate - sampleDate
- Lab Time: reportDate - labDate
- Edge case: if Lab Time has no positive values → show Diagnostic Time (reportDate - sampleDate)

Visualization: Weekly grouped bar chart (Transit Time vs Lab Time side-by-side).
"""

from dash import dcc, html
import dash_bootstrap_components as dbc


def create_lab_compliance_tab() -> dbc.Container:
    """Create the Laboratory Compliance tab layout."""
    return dbc.Container([
        html.H3("Cumplimiento de Laboratorio", className="mt-4 mb-3"),
        html.Hr(),

        # Date Range Filter
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

        # KPI Cards
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6(id='lab-kpi-1-title', children="Tiempo de Tránsito Prom.",
                                className="text-muted mb-1"),
                        html.H3(id='lab-kpi-1-value', children="—",
                                className="text-primary fw-bold mb-0"),
                        html.Small("días (labDate - sampleDate)", className="text-muted")
                    ])
                ], className="shadow-sm h-100")
            ], md=4),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6(id='lab-kpi-2-title', children="Tiempo de Laboratorio Prom.",
                                className="text-muted mb-1"),
                        html.H3(id='lab-kpi-2-value', children="—",
                                className="text-info fw-bold mb-0"),
                        html.Small("días (reportDate - labDate)", className="text-muted")
                    ])
                ], className="shadow-sm h-100")
            ], md=4),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6("Total Muestras", className="text-muted mb-1"),
                        html.H3(id='lab-kpi-total-samples', children="—",
                                className="text-secondary fw-bold mb-0"),
                        html.Small("en el rango seleccionado", className="text-muted")
                    ])
                ], className="shadow-sm h-100")
            ], md=4),
        ], className="mb-4"),

        # Weekly Bar Chart
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(id='lab-weekly-chart-title',
                                   children="Comparación Semanal: Tiempo de Tránsito vs Tiempo de Laboratorio"),
                    dbc.CardBody([
                        dcc.Graph(id='lab-compliance-weekly-chart',
                                  config={'displayModeBar': False},
                                  style={'height': '400px'})
                    ])
                ], className="shadow-sm")
            ], md=12)
        ], className="mb-4"),

        # Distribution by Unit
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader("Demora Promedio por Unidad"),
                    dbc.CardBody([
                        dcc.Graph(id='lab-compliance-unit-chart',
                                  config={'displayModeBar': False},
                                  style={'height': '400px'})
                    ])
                ], className="shadow-sm")
            ], md=12)
        ], className="mb-4"),

    ], fluid=True, className="p-0")
