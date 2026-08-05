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

# ---------------------------------------------------------------------------
# User-friendly limit labels, equal/similar-value consolidation, and trace
# colors - shared by every oil time-series/radar visualization so none of this
# is duplicated (or drifts) per chart.
# ---------------------------------------------------------------------------

# Upper-limit line color (unchanged - existing "condemnation line" red).
UPPER_LIMIT_COLOR = '#dc3545'
# Lower-limit line color. Must be purple (not blue) per the user-facing
# requirement, and centrally defined here so no chart hardcodes its own.
LOWER_LIMIT_COLOR = '#6f42c1'

# Tier -> severity word (direction-agnostic) and direction word, used to build
# combined labels like "Límite marginal y condenatorio de viscosidad".
FOUR_LIMIT_TIER_WORDS = {
    'LIC': 'condenatorio',
    'LIM': 'marginal',
    'LSM': 'marginal',
    'LSC': 'condenatorio',
}
FOUR_LIMIT_TIER_DIRECTION = {
    'LIC': 'inferior',
    'LIM': 'inferior',
    'LSM': 'superior',
    'LSC': 'superior',
}

# Tolerance used to decide whether two limit values are "close enough" to be
# treated as equivalent and rendered as a single consolidated trace, instead
# of two overlapping/duplicated lines. Scale-aware: the absolute floor covers
# small-magnitude essays, the relative term covers large-magnitude ones.
LIMIT_VALUE_ABS_TOLERANCE = 0.5
LIMIT_VALUE_REL_TOLERANCE = 0.02  # 2% of the larger of the two values


def limit_values_are_equivalent(value_a, value_b) -> bool:
    """
    True when two limit values are equal or close enough (scale-aware
    tolerance) to be treated as the same line. Null/non-numeric input is
    never equivalent to anything (never silently coerced to 0).
    """
    if value_a is None or value_b is None:
        return False
    try:
        value_a = float(value_a)
        value_b = float(value_b)
    except (TypeError, ValueError):
        return False
    if pd.isna(value_a) or pd.isna(value_b):
        return False
    tolerance = max(LIMIT_VALUE_ABS_TOLERANCE, LIMIT_VALUE_REL_TOLERANCE * max(abs(value_a), abs(value_b)))
    return abs(value_a - value_b) <= tolerance


def _single_tier_label(feature: str, tier: str, other_line_exists: bool) -> str:
    if not other_line_exists:
        return f"Límite {feature}"
    return f"Límite {FOUR_LIMIT_TIER_DIRECTION[tier]} {feature}"


def _combined_tier_label(feature: str, tiers) -> str:
    words = list(dict.fromkeys(FOUR_LIMIT_TIER_WORDS[t] for t in tiers))
    directions = {FOUR_LIMIT_TIER_DIRECTION[t] for t in tiers}
    joined = " y ".join(words)
    if directions == {'inferior'}:
        return f"Límite {joined} inferior de {feature}"
    return f"Límite {joined} de {feature}"


def consolidate_limit_entries(entries):
    """
    Group limit entries whose values are equivalent (within
    limit_values_are_equivalent tolerance) into single consolidated lines with
    a user-friendly label, so equal/near-equal limits never render as
    duplicated overlapping traces.

    Args:
        entries: list of dicts, each {'value': float, 'tier': 'LIC'|'LIM'|'LSM'|'LSC',
            'feature': str}. `feature` should be the same display name already
            used for that essay's value trace (e.g. its legend name). Null/
            non-numeric values must be filtered out by the caller before
            calling this (an entry with a non-numeric value is dropped here
            defensively rather than plotted).

    Returns:
        List of dicts, one per consolidated line, each:
        {'value': float, 'label': str, 'tiers': [...], 'features': [...]}
        - Single feature, single tier, no sibling line for that feature ->
          "Límite {feature}"
        - Single feature, single tier, WITH a sibling line for that feature
          (e.g. a separate upper and lower line both present) ->
          "Límite superior/inferior {feature}"
        - Single feature, multiple tiers merged (e.g. LSM and LSC coincide) ->
          "Límite {tier words} [inferior] de {feature}"
        - Multiple features merged (same tier, different essays) ->
          "Límite {feature1} y {feature2}"
    """
    valid_entries = []
    for e in entries:
        value = e.get('value')
        if value is None:
            continue
        try:
            value = float(value)
        except (TypeError, ValueError):
            continue
        if pd.isna(value):
            continue
        valid_entries.append({**e, 'value': value})

    if not valid_entries:
        return []

    sorted_entries = sorted(valid_entries, key=lambda e: e['value'])
    clusters = []
    for entry in sorted_entries:
        if clusters and limit_values_are_equivalent(clusters[-1]['value'], entry['value']):
            clusters[-1]['members'].append(entry)
            clusters[-1]['value'] = sum(m['value'] for m in clusters[-1]['members']) / len(clusters[-1]['members'])
        else:
            clusters.append({'value': entry['value'], 'members': [entry]})

    # How many distinct rendered lines touch each feature - needed to decide
    # whether a lone single-tier line for a feature needs a direction
    # qualifier (a sibling line for that same feature exists elsewhere).
    feature_cluster_count = {}
    for cluster in clusters:
        for feature in {m['feature'] for m in cluster['members']}:
            feature_cluster_count[feature] = feature_cluster_count.get(feature, 0) + 1

    results = []
    for cluster in clusters:
        members = cluster['members']
        features = list(dict.fromkeys(m['feature'] for m in members))
        tiers = list(dict.fromkeys(m['tier'] for m in members))

        if len(features) > 1:
            label = "Límite " + " y ".join(features)
        elif len(tiers) > 1:
            label = _combined_tier_label(features[0], tiers)
        else:
            other_line_exists = feature_cluster_count.get(features[0], 1) > 1
            label = _single_tier_label(features[0], tiers[0], other_line_exists)

        results.append({'value': cluster['value'], 'label': label, 'tiers': tiers, 'features': features})

    return results


def limit_line_color(tiers) -> str:
    """
    Trace color for a (possibly consolidated) limit line, based on the
    direction of its tier(s): purple for lower-only, red for upper (or mixed).
    Central definition so no chart hardcodes its own upper/lower colors.
    """
    directions = {FOUR_LIMIT_TIER_DIRECTION[t] for t in tiers}
    return LOWER_LIMIT_COLOR if directions == {'inferior'} else UPPER_LIMIT_COLOR


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

        # Collect limits for consolidation (equal/near-equal values across
        # essays sharing this chart must render as one line, not duplicates).
        upper_entries = []  # [{'value', 'tier': 'LSC', 'feature': essay}, ...]
        lower_entries = []  # [{'value', 'tier': 'LIC', 'feature': essay}, ...] - only when available

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
                upper_entries.append({'value': essay_limits['LSC'], 'tier': 'LSC', 'feature': essay})

            # Collect lower condemnation limit (LIC) - only draw when BOTH LIC
            # and LIM are available; never render a lower-limit trace for
            # essay groups where the contract nulls out lower limits
            # (Desgaste, Aditivo) or where min_value <= 0.
            if essay_limits and essay_limits.get('LIC') is not None and essay_limits.get('LIM') is not None:
                lower_entries.append({'value': essay_limits['LIC'], 'tier': 'LIC', 'feature': essay})

        for line in consolidate_limit_entries(upper_entries):
            fig.add_hline(
                y=line['value'],
                line=dict(color=UPPER_LIMIT_COLOR, width=1.5, dash='dash'),
                annotation_text=line['label'],
                annotation_position="top right",
                annotation_font=dict(size=8, color=UPPER_LIMIT_COLOR),
            )

        for line in consolidate_limit_entries(lower_entries):
            fig.add_hline(
                y=line['value'],
                line=dict(color=LOWER_LIMIT_COLOR, width=1.5, dash='dash'),
                annotation_text=line['label'],
                annotation_position="bottom right",
                annotation_font=dict(size=8, color=LOWER_LIMIT_COLOR),
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
