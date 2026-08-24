"""
Predictive Overview Tab - Fleet status, KPIs, priority cards, failure mode table.
Supports multi-component model: auto-discovers component CSVs (motor, transmision, etc.)
"""

from dash import html, dcc
import pandas as pd
import os
import re
from functools import lru_cache
from pathlib import Path
from config.settings import get_settings
from src.utils.logger import get_logger
from dashboard.components.predictive_config import (
    get_failure_modes_for_component,
    get_failure_modes_dict,
)
from dashboard.components.predictive_kpis import create_kpi_card, create_kpi_row
from dashboard.components.accumulated_curve import (
    render_accumulated_section,
    build_accumulated_data,
    build_accumulated_figure,
    _empty_state as _accumulated_empty_state,
)
from src.data.loaders import get_latest_analisis_inteligente, get_model_run_date
from src.data.catalog import dashboard_data_root
from src.data.fast_io import read_csv as fast_read_csv
from dashboard.components.labels import NO_DATA_BG, NO_DATA_TEXT

logger = get_logger(__name__)


# ── Data Loading (Multi-Component) ────────────────────────────────────────────

@lru_cache(maxsize=16)
def _discover_components_cached(client: str, data_dir: str, directory_mtime_ns: int) -> dict:
    """Cache component discovery until the directory generation changes."""

    data_path = Path(data_dir)
    if not data_path.exists():
        return {}

    components = {}
    for fname in sorted(os.listdir(data_path)):
        if fname.endswith(".csv"):
            component_name = fname.replace(".csv", "")
            components[component_name] = data_path / fname
    return components


def _discover_components(client: str) -> dict:
    """Auto-discover available component CSV files for a client.

    The cache key includes the directory mtime so a newly materialized
    component becomes visible without restarting the worker.
    """
    data_dir = dashboard_data_root() / "predictive" / "golden" / client.lower()

    if not data_dir.exists():
        return {}
    try:
        directory_mtime_ns = data_dir.stat().st_mtime_ns
    except OSError:
        return {}
    return _discover_components_cached(client.lower(), str(data_dir), directory_mtime_ns)


@lru_cache(maxsize=16)
def _load_component_data_cached(
    filepath: str,
    component: str,
    client: str,
    mtime_ns: int,
    size: int,
):
    """Load and precompute predictive data for a single component.

    Cached per (filepath, component, client): this CSV can be 20+MB and the
    rolling-window computation below isn't cheap, so re-parsing it on every
    callback firing (filter change, tab switch) is wasted work. Cache clears
    on process restart, matching the data-refresh boundary already used for
    the other client-keyed loaders in src/data/loaders.py. The only current
    caller treats the returned DataFrames as read-only (copies before any
    mutation) — any future caller that needs to mutate df/df_latest must copy
    first, since these objects are shared across calls.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        logger.warning(f"Predictive data not found: {filepath}")
        return None, None, {}

    df = fast_read_csv(filepath)
    df["Fecha"] = pd.to_datetime(df["Fecha"])
    df = df.copy()  # defragment after column assignment

    # Get component-specific failure modes
    failure_modes = get_failure_modes_dict(component, client)
    fm_keys = list(failure_modes.keys())
    score_cols = [c for c in fm_keys if c in df.columns] + ["ranking"]

    # Sort once by Unit+Fecha. Every per-unit "last row" / rolling computation
    # below reuses this ordering instead of re-sorting the full frame again —
    # each Unit's rows are already chronological within their block, which is
    # all groupby("Unit").last()/rolling() need.
    df_sorted = df.sort_values(["Unit", "Fecha"]).copy()

    # Latest snapshot per unit
    df_latest = df_sorted.groupby("Unit").last().reset_index()

    # Rolling averages - compute all at once to avoid fragmentation
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

    # Get latest rolling values (df_sorted is still Unit+Fecha ordered here —
    # concat above doesn't reorder rows, so no re-sort is needed)
    latest_rolling = df_sorted.groupby("Unit").last().reset_index()

    # Merge rolling into df_latest (all at once to avoid fragmentation)
    new_cols = {}
    new_cols["avg_ranking_30d"] = latest_rolling["ranking_30d"].values if "ranking_30d" in latest_rolling.columns else df_latest["ranking"].values
    new_cols["avg_ranking_60d"] = latest_rolling["ranking_60d"].values if "ranking_60d" in latest_rolling.columns else df_latest["ranking"].values
    new_cols["ranking_acum_90d"] = latest_rolling["ranking_90d"].values if "ranking_90d" in latest_rolling.columns else df_latest["ranking"].values

    # Compute max failure mode 30d average per unit (for status classification)
    fm_30d_cols = [f"{col}_30d" for col in fm_keys if f"{col}_30d" in latest_rolling.columns]
    if fm_30d_cols:
        new_cols["max_fm_30d"] = latest_rolling[fm_30d_cols].max(axis=1).values
        # Also merge individual FM rolling columns (30d, 60d, 90d) for display
        for col in fm_keys:
            for suffix in ["_30d", "_60d", "_90d"]:
                col_name = f"{col}{suffix}"
                if col_name in latest_rolling.columns:
                    new_cols[col_name] = latest_rolling[col_name].values
    else:
        new_cols["max_fm_30d"] = 0.0

    df_latest = df_latest.assign(**new_cols)

    # Previous ranking (second-to-last date)
    dates = sorted(df["Fecha"].unique())
    prev_ranking = {}
    if len(dates) >= 2:
        prev_date = dates[-2]
        df_prev = df[df["Fecha"] == prev_date]
        prev_ranking = dict(zip(df_prev["Unit"], df_prev["ranking"]))

    return df, df_latest, prev_ranking


def _load_component_data(filepath: Path, component: str, client: str = "cda"):
    """Load a predictive component with invalidation on file generation."""
    filepath = Path(filepath)
    if not filepath.exists():
        return None, None, {}
    stat = filepath.stat()
    result = _load_component_data_cached(
        str(filepath), component, client, stat.st_mtime_ns, stat.st_size
    )
    # The cached frames are treated as immutable by the presentation layer.
    # Avoid copying tens of MB when Resumen and Evidencia mount together.
    return result[0], result[1], result[2]


# ── Color helpers ─────────────────────────────────────────────────────────────

def _status_colors(status: str) -> dict:
    return {
        "Anormal": {"border": "#e24b4a", "bg": "#fcebeb", "text": "#a32d2d"},
        "Alerta":  {"border": "#ef9f27", "bg": "#faeeda", "text": "#854f0b"},
        "Normal":  {"border": "#1d9e75", "bg": "#eaf3de", "text": "#3b6d11"},
    }.get(status, {"border": "#888", "bg": "#f0f0f0", "text": "#444"})


# Group order for priority cards: Anormal, then Alerta, then Normal (REQ-PR-07)
_STATUS_RANK = {"Anormal": 0, "Alerta": 1, "Normal": 2}

# Section header text above each status group (REQ-PR-11)
_STATUS_GROUP_LABELS = {
    "Anormal": "Unidades Anormales",
    "Alerta": "Unidades Alerta",
    "Normal": "Unidades Normales",
}


def _normalize_unit_id(uid) -> str:
    """T_09 -> T_9. Component CSVs zero-pad unit ids; analisis_inteligente.parquet
    doesn't, so lookups against it must normalize both sides first."""
    m = re.match(r"^([A-Za-z]+_)0*(\d+)$", str(uid))
    return f"{m.group(1)}{m.group(2)}" if m else str(uid)


def attach_status(latest: pd.DataFrame, client: str, component: str) -> pd.DataFrame:
    """Attach `estado` from analisis_inteligente.parquet as `status` (REQ-PR-04).

    Units with no analisis_inteligente row (e.g. not yet scored) default to
    "Normal" so only the three file-defined labels ever appear (REQ-PR-05).
    """
    latest = latest.copy()
    ai_latest = get_latest_analisis_inteligente(client, component) if client else pd.DataFrame()
    if not ai_latest.empty and "estado" in ai_latest.columns:
        # Title-case the raw value: the file's casing isn't guaranteed (seen as
        # both "Normal" and "normal"), but status/color/sort lookups below key
        # off the exact capitalized labels "Normal"/"Alerta"/"Anormal".
        estado_map = {
            _normalize_unit_id(u): str(e).strip().title()
            for u, e in zip(ai_latest["Unit"], ai_latest["estado"])
        }
    else:
        estado_map = {}
    latest["status"] = latest["Unit"].apply(
        lambda u: estado_map.get(_normalize_unit_id(u), "Normal")
    )
    latest["_status_rank"] = latest["status"].map(_STATUS_RANK).fillna(3)
    return latest


def _score_cell_style(value) -> dict:
    """Cell style for a ranking/score value. `None`/NaN get their own
    neutral style (W34-10) — a missing value must never look like the
    healthiest possible score, which is what green at 0 read as before."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        # Same shared NO_DATA_* tokens the Estado x Unidad and Estado de
        # Datos tables' "no data" badges use (dashboard/components/labels.py)
        # — quality-review follow-up: this used to be its own independent
        # literal, a third copy of the same two values kept in sync only by
        # a comment.
        return {"background": NO_DATA_BG, "text": NO_DATA_TEXT}
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


def _priority_card(unit, score, acum_30d, delta, status, drivers, horometro_text="—"):
    colors = _status_colors(status)

    # W34-10: a unit with no computed ranking yet must not render the literal
    # text "nan"/"+nan" — found during visual QA, same "missing is not zero"
    # gap this improvement already closed in the failure-mode table.
    acum_headline_text = f"{acum_30d:.0f}" if pd.notna(acum_30d) else "—"
    score_recent_text = f"Reciente: {score:.1f}" if pd.notna(score) else "Reciente: —"

    if pd.isna(delta):
        delta_cls, delta_txt = "delta-badge delta-neu", "—"
    elif delta > 1:
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
            html.Span(acum_headline_text, className="pc-score"),
        ], className="pc-score-row"),
        html.Div([
            html.Span([
                html.Span(score_recent_text, className="pc-acum"),
                html.Span(delta_txt, className=delta_cls, style={"marginLeft": "6px"}),
            ], style={"display": "inline-flex", "alignItems": "center"}),
            html.Span([
                html.I(className="fas fa-clock", style={"fontSize": "10px", "marginRight": "4px", "opacity": "0.7"}),
                horometro_text,
            ], style={
                "fontSize": "11px", "color": "#0891B2", "fontWeight": "600",
                "display": "inline-flex", "alignItems": "center",
            }),
        ], style={"display": "flex", "justifyContent": "space-between", "alignItems": "center", "marginBottom": "8px"}),
        html.Div("Factores principales", className="drivers-label"),
        *[_driver_bar(name, val) for name, val in drivers],
    ], className="priority-card",
       style={"borderLeftColor": colors["border"]})


# Ranking window options for the bottom table's single ranking column (REQ-PR-09)
WINDOW_LABELS = {
    "ranking": "Hoy",
    "avg_ranking_30d": "Prom 30d",
    "avg_ranking_60d": "Prom 60d",
    "ranking_acum_90d": "Prom 90d",
}
WINDOW_SUFFIX = {
    "ranking": "",
    "avg_ranking_30d": "_30d",
    "avg_ranking_60d": "_60d",
    "ranking_acum_90d": "_90d",
}


def _failure_table(sorted_df, window, sort_by, ascending, failure_modes):
    """Bottom ranking table: one ranking column driven by `window`, plus one
    column per failure mode. `sort_by` is either `window` itself or a failure
    mode key - clicking a failure-mode header sorts by that column (REQ-PR-10)
    while the ranking column stays a single value driven by the window
    dropdown (REQ-PR-09, option ii).
    """
    fm_keys = list(failure_modes.keys())
    fm_labels = list(failure_modes.values())
    fm_suffix = WINDOW_SUFFIX.get(window, "_30d")

    def _arrow(is_active):
        return ("↑" if ascending else "↓") if is_active else ""

    def _th_label(label, is_active):
        return html.Div([
            html.Span(label),
            html.Span(_arrow(is_active), style={
                "marginLeft": "4px", "fontSize": "10px", "opacity": "0.6",
            }),
        ], style={"display": "flex", "alignItems": "center", "gap": "2px"})

    ranking_active = sort_by == window
    ranking_th = html.Th(
        _th_label(WINDOW_LABELS.get(window, "Prom 30d"), ranking_active),
        className="fm-th fm-th-active" if ranking_active else "fm-th",
    )

    def _fm_th(label, key):
        is_active = key == sort_by
        return html.Th(
            html.Button(
                _th_label(label, is_active),
                id={"type": "predictive-fm-col-header", "key": key},
                n_clicks=0,
                style={
                    "background": "none", "border": "none", "padding": 0, "margin": 0,
                    "font": "inherit", "color": "inherit", "cursor": "pointer", "width": "100%",
                },
            ),
            className="fm-th fm-th-active" if is_active else "fm-th",
        )

    header = html.Thead(html.Tr([
        html.Th("Unidad", className="fm-th fm-th-unit"),
        ranking_th,
        html.Th("Estado", className="fm-th"),  # W34-10: was "Status" (English)
        *[_fm_th(lbl, key) for key, lbl in zip(fm_keys, fm_labels)],
    ]))

    rows = []
    for _, r in sorted_df.iterrows():
        status = r["status"]
        colors = _status_colors(status)
        # W34-10: `pd.notna` before the cast, not a bare `.get(key, 0)` —
        # that only defaults when the KEY is absent, not when the row's
        # VALUE is NaN. A present-but-NaN ranking used to sail through as
        # the literal string "nan", styled green by _score_cell_style's old
        # fall-through. `None` here (never `0.0`) keeps the null
        # distinguishable all the way to render time.
        ranking_val = float(r[window]) if window in r.index and pd.notna(r[window]) else None

        style = _score_cell_style(ranking_val)
        cells = [
            html.Td(r["Unit"], className="fm-td fm-td-unit"),
            html.Td(
                f"{ranking_val:.1f}" if ranking_val is not None else "—",
                className="fm-td fm-td-score fm-td-active" if ranking_active else "fm-td fm-td-score",
                style={"background": style["background"], "color": style["text"],
                       "fontWeight": "600" if ranking_active else "500"},
            ),
            html.Td(
                html.Span(status, className="status-badge",
                          style={"background": colors["bg"], "color": colors["text"]}),
                className="fm-td",
            ),
        ]

        for key in fm_keys:
            col_name = f"{key}{fm_suffix}" if fm_suffix else key
            # W34-10: None (not 0.0) when the column is absent or the value
            # is NaN — a missing failure-mode score must not render "0" in
            # the same green a genuinely healthy 0 score gets.
            val = float(r[col_name]) if col_name in r.index and pd.notna(r[col_name]) else None
            fm_style = _score_cell_style(val)
            is_sort = key == sort_by
            cells.append(html.Td(
                f"{val:.0f}" if val is not None else "—",
                className="fm-td fm-td-score fm-td-active" if is_sort else "fm-td fm-td-score",
                style={"background": fm_style["background"], "color": fm_style["text"],
                       "fontWeight": "600" if is_sort else "500"},
            ))

        rows.append(html.Tr(cells, className="fm-tr"))

    return html.Div([
        html.Table([header, html.Tbody(rows)], className="fm-table"),
    ], className="fm-table-wrapper")


# ── Component Overview Renderer ───────────────────────────────────────────────

def _load_component_hours_if_available(client: str):
    """
    Carga el parquet de horas de componente SOLO si el archivo existe para
    este cliente, leyéndolo DIRECTAMENTE del disco (igual que el dashboard
    antiguo) para garantizar que la curva reciba exactamente los mismos datos.

    Ruta: data/oil/golden/<client>/cleaned_component_hours.parquet

    Devuelve el DataFrame de horas, o None si el archivo no existe / no se puede
    leer. None significa "este cliente no tiene datos de horas" → el overview
    usa el hero clásico y omite la curva acumulada.
    """
    if not client:
        return None
    try:
        settings = get_settings()
        # Ruta directa al parquet, misma que usaba el dashboard antiguo.
        hours_path = dashboard_data_root() / "oil" / "golden" / client.lower() / "cleaned_component_hours.parquet"
        if not hours_path.exists():
            return None

        df_hours = pd.read_parquet(hours_path)
        if df_hours is None or df_hours.empty:
            return None

        # La curva cruza por fecha; asegurar tipo datetime como en el antiguo.
        if "sampleDate" in df_hours.columns:
            df_hours["sampleDate"] = pd.to_datetime(df_hours["sampleDate"])

        return df_hours
    except Exception as exc:  # noqa: BLE001 - ante cualquier problema, sin curva
        logger.warning(f"No se pudieron cargar horas de componente para {client}: {exc}")
        return None


def _render_component_overview(df_latest, prev_ranking, component: str,
                              client: str = None, df=None):
    """
    Render overview content for a specific component.

    Status (Anormal / Alerta / Normal) comes from `estado` in
    analisis_inteligente.parquet for every client (REQ-PR-04/05) - there is a
    single hero regardless of whether component-hours data is available. The
    accumulated-risk curve, when buildable, is still shown as its own section
    further down the page; it no longer drives the hero's counts.

    Args:
        df: histórico completo del componente (Unit, Fecha, ranking, ...),
            necesario para construir la curva acumulada. Si es None, se omite.
    """
    failure_modes = get_failure_modes_dict(component, client)

    latest = attach_status(df_latest, client, component)
    avg_ranking = float(latest["ranking"].mean())

    counts = latest["status"].value_counts()
    n_anormal = counts.get("Anormal", 0)
    n_alert = counts.get("Alerta", 0)
    n_normal = counts.get("Normal", 0)

    model_run_date = get_model_run_date(client, component) if client else None
    model_run_date_str = model_run_date.strftime("%d %b %Y") if model_run_date is not None else "—"

    # ── Curva acumulada (solo si hay horas de componente) ──
    # Requiere el histórico completo (df) y que exista el parquet de horas para
    # este cliente; si algo falta, la sección se omite (no afecta el hero).
    df_component_hours = _load_component_hours_if_available(client)
    accumulated = None

    if df is not None and not df.empty and df_component_hours is not None:
        try:
            df_acum = build_accumulated_data(df, df_component_hours, component)
            if not df_acum.empty:
                _fig, _resumen = build_accumulated_figure(df_acum, component=component)
                if _fig is not None:
                    accumulated = render_accumulated_section(df, df_component_hours, component)
        except Exception as exc:  # noqa: BLE001 - la curva nunca rompe el overview
            logger.warning(f"No se pudo construir la curva acumulada para {client}/{component}: {exc}")
            accumulated = None

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
            create_kpi_card(n_anormal, "Unidades Anormales", "fas fa-exclamation-triangle", "danger"),
            create_kpi_card(n_alert, "Unidades en Alerta", "fas fa-exclamation-circle", "warning"),
            create_kpi_card(n_normal, "Unidades Normales", "fas fa-check-circle", "success"),
            create_kpi_card(model_run_date_str, "Fecha Ejecución Modelo", "fas fa-calendar-check", "info"),
        ])
    ])

    # Priority cards — load horómetro data
    import re as _re
    horometro_map = {}
    if client:
        try:
            from src.data.loaders import load_component_hours
            settings = get_settings()
            allowed = [c.upper() for c in settings.component_hours_allowed_clients]
            if client.upper() in allowed:
                comp_hours_file = settings.get_component_hours_path(client.lower())
                if comp_hours_file.exists():
                    all_hours = load_component_hours(comp_hours_file)
                    if not all_hours.empty:
                        def _norm_uid(uid):
                            m = _re.match(r'^([A-Za-z]+_)0*(\d+)$', str(uid))
                            return f"{m.group(1)}{m.group(2)}" if m else str(uid)

                        comp_hours = all_hours[all_hours['componentName'] == component].copy()
                        if not comp_hours.empty:
                            comp_hours['_uid_norm'] = comp_hours['unitId'].apply(_norm_uid)
                            idx = comp_hours.groupby('_uid_norm')['sampleDate'].idxmax()
                            latest_hours = comp_hours.loc[idx]
                            for _, row_h in latest_hours.iterrows():
                                uid = row_h['_uid_norm']
                                hrs = row_h['componentHours_cleaned']
                                if pd.notna(hrs):
                                    horometro_map[uid] = f"{hrs:,.0f} h"
        except Exception as e:
            logger.warning(f"Could not load component hours for overview cards: {e}")

    def _norm_uid_simple(uid):
        m = _re.match(r'^([A-Za-z]+_)0*(\d+)$', str(uid))
        return f"{m.group(1)}{m.group(2)}" if m else str(uid)

    cards_by_status = {"Anormal": [], "Alerta": [], "Normal": []}
    for _, r in latest.sort_values(["_status_rank", "avg_ranking_30d"], ascending=[True, False]).iterrows():
        score = r["ranking"]
        delta = score - prev_ranking.get(r["Unit"], score)
        drivers = sorted(
            [(failure_modes[c], float(r[f"{c}_30d"])) for c in failure_modes
             if f"{c}_30d" in r.index and pd.notna(r[f"{c}_30d"])],
            key=lambda x: x[1], reverse=True,
        )[:3]
        unit_norm = _norm_uid_simple(r["Unit"])
        horo_text = horometro_map.get(unit_norm, "—")
        card = _priority_card(
            unit=r["Unit"], score=score,
            acum_30d=float(r["avg_ranking_30d"]),
            delta=delta, status=r["status"], drivers=drivers,
            horometro_text=horo_text,
        )
        cards_by_status.setdefault(r["status"], []).append(card)

    # Section headers above each status group (REQ-PR-11) - groups with no
    # units are skipped rather than shown empty. Any status outside the three
    # known ones (shouldn't happen post attach_status, but don't silently
    # drop cards if it does) is appended after, rather than lost.
    known_statuses = ["Anormal", "Alerta", "Normal"]
    extra_statuses = [s for s in cards_by_status if s not in known_statuses]
    group_sections = []
    for status in known_statuses + extra_statuses:
        group_cards = cards_by_status.get(status, [])
        if not group_cards:
            continue
        colors = _status_colors(status)
        group_sections.append(html.Div([
            html.Div([
                html.Span(_STATUS_GROUP_LABELS.get(status, f"Unidades {status}"), style={
                    "fontWeight": "700", "fontSize": "13px", "color": colors["text"],
                    "textTransform": "uppercase", "letterSpacing": "0.04em",
                }),
                html.Span(f"({len(group_cards)})", style={
                    "fontSize": "12px", "color": "var(--text-light)", "marginLeft": "6px",
                }),
            ], style={
                "borderLeft": f"3px solid {colors['border']}",
                "paddingLeft": "10px", "margin": "18px 0 10px",
            }),
            html.Div(group_cards, className="priority-grid"),
        ]))

    priority = html.Div([
        html.Div([
            html.H4([
                html.I(className="fas fa-bullseye me-2"),
                "Estado Flota — Prioridad"
            ], className="text-primary mb-3 mt-4"),
            html.P("Agrupadas por estado (Anormal, Alerta, Normal) y ordenadas por promedio de ranking de 30 días",
                   className="text-muted mb-3"),
        ]),
        html.Div(group_sections),
    ])

    # Failure mode table
    # W34-10: "Unit" as a secondary key makes tie order deterministic across
    # renders — plain `sort_values` on one column falls back to an unstable
    # quicksort for ties, so two identical-input renders could otherwise show
    # tied units in a different order.
    sorted_df = latest.sort_values(["avg_ranking_30d", "Unit"], ascending=[False, True])
    table_section = html.Div([
        html.Div([
            html.Div([
                html.H4([
                    html.I(className="fas fa-table me-2"),
                    "Riesgo por Modo de Falla"
                ], className="text-primary mb-0"),
                html.Div([
                    html.Span("Ordenar por: ", className="text-muted me-2",
                              style={"fontSize": "0.85rem", "fontWeight": "500"}),
                    dcc.Dropdown(
                        id="predictive-fm-sort-selector",
                        options=[
                            {"label": "Hoy", "value": "ranking"},
                            {"label": "30 días", "value": "avg_ranking_30d"},
                            {"label": "60 días", "value": "avg_ranking_60d"},
                            {"label": "90 días", "value": "ranking_acum_90d"},
                        ],
                        value="avg_ranking_30d",
                        clearable=False,
                        style={"width": "140px", "fontSize": "0.85rem"},
                    ),
                ], style={"display": "flex", "alignItems": "center"}),
            ], style={
                "display": "flex", "justifyContent": "space-between",
                "alignItems": "center", "borderBottom": "1px solid #dee2e6",
                "paddingBottom": "12px", "marginBottom": "12px",
            }),
            html.P("Vista de modos de falla por unidad — ordenado de mayor a menor riesgo",
                   className="text-muted mb-3", style={"fontSize": "0.85rem"}),
        ]),
        html.Div(
            _failure_table(sorted_df, "avg_ranking_30d", "avg_ranking_30d", False, failure_modes),
            id="predictive-fm-table-container",
        ),
        dcc.Store(
            id="predictive-fm-table-state",
            data={"window": "avg_ranking_30d", "sort_by": "avg_ranking_30d", "ascending": False},
        ),
    ], className="card", style={"marginTop": "16px"})

    curve_content = accumulated if accumulated is not None else _accumulated_empty_state(
        "Curva acumulada no disponible: no hay datos de horómetro suficientes para este cliente/componente."
    )

    risk_section = html.Div([
        html.H4([
            html.I(className="fas fa-shield-alt me-2"),
            "Análisis de Riesgo"
        ], className="text-primary mb-3 mt-4"),
        dcc.Tabs(
            id='predictive-risk-view-selector',
            value='prioridad',
            children=[
                dcc.Tab(label='  Riesgo Acumulado', value='acumulado',
                        className='custom-tab', selected_className='custom-tab--selected'),
                dcc.Tab(label='  Prioridad Actual', value='prioridad',
                        className='custom-tab', selected_className='custom-tab--selected'),
            ],
            className='mb-3'
        ),
        html.Div(id='predictive-risk-curve-container', children=[curve_content],
                 style={'display': 'none'}),
        html.Div(id='predictive-risk-priority-container', children=[priority],
                 style={'display': 'block'}),
    ])

    children = [hero, risk_section, table_section]
    return html.Div(children)


# ── Component Icon Map ────────────────────────────────────────────────────────

COMPONENT_ICONS = {
    "motor": "fas fa-cog",
    "transmision": "fas fa-exchange-alt",
    "engine": "fas fa-cog",
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

    df, df_latest, prev_ranking = _load_component_data(filepath, component, client)

    if df_latest is None or df_latest.empty:
        return html.Div([
            html.Div([
                html.I(className="fas fa-brain me-3"),
                f"Predictivo — {component.title()} — Resumen"
            ], className="page-title", style={"display": "flex", "alignItems": "center"}),
            html.P(f"No hay datos disponibles para {component}.",
                   className="text-muted", style={"padding": "40px", "textAlign": "center"})
        ])

    return _render_component_overview(df_latest, prev_ranking, component, client)
