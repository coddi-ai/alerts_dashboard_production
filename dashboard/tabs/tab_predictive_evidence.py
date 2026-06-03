"""
Predictive Evidence Tab - Per-unit detailed evidence with oil and telemetry.
Supports multi-component model: auto-discovers component CSVs (motor, transmision, etc.)
"""

from dash import html, dcc
import pandas as pd
import os
from pathlib import Path
from config.settings import get_settings
from src.utils.logger import get_logger
from dashboard.components.predictive_config import (
    get_failure_mode_options,
    get_failure_modes_dict,
    get_oil_variables_for_mode,
    get_telemetry_signals_for_mode,
    OIL_LABELS,
    TELEMETRY_LABELS,
    OIL_THRESHOLDS,
)
from dashboard.components.predictive_kpis import create_kpi_card, create_kpi_row
from dashboard.components.predictive_charts import (
    create_fleet_scatter,
    create_comparative_bars,
    create_oil_timeseries_90d,
    create_telemetry_signal_chart,
)
from dashboard.components.predictive_tables import create_oil_variables_table

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
    """Load predictive data for a single component."""
    if not filepath.exists():
        logger.warning(f"Predictive data not found: {filepath}")
        return None, None

    df = pd.read_csv(filepath)
    df["Fecha"] = pd.to_datetime(df["Fecha"])

    # Compute rolling averages (concat at once to avoid fragmentation)
    df_sorted = df.sort_values(["Unit", "Fecha"]).copy()
    rolling_cols = {
        "ranking_30d": df_sorted.groupby("Unit")["ranking"].transform(
            lambda x: x.rolling(30, min_periods=1).mean()
        ),
        "ranking_90d": df_sorted.groupby("Unit")["ranking"].transform(
            lambda x: x.rolling(90, min_periods=1).mean()
        ),
    }
    df_sorted = pd.concat([df_sorted, pd.DataFrame(rolling_cols, index=df_sorted.index)], axis=1)

    # Latest snapshot
    df_latest = df_sorted.sort_values("Fecha").groupby("Unit").last().reset_index()
    df_latest = df_latest.assign(
        avg_ranking_30d=df_latest["ranking_30d"],
        ranking_acum_90d=df_latest["ranking_90d"],
    )

    return df_sorted, df_latest


# ── Helper functions ──────────────────────────────────────────────────────────

def _ranking_color(val):
    if val >= 70:
        return "#e24b4a"
    if val >= 40:
        return "#ef9f27"
    return "#1d9e75"


def _kpi_card(label, value, color, sub):
    return html.Div([
        html.Div(className="kpi-accent", style={"background": color}),
        html.Div(label, className="kpi-label"),
        html.Div(str(value), className="kpi-value"),
        html.Div(sub, className="kpi-sub"),
    ], className="kpi-card")


def _status_colors(status):
    return {
        "Crítica":   {"border": "#e24b4a", "bg": "#fcebeb", "text": "#a32d2d"},
        "Alerta":    {"border": "#ef9f27", "bg": "#faeeda", "text": "#854f0b"},
        "Saludable": {"border": "#1d9e75", "bg": "#eaf3de", "text": "#3b6d11"},
    }.get(status, {"border": "#888", "bg": "#f0f0f0", "text": "#444"})


# ── Render functions (called by callbacks) ────────────────────────────────────

def render_initial_content(unit, df, df_latest, component="motor"):
    """Render KPIs and fleet comparison for a unit."""
    failure_modes = get_failure_modes_dict(component)

    latest = df_latest.copy()
    p80_90d = float(latest["ranking_acum_90d"].quantile(0.80)) if "ranking_acum_90d" in latest.columns else 50.0
    latest["status"] = "Saludable"
    latest.loc[latest["ranking_acum_90d"] >= p80_90d, "status"] = "Alerta"
    latest.loc[
        (latest["ranking"] > 80) & (latest["ranking_acum_90d"] >= p80_90d),
        "status",
    ] = "Crítica"

    STATUS_COLORS = {"Crítica": "#e24b4a", "Alerta": "#ef9f27", "Saludable": "#1d9e75"}

    if not unit or unit not in df["Unit"].values:
        return html.Div(html.P("No hay datos disponibles.", className="text-muted text-center", style={"padding": "40px"}))

    row = latest[latest["Unit"] == unit]
    if row.empty:
        return html.Div(html.P("No hay datos disponibles.", className="text-muted text-center", style={"padding": "40px"}))
    row = row.iloc[0]

    # Dominant failure mode
    fm_keys = list(failure_modes.keys())
    fm_scores = {k: float(row[k]) if k in row.index and pd.notna(row[k]) else 0.0 for k in fm_keys}
    dominant_mode = max(fm_scores, key=fm_scores.get) if fm_scores else fm_keys[0]
    dominant_label = failure_modes[dominant_mode]

    # KPIs
    ranking_val = float(row["ranking"])
    ranking_90d_val = float(row.get("ranking_acum_90d", 0))

    df_unit = df[df["Unit"] == unit].sort_values("Fecha")
    last_date_str = df_unit["Fecha"].max().strftime("%d %b %Y") if not df_unit.empty else "—"

    kpis = [
        _kpi_card("Ranking actual", f"{ranking_val:.0f}", _ranking_color(ranking_val), "escala 0-100"),
        _kpi_card("Riesgo acum. 90d", f"{ranking_90d_val:.1f}", _ranking_color(ranking_90d_val), "índice histórico"),
        _kpi_card("Modo dominante", dominant_label, "#7C3AED", f"Score: {fm_scores[dominant_mode]:.1f}"),
        _kpi_card("Última evidencia", last_date_str, "#0891B2", "fecha más reciente"),
    ]

    # Fleet charts
    scatter_fig = create_fleet_scatter(latest, unit, STATUS_COLORS, p80_90d)
    bar_fig = create_comparative_bars(row, latest, failure_modes)

    return html.Div([
        # KPIs
        html.Div([
            html.Div([
                html.H4([html.I(className="fas fa-tachometer-alt me-2"), "Resumen de Condición"],
                        className="text-primary mb-2"),
                html.P(f"Indicadores principales de riesgo de la unidad {unit}", className="text-muted mb-3"),
            ]),
            html.Div(kpis, className="kpi-row"),
        ], className="card shadow-sm", style={"marginBottom": "1.5rem"}),

        # Fleet comparison
        html.Div([
            html.Div([
                html.H4([html.I(className="fas fa-chart-line me-2"), "Comparación Flota"],
                        className="text-primary mb-3 mt-4 pb-2 border-bottom"),
                html.P("Análisis de posición de la unidad respecto al resto de equipos", className="text-muted mb-3"),
            ]),
            html.Div([
                html.Div([
                    html.Div([
                        html.Span([html.I(className="fas fa-dot-circle me-1"), "Posición en la flota"],
                                  className="card-subtitle fw-500"),
                        html.Span("Ranking actual vs riesgo acumulado 90 días",
                                  style={"fontSize": "11px", "color": "var(--text-light)"}),
                    ], style={"marginBottom": "8px"}),
                    dcc.Graph(figure=scatter_fig, config={"displayModeBar": False}),
                ], className="card shadow-sm", style={"padding": "16px"}),
                html.Div([
                    html.Div([
                        html.Span([html.I(className="fas fa-chart-bar me-1"), "Perfil de riesgo"],
                                  className="card-subtitle fw-500"),
                        html.Span("Comparación por modo de falla vs promedio de la flota",
                                  style={"fontSize": "11px", "color": "var(--text-light)"}),
                    ], style={"marginBottom": "8px"}),
                    dcc.Graph(figure=bar_fig, config={"displayModeBar": False}),
                ], className="card shadow-sm", style={"padding": "16px"}),
            ], className="ev-two-col"),
        ], className="card shadow-sm", style={"marginBottom": "1.5rem", "padding": "20px"}),
    ])


def render_detailed_evidence(unit, df, df_latest, failure_mode, component="motor"):
    """Render oil and telemetry evidence for a unit and failure mode."""
    failure_modes = get_failure_modes_dict(component)

    if not failure_mode or failure_mode not in failure_modes:
        return html.Div(html.P("Seleccione un modo de falla válido.", className="text-muted text-center", style={"padding": "40px"}))

    selected_label = failure_modes[failure_mode]
    row = df_latest[df_latest["Unit"] == unit]
    if row.empty:
        return html.Div(html.P("No hay datos disponibles.", className="text-muted text-center", style={"padding": "40px"}))
    row = row.iloc[0]

    fm_keys = list(failure_modes.keys())
    fm_scores = {k: float(row[k]) if k in row.index and pd.notna(row[k]) else 0.0 for k in fm_keys}

    df_unit = df[df["Unit"] == unit].sort_values("Fecha")

    # Oil evidence
    oil_vars = get_oil_variables_for_mode(failure_mode, component)
    oil_subtitle = f"Variables asociadas a {selected_label}"

    if oil_vars and not df_unit.empty:
        ts_fig = create_oil_timeseries_90d(df_unit, oil_vars, OIL_LABELS)
        oil_chart = dcc.Graph(figure=ts_fig, config={"displayModeBar": False}) if ts_fig else html.P(
            "No hay suficientes datos históricos.", style={"color": "var(--text-muted)", "fontSize": "13px"})
        oil_table = create_oil_variables_table(df_unit, oil_vars, OIL_LABELS, OIL_THRESHOLDS)
    else:
        oil_chart = html.P("Este modo de falla no tiene variables de aceite asociadas.",
                           style={"color": "var(--text-muted)", "fontSize": "13px", "fontStyle": "italic"})
        oil_table = html.Div()

    # Telemetry evidence
    telem_signals = get_telemetry_signals_for_mode(failure_mode, component)
    telem_subtitle = f"Alertas operacionales asociadas a {selected_label}"

    if not df_unit.empty:
        fecha_fin = df_unit["Fecha"].max()
        fecha_inicio = fecha_fin - pd.Timedelta(days=90)
        df_unit_90d = df_unit[df_unit["Fecha"] >= fecha_inicio]
        window_text = f"⏱️ Ventana: {fecha_inicio.strftime('%d %b %Y')} – {fecha_fin.strftime('%d %b %Y')}"
    else:
        df_unit_90d = df_unit
        window_text = ""

    if telem_signals:
        charts = []
        for signal in telem_signals:
            fig = create_telemetry_signal_chart(df_unit_90d, signal, TELEMETRY_LABELS)
            if fig:
                charts.append(html.Div([dcc.Graph(figure=fig, config={"displayModeBar": False})], style={"marginBottom": "20px"}))
        telem_charts = html.Div(charts) if charts else html.P(
            "No hay alertas registradas en los últimos 90 días.", style={"color": "var(--text-muted)", "fontSize": "13px"})
    else:
        telem_charts = html.P("Este modo de falla no tiene señales de telemetría asociadas.",
                              style={"color": "var(--text-muted)", "fontSize": "13px"})
        window_text = ""

    return html.Div([
        # Mode info header
        html.Div([
            html.H5([html.I(className="fas fa-cogs me-2"), f"Modo de Falla: {selected_label}"],
                    className="mb-2 text-primary"),
            html.P(f"Score: {fm_scores.get(failure_mode, 0.0):.1f}", className="text-muted mb-2", style={"fontSize": "12px"}),
        ], className="card shadow-sm", style={"marginBottom": "1.5rem", "padding": "16px"}),

        # Oil evidence
        html.Div([
            html.Div([
                html.H4([html.I(className="fas fa-oil-can me-2"), "Evidencia Tribológica"],
                        className="text-primary mb-3 mt-4 pb-2 border-bottom"),
                html.P(oil_subtitle, className="text-muted mb-3"),
            ]),
            html.Span([html.I(className="fas fa-calendar-alt me-1"), "Ventana: últimos 90 días"],
                      className="text-muted", style={"fontSize": "11px", "display": "inline-block", "marginBottom": "8px"}),
            html.Div(oil_chart, style={"marginBottom": "24px"}),
            html.Div([
                html.Span([html.I(className="fas fa-table me-1"), "Resumen de variables"],
                          className="fw-500", style={"fontSize": "13px", "display": "block", "marginBottom": "8px"}),
                oil_table,
            ]),
        ], className="card shadow-sm", style={"marginBottom": "1.5rem", "padding": "20px"}),

        # Telemetry evidence
        html.Div([
            html.Div([
                html.H4([html.I(className="fas fa-signal me-2"), "Evidencia de Telemetría"],
                        className="text-primary mb-3 mt-4 pb-2 border-bottom"),
                html.P(telem_subtitle, className="text-muted mb-2"),
            ]),
            html.Div([
                html.Div(window_text, style={"fontSize": "11px", "color": "var(--text-muted)", "marginBottom": "4px"}),
                html.Div([
                    html.I(className="fas fa-info-circle me-1"),
                    "Las tasas representan el porcentaje del tiempo en alerta dentro de cada estado operacional"
                ], className="text-muted", style={"fontSize": "11px", "fontStyle": "italic", "marginBottom": "12px"}),
            ]),
            telem_charts,
        ], className="card shadow-sm", style={"marginBottom": "1.5rem", "padding": "20px"}),
    ])


# ── Main Layout ───────────────────────────────────────────────────────────────

def layout(client: str, component: str):
    """
    Render the predictive evidence tab for a specific component.
    Called by navigation_callbacks with client and component.
    """
    components = _discover_components(client)
    filepath = components.get(component)

    if not filepath:
        return html.Div([
            html.Div([
                html.I(className="fas fa-microscope me-3"),
                f"Predictivo — {component.title()} — Evidencia"
            ], className="page-title", style={"display": "flex", "alignItems": "center"}),
            html.P(f"No hay datos predictivos disponibles para {component}.",
                   className="text-muted", style={"padding": "40px", "textAlign": "center"})
        ])

    # Load component data
    df, df_latest = _load_component_data(filepath, component)
    units = sorted(df["Unit"].unique()) if df is not None else []
    failure_mode_options = get_failure_mode_options(component)

    return html.Div([
        # Page header
        html.Div([
            html.Div([
                html.I(className="fas fa-microscope me-2"),
                f"Evidencia por Unidad — {component.title()}"
            ], className="page-title", style={"display": "flex", "alignItems": "center"}),
            html.Div(f"Análisis detallado de riesgo, aceite y telemetría — {component}", className="page-subtitle"),
        ], style={"marginBottom": "16px"}),

        # Header with unit selector
        html.Div([
            html.Div([
                dcc.Dropdown(
                    id="predictive-ev-unit",
                    options=[{"label": u, "value": u} for u in units],
                    value=units[0] if units else None,
                    clearable=False,
                    className="ev-unit-dropdown",
                ),
            ], className="ev-unit-selector"),
        ], className="ev-page-header"),

        # Unit banner
        html.Div(id="predictive-ev-unit-banner", style={"marginTop": "1rem"}),

        # KPIs and fleet (updated by callback)
        html.Div(id="predictive-ev-initial-content", className="mt-4"),

        # Failure mode selector
        html.Div([
            html.Div([
                html.H5([html.I(className="fas fa-cogs me-2"), "Seleccionar Modo de Falla"], className="mb-2"),
                html.P("Elige un modo de falla para ver evidencia detallada de aceite y telemetría",
                       className="text-muted mb-2", style={"fontSize": "12px"}),
            ]),
            dcc.Dropdown(
                id="predictive-ev-failure-mode",
                options=failure_mode_options,
                value=None,
                clearable=False,
                className="ev-unit-dropdown",
                style={"marginTop": "8px"}
            ),
        ], className="card shadow-sm", style={"marginBottom": "1.5rem", "padding": "16px"}),

        # Detailed evidence (updated by callback)
        html.Div(id="predictive-ev-detailed-content"),

        # Hidden stores for client and component (used by callbacks)
        dcc.Store(id="predictive-ev-client-store", data=client),
        dcc.Store(id="predictive-ev-component-store", data=component),
    ], className="overview-container")
