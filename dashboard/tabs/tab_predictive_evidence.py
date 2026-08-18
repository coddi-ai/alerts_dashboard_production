"""
Predictive Evidence Tab - Per-unit detailed evidence with oil and telemetry.
Supports multi-component model: auto-discovers component CSVs (motor, transmision, etc.)
"""

from dash import html, dcc
import pandas as pd
import re
import os
from pathlib import Path
from config.settings import get_settings
from src.utils.logger import get_logger
from dashboard.components.predictive_config import (
    get_failure_mode_options,
    get_failure_modes_dict,
    get_failure_modes_for_component,
    get_failure_mode_methodology,
    get_oil_variables_for_mode,
    get_telemetry_signals_for_mode,
    OIL_LABELS,
    TELEMETRY_LABELS,
    load_predictive_oil_limits_four,
)
from dashboard.components.predictive_kpis import create_kpi_card, create_kpi_row
from dashboard.components.predictive_charts import (
    create_fleet_scatter,
    create_comparative_bars,
    create_oil_timeseries_90d,
    create_telemetry_signal_chart,
)
from dashboard.components.predictive_tables import create_oil_variables_table
from dashboard.components.oil_charts import get_essay_limits_four, classify_four_limit_value
from dashboard.components.ai_analysis_panel import create_ai_analysis_panel
from src.data.loaders import load_analisis_inteligente

logger = get_logger(__name__)


# ── Client-scoped label/threshold resolution ──────────────────────────────────

def _resolve_client_dicts(client, component):
    """
    Resolve the per-client OIL_LABELS / TELEMETRY_LABELS, and the four-limit
    Stewart dict (LIC/LIM/LSM/LSC, data contract v2.8) for `component`.
    Labels fall back to 'cda' if the client is missing so callers never
    KeyError. Returns (oil_labels, telem_labels, oil_limits_four) -
    oil_limits_four is {} when unavailable (see
    load_predictive_oil_limits_four for why this never silently falls back to
    the legacy three-limit structure).
    """
    ckey = (client or "cda").lower()
    oil_labels = OIL_LABELS.get(ckey, OIL_LABELS["cda"])
    telem_labels = TELEMETRY_LABELS.get(ckey, TELEMETRY_LABELS["cda"])
    oil_limits_four = load_predictive_oil_limits_four(ckey, component)
    return oil_labels, telem_labels, oil_limits_four


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


def _load_component_data(filepath: Path, component: str, client: str = "cda"):
    """Load predictive data for a single component."""
    if not filepath.exists():
        logger.warning(f"Predictive data not found: {filepath}")
        return None, None

    df = pd.read_csv(filepath)
    df["Fecha"] = pd.to_datetime(df["Fecha"])

    # Get failure mode keys for this component
    failure_modes = get_failure_modes_dict(component, client)
    fm_keys = list(failure_modes.keys())

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
    # Also compute 30d rolling for each failure mode (for status classification)
    for fm in fm_keys:
        if fm in df_sorted.columns:
            rolling_cols[f"{fm}_30d"] = df_sorted.groupby("Unit")[fm].transform(
                lambda x: x.rolling(30, min_periods=1).mean()
            )
    df_sorted = pd.concat([df_sorted, pd.DataFrame(rolling_cols, index=df_sorted.index)], axis=1)

    # Latest snapshot
    df_latest = df_sorted.sort_values("Fecha").groupby("Unit").last().reset_index()

    # Compute max failure mode 30d average per unit
    fm_30d_cols = [f"{fm}_30d" for fm in fm_keys if f"{fm}_30d" in df_latest.columns]
    max_fm_30d = df_latest[fm_30d_cols].max(axis=1) if fm_30d_cols else 0.0

    df_latest = df_latest.assign(
        avg_ranking_30d=df_latest["ranking_30d"],
        ranking_acum_90d=df_latest["ranking_90d"],
        max_fm_30d=max_fm_30d,
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


# ── Insight generation (AI-style explanations) ────────────────────────────────

def _parse_bold(text):
    """Convert **bold** markers to html.Strong elements."""
    parts = re.split(r'\*\*(.+?)\*\*', text)
    return [html.Strong(p) if i % 2 else p for i, p in enumerate(parts) if p]


def _oil_date_col(df) -> str:
    """
    Nombre de la columna de fecha de las muestras de aceite.
    CDA usa 'sampleDate'; Capstone no la tiene y usa 'Fecha' para todo.
    """
    if "sampleDate" in df.columns:
        return "sampleDate"
    return "Fecha"


def _analyze_oil_observations(df_unit, oil_vars, df_latest, oil_labels, oil_limits_four):
    """Generate data-driven observations for oil variables."""
    observations = []
    if not oil_vars or df_unit.empty:
        return observations

    date_col = _oil_date_col(df_unit)
    df_sorted = df_unit.sort_values(date_col)
    last_sample = df_sorted.iloc[-1]
    oil_range = last_sample.get("oilHourRange", "LT_1000")

    # Deduplicate by sample date for trend analysis
    df_oil = df_sorted.drop_duplicates(subset=[date_col]).sort_values(date_col)

    for var in oil_vars:
        if var not in df_sorted.columns:
            continue

        current_val = last_sample.get(var)
        if pd.isna(current_val):
            continue
        current_val = float(current_val)
        label = oil_labels.get(var, var)

        # 1. Threshold check - four-limit Stewart output (LIC/LIM/LSM/LSC, v2.8)
        essay_limits = get_essay_limits_four(oil_limits_four, var, oil_range)
        if essay_limits and essay_limits.get('LSM') is not None and essay_limits.get('LSC') is not None:
            status = classify_four_limit_value(
                current_val, essay_limits.get('LIC'), essay_limits.get('LIM'),
                essay_limits['LSM'], essay_limits['LSC']
            )
            if status == 'Superior Condenatorio':
                observations.append({
                    "type": "critical",
                    "icon": "fas fa-exclamation-triangle",
                    "text": f"{label} está en **{current_val:.1f}**, superando el límite superior condenatorio ({essay_limits['LSC']:.0f})"
                })
            elif status == 'Superior Marginal':
                observations.append({
                    "type": "warning",
                    "icon": "fas fa-exclamation-circle",
                    "text": f"{label} está en **{current_val:.1f}**, en zona de alerta (límite superior marginal: {essay_limits['LSM']:.0f})"
                })
            elif status == 'Inferior Condenatorio':
                observations.append({
                    "type": "critical",
                    "icon": "fas fa-exclamation-triangle",
                    "text": f"{label} está en **{current_val:.1f}**, por debajo del límite inferior condenatorio ({essay_limits['LIC']:.0f})"
                })
            elif status == 'Inferior Marginal':
                observations.append({
                    "type": "warning",
                    "icon": "fas fa-exclamation-circle",
                    "text": f"{label} está en **{current_val:.1f}**, en zona de alerta (límite inferior marginal: {essay_limits['LIM']:.0f})"
                })
            elif status == 'Normal':
                observations.append({
                    "type": "ok",
                    "icon": "fas fa-check-circle",
                    "text": f"{label} está en **{current_val:.1f}**, dentro de rango normal"
                })

        # 2. Trend analysis (unique oil samples)
        samples = df_oil[df_oil[var].notna()]
        if len(samples) >= 3:
            recent = samples.tail(5)
            first_val = float(recent[var].iloc[0])
            last_val = float(recent[var].iloc[-1])
            n_samples = len(recent)
            if first_val > 0.01:
                change_pct = ((last_val - first_val) / first_val) * 100
                if change_pct > 25:
                    observations.append({
                        "type": "warning",
                        "icon": "fas fa-arrow-up",
                        "text": f"{label} muestra tendencia al alza (**{change_pct:+.0f}%** en las últimas {n_samples} muestras)"
                    })
                elif change_pct < -25:
                    observations.append({
                        "type": "ok",
                        "icon": "fas fa-arrow-down",
                        "text": f"{label} muestra tendencia a la baja (**{change_pct:+.0f}%** en las últimas {n_samples} muestras)"
                    })

        # 3. Fleet comparison
        if var in df_latest.columns:
            fleet_avg = float(df_latest[var].mean())
            if fleet_avg > 0.01:
                ratio = (current_val / fleet_avg - 1) * 100
                if ratio > 40:
                    observations.append({
                        "type": "warning",
                        "icon": "fas fa-users",
                        "text": f"{label} está un **{ratio:.0f}%** por encima del promedio de la flota ({fleet_avg:.1f})"
                    })

    return observations


def _analyze_telemetry_observations(df_unit, telem_vars, telem_labels, days=90):
    """Generate data-driven observations for telemetry signals."""
    observations = []
    if not telem_vars or df_unit.empty:
        return observations

    fecha_fin = df_unit["Fecha"].max()
    fecha_inicio = fecha_fin - pd.Timedelta(days=days)
    df_window = df_unit[df_unit["Fecha"] >= fecha_inicio]

    if df_window.empty:
        return observations

    for signal in telem_vars:
        signal_label = telem_labels.get(signal, signal)
        alert_cols = [c for c in df_window.columns if f"_{signal}_alert_rate" in c]
        critic_cols = [c for c in df_window.columns if f"_{signal}_critic_rate" in c]

        # Critic rate analysis
        if critic_cols:
            avg_critic = df_window[critic_cols].mean().mean()
            if avg_critic > 0.15:
                observations.append({
                    "type": "critical",
                    "icon": "fas fa-exclamation-triangle",
                    "text": f"{signal_label} presenta tasa crítica promedio de **{avg_critic:.1%}** en los últimos {days} días"
                })
            elif avg_critic > 0.05:
                observations.append({
                    "type": "warning",
                    "icon": "fas fa-exclamation-circle",
                    "text": f"{signal_label} presenta tasa crítica de **{avg_critic:.1%}** en los últimos {days} días"
                })

            # Recent spike detection (last 7 days vs prior)
            recent = df_window[df_window["Fecha"] >= fecha_fin - pd.Timedelta(days=7)]
            prior = df_window[df_window["Fecha"] < fecha_fin - pd.Timedelta(days=7)]
            if not recent.empty and not prior.empty:
                recent_avg = recent[critic_cols].mean().mean()
                prior_avg = prior[critic_cols].mean().mean()
                if recent_avg > 0.1 and prior_avg > 0.001 and recent_avg / prior_avg > 2:
                    observations.append({
                        "type": "critical",
                        "icon": "fas fa-bolt",
                        "text": f"{signal_label} muestra un **aumento reciente** en tasa crítica (última semana vs promedio previo)"
                    })

        # Alert rate analysis
        if alert_cols:
            avg_alert = df_window[alert_cols].mean().mean()
            if avg_alert > 0.20:
                observations.append({
                    "type": "warning",
                    "icon": "fas fa-bell",
                    "text": f"{signal_label} presenta tasa de alerta promedio de **{avg_alert:.1%}** en los últimos {days} días"
                })

        # If no alerts at all → positive observation
        if alert_cols and critic_cols:
            total_rate = df_window[alert_cols + critic_cols].mean().mean()
            if total_rate < 0.02:
                observations.append({
                    "type": "ok",
                    "icon": "fas fa-check-circle",
                    "text": f"{signal_label} sin alertas significativas en los últimos {days} días"
                })

    return observations


def _generate_insight_data(unit, df_unit, df_latest, failure_mode, component="motor", client="cda"):
    """Generate complete insight data for a failure mode and unit."""
    oil_labels, telem_labels, oil_limits_four = _resolve_client_dicts(client, component)
    modes = get_failure_modes_for_component(component, client)
    mode_config = modes.get(failure_mode, {})
    if not mode_config:
        return None

    label = mode_config["label"]
    oil_vars = mode_config.get("oil_variables", [])
    telem_vars = mode_config.get("telemetry_variables", [])
    methodology = get_failure_mode_methodology(failure_mode, component, client)

    # Score
    row = df_latest[df_latest["Unit"] == unit]
    if row.empty:
        return None
    row = row.iloc[0]
    score = float(row[failure_mode]) if failure_mode in row.index and pd.notna(row[failure_mode]) else 0.0

    # Variable names for display
    var_names = []
    if oil_vars:
        var_names.extend([oil_labels.get(v, v) for v in oil_vars])
    if telem_vars:
        var_names.extend([telem_labels.get(v, v) for v in telem_vars])

    # Collect observations
    observations = []
    observations.extend(_analyze_oil_observations(df_unit, oil_vars, df_latest, oil_labels, oil_limits_four))
    observations.extend(_analyze_telemetry_observations(df_unit, telem_vars, telem_labels))

    # Fleet comparison for the overall failure mode score
    if failure_mode in df_latest.columns:
        fleet_p80 = float(df_latest[failure_mode].quantile(0.80))
        fleet_avg = float(df_latest[failure_mode].mean())
        if score > fleet_p80 and score > 10:
            observations.insert(0, {
                "type": "warning",
                "icon": "fas fa-chart-line",
                "text": f"El puntaje de esta unidad (**{score:.0f}**) está por encima del percentil 80 de la flota ({fleet_p80:.0f})"
            })
    else:
        fleet_avg = 0.0

    # Sort: critical first, then warning, then ok
    priority = {"critical": 0, "warning": 1, "info": 2, "ok": 3}
    observations.sort(key=lambda x: priority.get(x["type"], 2))

    # Observation window
    n_days = 90
    if not df_unit.empty:
        fecha_fin = df_unit["Fecha"].max()
        fecha_inicio = fecha_fin - pd.Timedelta(days=90)
        n_days = (fecha_fin - fecha_inicio).days

    return {
        "unit": unit,
        "score": score,
        "label": label,
        "var_names": var_names,
        "methodology": methodology,
        "observations": observations,
        "n_days": n_days,
        "fleet_avg": fleet_avg,
    }


def _get_unit_ai_analysis(df_analisis, unit):
    """
    Return the most recent analisis_inteligente.parquet row for `unit`
    (one row per Unit per Fecha), or None if there's no AI analysis on file.
    """
    if df_analisis is None or df_analisis.empty or not unit or "Unit" not in df_analisis.columns:
        return None
    rows = df_analisis[df_analisis["Unit"] == unit]
    if rows.empty:
        return None
    if "Fecha" in rows.columns:
        rows = rows.sort_values("Fecha")
    return rows.iloc[-1]


def _build_insight_panel(insight):
    """Build the AI insight panel UI component."""
    if not insight:
        return html.Div()

    score = insight["score"]
    unit = insight["unit"]
    label = insight["label"]
    var_names = insight["var_names"]
    methodology = insight.get("methodology", "")
    observations = insight.get("observations", [])
    n_days = insight.get("n_days", 90)

    # Score styling
    if score >= 70:
        score_color, score_level = "#e24b4a", "alto"
    elif score >= 40:
        score_color, score_level = "#ef9f27", "medio"
    else:
        score_color, score_level = "#1d9e75", "bajo"

    vars_text = ", ".join(var_names) if var_names else "—"

    # Build observation items
    type_styles = {
        "critical": {"bg": "#fcebeb", "border": "#e24b4a", "icon_color": "#a32d2d"},
        "warning":  {"bg": "#faeeda", "border": "#ef9f27", "icon_color": "#854f0b"},
        "ok":       {"bg": "#eaf3de", "border": "#1d9e75", "icon_color": "#3b6d11"},
        "info":     {"bg": "#e8f4f8", "border": "#0891B2", "icon_color": "#155e75"},
    }

    obs_items = []
    for obs in observations:
        st = type_styles.get(obs["type"], type_styles["info"])
        obs_items.append(html.Div([
            html.I(className=f"{obs['icon']}", style={
                "color": st["icon_color"], "fontSize": "12px", "marginTop": "2px", "flexShrink": "0"
            }),
            html.Span(_parse_bold(obs["text"]), style={"fontSize": "12px", "color": "#374151", "lineHeight": "1.5"}),
        ], className="insight-obs-item", style={
            "background": st["bg"],
            "borderLeft": f"3px solid {st['border']}",
        }))

    if not obs_items:
        obs_items = [html.Div([
            html.I(className="fas fa-check-circle", style={
                "color": "#3b6d11", "fontSize": "12px", "marginTop": "2px", "flexShrink": "0"
            }),
            html.Span("No se detectaron anomalías significativas para este modo de falla.",
                       style={"fontSize": "12px", "color": "#374151"}),
        ], className="insight-obs-item", style={
            "background": "#eaf3de", "borderLeft": "3px solid #1d9e75",
        })]

    return html.Div([
        # ── Header
        html.Div([
            html.Div([
                html.I(className="fas fa-robot", style={"fontSize": "18px", "color": "#7C3AED"}),
            ], className="insight-icon-wrapper"),
            html.Div([
                html.Span("Análisis Inteligente", style={
                    "fontSize": "14px", "fontWeight": "600", "color": "#374151"
                }),
                html.Span(f" — {label}", style={
                    "fontSize": "14px", "fontWeight": "400", "color": "#6B7280"
                }),
            ]),
        ], className="insight-header"),

        # ── Methodology: what is analyzed
        html.Div([
            html.Div([
                html.I(className="fas fa-search", style={"color": "#7C3AED", "fontSize": "11px"}),
                html.Span("¿Qué se analiza?", className="insight-section-label",
                           style={"color": "#7C3AED"}),
            ], style={"display": "flex", "alignItems": "center", "gap": "6px", "marginBottom": "6px"}),
            html.P([
                f"Este modo de falla se detecta monitoreando: ",
                html.Strong(vars_text), "."
            ], style={"fontSize": "12px", "color": "#4B5563", "lineHeight": "1.5", "margin": "0 0 4px 0"}),
            html.P(methodology, style={
                "fontSize": "12px", "color": "#6B7280", "lineHeight": "1.5",
                "margin": "0", "fontStyle": "italic"
            }) if methodology else None,
        ], className="insight-section", style={
            "background": "#F5F3FF", "borderLeft": "3px solid #7C3AED"
        }),

        # ── Score result
        html.Div([
            html.Div([
                html.I(className="fas fa-gauge-high", style={"color": score_color, "fontSize": "11px"}),
                html.Span("Resultado", className="insight-section-label",
                           style={"color": score_color}),
            ], style={"display": "flex", "alignItems": "center", "gap": "6px", "marginBottom": "6px"}),
            html.P([
                "La unidad ",
                html.Strong(unit),
                " tiene un puntaje de ",
                html.Strong(f"{score:.1f}/100", style={"color": score_color}),
                f" (riesgo {score_level}) para {label}."
            ], style={"fontSize": "12px", "color": "#374151", "lineHeight": "1.5", "margin": "0"}),
        ], className="insight-section", style={
            "background": "#F9FAFB", "borderLeft": f"3px solid {score_color}"
        }),

        # ── Observations
        html.Div([
            html.Div([
                html.I(className="fas fa-clipboard-list", style={"color": "#374151", "fontSize": "11px"}),
                html.Span(f"Observaciones — últimos {n_days} días", className="insight-section-label",
                           style={"color": "#374151"}),
            ], style={"display": "flex", "alignItems": "center", "gap": "6px", "marginBottom": "10px"}),
            html.Div(obs_items),
        ]),

    ], className="insight-panel")


# ── Render functions (called by callbacks) ────────────────────────────────────

def render_initial_content(unit, df, df_latest, component="motor", client=None):
    """Render KPIs and fleet comparison for a unit."""
    failure_modes = get_failure_modes_dict(component, client)

    latest = df_latest.copy()
    # Status classification (fixed thresholds)
    latest["status"] = "Saludable"
    latest.loc[
        (latest["avg_ranking_30d"] >= 30) | (latest["max_fm_30d"] >= 50),
        "status",
    ] = "Alerta"
    latest.loc[
        (latest["avg_ranking_30d"] >= 60) | (latest["max_fm_30d"] >= 80),
        "status",
    ] = "Crítica"

    STATUS_COLORS = {"Crítica": "#e24b4a", "Alerta": "#ef9f27", "Saludable": "#1d9e75"}

    if not unit or unit not in df["Unit"].values:
        return html.Div(html.P("No hay datos disponibles.", className="text-muted text-center", style={"padding": "40px"}))

    row = latest[latest["Unit"] == unit]
    if row.empty:
        return html.Div(html.P("No hay datos disponibles.", className="text-muted text-center", style={"padding": "40px"}))
    row = row.iloc[0]

    # Dominant failure mode (use 30d averages for consistency)
    fm_keys = list(failure_modes.keys())
    fm_scores = {k: float(row[f"{k}_30d"]) if f"{k}_30d" in row.index and pd.notna(row[f"{k}_30d"]) else 0.0 for k in fm_keys}
    dominant_mode = max(fm_scores, key=fm_scores.get) if fm_scores else fm_keys[0]
    dominant_label = failure_modes[dominant_mode]

    # KPIs
    ranking_val = float(row["ranking"])
    ranking_90d_val = float(row.get("ranking_acum_90d", 0))

    df_unit = df[df["Unit"] == unit].sort_values("Fecha")
    last_evidence_date = df_unit["Fecha"].max() if not df_unit.empty else None
    last_date_str = last_evidence_date.strftime("%d %b %Y") if last_evidence_date is not None else "—"

    # ── Load component horómetro at last evidence date ──
    horometro_value = "—"
    horometro_sub = "horas acumuladas del componente"
    if client and last_evidence_date is not None:
        try:
            from config.settings import get_settings as _get_settings
            from src.data.loaders import load_component_hours
            import re as _re
            _settings = _get_settings()
            allowed = [c.upper() for c in _settings.component_hours_allowed_clients]
            if client.upper() in allowed:
                comp_hours_file = _settings.get_component_hours_path(client.lower())
                if comp_hours_file.exists():
                    all_hours = load_component_hours(comp_hours_file)
                    if not all_hours.empty:
                        # Normalize unit IDs for matching (T_09 vs T_9)
                        def _normalize_unit(uid):
                            m = _re.match(r'^([A-Za-z]+_)0*(\d+)$', str(uid))
                            return f"{m.group(1)}{m.group(2)}" if m else str(uid)

                        unit_norm = _normalize_unit(unit)
                        all_hours['_unitId_norm'] = all_hours['unitId'].apply(_normalize_unit)

                        # Filter by normalized unit and component
                        unit_comp_hours = all_hours[
                            (all_hours['_unitId_norm'] == unit_norm) &
                            (all_hours['componentName'] == component)
                        ].copy()

                        if not unit_comp_hours.empty:
                            # Find reading closest to last evidence date
                            unit_comp_hours['date_diff'] = abs(
                                unit_comp_hours['sampleDate'] - last_evidence_date
                            )
                            closest = unit_comp_hours.sort_values('date_diff').iloc[0]
                            hrs = closest['componentHours_cleaned']
                            date_val = closest['sampleDate']
                            if pd.notna(hrs):
                                horometro_value = f"{hrs:,.0f}"
                            if pd.notna(date_val):
                                horometro_sub = f"al {pd.to_datetime(date_val).strftime('%d %b %Y')}"
                        else:
                            logger.info(f"No component hours found for unit={unit} (norm={unit_norm}), component={component}")
        except Exception as e:
            logger.warning(f"Could not load component hours for KPI: {e}")

    component_label = (component or "").title()

    kpis = [
        _kpi_card("Ranking actual", f"{ranking_val:.0f}", _ranking_color(ranking_val), "escala 0-100"),
        _kpi_card("Riesgo acum. 90d", f"{ranking_90d_val:.1f}", _ranking_color(ranking_90d_val), "índice histórico"),
        _kpi_card(f"Horas del {component_label}", horometro_value, "#0891B2", horometro_sub),
        _kpi_card("Modo dominante", dominant_label, "#7C3AED", f"Score: {fm_scores[dominant_mode]:.1f}"),
        _kpi_card("Última evidencia", last_date_str, "#6B7280", "fecha más reciente"),
    ]

    # Fleet charts
    scatter_fig = create_fleet_scatter(latest, unit, STATUS_COLORS, 30.0)
    bar_fig = create_comparative_bars(row, latest, failure_modes)

    # AI analysis (analisis_inteligente.parquet) for the selected unit
    ai_row = _get_unit_ai_analysis(load_analisis_inteligente(client), unit) if client else None
    ai_section = (
        html.Div(
            create_ai_analysis_panel(
                ai_row.get("diagnostico"),
                ai_row.get("causa_probable"),
                ai_row.get("acciones"),
            ),
            style={"marginBottom": "1.5rem"},
        )
        if ai_row is not None else html.Div()
    )

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

        # AI analysis
        ai_section,

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


def render_detailed_evidence(unit, df, df_latest, failure_mode, component="motor", client="cda"):
    """Render oil and telemetry evidence for a unit and failure mode."""
    oil_labels, telem_labels, oil_limits_four = _resolve_client_dicts(client, component)
    failure_modes = get_failure_modes_dict(component, client)

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
    oil_vars = get_oil_variables_for_mode(failure_mode, component, client)
    oil_subtitle = f"Variables asociadas a {selected_label}"

    # Build oil variable options for the selector (all associated vars, pre-selected)
    oil_var_options = [{"label": oil_labels.get(v, v), "value": v} for v in oil_vars if v in df_unit.columns]
    oil_var_defaults = [v for v in oil_vars if v in df_unit.columns]

    # Get oil range for threshold display
    oil_range_val = "LT_1000"
    if oil_vars and not df_unit.empty:
        df_sorted_oil = df_unit.sort_values(_oil_date_col(df_unit))
        last_sample = df_sorted_oil.iloc[-1]
        oil_range_val = last_sample.get("oilHourRange", "LT_1000")

    # Oil variables table (static, always shows all vars for the mode)
    if oil_vars and not df_unit.empty:
        oil_table = create_oil_variables_table(df_unit, oil_vars, oil_labels, oil_limits_four)
    else:
        oil_table = html.Div()

    # Telemetry evidence
    telem_signals = get_telemetry_signals_for_mode(failure_mode, component, client)
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
            fig = create_telemetry_signal_chart(df_unit_90d, signal, telem_labels)
            if fig:
                charts.append(html.Div([dcc.Graph(figure=fig, config={"displayModeBar": False})], style={"marginBottom": "20px"}))
        telem_charts = html.Div(charts) if charts else html.P(
            "No hay alertas registradas en los últimos 90 días.", style={"color": "var(--text-muted)", "fontSize": "13px"})
    else:
        telem_charts = html.P("Este modo de falla no tiene señales de telemetría asociadas.",
                              style={"color": "var(--text-muted)", "fontSize": "13px"})
        window_text = ""

    # Generate AI insight
    insight = _generate_insight_data(unit, df_unit, df_latest, failure_mode, component, client)

    return html.Div([
        # AI Insight panel
        _build_insight_panel(insight),

        # Oil evidence
        html.Div([
            html.Div([
                html.H4([html.I(className="fas fa-oil-can me-2"), "Evidencia Tribológica"],
                        className="text-primary mb-3 mt-4 pb-2 border-bottom"),
                html.P(oil_subtitle, className="text-muted mb-3"),
            ]),
            # Oil variable selector
            html.Div([
                html.Div([
                    html.I(className="fas fa-filter me-2", style={"color": "#0891B2"}),
                    html.Span("Variables de aceite:", className="fw-500", style={"fontSize": "13px"}),
                ], style={"display": "flex", "alignItems": "center", "marginBottom": "8px"}),
                dcc.Dropdown(
                    id="predictive-oil-var-selector",
                    options=oil_var_options,
                    value=oil_var_defaults,
                    multi=True,
                    placeholder="Seleccionar variables de aceite...",
                    className="mb-3",
                    style={"fontSize": "13px"},
                ),
                html.P([
                    html.I(className="fas fa-info-circle me-1"),
                    "Si seleccionas 1 sola variable, se muestran sus límites disponibles."
                ], className="text-muted", style={"fontSize": "11px", "fontStyle": "italic", "marginBottom": "12px"}),
            ], style={"marginBottom": "8px"}),
            # Hidden stores for oil chart callback
            dcc.Store(id="predictive-oil-range-store", data=oil_range_val),
            html.Span([html.I(className="fas fa-calendar-alt me-1"), "Ventana: últimos 90 días"],
                      className="text-muted", style={"fontSize": "11px", "display": "inline-block", "marginBottom": "8px"}),
            # Dynamic oil chart (updated by callback)
            html.Div(id="predictive-oil-chart-container", style={"marginBottom": "24px"}),
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
    df, df_latest = _load_component_data(filepath, component, client)
    units = sorted(df["Unit"].unique()) if df is not None else []
    failure_mode_options = get_failure_mode_options(component, client)

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