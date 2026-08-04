"""Warning Viewer dashboard page (TRD §10.2, REQ-027..029).

KPI cards, the 5 lifecycle charts, and a filterable/sortable table reading all
4 Parquet state files for the active client.

Registered as a page (`/erp/seguimiento-avisos`) in the shell app — run via
`python -m dashboard.app`.
"""
from __future__ import annotations

import logging

import dash_ag_grid as dag
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.express as px
from dash import Input, Output, callback, dcc, html

from agent import warning_writer
from agent.client_config import CLIENTS_DIR
from agent.envelope import (
    CONDITION_LABEL_LABELS,
    ConditionLabel,
    Severity,
    SEVERITY_LABELS,
    Source,
    SOURCE_LABELS,
    STATUS_LABELS,
    System,
    SYSTEM_LABELS,
    WarningStatus,
)

logger = logging.getLogger(__name__)

TABLE_COLUMNS = [
    "warning_id",
    "asset_id",
    "source",
    "system",
    "condition_label",
    "severity",
    "status",
    "generated_at",
    "validated_by",
    "erp_reference",
]

_EMPTY_TABLE_DF = pd.DataFrame(columns=TABLE_COLUMNS + ["client_id", "validated_at"])

# design-system semantic colors (ui_notes.md palette): Alerta=warning (caution), Anormal=danger
_LABEL_COLOR = {"Alerta": "#ffc107", "Anormal": "#dc3545"}
_SOURCE_COLOR = "#17a2b8"
# categorical palette for the system distribution chart — distinct hues, colorblind-safe order
_SYSTEM_COLOR_SEQUENCE = [
    "#4c78a8", "#f58518", "#54a24b", "#e45756", "#72b7b2",
    "#eeca3b", "#b279a2", "#ff9da6", "#9d755d",
]


def load_all_warnings(client_id: str) -> pd.DataFrame:
    """Combine all 4 state files for a client into one DataFrame (one row per Warning)."""
    rows = [
        w.model_dump(mode="json")
        for state in warning_writer.STATES
        for w in warning_writer.read_warnings(client_id, state)
    ]
    if not rows:
        return _EMPTY_TABLE_DF.copy()
    df = pd.DataFrame(rows)
    df["generated_at"] = pd.to_datetime(df["generated_at"])
    df["validated_at"] = pd.to_datetime(df["validated_at"])
    return df


def compute_kpis(df: pd.DataFrame) -> dict:
    """REQ-027: total, pending, validated & sent, rejected, avg time to validation."""
    validated_mask = df["validated_at"].notna() if "validated_at" in df else pd.Series(dtype=bool)
    if validated_mask.any():
        deltas = df.loc[validated_mask, "validated_at"] - df.loc[validated_mask, "generated_at"]
        avg_hours = round(deltas.dt.total_seconds().mean() / 3600, 1)
    else:
        avg_hours = None
    return {
        "total": len(df),
        "pending": int((df["status"] == "pending").sum()),
        "validated_and_sent": int(df["status"].isin(["validated", "sent"]).sum()),
        "rejected": int((df["status"] == "rejected").sum()),
        "avg_hours_to_validation": avg_hours,
    }


def apply_filters(
    df: pd.DataFrame,
    source: str | None = None,
    system: str | None = None,
    condition_label: str | None = None,
    severity: str | None = None,
    status: str | None = None,
    asset_id: str | None = None,
    from_date=None,
    to_date=None,
) -> pd.DataFrame:
    """REQ-029: filter by source, system, condition label, severity, status, asset, date range."""
    filtered = df
    if source:
        filtered = filtered[filtered["source"] == source]
    if system:
        filtered = filtered[filtered["system"] == system]
    if condition_label:
        filtered = filtered[filtered["condition_label"] == condition_label]
    if severity:
        filtered = filtered[filtered["severity"] == severity]
    if status:
        filtered = filtered[filtered["status"] == status]
    if asset_id:
        filtered = filtered[filtered["asset_id"] == asset_id]
    if from_date:
        filtered = filtered[filtered["generated_at"] >= pd.to_datetime(from_date)]
    if to_date:
        filtered = filtered[filtered["generated_at"] <= pd.to_datetime(to_date)]
    return filtered


def validation_rate_trend(df: pd.DataFrame) -> pd.DataFrame:
    """REQ-028: % sent vs rejected per day, among warnings that reached a terminal state."""
    resolved = df[df["status"].isin(["sent", "rejected"]) & df["validated_at"].notna()].copy()
    if resolved.empty:
        return pd.DataFrame(columns=["day", "outcome", "rate"])
    resolved["day"] = resolved["validated_at"].dt.date
    counts = resolved.groupby(["day", "status"]).size().reset_index(name="count")
    counts["rate"] = counts["count"] / counts.groupby("day")["count"].transform("sum") * 100
    return counts.rename(columns={"status": "outcome"})[["day", "outcome", "rate"]]


def _kpi_card(icon: str, label: str, value_id: str, text_color: str, bg: str) -> dbc.Col:
    return dbc.Col(
        dbc.Card(
            dbc.CardBody(
                html.Div(
                    [
                        html.I(className=f"fas {icon} fa-2x {text_color} mb-2"),
                        html.H6(
                            label,
                            className="text-muted mb-2",
                            style={"fontSize": "0.85rem", "letterSpacing": "0.5px"},
                        ),
                        html.H2(id=value_id, className=f"{text_color} mb-0 fw-bold"),
                    ],
                    className="text-center",
                )
            ),
            className="shadow-sm border-0",
            style={"backgroundColor": bg},
        ),
        md=2,
    )


def _filter_dropdown(id_, label, icon, options=None, clearable=True, **kwargs):
    return dbc.Col(
        [
            html.Label([html.I(className=f"fas {icon} me-1"), f" {label}"], className="fw-bold mb-2"),
            dcc.Dropdown(id=id_, options=options or [], clearable=clearable, **kwargs),
        ],
        md=2,
    )


def layout(**_kwargs):
    client_ids = sorted(p.stem for p in CLIENTS_DIR.glob("*.yaml")) if CLIENTS_DIR.exists() else []

    def _options(enum_cls, labels=None):
        labels = labels or {}
        return [{"label": labels.get(v, v.value), "value": v.value} for v in enum_cls]

    return dbc.Container(
        [
            html.Div(
                [
                    html.H3(
                        [html.I(className="fas fa-chart-bar me-2"), "Seguimiento de Avisos"],
                        className="text-primary mb-2",
                    ),
                    html.P(
                        "Visión global del ciclo de vida de los avisos: pendientes, enviados al ERP y rechazados.",
                        className="text-muted",
                    ),
                ],
                className="mb-4",
            ),
            dbc.Card(
                [
                    dbc.CardHeader(
                        html.H5([html.I(className="fas fa-filter me-2"), "Filtros"], className="mb-0"),
                        className="bg-light",
                    ),
                    dbc.CardBody(
                        [
                            dbc.Row(
                                [
                                    _filter_dropdown(
                                        "erp-viewer-filter-client",
                                        "Cliente",
                                        "fa-building",
                                        [{"label": c, "value": c} for c in client_ids],
                                        clearable=False,
                                        value=client_ids[0] if client_ids else None,
                                        placeholder="Seleccione un cliente...",
                                    ),
                                    _filter_dropdown(
                                        "erp-viewer-filter-source",
                                        "Fuente",
                                        "fa-cogs",
                                        _options(Source, SOURCE_LABELS),
                                        placeholder="Todas las fuentes...",
                                    ),
                                    _filter_dropdown(
                                        "erp-viewer-filter-system",
                                        "Sistema",
                                        "fa-cog",
                                        _options(System, SYSTEM_LABELS),
                                        placeholder="Todos los sistemas...",
                                    ),
                                    _filter_dropdown(
                                        "erp-viewer-filter-label",
                                        "Clasificación",
                                        "fa-tag",
                                        _options(ConditionLabel, CONDITION_LABEL_LABELS),
                                        placeholder="Todas...",
                                    ),
                                    _filter_dropdown(
                                        "erp-viewer-filter-severity",
                                        "Severidad",
                                        "fa-tachometer-alt",
                                        _options(Severity, SEVERITY_LABELS),
                                        placeholder="Todas...",
                                    ),
                                    _filter_dropdown(
                                        "erp-viewer-filter-status",
                                        "Estado",
                                        "fa-info-circle",
                                        _options(WarningStatus, STATUS_LABELS),
                                        placeholder="Todos...",
                                    ),
                                    _filter_dropdown(
                                        "erp-viewer-filter-asset",
                                        "Id Del Activo",
                                        "fa-truck",
                                        [],
                                        placeholder="Todos los equipos...",
                                    ),
                                ],
                                className="g-3",
                            ),
                            dbc.Row(
                                dbc.Col(
                                    [
                                        html.Label(
                                            [html.I(className="fas fa-calendar-alt me-1"), " Rango de fechas"],
                                            className="fw-bold mb-2",
                                        ),
                                        dcc.DatePickerRange(id="erp-viewer-filter-dates", display_format="DD/MM/YYYY"),
                                    ],
                                    md=4,
                                ),
                                className="g-3 mt-1",
                            ),
                        ]
                    ),
                ],
                className="shadow-sm mb-4",
            ),
            dbc.Row(
                [
                    _kpi_card("fa-bell", "Total Avisos", "erp-viewer-kpi-total", "text-primary", "#f0f8ff"),
                    _kpi_card("fa-clock", "Pendientes", "erp-viewer-kpi-pending", "text-warning", "#fffcf0"),
                    _kpi_card(
                        "fa-check-circle", "Validados y Enviados", "erp-viewer-kpi-sent", "text-success", "#f0fff4"
                    ),
                    _kpi_card("fa-times-circle", "Rechazados", "erp-viewer-kpi-rejected", "text-danger", "#fff5f5"),
                    _kpi_card(
                        "fa-hourglass-half",
                        "Horas prom. a validación",
                        "erp-viewer-kpi-avg-hours",
                        "text-info",
                        "#f0fdff",
                    ),
                ],
                className="g-3 mb-4",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.H5(
                                        [html.I(className="fas fa-chart-bar me-2"), "Avisos por Fuente"],
                                        className="mb-0",
                                    ),
                                    className="bg-light",
                                ),
                                dbc.CardBody(
                                    dcc.Loading(
                                        dcc.Graph(id="erp-viewer-chart-by-source", config={"displayModeBar": False}),
                                        type="circle",
                                    )
                                ),
                            ],
                            className="shadow-sm mb-4 h-100",
                        ),
                        md=6,
                    ),
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.H5(
                                        [html.I(className="fas fa-tag me-2"), "Avisos por Clasificación"],
                                        className="mb-0",
                                    ),
                                    className="bg-light",
                                ),
                                dbc.CardBody(
                                    dcc.Loading(
                                        dcc.Graph(id="erp-viewer-chart-by-label", config={"displayModeBar": False}),
                                        type="circle",
                                    )
                                ),
                            ],
                            className="shadow-sm mb-4 h-100",
                        ),
                        md=6,
                    ),
                ],
                className="gx-3",
            ),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.H5(
                                        [html.I(className="fas fa-tachometer-alt me-2"), "Avisos por Severidad"],
                                        className="mb-0",
                                    ),
                                    className="bg-light",
                                ),
                                dbc.CardBody(
                                    dcc.Loading(
                                        dcc.Graph(id="erp-viewer-chart-by-severity", config={"displayModeBar": False}),
                                        type="circle",
                                    )
                                ),
                            ],
                            className="shadow-sm mb-4 h-100",
                        ),
                        md=4,
                    ),
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.H5(
                                        [html.I(className="fas fa-cogs me-2"), "Avisos por Sistema"],
                                        className="mb-0",
                                    ),
                                    className="bg-light",
                                ),
                                dbc.CardBody(
                                    dcc.Loading(
                                        dcc.Graph(id="erp-viewer-chart-by-system", config={"displayModeBar": False}),
                                        type="circle",
                                    )
                                ),
                            ],
                            className="shadow-sm mb-4 h-100",
                        ),
                        md=4,
                    ),
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.H5(
                                        [html.I(className="fas fa-chart-line me-2"), "Avisos en el Tiempo"],
                                        className="mb-0",
                                    ),
                                    className="bg-light",
                                ),
                                dbc.CardBody(
                                    dcc.Loading(
                                        dcc.Graph(id="erp-viewer-chart-over-time", config={"displayModeBar": False}),
                                        type="circle",
                                    )
                                ),
                            ],
                            className="shadow-sm mb-4 h-100",
                        ),
                        md=4,
                    ),
                ],
                className="gx-3",
            ),
            dbc.Card(
                [
                    dbc.CardHeader(
                        html.H5(
                            [html.I(className="fas fa-percentage me-2"), "Tendencia de Tasa de Validación"],
                            className="mb-0",
                        ),
                        className="bg-light",
                    ),
                    dbc.CardBody(
                        dcc.Loading(
                            dcc.Graph(id="erp-viewer-chart-validation-rate", config={"displayModeBar": False}),
                            type="circle",
                        )
                    ),
                ],
                className="shadow-sm mb-4",
            ),
            html.Div(
                [
                    html.H4(
                        [html.I(className="fas fa-table me-2"), "Registro de Avisos"],
                        className="text-primary mb-3 mt-4 pb-2 border-bottom",
                    ),
                    html.P("Historial completo de avisos generados por el sistema.", className="text-muted mb-3"),
                ]
            ),
            dbc.Card(
                dbc.CardBody(
                    dcc.Loading(
                        dag.AgGrid(
                            id="erp-viewer-table",
                            columnDefs=[
                                {"field": "warning_id", "headerName": "ID", "width": 120},
                                {"field": "asset_id", "headerName": "Asset"},
                                {"field": "source", "headerName": "Fuente"},
                                {"field": "system", "headerName": "Sistema"},
                                {"field": "condition_label", "headerName": "Clasificación"},
                                {"field": "severity", "headerName": "Severidad"},
                                {"field": "status", "headerName": "Estado"},
                                {"field": "generated_at", "headerName": "Generado"},
                                {"field": "validated_by", "headerName": "Validado por"},
                                {"field": "erp_reference", "headerName": "Ref. ERP"},
                            ],
                            rowData=[],
                            dashGridOptions={"pagination": True, "paginationPageSize": 20},
                            columnSize="responsiveSizeToFit",
                            style={"height": "500px"},
                        ),
                        type="circle",
                    )
                ),
                className="shadow-sm mb-4",
            ),
            html.Div(id="erp-viewer-row-detail"),
        ],
        fluid=True,
        className="p-4",
    )


@callback(
    Output("erp-viewer-filter-asset", "options"),
    Output("erp-viewer-filter-asset", "value"),
    Input("erp-viewer-filter-client", "value"),
)
def _populate_asset_options(client_id):
    """Asset ID is a dropdown, not free text — options come from that client's own data."""
    if not client_id:
        return [], None
    assets = sorted(load_all_warnings(client_id)["asset_id"].dropna().unique())
    logger.info("client=%s asset_options=%d", client_id, len(assets))
    return [{"label": a, "value": a} for a in assets], None


@callback(
    Output("erp-viewer-kpi-total", "children"),
    Output("erp-viewer-kpi-pending", "children"),
    Output("erp-viewer-kpi-sent", "children"),
    Output("erp-viewer-kpi-rejected", "children"),
    Output("erp-viewer-kpi-avg-hours", "children"),
    Output("erp-viewer-chart-by-source", "figure"),
    Output("erp-viewer-chart-by-label", "figure"),
    Output("erp-viewer-chart-by-severity", "figure"),
    Output("erp-viewer-chart-by-system", "figure"),
    Output("erp-viewer-chart-over-time", "figure"),
    Output("erp-viewer-chart-validation-rate", "figure"),
    Output("erp-viewer-table", "rowData"),
    Input("erp-viewer-filter-client", "value"),
    Input("erp-viewer-filter-source", "value"),
    Input("erp-viewer-filter-system", "value"),
    Input("erp-viewer-filter-label", "value"),
    Input("erp-viewer-filter-severity", "value"),
    Input("erp-viewer-filter-status", "value"),
    Input("erp-viewer-filter-asset", "value"),
    Input("erp-viewer-filter-dates", "start_date"),
    Input("erp-viewer-filter-dates", "end_date"),
)
def _refresh(client_id, source, system, condition_label, severity, status, asset_id, start_date, end_date):
    empty_fig = px.bar()
    if not client_id:
        logger.warning("refresh skipped: no client selected")
        return "0", "0", "0", "0", "–", empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, empty_fig, []

    df = load_all_warnings(client_id)
    filtered = apply_filters(
        df, source, system, condition_label, severity, status, asset_id, start_date, end_date
    )
    logger.info(
        "client=%s loaded=%d after_filters=%d source=%s system=%s label=%s severity=%s status=%s asset=%s",
        client_id,
        len(df),
        len(filtered),
        source,
        system,
        condition_label,
        severity,
        status,
        asset_id,
    )

    kpis = compute_kpis(filtered)
    avg_hours_display = kpis["avg_hours_to_validation"] if kpis["avg_hours_to_validation"] is not None else "–"

    if filtered.empty:
        return (
            str(kpis["total"]),
            str(kpis["pending"]),
            str(kpis["validated_and_sent"]),
            str(kpis["rejected"]),
            str(avg_hours_display),
            empty_fig,
            empty_fig,
            empty_fig,
            empty_fig,
            empty_fig,
            empty_fig,
            [],
        )

    display = filtered.assign(
        source_label=filtered["source"].map(lambda s: SOURCE_LABELS.get(Source(s), s)),
        system_label=filtered["system"].map(lambda s: SYSTEM_LABELS.get(System(s), s)),
        condition_label_label=filtered["condition_label"].map(
            lambda s: CONDITION_LABEL_LABELS.get(ConditionLabel(s), s)
        ),
        severity_label=filtered["severity"].map(lambda s: SEVERITY_LABELS.get(Severity(s), s)),
    )

    by_source = px.bar(
        display.groupby("source_label").size().reset_index(name="count"),
        x="source_label",
        y="count",
        title=None,
        color_discrete_sequence=[_SOURCE_COLOR],
        labels={"source_label": "Fuente"},
    )
    by_label = px.bar(
        display.groupby(["source_label", "condition_label_label"]).size().reset_index(name="count"),
        x="source_label",
        y="count",
        color="condition_label_label",
        title=None,
        color_discrete_map=_LABEL_COLOR,
        labels={"source_label": "Fuente", "condition_label_label": "Clasificación"},
    )
    by_severity = px.pie(
        display.groupby("severity_label").size().reset_index(name="count"),
        names="severity_label",
        values="count",
    )
    by_system = px.pie(
        display.groupby("system_label").size().reset_index(name="count"),
        names="system_label",
        values="count",
        color_discrete_sequence=_SYSTEM_COLOR_SEQUENCE,
    )
    over_time = (
        filtered.assign(day=filtered["generated_at"].dt.date).groupby("day").size().reset_index(name="count")
    )
    over_time_fig = px.line(over_time, x="day", y="count")

    trend = validation_rate_trend(filtered)
    validation_fig = px.line(trend, x="day", y="rate", color="outcome") if not trend.empty else px.line()

    for fig in (by_source, by_label, by_severity, by_system, over_time_fig, validation_fig):
        fig.update_layout(margin=dict(l=20, r=20, t=20, b=20))

    table_data = filtered[TABLE_COLUMNS].astype(str).to_dict("records")
    return (
        str(kpis["total"]),
        str(kpis["pending"]),
        str(kpis["validated_and_sent"]),
        str(kpis["rejected"]),
        str(avg_hours_display),
        by_source,
        by_label,
        by_severity,
        by_system,
        over_time_fig,
        validation_fig,
        table_data,
    )


@callback(
    Output("erp-viewer-row-detail", "children"),
    Input("erp-viewer-table", "cellClicked"),
)
def _row_detail(cell):
    if not cell or not cell.get("data"):
        return ""
    row = cell["data"]
    if row.get("status") not in ("sent", "rejected"):
        return ""
    logger.info("row detail opened warning_id=%s status=%s", row.get("warning_id"), row.get("status"))
    return dbc.Card(dbc.CardBody(html.Pre(str(row))), className="shadow-sm mt-3")
