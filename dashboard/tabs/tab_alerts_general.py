"""Executive alerts overview layout."""

from datetime import date, timedelta
from dash import html, dcc
import dash_bootstrap_components as dbc


def _default_alert_dates() -> tuple[str, str]:
    today = date.today()
    return (today - timedelta(days=27)).isoformat(), today.isoformat()


def create_layout() -> html.Div:
    start_date, end_date = _default_alert_dates()
    return html.Div([
        dcc.Store(id="alerts-selected-alert-id"),
        html.Div(id="alerts-summary-stats", className="mb-3"),
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Div([
                            html.I(className="fas fa-filter me-2"),
                            html.Span("Filtro temporal", className="fw-bold"),
                        ], className="d-flex align-items-center mb-2"),
                    ], width="auto"),
                    dbc.Col([
                        dcc.DatePickerRange(
                            id="alerts-date-range-picker",
                            start_date=start_date,
                            end_date=end_date,
                            display_format="DD/MM/YYYY",
                            start_date_placeholder_text="Fecha inicio",
                            end_date_placeholder_text="Fecha fin",
                            clearable=False,
                            className="w-100",
                        ),
                    ], width="auto"),
                    dbc.Col([
                        dbc.Button(
                            [html.I(className="fas fa-undo me-1"), "Restablecer últimas 4 semanas"],
                            id="alerts-date-range-clear",
                            color="outline-secondary",
                            size="sm",
                        )
                    ], width="auto"),
                ], align="center", className="g-2"),
                html.Div(id="alerts-general-filter-summary", className="small text-muted mt-2"),
            ])
        ], className="shadow-sm mb-3"),
        html.H4([html.I(className="fas fa-chart-bar me-2"), "Análisis semanal de alertas"], className="text-primary mb-3 mt-4"),
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H5([html.I(className="fas fa-truck me-2"), "Distribución por unidad"], className="mb-0"), className="bg-light"),
                    dbc.CardBody(dcc.Loading(dcc.Graph(id="alerts-unit-distribution-chart", config={"displayModeBar": False}), type="circle")),
                ], className="shadow-sm mb-4 h-100"),
            ], lg=4),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H5([html.I(className="fas fa-calendar-week me-2"), "Evolución temporal"], className="mb-0"), className="bg-light"),
                    dbc.CardBody(dcc.Loading(dcc.Graph(id="alerts-month-distribution-chart", config={"displayModeBar": False}), type="circle")),
                ], className="shadow-sm mb-4 h-100"),
            ], lg=4),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H5([html.I(className="fas fa-cogs me-2"), "Distribución por sistema"], className="mb-0"), className="bg-light"),
                    dbc.CardBody(dcc.Loading(dcc.Graph(id="alerts-system-distribution-chart", config={"displayModeBar": False}), type="circle")),
                ], className="shadow-sm mb-4 h-100"),
            ], lg=4),
        ], className="g-3"),
        html.H4([html.I(className="fas fa-database me-2"), "Listado de alertas"], className="text-primary mb-3 mt-4"),
        dbc.Card([
            dbc.CardHeader([
                html.H5([html.I(className="fas fa-table me-2"), "Alertas del período"], className="mb-0"),
                html.Small("Seleccione una fila para leer el resumen completo.", className="text-muted"),
            ], className="bg-light"),
            dbc.CardBody([
                dcc.Loading(html.Div(id="alerts-table-container"), type="circle"),
                html.Div(id="alerts-general-selected-alert", className="mt-3 px-2 pb-2"),
            ], className="p-2"),
        ], className="shadow-sm mb-4"),
    ], className="p-4")


def create_summary_stats_display(total_alerts: int, total_units: int, telemetry_pct: float = 0, oil_pct: float = 0, mixed_count: int = 0) -> html.Div:
    """Render only the three client-facing alert KPIs."""
    cards = [
        ("Total de alertas", total_alerts, "fas fa-exclamation-triangle", "#355c7d", "#eef4f8"),
        ("Unidades afectadas", total_units, "fas fa-truck", "#4f8a8b", "#edf7f6"),
        ("Alertas mixtas", mixed_count, "fas fa-layer-group", "#7c6a9a", "#f3eff8"),
    ]
    return html.Div([
        html.H4([html.I(className="fas fa-chart-line me-2"), "Resumen ejecutivo"], className="text-primary mb-3"),
        dbc.Row([
            dbc.Col(
                dbc.Card(dbc.CardBody([
                    html.Div([
                        html.I(className=f"{icon} fa-2x mb-2", style={"color": color}),
                        html.H6(label, className="text-muted text-uppercase mb-2", style={"fontSize": "0.82rem", "letterSpacing": "0.4px"}),
                        html.H2(f"{value:,}", className="mb-0 fw-bold", style={"color": color}),
                    ], className="text-center")
                ]), className="shadow-sm border-0", style={"backgroundColor": background}), md=4
            ) for label, value, icon, color, background in cards
        ], className="g-3"),
    ])
