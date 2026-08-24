"""Executive alerts overview layout."""

from datetime import date, timedelta
from dash import html, dcc
import dash_bootstrap_components as dbc

from dashboard.components.labels import SOURCE_STYLE, source_style, light_tint


# Fixed heights for the three weekly-analysis cards (Distribución por unidad /
# Evolución temporal / Distribución por sistema) so the row's height stays
# constant regardless of fleet size; large unit counts scroll horizontally
# inside the card instead of growing it vertically.
ALERTS_CHART_CARD_HEIGHT = 500
ALERTS_CHART_CARD_BODY_HEIGHT = 420


def _default_alert_dates() -> tuple[str, str]:
    today = date.today()
    return (today - timedelta(days=27)).isoformat(), today.isoformat()


def _build_source_legend() -> html.Div:
    """Color legend for the alert source (Trigger_type) — decodes the same
    colors the table's Mixto row-highlight and the "Alertas multitécnicas"
    KPI card use, all read from labels.py's SOURCE_STYLE (W34-04)."""
    canonical_keys = ("Telemetria", "Tribologia", "Mixto")  # one entry per concept, not per alias
    swatches = []
    for raw in canonical_keys:
        label, color = source_style(raw)
        swatches.append(
            html.Span([
                html.Span(style={
                    "display": "inline-block", "width": "10px", "height": "10px",
                    "borderRadius": "2px", "backgroundColor": color, "marginRight": "6px",
                }),
                label,
            ], className="d-inline-flex align-items-center me-3")
        )
    return html.Div(
        [html.Small("Fuente: ", className="text-muted fw-bold me-2")] + swatches,
        className="d-flex flex-wrap align-items-center mt-2",
    )


def create_layout() -> html.Div:
    start_date, end_date = _default_alert_dates()
    return html.Div([
        dcc.Store(id="alerts-selected-alert-id"),
        dcc.Store(id="alerts-general-active-filters", data={}),
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
                html.Div([
                    html.Div(id="alerts-general-active-filter-badges", className="d-flex flex-wrap align-items-center"),
                    dbc.Button(
                        [html.I(className="fas fa-eraser me-1"), "Limpiar filtros"],
                        id="alerts-general-filter-clear-all",
                        color="link",
                        size="sm",
                        className="p-0 ms-1 align-baseline",
                        style={"display": "none"},
                    ),
                ], className="mt-2 d-flex flex-wrap align-items-center"),
            ])
        ], className="shadow-sm mb-3"),
        html.H4([html.I(className="fas fa-chart-bar me-2"), "Análisis semanal de alertas"], className="text-primary mb-3 mt-4"),
        html.P(
            "Haga clic en una barra o segmento para filtrar el resto de la vista. Haga clic de nuevo para quitar el filtro.",
            className="small text-muted mb-3",
        ),
        dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H5([html.I(className="fas fa-truck me-2"), "Distribución por unidad"], className="mb-0"), className="bg-light"),
                    dbc.CardBody(
                        dcc.Loading(
                            dcc.Graph(id="alerts-unit-distribution-chart", config={"displayModeBar": False}),
                            type="circle",
                        ),
                        style={"height": f"{ALERTS_CHART_CARD_BODY_HEIGHT}px", "overflow": "hidden"},
                    ),
                ], className="shadow-sm mb-4", style={"height": f"{ALERTS_CHART_CARD_HEIGHT}px"}),
            ], lg=4),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H5([html.I(className="fas fa-calendar-week me-2"), "Evolución temporal"], className="mb-0"), className="bg-light"),
                    dbc.CardBody(
                        dcc.Loading(dcc.Graph(id="alerts-month-distribution-chart", config={"displayModeBar": False}), type="circle"),
                        style={"height": f"{ALERTS_CHART_CARD_BODY_HEIGHT}px", "overflow": "hidden"},
                    ),
                ], className="shadow-sm mb-4", style={"height": f"{ALERTS_CHART_CARD_HEIGHT}px"}),
            ], lg=4),
            dbc.Col([
                dbc.Card([
                    dbc.CardHeader(html.H5([html.I(className="fas fa-sitemap me-2"), "Distribución por sistema"], className="mb-0"), className="bg-light"),
                    dbc.CardBody(
                        dcc.Loading(dcc.Graph(id="alerts-system-distribution-chart", config={"displayModeBar": False}), type="circle"),
                        style={"height": f"{ALERTS_CHART_CARD_BODY_HEIGHT}px", "overflow": "hidden"},
                    ),
                ], className="shadow-sm mb-4", style={"height": f"{ALERTS_CHART_CARD_HEIGHT}px"}),
            ], lg=4),
        ], className="g-3"),
        html.H4([html.I(className="fas fa-database me-2"), "Listado de alertas"], className="text-primary mb-3 mt-4"),
        dbc.Card([
            dbc.CardHeader([
                html.H5([html.I(className="fas fa-table me-2"), "Alertas del período"], className="mb-0"),
                html.Small("Seleccione una fila para leer el resumen completo.", className="text-muted"),
                _build_source_legend(),
            ], className="bg-light"),
            dbc.CardBody([
                dcc.Loading(html.Div(id="alerts-table-container"), type="circle"),
                html.Div(id="alerts-general-selected-alert", className="mt-3 px-2 pb-2"),
            ], className="p-2"),
        ], className="shadow-sm mb-4"),
    ], className="p-4")


def create_summary_stats_display(total_alerts: int, total_units: int, telemetry_pct: float = 0, oil_pct: float = 0, mixed_count: int = 0) -> html.Div:
    """Render only the three client-facing alert KPIs."""
    # W34-04: same color as the table's Mixto highlight and the legend above
    # — this card used to have its own independent accent (#7c6a9a) that had
    # drifted from the table's border color (#6f42c1).
    mixto_color = source_style("Mixto")[1]
    cards = [
        ("Total de alertas", total_alerts, "fas fa-exclamation-triangle", "#355c7d", "#eef4f8"),
        ("Unidades afectadas", total_units, "fas fa-truck", "#4f8a8b", "#edf7f6"),
        ("Alertas multitécnicas", mixed_count, "fas fa-layer-group", mixto_color, light_tint(mixto_color)),
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


_ACTIVE_FILTER_LABELS = {
    "unit": ("Unidad", "fas fa-truck"),
    "week": ("Semana", "fas fa-calendar-week"),
    "system": ("Sistema", "fas fa-cogs"),
}


def _format_active_filter_value(key: str, value: str) -> str:
    if key == "week":
        try:
            return date.fromisoformat(value).strftime("%d/%m/%Y")
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def create_active_filter_badges(active_filters: dict | None) -> list:
    """Render one removable chip per active cross-filter.

    The "Limpiar filtros" button lives permanently in the static layout
    (just hidden/shown) rather than here: a literal (non-pattern-matching)
    Dash Input must reference a component that exists in the layout at all
    times, and this function's output is only mounted conditionally.
    """
    active_filters = active_filters or {}
    chips = []
    for key, value in active_filters.items():
        if not value:
            continue
        label, icon = _ACTIVE_FILTER_LABELS.get(key, (key.title(), "fas fa-filter"))
        chips.append(
            dbc.Badge(
                [
                    html.I(className=f"{icon} me-1"),
                    f"{label}: {_format_active_filter_value(key, value)}",
                    html.I(className="fas fa-times ms-2"),
                ],
                id={"type": "alerts-general-filter-chip", "key": key},
                color="primary",
                pill=True,
                className="me-2 mb-1",
                style={"cursor": "pointer", "fontSize": "0.85rem"},
            )
        )
    return chips
