"""
Telemetry Fleet Overview Tab Layout (Page 1).

Answers: "How is my fleet behaving currently?"
Shows: Fleet status KPIs, system heatmap, priority table, AI assessments.
"""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc


def create_telemetry_fleet_layout() -> html.Div:
    """Create fleet overview tab layout."""

    return html.Div([
        # KPI Cards Row
        html.Div(id='telemetry-fleet-kpi-row'),

        # System Health Heatmap (full width, professional card)
        dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="fas fa-th me-2"),
                    "Mapa de Calor — Riesgo por Sistema y Unidad"
                ], className="mb-0")
            ], className="bg-light"),
            dbc.CardBody([
                html.P(
                    "Comparación del Risk Score por unidad y sistema. "
                    "Las unidades se ordenan de mayor a menor riesgo agregado.",
                    className="text-muted mb-3"
                ),
                # Insight KPIs above heatmap
                html.Div(id='telemetry-fleet-heatmap-insights', className="mb-3"),
                # Risk band legend
                html.Div([
                    html.Small([
                        html.Span("0–20 ", className="fw-bold", style={"color": "#28a745"}),
                        html.Span("Bajo", className="me-3"),
                        html.Span("20–40 ", className="fw-bold", style={"color": "#6c757d"}),
                        html.Span("Moderado", className="me-3"),
                        html.Span("40–60 ", className="fw-bold", style={"color": "#f39c12"}),
                        html.Span("Alto", className="me-3"),
                        html.Span("60+ ", className="fw-bold", style={"color": "#dc3545"}),
                        html.Span("Crítico"),
                    ])
                ], className="text-center mb-2"),
                dcc.Loading(
                    dcc.Graph(
                        id='telemetry-fleet-heatmap',
                        config={'displayModeBar': False}
                    ),
                    type='circle'
                )
            ])
        ], className="shadow-sm mb-4"),

        # AI Assessments Table
        html.Div([
            html.H4([
                html.I(className="fas fa-robot me-2"),
                "Evaluaciones IA"
            ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
            html.P("Resumen ejecutivo generado por IA para cada unidad", className="text-muted mb-3")
        ]),
        dbc.Card([
            dbc.CardBody([
                dcc.Loading(
                    html.Div(id='telemetry-fleet-ai-table'),
                    type='circle'
                )
            ])
        ], className="shadow-sm mb-4")
    ])
