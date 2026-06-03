"""
Predictive Overview Tab - Fleet status, KPIs, priority cards, failure mode table.
Supports multi-component model: auto-discovers component CSVs (motor, transmision, etc.)
"""

from dash import html, dcc
import pandas as pd
import os
from pathlib import Path
from config.settings import get_settings
from src.utils.logger import get_logger
from dashboard.components.predictive_config import (
    get_failure_modes_for_component,
    get_failure_modes_dict,
)
from dashboard.components.predictive_kpis import create_kpi_card, create_kpi_row

logger = get_logger(__name__)


# ── Data Loading (Multi-Component) ────────────────────────────────────────────

def _discover_components(client: str) -> dict:
    """Auto-discover available component CSV files for a client."""
    settings = get_settings()
    data_dir = Path(settings.data_root) / "predictive" / "golden" / client

    if not data_dir.exists():
        return {}

    components = {}
    for fname in sorted(os.listdir(data_dir)):
        if fname.endswith(".csv"):
            component_name = fname.replace(".csv", "")
            components[component_name] = data_dir / fname

    return components


def _load_component_data(filepath: Path, component: str):
    """Load and precompute predictive data for a single component."""
    if not filepath.exists():
        logger.warning(f"Predictive data not found: {filepath}")
        return None, None, {}

    df = pd.read_csv(filepath)
    df["Fecha"] = pd.to_datetime(df["Fecha"])
    df = df.copy()  # defragment after column assignment

    # Get component-specific failure modes
    failure_modes = get_failure_modes_dict(component)
    fm_keys = list(failure_modes.keys())
    score_cols = [c for c in fm_keys if c in df.columns] + ["ranking"]

    # Latest snapshot per unit
    df_latest = df.sort_values("Fecha").groupby("Unit").last().reset_index()

    # Rolling averages - compute all at once to avoid fragmentation
    df_sorted = df.sort_values(["Unit", "Fecha"]).copy()
    rolling_cols = {}
    for col in score_cols:
        if col in df_sorted.columns:
            grouped = df_sorted.groupby("Unit")[col]
            rolling_cols[f"{col}_30d"] = grouped.transform(
                lambda x: x.rolling(30, min_periods=1).mean()
            )
            rolling_cols[f"{col}_60d"] = grouped.transform(
                lambda x: x.rolling(60, min_periods=1).mean()
            )
            rolling_cols[f"{col}_90d"] = grouped.transform(
                lambda x: x.rolling(90, min_periods=1).mean()
            )

    if rolling_cols:
        df_sorted = pd.concat([df_sorted, pd.DataFrame(rolling_cols, index=df_sorted.index)], axis=1)

    # Get latest rolling values
    latest_rolling = df_sorted.sort_values("Fecha").groupby("Unit").last().reset_index()

    # Merge rolling into df_latest (all at once to avoid fragmentation)
    new_cols = {}
    new_cols["avg_ranking_30d"] = latest_rolling["ranking_30d"].values if "ranking_30d" in latest_rolling.columns else df_latest["ranking"].values
    new_cols["avg_ranking_60d"] = latest_rolling["ranking_60d"].values if "ranking_60d" in latest_rolling.columns else df_latest["ranking"].values
    new_cols["ranking_acum_90d"] = latest_rolling["ranking_90d"].values if "ranking_90d" in latest_rolling.columns else df_latest["ranking"].values
    df_latest = df_latest.assign(**new_cols)

    # Previous ranking (second-to-last date)
    dates = sorted(df["Fecha"].unique())
    prev_ranking = {}
    if len(dates) >= 2:
        prev_date = dates[-2]
        df_prev = df[df["Fecha"] == prev_date]
        prev_ranking = dict(zip(df_prev["Unit"], df_prev["ranking"]))

    return df, df_latest, prev_ranking


# ── Color helpers ─────────────────────────────────────────────────────────────

def _status_colors(status: str) -> dict:
    return {
        "Crítica":   {"border": "#e24b4a", "bg": "#fcebeb", "text": "#a32d2d"},
        "Alerta":    {"border": "#ef9f27", "bg": "#faeeda", "text": "#854f0b"},
        "Saludable": {"border": "#1d9e75", "bg": "#eaf3de", "text": "#3b6d11"},
    }.get(status, {"border": "#888", "bg": "#f0f0f0", "text": "#444"})


def _score_cell_style(value: float) -> dict:
    if value >= 70:
        return {"background": "#fcebeb", "text": "#a32d2d"}
    if value >= 40:
        return {"background": "#faeeda", "text": "#854f0b"}
    return {"background": "#eaf3de", "text": "#3b6d11"}


def _driver_bar_color(value: float) -> str:
    if value >= 70:
        return "#e24b4a"
    if value >= 40:
        return "#ef9f27"
    return "#1d9e75"


# ── Components ────────────────────────────────────────────────────────────────

def _driver_bar(name: str, value: float):
    pct = min(value, 100)
    return html.Div([
        html.Span(name, className="driver-name"),
        html.Div(
            html.Div(className="driver-fill",
                     style={"width": f"{pct}%", "background": _driver_bar_color(value)}),
            className="driver-bg"
        ),
        html.Span(f"{value:.0f}", className="driver-val"),
    ], className="driver-row")


def _priority_card(unit, score, acum_30d, delta, status, drivers):
    colors = _status_colors(status)

    if delta > 1:
        delta_cls, delta_txt = "delta-badge delta-pos", f"+{delta:.1f}"
    elif delta < -1:
        delta_cls, delta_txt = "delta-badge delta-neg", f"{delta:.1f}"
    else:
        delta_cls, delta_txt = "delta-badge delta-neu", f"{delta:+.1f}"

    return html.Div([
        html.Div([
            html.Span(unit, className="pc-unit"),
            html.Span(status, className="status-badge",
                      style={"background": colors["bg"], "color": colors["text"]}),
        ], className="pc-header"),
        html.Div([
            html.Span(f"{score:.0f}", className="pc-score"),
            html.Span(delta_txt, className=delta_cls),
        ], className="pc-score-row"),
        html.Div(f"Prom 30d: {acum_30d:.1f}", className="pc-acum"),
        html.Div("Factores principales", className="drivers-label"),
        *[_driver_bar(name, val) for name, val in drivers],
    ], className="priority-card",
       style={"borderLeftColor": colors["border"]})


def _failure_table(sorted_df, sort_col, failure_modes):
    fm_keys = list(failure_modes.keys())
    fm_labels = list(failure_modes.values())

    def _th(label, col_id):
        is_active = col_id == sort_col
        return html.Th(
            html.Div([
                html.Span(label),
                html.Span("↓" if is_active else "", style={
                    "marginLeft": "4px", "fontSize": "10px", "opacity": "0.6",
                }),
            ], style={"display": "flex", "alignItems": "center", "gap": "2px"}),
            className="fm-th fm-th-active" if is_active else "fm-th",
        )

    header = html.Thead(html.Tr([
        html.Th("Unidad", className="fm-th fm-th-unit"),
        html.Th("Hoy", className="fm-th fm-th-ranking"),
        _th("Prom 30d", "avg_ranking_30d"),
        _th("Prom 60d", "avg_ranking_60d"),
        _th("Prom 90d", "ranking_acum_90d"),
        html.Th("Status", className="fm-th"),
        *[_th(lbl, key) for key, lbl in zip(fm_keys, fm_labels)],
    ]))

    rows = []
    for _, r in sorted_df.iterrows():
        status = r["status"]
        colors = _status_colors(status)
        avg30 = float(r.get("avg_ranking_30d", 0))
        avg60 = float(r.get("avg_ranking_60d", 0))
        avg90 = float(r.get("ranking_acum_90d", 0))

        def _avg_cell(val, col_id):
            s = _score_cell_style(val)
            is_sort = col_id == sort_col
            return html.Td(
                f"{val:.1f}",
                className="fm-td fm-td-score fm-td-active" if is_sort else "fm-td fm-td-score",
                style={"background": s["background"], "color": s["text"],
                       "fontWeight": "600" if is_sort else "500"},
            )

        cells = [
            html.Td(r["Unit"], className="fm-td fm-td-unit"),
            html.Td(f"{r['ranking']:.0f}", className="fm-td fm-td-ranking"),
            _avg_cell(avg30, "avg_ranking_30d"),
            _avg_cell(avg60, "avg_ranking_60d"),
            _avg_cell(avg90, "ranking_acum_90d"),
            html.Td(
                html.Span(status, className="status-badge",
                          style={"background": colors["bg"], "color": colors["text"]}),
                className="fm-td",
            ),
        ]

        for key in fm_keys:
            val = float(r[key]) if key in r.index and pd.notna(r[key]) else 0.0
            style = _score_cell_style(val)
            is_sort = key == sort_col
            cells.append(html.Td(
                f"{val:.0f}",
                className="fm-td fm-td-score fm-td-active" if is_sort else "fm-td fm-td-score",
                style={"background": style["background"], "color": style["text"],
                       "fontWeight": "600" if is_sort else "500"},
            ))

        rows.append(html.Tr(cells, className="fm-tr"))

    return html.Div([
        html.Table([header, html.Tbody(rows)], className="fm-table"),
    ], className="fm-table-wrapper")


# ── Component Overview Renderer ───────────────────────────────────────────────

def _render_component_overview(df_latest, prev_ranking, component: str):
    """Render overview content for a specific component."""
    failure_modes = get_failure_modes_dict(component)

    # Status classification
    latest = df_latest.copy()
    p80_30d = float(latest["avg_ranking_30d"].quantile(0.80))
    avg_ranking = float(latest["ranking"].mean())

    latest["status"] = "Saludable"
    latest.loc[latest["avg_ranking_30d"] >= p80_30d, "status"] = "Alerta"
    latest.loc[
        (latest["ranking"] > 80) & (latest["avg_ranking_30d"] >= p80_30d),
        "status",
    ] = "Crítica"

    counts = latest["status"].value_counts()
    n_critical = counts.get("Crítica", 0)
    n_alert = counts.get("Alerta", 0)
    n_healthy = counts.get("Saludable", 0)

    # Hero KPIs
    hero = html.Div([
        html.Div([
            html.Div([
                html.I(className="fas fa-chart-bar me-2"),
                f"Estado de Flota — {component.title()}"
            ], className="page-title", style={"display": "flex", "alignItems": "center"}),
            html.Div(f"Resumen de riesgo operacional por unidad — componente {component}", className="page-subtitle"),
        ], style={"marginBottom": "16px"}),
        create_kpi_row([
            create_kpi_card(f"{avg_ranking:.1f}", "Ranking Flota", "fas fa-tachometer-alt", "primary", "promedio actual"),
            create_kpi_card(n_critical, "Unidades Críticas", "fas fa-exclamation-triangle", "danger", "unidades > P80 + >80"),
            create_kpi_card(n_alert, "Unidades en Alerta", "fas fa-exclamation-circle", "warning", "unidades > P80"),
            create_kpi_card(n_healthy, "Unidades Saludables", "fas fa-check-circle", "success", "bajo umbral"),
        ])
    ])

    # Priority cards
    cards = []
    for _, r in latest.sort_values("avg_ranking_30d", ascending=False).iterrows():
        score = r["ranking"]
        delta = score - prev_ranking.get(r["Unit"], score)
        drivers = sorted(
            [(failure_modes[c], r[c]) for c in failure_modes if c in r.index and pd.notna(r[c])],
            key=lambda x: x[1], reverse=True,
        )[:3]
        cards.append(_priority_card(
            unit=r["Unit"], score=score,
            acum_30d=float(r["avg_ranking_30d"]),
            delta=delta, status=r["status"], drivers=drivers,
        ))

    priority = html.Div([
        html.Div([
            html.H4([
                html.I(className="fas fa-bullseye me-2"),
                "Estado Flota — Prioridad"
            ], className="text-primary mb-3 mt-4"),
            html.P("Unidades ordenadas por promedio de ranking de 30 días", className="text-muted mb-3"),
        ]),
        html.Div(cards, className="priority-grid"),
    ])

    # Failure mode table
    sorted_df = latest.sort_values("avg_ranking_30d", ascending=False)
    table_section = html.Div([
        html.Div([
            html.H4([
                html.I(className="fas fa-table me-2"),
                "Riesgo por Modo de Falla"
            ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
            html.P("Vista de modos de falla por unidad", className="text-muted mb-3"),
        ]),
        _failure_table(sorted_df, "avg_ranking_30d", failure_modes),
    ], className="card", style={"marginTop": "16px"})

    return html.Div([hero, priority, table_section])


# ── Component Icon Map ────────────────────────────────────────────────────────

COMPONENT_ICONS = {
    "motor": "fas fa-cog",
    "transmision": "fas fa-exchange-alt",
}


# ── Main Layout ───────────────────────────────────────────────────────────────

def layout(client: str, component: str):
    """
    Render the predictive overview for a specific component.
    Called by navigation_callbacks with client and component.
    """
    components = _discover_components(client)
    filepath = components.get(component)

    if not filepath:
        return html.Div([
            html.Div([
                html.I(className="fas fa-brain me-3"),
                f"Predictivo — {component.title()} — Resumen"
            ], className="page-title", style={"display": "flex", "alignItems": "center"}),
            html.P(f"No hay datos predictivos disponibles para {component}.",
                   className="text-muted", style={"padding": "40px", "textAlign": "center"})
        ])

    df, df_latest, prev_ranking = _load_component_data(filepath, component)

    if df_latest is None or df_latest.empty:
        return html.Div([
            html.Div([
                html.I(className="fas fa-brain me-3"),
                f"Predictivo — {component.title()} — Resumen"
            ], className="page-title", style={"display": "flex", "alignItems": "center"}),
            html.P(f"No hay datos disponibles para {component}.",
                   className="text-muted", style={"padding": "40px", "textAlign": "center"})
        ])

    return _render_component_overview(df_latest, prev_ranking, component)
