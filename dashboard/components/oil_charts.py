"""
Shared oil time-series chart grid builder.

Used by both the Monitoring > Oil > Details time-series analysis section
(dashboard/callbacks/reports_callbacks.py) and the Alerts > Detail > Oil
Evidence "Tendencia" view (dashboard/callbacks/alerts_callbacks.py), so both
views render from the same chart-generation logic, variable combinations and
limits.

Limits are sourced from the four-limit Stewart output (stewart_limits_four.parquet,
data contract v2.8: LIC/LIM/LSM/LSC) rather than the legacy three-limit
stewart_limits.parquet/stewart_limits_inferior.parquet pair. Whether a lower
limit line is drawn for a given essay is decided per-essay from the data
(LIC/LIM both present) rather than from a fixed per-chart flag, since the new
contract nulls LIC/LIM for whole essay groups (Desgaste, Aditivo).
"""

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import dash_bootstrap_components as dbc
from dash import html, dcc


# Standard oil analysis chart pairings for the time-series grid.
TIME_SERIES_CHARTS = [
    {'title': 'Hierro & PQ', 'essays': ['Hierro', 'Índice PQ']},
    {'title': 'Cobre & Estaño', 'essays': ['Cobre', 'Estaño']},
    {'title': 'Cromo & Plomo', 'essays': ['Cromo', 'Plomo']},
    {'title': 'Silicio & Aluminio', 'essays': ['Silicio', 'Aluminio']},
    {'title': 'Sodio & Potasio', 'essays': ['Sodio', 'Potasio']},
    {'title': 'Combustible & Agua', 'essays': ['Combustible', 'Agua']},
    {'title': 'Viscocidad', 'essays': ['Viscocidad']},
    {'title': 'Hollín & Oxidación', 'essays': ['Hollín', 'Oxidación']},
]

# Colorblind-safe palette for the "Paquete de Aditivos" chart, which can plot
# more essays than the 2-color palette used by the other paired charts.
ADITIVOS_PALETTE = [
    '#0072B2', '#009E73', '#56B4E9', '#332288',
    '#44AA99', '#88CCEE', '#117733', '#999933',
]


# Severity order (worst first) and badge-color mapping for the five-tier
# four-limit classification (data contract v2.8).
FOUR_LIMIT_STATUS_ORDER = {
    'Inferior Condenatorio': 0,
    'Superior Condenatorio': 0,
    'Inferior Marginal': 1,
    'Superior Marginal': 1,
    'Normal': 2,
}

FOUR_LIMIT_STATUS_COLORS = {
    'Normal': 'success',
    'Inferior Marginal': 'warning',
    'Superior Marginal': 'warning',
    'Inferior Condenatorio': 'danger',
    'Superior Condenatorio': 'danger',
}

FOUR_LIMIT_STATUS_HEX_COLORS = {
    'Normal': '#28a745',
    'Inferior Marginal': '#ffc107',
    'Superior Marginal': '#ffc107',
    'Inferior Condenatorio': '#dc3545',
    'Superior Condenatorio': '#dc3545',
}


def get_essay_limits_four(comp_limits_four, essay, oil_hour_range):
    """
    Get four-limit (LIC/LIM/LSM/LSC) essay limits with oil-hour stratification
    fallback logic (data contract v2.8).

    Fallback hierarchy:
    1. Try exact match: oilHourRange from sample
    2. Try 'ALL'
    3. Try averaging across all available oil hour ranges
    4. Return None if essay not found

    Args:
        comp_limits_four: Nested dict {essay: {oilHourRange: {LIC, LIM, LSM, LSC, ...}}}
        essay: Essay name
        oil_hour_range: Oil hour range from sample ('LT_1000', 'GE_1000', 'UNKNOWN')

    Returns:
        Dict with LIC, LIM, LSM, LSC (LIC/LIM may be None) or None if not found.
    """
    if not comp_limits_four or essay not in comp_limits_four:
        return None

    essay_limits = comp_limits_four[essay]
    if not essay_limits:
        return None

    if oil_hour_range in essay_limits:
        return essay_limits[oil_hour_range]

    if 'ALL' in essay_limits:
        return essay_limits['ALL']

    available_ranges = list(essay_limits.keys())
    if not available_ranges:
        return None

    def _avg(field):
        # Never treat a missing (null) lower limit as zero: average only over
        # the buckets where this field is actually present.
        values = [essay_limits[r][field] for r in available_ranges if essay_limits[r].get(field) is not None]
        return sum(values) / len(values) if values else None

    return {
        'LIC': _avg('LIC'),
        'LIM': _avg('LIM'),
        'LSM': _avg('LSM'),
        'LSC': _avg('LSC'),
    }


def classify_four_limit_value(value: float, LIC, LIM, LSM: float, LSC: float) -> str:
    """
    Classify a value against the four-limit Stewart output (data contract v2.8).

    Boundary semantics (must match the main service exactly):
        value < LIC            -> Inferior Condenatorio
        LIC <= value < LIM      -> Inferior Marginal
        LIM <= value <= LSM     -> Normal
        LSM < value <= LSC      -> Superior Marginal
        value > LSC             -> Superior Condenatorio

    Lower-limit evaluation is only applied when BOTH LIC and LIM are available
    (a null lower limit is never treated as a lower limit of zero). Otherwise:
        value <= LSM            -> Normal
        LSM < value <= LSC      -> Superior Marginal
        value > LSC             -> Superior Condenatorio
    """
    has_lower = LIC is not None and LIM is not None
    if has_lower:
        if value < LIC:
            return 'Inferior Condenatorio'
        if value < LIM:
            return 'Inferior Marginal'
    if value <= LSM:
        return 'Normal'
    if value <= LSC:
        return 'Superior Marginal'
    return 'Superior Condenatorio'


def build_oil_time_series_grid(history: pd.DataFrame, comp_limits_four: dict, oil_hour_range: str):
    """
    Build the 9-chart oil analysis time-series grid.

    Args:
        history: Pre-filtered, pre-sorted (by sampleDate ascending) rows for a
            single equipment/component pair, from the classified oil reports
            (golden/{client}/classified.parquet schema).
        comp_limits_four: Four-limit (LIC/LIM/LSM/LSC) Stewart limits for this
            component, as returned by
            load_stewart_limits_four(...)[client][machine][component]. May be
            an empty dict if unavailable.
        oil_hour_range: oilHourRange of the most recent sample in `history`,
            used for stratified limit lookup via get_essay_limits_four.

    Returns:
        A dbc.Row of chart columns, or an html.P placeholder if there is
        nothing to plot.
    """
    if history.empty:
        return html.P("Sin historial para este equipo/componente", className="text-muted")

    # Discover all "Aditivo" essays from the essays mapping table and build the
    # "Paquete de Aditivos" charts for this render. Split into two side-by-side
    # charts (same 2-column layout as the pairs above) so the lines stay readable.
    charts_to_render = list(TIME_SERIES_CHARTS)
    essays_file = Path("data/oil/essays_elements.xlsx")
    if essays_file.exists():
        essays_df = pd.read_excel(essays_file)
        essays_df = essays_df.dropna(subset=['ElementNameSpanish', 'GroupElement'])
        aditivo_essays = essays_df[essays_df['GroupElement'] == 'Aditivo']['ElementNameSpanish'].tolist()
        if aditivo_essays:
            primary_aditivos = [e for e in ['Calcio', 'Zinc', 'Fósforo'] if e in aditivo_essays]
            other_aditivos = [e for e in aditivo_essays if e not in primary_aditivos]
            if primary_aditivos:
                charts_to_render.append({
                    'title': 'Aditivos: Calcio, Zinc & Fósforo',
                    'essays': primary_aditivos,
                    'palette': ADITIVOS_PALETTE,
                })
            if other_aditivos:
                charts_to_render.append({
                    'title': 'Aditivos: Otros',
                    'essays': other_aditivos,
                    'palette': ADITIVOS_PALETTE,
                })

    # Generate charts in a 2-column grid, with any full-width charts spanning both columns
    chart_elements = []
    for chart_config in charts_to_render:
        essays = chart_config['essays']
        title = chart_config['title']
        is_full_width = chart_config.get('full_width', False)
        col_width = 12 if is_full_width else 6

        # Check if any essay has data
        available_essays = [e for e in essays if e in history.columns and history[e].notna().any()]
        if not available_essays:
            # Show empty placeholder
            chart_elements.append(
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H6(title, className="text-muted text-center mb-2", style={'fontSize': '0.85rem'}),
                            html.P("Sin datos", className="text-muted text-center small")
                        ])
                    ], className="h-100")
                ], md=col_width, className="mb-3")
            )
            continue

        # Create figure
        fig = go.Figure()
        colors = chart_config.get('palette', ['#1f77b4', '#ff7f0e'])

        # Collect limits for deduplication
        limit_entries = []  # [(value, essay_name), ...]  -- upper (LSC)
        limit_entries_lower = []  # [(value, essay_name), ...]  -- lower (LIC), only when available

        for idx, essay in enumerate(available_essays):
            essay_values = history[essay].dropna()
            if essay_values.empty:
                continue
            essay_dates = history.loc[essay_values.index, 'sampleDate']

            fig.add_trace(go.Scatter(
                x=essay_dates,
                y=essay_values,
                mode='lines+markers',
                name=essay,
                line=dict(color=colors[idx % len(colors)], width=2),
                marker=dict(size=4),
            ))

            # Collect upper condemnation limit (LSC) - always available
            essay_limits = get_essay_limits_four(comp_limits_four, essay, oil_hour_range)
            if essay_limits and essay_limits.get('LSC') is not None:
                limit_entries.append((essay_limits['LSC'], essay))

            # Collect lower condemnation limit (LIC) - only draw when BOTH LIC
            # and LIM are available; never render a lower-limit trace for
            # essay groups where the contract nulls out lower limits
            # (Desgaste, Aditivo) or where min_value <= 0.
            if essay_limits and essay_limits.get('LIC') is not None and essay_limits.get('LIM') is not None:
                limit_entries_lower.append((essay_limits['LIC'], essay))

        # Consolidate duplicate limits (same value → one line, combined label)
        limit_by_value = {}
        for val, name in limit_entries:
            rounded_val = round(val, 2)
            limit_by_value.setdefault(rounded_val, []).append(name)

        for val, names in limit_by_value.items():
            if len(names) > 1:
                label = " y ".join(names) + " LSC"
            else:
                label = f"{names[0]} LSC" if len(available_essays) > 1 else "LSC"
            fig.add_hline(
                y=val,
                line=dict(color='#dc3545', width=1.5, dash='dash'),
                annotation_text=label,
                annotation_position="top right",
                annotation_font=dict(size=8, color='#dc3545'),
            )

        # Consolidate duplicate lower limits the same way
        limit_by_value_lower = {}
        for val, name in limit_entries_lower:
            rounded_val = round(val, 2)
            limit_by_value_lower.setdefault(rounded_val, []).append(name)

        for val, names in limit_by_value_lower.items():
            if len(names) > 1:
                label = " y ".join(names) + " LIC"
            else:
                label = f"{names[0]} LIC" if len(available_essays) > 1 else "LIC"
            fig.add_hline(
                y=val,
                line=dict(color='#0072B2', width=1.5, dash='dash'),
                annotation_text=label,
                annotation_position="bottom right",
                annotation_font=dict(size=8, color='#0072B2'),
            )

        fig.update_layout(
            title=dict(text=title, font=dict(size=12), x=0.5, xanchor='center'),
            height=280 if is_full_width else 220,
            margin=dict(l=40, r=15, t=35, b=30),
            showlegend=True,
            legend=dict(
                orientation='h', yanchor='bottom', y=-0.35,
                xanchor='center', x=0.5, font=dict(size=9)
            ),
            xaxis=dict(tickfont=dict(size=9)),
            yaxis=dict(tickfont=dict(size=9)),
            hovermode='x unified',
            plot_bgcolor='white',
            paper_bgcolor='white'
        )
        fig.update_xaxes(showgrid=True, gridwidth=1, gridcolor='#f0f0f0')
        fig.update_yaxes(showgrid=True, gridwidth=1, gridcolor='#f0f0f0')

        chart_elements.append(
            dbc.Col([
                dcc.Graph(figure=fig, config={'displayModeBar': False})
            ], md=col_width, className="mb-3")
        )

    if not chart_elements:
        return html.P("Sin datos de ensayos disponibles", className="text-muted")

    return dbc.Row(chart_elements)
