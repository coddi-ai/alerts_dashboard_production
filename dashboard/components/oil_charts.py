"""
Shared oil time-series chart grid builder.

Used by both the Monitoring > Oil > Details time-series analysis section
(dashboard/callbacks/reports_callbacks.py) and the Alerts > Detail > Oil
Evidence "Tendencia" view (dashboard/callbacks/alerts_callbacks.py), so both
views render from the same chart-generation logic, variable combinations and
limits.
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
    {'title': 'Viscocidad', 'essays': ['Viscocidad'], 'show_lower_limit': True},
    {'title': 'Hollín & Oxidación', 'essays': ['Hollín', 'Oxidación']},
]

# Colorblind-safe palette for the "Paquete de Aditivos" chart, which can plot
# more essays than the 2-color palette used by the other paired charts.
ADITIVOS_PALETTE = [
    '#0072B2', '#009E73', '#56B4E9', '#332288',
    '#44AA99', '#88CCEE', '#117733', '#999933',
]


def get_essay_limits(comp_limits, essay, oil_hour_range):
    """
    Get essay limits with oil-hour stratification fallback logic (v2.3).

    Fallback hierarchy:
    1. Try exact match: oilHourRange from sample
    2. Try 'ALL' for v2.2 compatibility
    3. Try averaging across all available oil hour ranges
    4. Return None if essay not found

    Args:
        comp_limits: Nested dict {essay: {oilHourRange: {threshold_normal, ...}}}
        essay: Essay name
        oil_hour_range: Oil hour range from sample ('LT_1000', 'GE_1000', 'UNKNOWN')

    Returns:
        Dict with threshold_normal, threshold_alert, threshold_critic or None
    """
    if essay not in comp_limits:
        return None

    essay_limits = comp_limits[essay]

    # If essay_limits is already a dict with thresholds (v2.2 format), return it
    if 'threshold_normal' in essay_limits:
        return essay_limits

    # v2.3 format: try exact oilHourRange match
    if oil_hour_range in essay_limits:
        return essay_limits[oil_hour_range]

    # Fallback: try 'ALL' for v2.2 compatibility
    if 'ALL' in essay_limits:
        return essay_limits['ALL']

    # Fallback: average across all available oil hour ranges
    if essay_limits:
        available_ranges = list(essay_limits.keys())
        if available_ranges:
            avg_limits = {
                'threshold_normal': sum(essay_limits[r].get('threshold_normal', 0) for r in available_ranges) / len(available_ranges),
                'threshold_alert': sum(essay_limits[r].get('threshold_alert', 0) for r in available_ranges) / len(available_ranges),
                'threshold_critic': sum(essay_limits[r].get('threshold_critic', 0) for r in available_ranges) / len(available_ranges)
            }
            return avg_limits

    return None


def build_oil_time_series_grid(history: pd.DataFrame, comp_limits: dict, comp_limits_inferior: dict, oil_hour_range: str):
    """
    Build the 9-chart oil analysis time-series grid.

    Args:
        history: Pre-filtered, pre-sorted (by sampleDate ascending) rows for a
            single equipment/component pair, from the classified oil reports
            (golden/{client}/classified.parquet schema).
        comp_limits: Upper (condemnation) Stewart limits for this component,
            as returned by load_stewart_limits(...)[client][machine][component].
        comp_limits_inferior: Lower Stewart limits for this component, same
            shape as comp_limits (may be an empty dict if unavailable).
        oil_hour_range: oilHourRange of the most recent sample in `history`,
            used for stratified limit lookup via get_essay_limits.

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
                    'show_lower_limit': True,
                })
            if other_aditivos:
                charts_to_render.append({
                    'title': 'Aditivos: Otros',
                    'essays': other_aditivos,
                    'palette': ADITIVOS_PALETTE,
                    'show_lower_limit': True,
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
        limit_entries = []  # [(value, essay_name), ...]
        limit_entries_lower = []  # [(value, essay_name), ...]
        show_lower_limit = chart_config.get('show_lower_limit', False)

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

            # Collect upper condemnation limit (threshold_critic)
            essay_limits = get_essay_limits(comp_limits, essay, oil_hour_range)
            if essay_limits and 'threshold_critic' in essay_limits:
                limit_entries.append((essay_limits['threshold_critic'], essay))

            # Collect lower condemnation limit (threshold_critic from the inferior table)
            if show_lower_limit:
                essay_limits_lower = get_essay_limits(comp_limits_inferior, essay, oil_hour_range)
                if essay_limits_lower and 'threshold_critic' in essay_limits_lower:
                    limit_entries_lower.append((essay_limits_lower['threshold_critic'], essay))

        # Consolidate duplicate limits (same value → one line, combined label)
        limit_by_value = {}
        for val, name in limit_entries:
            rounded_val = round(val, 2)
            limit_by_value.setdefault(rounded_val, []).append(name)

        for val, names in limit_by_value.items():
            if len(names) > 1:
                label = " y ".join(names) + " Límite"
            else:
                label = f"Límite {names[0]}" if len(available_essays) > 1 else "Límite"
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
                label = " y ".join(names) + " Límite Inferior"
            else:
                label = f"Límite Inferior {names[0]}" if len(available_essays) > 1 else "Límite Inferior"
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
