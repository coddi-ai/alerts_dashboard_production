# Standard color mapping for sistema
SISTEMA_COLORS = {
    'Tren de Fuerza': '#4f8a8b',
    'Tren de fuerza': '#4f8a8b',
    'Motor': '#355c7d',
    'Frenos': '#d08c60',
    'Direccion': '#7c6a9a',
    'Dirección': '#7c6a9a',
    'Dirección': '#7c6a9a',
}
"""
Chart components for Alerts Dashboard.

Functions to create Plotly figures for alerts analytics.
"""

import ast
import math
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import yaml
from plotly.subplots import make_subplots
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import dash_bootstrap_components as dbc
from dash import html
import plotly.colors

from src.utils.logger import get_logger
from src.utils.date_utils import to_local_naive

logger = get_logger(__name__)

# Keep raw values for filtering, but use one client-facing label in every
# alert chart. Capstone publishes ``motor`` while the dashboard presents it
# as ``Motor``.
SYSTEM_TRANSLATION = {
    'Tren de Fuerza': 'Tren de fuerza',
    'Tren de fuerza': 'Tren de fuerza',
    'tren de fuerza': 'Tren de fuerza',
    'Motor': 'Motor',
    'motor': 'Motor',
    'Frenos': 'Frenos',
    'frenos': 'Frenos',
    'Direccion': 'Dirección',
    'Dirección': 'Dirección',
}


def translate_system_label(value) -> str:
    """Return the display label for a raw alert system value."""
    if value is None or (not isinstance(value, (list, tuple, dict)) and pd.isna(value)):
        return 'Sin sistema'
    raw = str(value).strip()
    if not raw:
        return 'Sin sistema'
    translated = SYSTEM_TRANSLATION.get(raw)
    if translated is not None:
        return translated
    folded = raw.casefold()
    for key, label in SYSTEM_TRANSLATION.items():
        if key.casefold() == folded:
            return label
    return raw

# Operational state color mapping
STATE_COLORS = {
    'Operacional': '#2ecc71',  # Green
    'Ralenti': '#f39c12',      # Orange
    'Ralentí': '#f39c12',
    'IDLE': '#f39c12',
    'PREPARACION': '#f39c12',
    'PREPARACIÓN': '#f39c12',
    'Preparación': '#f39c12',
    'RPM_BAJA': '#f39c12',
    'HABILITADO': '#2ecc71',
    'Habilitado': '#2ecc71',
    'Potencia': '#2ecc71',
    'potencia': '#2ecc71',
    'Transicion': '#f39c12',
    'ND': '#95a5a6'            # Gray
}

STATE_LABELS = {
    'HABILITADO': 'Operacional',
    'Habilitado': 'Operacional',
    'Operacional': 'Operacional',
    'Potencia': 'Potencia',
    'potencia': 'Potencia',
    'PREPARACION': 'Preparación',
    'PREPARACIÓN': 'Preparación',
    'Preparación': 'Preparación',
    'Ralenti': 'Ralentí',
    'Ralentí': 'Ralentí',
    'IDLE': 'Ralentí',
    'RPM_BAJA': 'Ralentí / RPM baja',
}

# Capstone state labels may arrive with either UTF-8 or legacy decoded text.
# Normalize both forms for the legend without changing CDA's existing states.
STATE_COLORS.update({
    'Preparaci\u00f3n': '#f39c12',
    'PREPARACI\u00d3N': '#f39c12',
    'Transici\u00f3n': '#f39c12',
    'Transicion': '#f39c12',
})
STATE_LABELS.update({
    'Preparaci\u00f3n': 'Preparaci\u00f3n',
    'PREPARACI\u00d3N': 'Preparaci\u00f3n',
    'Preparación': 'Preparaci\u00f3n',
    'PREPARACION': 'Preparaci\u00f3n',
    'Transici\u00f3n': 'Transici\u00f3n',
    'Transicion': 'Transici\u00f3n',
})

# Explicit canonical aliases keep Capstone's accented state values in the
# same palette as their unaccented/legacy variants.
STATE_COLORS['Transición'] = '#f39c12'
STATE_LABELS['Transición'] = 'Transición'


def _state_lookup(value, mapping: Dict, default):
    """Resolve state aliases case-insensitively while preserving raw values."""
    if value is None or (not isinstance(value, (list, tuple, dict)) and pd.isna(value)):
        return default
    raw = str(value).strip()
    if not raw:
        return default
    if raw in mapping:
        return mapping[raw]
    folded = raw.casefold()
    for key, mapped in mapping.items():
        if str(key).casefold() == folded:
            return mapped
    return default


def _state_color(value, default='#95a5a6'):
    return _state_lookup(value, STATE_COLORS, default)


def _state_label(value):
    fallback = str(value).strip() if value is not None else ''
    return _state_lookup(value, STATE_LABELS, fallback)

# Spanish feature names mapping
# Signal labels live in src/charts/signals.py so the dashboard and Campbell AI use
# the same catalogue; re-exported here for existing importers. SIGNAL_LABELS is a
# read-only view (types.MappingProxyType) \u2014 see the W34-11 note in
# src/charts/signals.py. The Capstone canonical codes that used to be injected
# here via `FEATURE_NAMES_ES.update(...)` at import time now live in the
# catalogue itself, so there is exactly one definition instead of a static base
# plus a runtime patch whose effect depended on import order.
from src.charts.signals import OMITTED_SIGNALS, SIGNAL_LABELS

FEATURE_NAMES_ES = SIGNAL_LABELS

# Features to omit from dashboard
OMITTED_FEATURES = list(OMITTED_SIGNALS)

# Signals that ARE catalogued (they have a real label in SIGNAL_LABELS) but
# never get their own subplot in the sensor-trends chart because they are
# already shown as a dedicated KPI card in create_context_kpis_cards_golden:
# EngSpd -> "Velocidad Motor", Payload -> "Carga". This is a different concept
# from OMITTED_SIGNALS (signals absent from the catalogue entirely, e.g.
# GroundSpd/EngLoad) \u2014 collected here, not duplicated, so
# create_telemetry_evidence_section (alerts_callbacks.py, the only consumer)
# has one place to combine both exclusion reasons instead of a third
# independently hardcoded list.
KPI_ONLY_SIGNALS: tuple[str, ...] = ('Payload', 'EngSpd')


def select_plottable_signals(feature_names: List[str]) -> tuple[List[str], List[str]]:
    """Split candidate `_Value` feature names into (plottable, uncatalogued).

    A signal gets its own sensor-trends panel only when it is both present in
    the source (the caller already restricted `feature_names` to columns that
    exist) and permitted: catalogued in SIGNAL_LABELS, and not one of the
    signals shown elsewhere instead (KPI_ONLY_SIGNALS) or excluded from the
    catalogue entirely (OMITTED_SIGNALS). Pulled out as a pure function (W34-11)
    so the rule is unit-testable without building a full alert/telemetry
    fixture; the only caller is create_telemetry_evidence_section in
    alerts_callbacks.py.

    Returns:
        (plottable, uncatalogued) — `plottable` keeps the input order;
        `uncatalogued` lists source columns that exist but have no catalogue
        entry (worth a log line at the call site, not silence).
    """
    excluded = set(KPI_ONLY_SIGNALS) | set(OMITTED_SIGNALS)
    uncatalogued = [
        name for name in feature_names
        if name not in excluded and name not in FEATURE_NAMES_ES
    ]
    plottable = [
        name for name in feature_names
        if name not in excluded and name in FEATURE_NAMES_ES
    ]
    return plottable, uncatalogued


# Shared sizing for the three "Análisis semanal de alertas" charts so their
# cards render at the same height regardless of fleet size.
ALERTS_CHART_HEIGHT = 400

# Pareto chart (Distribución por unidad) styling: bars are not segmented by
# system, so a single accent color is used for the count bars and a
# contrasting color for the cumulative-percentage line.
PARETO_BAR_COLOR = '#355c7d'
PARETO_LINE_COLOR = '#d08c60'

def create_alerts_per_unit_chart(alerts_df: pd.DataFrame) -> go.Figure:
    """
    Create a Pareto chart of alerts per unit: units on the X-axis sorted by
    descending alert count (bars, primary Y-axis) with a cumulative-percentage
    line (secondary Y-axis, fixed 0-100%). Units are not segmented/colored by
    system and no legend is shown - the axes and hover text carry that.

    The two Y-axes scale independently: the primary axis fits the largest
    unit's count (not the total alert count), so bars stay readable instead
    of being compressed near the bottom for fleets with many total alerts.

    Renders responsively (no fixed pixel width) so the whole Pareto - every
    bar plus the secondary axis - fits inside the fixed-height card without
    horizontal scrolling; tick/label density and on-bar text shrink or drop
    as the fleet grows so labels stay readable instead of overlapping - full
    per-unit detail (count + cumulative %) is always available on hover.

    Args:
        alerts_df: DataFrame with column ['UnitId']

    Returns:
        Plotly Figure with a bar + line combo chart
    """
    if alerts_df.empty:
        logger.warning("Cannot create alerts per unit chart: empty dataframe")
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )

    try:
        counts = alerts_df.groupby('UnitId').size().reset_index(name='Count')
        counts = counts.sort_values('Count', ascending=False).reset_index(drop=True)

        total = int(counts['Count'].sum())
        counts['CumulativePct'] = (counts['Count'].cumsum() / total * 100) if total else 0.0
        # Guard against float drift so the last point always reads exactly 100%.
        if len(counts):
            counts.loc[counts.index[-1], 'CumulativePct'] = 100.0

        unit_count = len(counts)
        max_count = int(counts['Count'].max()) if unit_count else 0
        # Shrink tick/value fonts (and rotate on-bar values) as the fleet
        # grows, so labels keep fitting the fixed card width without
        # overlapping - unit-level detail is still always available on hover.
        if unit_count <= 12:
            tick_font_size, value_font_size, value_angle = 11, 11, 0
        elif unit_count <= 25:
            tick_font_size, value_font_size, value_angle = 10, 9, 0
        elif unit_count <= 45:
            tick_font_size, value_font_size, value_angle = 8, 8, -90
        else:
            tick_font_size, value_font_size, value_angle = 7, 7, -90

        # Above this many units, on-bar count labels start to overlap - drop
        # them and lean on hover instead of forcing every label into view.
        show_bar_text = unit_count <= 25
        bar_text = counts['Count'].map(lambda value: f'{int(value)}') if show_bar_text else None

        # Cumulative-% labels are shown for at most ~12 points, evenly spaced,
        # always including the last (100%) point - the rest stay hover-only
        # so dense fleets don't stack overlapping percentage labels.
        label_step = max(1, math.ceil(unit_count / 12)) if unit_count else 1
        cumulative_text = [
            f'{value:.0f}%' if (index % label_step == 0 or index == unit_count - 1) else ''
            for index, value in enumerate(counts['CumulativePct'])
        ]

        # Primary axis is independent of the secondary (0-100%) axis: it
        # fits the largest bar with headroom, so bars stay legible instead
        # of compressing toward the bottom as total alert count grows.
        axis_max = (max_count * 1.15) if max_count else 1

        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(
            go.Bar(
                x=counts['UnitId'],
                y=counts['Count'],
                name='Alertas',
                marker_color=PARETO_BAR_COLOR,
                text=bar_text,
                textposition='auto',
                textangle=value_angle,
                insidetextfont=dict(size=value_font_size, color='white'),
                outsidetextfont=dict(size=value_font_size, color='#2c3e50'),
                cliponaxis=False,
                hovertemplate='Alertas: %{y}<extra></extra>',
            ),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(
                x=counts['UnitId'],
                y=counts['CumulativePct'],
                name='% acumulado',
                mode='lines+markers+text',
                text=cumulative_text,
                textposition='top center',
                textfont=dict(size=value_font_size, color=PARETO_LINE_COLOR),
                line=dict(color=PARETO_LINE_COLOR, width=2),
                marker=dict(size=6, color=PARETO_LINE_COLOR),
                cliponaxis=False,
                hovertemplate='%% acumulado: %{y:.1f}%<extra></extra>',
            ),
            secondary_y=True,
        )

        xaxis_kwargs = dict(
            title_text='Identificador de Unidad',
            type='category',
            tickangle=-45,
            tickfont=dict(size=tick_font_size),
        )
        if unit_count > 40:
            # Thin out the X-axis tick labels (not the bars themselves) once
            # there are too many units for every label to stay readable.
            xaxis_kwargs.update(tickmode='linear', dtick=math.ceil(unit_count / 40))
        fig.update_xaxes(**xaxis_kwargs)
        fig.update_yaxes(
            title_text='Número de Alertas',
            range=[0, axis_max],
            nticks=6,
            secondary_y=False,
        )
        fig.update_yaxes(
            title_text='Porcentaje Acumulado',
            range=[0, 100],
            tickvals=[0, 20, 40, 60, 80, 100],
            ticksuffix='%',
            secondary_y=True,
        )
        fig.update_layout(
            template='plotly_white',
            showlegend=False,
            height=ALERTS_CHART_HEIGHT,
            margin=dict(l=55, r=55, t=30, b=80),
            hovermode='x unified',
        )

        logger.info("Created alerts per unit Pareto chart successfully")
        return fig

    except Exception as e:
        logger.error(f"Error creating alerts per unit chart: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_alerts_per_month_chart(alerts_df: pd.DataFrame) -> go.Figure:
    """
    Create vertical bar chart showing distribution of alerts per month.
    
    Args:
        alerts_df: DataFrame with columns ['Month', 'sistema']
    
    Returns:
        Plotly Figure with vertical bar chart
    """
    if alerts_df.empty:
        logger.warning("Cannot create alerts per month chart: empty dataframe")
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Count alerts per month and translated display system.
        alerts_per_month = alerts_df.copy()
        alerts_per_month['_system_display'] = alerts_per_month['sistema'].map(translate_system_label)
        alerts_per_month = alerts_per_month.groupby(
            ['Month', '_system_display']
        ).size().reset_index(name='Count')
        alerts_per_month['Month_str'] = alerts_per_month['Month'].astype(str)
        
        # Sort systems in reverse alphabetical order for consistent ordering
        alerts_per_month['_system_display'] = pd.Categorical(
            alerts_per_month['_system_display'],
            categories=sorted(alerts_per_month['_system_display'].unique(), reverse=True),
            ordered=True
        )
        alerts_per_month = alerts_per_month.sort_values('_system_display')
        
        # Create vertical bar chart
        fig = px.bar(
            alerts_per_month,
            x='Month_str',
            y='Count',
            color='_system_display',
            title=None,
            labels={'Month_str': 'Mes', 'Count': 'Número de Alertas', '_system_display': 'Sistema'},
            template='plotly_white',
            height=500,
            color_discrete_map=SISTEMA_COLORS
        )
        # Horizontal, compact legend at top right
        fig.update_layout(
            xaxis_tickangle=-45,
            showlegend=True,
            legend=dict(
                title='Sistema',
                orientation='h',
                x=1,
                y=1.08,
                xanchor='right',
                yanchor='bottom',
                font=dict(size=11),
                itemwidth=80
            ),
            hovermode='x unified'
        )
        
        logger.info("Created alerts per month chart successfully")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating alerts per month chart: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_alerts_per_week_chart(alerts_df: pd.DataFrame) -> go.Figure:
    """Create a weekly stacked alert evolution chart."""
    if alerts_df is None or alerts_df.empty:
        return go.Figure().add_annotation(text="No hay alertas para el período", x=0.5, y=0.5, showarrow=False)
    frame = alerts_df.copy()
    timestamp = pd.to_datetime(frame.get('Timestamp'), errors='coerce')
    frame = frame.loc[timestamp.notna()].copy()
    frame['_week_start'] = timestamp.loc[frame.index].dt.to_period('W-SUN').dt.start_time
    frame['_system_display'] = frame.get('sistema', '').map(translate_system_label)
    grouped = frame.groupby(['_week_start', '_system_display']).size().reset_index(name='Count')
    weeks = pd.date_range(frame['_week_start'].min(), frame['_week_start'].max(), freq='7D')
    systems = sorted(frame['_system_display'].dropna().unique())
    full = pd.MultiIndex.from_product([weeks, systems], names=['_week_start', '_system_display']).to_frame(index=False)
    grouped = full.merge(grouped, how='left', on=['_week_start', '_system_display']).fillna({'Count': 0})
    grouped['Semana'] = grouped['_week_start'].dt.strftime('%d/%m')
    grouped['_week_start_iso'] = grouped['_week_start'].dt.strftime('%Y-%m-%d')
    # Blank labels for zero-filled (week, system) combos so empty stack
    # segments don't render a dangling "0" at the baseline.
    grouped['_label'] = grouped['Count'].apply(lambda count: '' if count <= 0 else f'{int(count)}')
    fig = px.bar(
        grouped,
        x='Semana',
        y='Count',
        color='_system_display',
        barmode='stack',
        text='_label',
        labels={'Semana': 'Semana', 'Count': 'Alertas', '_system_display': 'Sistema'},
        color_discrete_map=SISTEMA_COLORS,
        template='plotly_white',
        height=ALERTS_CHART_HEIGHT,
        custom_data=['_week_start_iso'],
    )
    fig.update_traces(
        textposition='auto',
        insidetextfont=dict(size=10, color='white'),
        outsidetextfont=dict(size=10, color='#2c3e50'),
        cliponaxis=False,
        hovertemplate='<b>%{fullData.name}</b><br>Semana: %{x}<br>Alertas: %{y}<extra></extra>',
    )
    # A single-system client sees every stacked bar in one color anyway, so
    # the "Sistema" legend is redundant - only show it once there's more
    # than one system to actually distinguish.
    show_legend = len(systems) >= 2
    fig.update_layout(
        margin=dict(l=40, r=10, t=14 if show_legend else 8, b=48),
        showlegend=show_legend,
        legend=dict(orientation='h', y=1.08, x=1, xanchor='right', yanchor='bottom', font=dict(size=10)),
        hovermode='x unified',
    )
    return fig


def create_trigger_distribution_treemap(alerts_df: pd.DataFrame) -> go.Figure:
    """
    Create treemap showing distribution of alert triggers.
    
    Args:
        alerts_df: DataFrame with column ['Trigger_type']
    
    Returns:
        Plotly Figure with treemap
    """
    if alerts_df.empty:
        logger.warning("Cannot create trigger distribution treemap: empty dataframe")
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Count alerts by trigger type
        trigger_counts = alerts_df['Trigger_type'].value_counts().reset_index()
        trigger_counts.columns = ['Trigger_type', 'Frequency']
        
        # Create treemap (no frequency bar, just label)
        fig = px.treemap(
            trigger_counts,
            path=['Trigger_type'],
            values='Frequency',
            title=None,
            color_discrete_sequence=['#3498db'],
            height=500
        )
        fig.update_traces(
            textinfo='label+percent parent',
            textfont_size=14
        )
        fig.update_layout(showlegend=False)
        logger.info("Created trigger distribution treemap successfully")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating trigger distribution treemap: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_sensor_trends_chart(
    telemetry_values: pd.DataFrame,
    telemetry_states: pd.DataFrame,
    limits_config: pd.DataFrame,
    unit_id: str,
    sensor_columns: List[str],
    alert_time: datetime,
    window_start: datetime,
    window_end: datetime,
    feature_names: Dict[str, str]
) -> go.Figure:
    """
    **DEPRECATED**: Use create_sensor_trends_chart_golden() instead.
    
    Old implementation: Create multi-panel time series chart showing sensor trends with limits.
    This function loads from silver layer and performs complex merging operations.
    
    Args:
        telemetry_values: DataFrame with telemetry sensor values
        telemetry_states: DataFrame with operational states
        limits_config: DataFrame with sensor limits
        unit_id: Unit identifier
        sensor_columns: List of sensor column names to display
        alert_time: Alert timestamp
        window_start: Start of time window
        window_end: End of time window
        feature_names: Dictionary mapping feature codes to Spanish names
    
    Returns:
        Plotly Figure with subplots (one per sensor)
    """
    if telemetry_values.empty:
        logger.warning("Cannot create sensor trends chart: empty telemetry values")
        return go.Figure().add_annotation(
            text="No telemetry data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Filter data for unit and time window
        unit_data = telemetry_values[
            (telemetry_values['Unit'] == unit_id) &
            (telemetry_values['Fecha'] >= window_start) &
            (telemetry_values['Fecha'] <= window_end)
        ].copy()
        
        # Merge with states
        if not telemetry_states.empty:
            unit_data = unit_data.merge(
                telemetry_states[['Fecha', 'Unit', 'Estado', 'EstadoCarga']],
                on=['Fecha', 'Unit'],
                how='left'
            )
        
        if unit_data.empty:
            logger.warning("No telemetry data in time window")
            return go.Figure().add_annotation(
                text="No data in time window",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
        
        # Merge limits into unit_data
        if not limits_config.empty:
            unit_limits = limits_config[limits_config['Unit'] == unit_id].copy()
            
            for sensor in sensor_columns:
                feature_limits = unit_limits[unit_limits['Feature'] == sensor].copy()
                
                if not feature_limits.empty:
                    feature_limits = feature_limits.rename(columns={
                        'Limit_Lower': f'{sensor}_Lower',
                        'Limit_Upper': f'{sensor}_Upper'
                    })
                    
                    unit_data = unit_data.merge(
                        feature_limits[['Estado', 'EstadoCarga', f'{sensor}_Lower', f'{sensor}_Upper']],
                        on=['Estado', 'EstadoCarga'],
                        how='left'
                    )
        
        # Create subplots
        fig = make_subplots(
            rows=len(sensor_columns),
            cols=1,
            shared_xaxes=True,
            subplot_titles=[feature_names.get(sensor, sensor) for sensor in sensor_columns],
            vertical_spacing=0.08
        )
        
        # Plot each sensor
        for idx, sensor in enumerate(sensor_columns, 1):
            sensor_name = feature_names.get(sensor, sensor)
            
            # Plot data points colored by operational state
            for estado in unit_data['Estado'].dropna().unique():
                estado_data = unit_data[unit_data['Estado'] == estado]
                
                fig.add_trace(
                    go.Scatter(
                        x=estado_data['Fecha'],
                        y=estado_data[sensor],
                        mode='markers',
                        name=f'{estado}',
                        legendgroup=estado,
                        showlegend=(idx == 1),  # Only show legend for first subplot
                        marker=dict(
                            color=_state_color(estado),
                            size=6
                        ),
                        hovertemplate=(
                            f'<b>{sensor_name}</b><br>' +
                            'Hora: %{x}<br>' +
                            'Valor: %{y:.2f}<br>' +
                            f'Estado: {estado}<br>' +
                            '<extra></extra>'
                        )
                    ),
                    row=idx,
                    col=1
                )
            
            # Plot continuous limit lines
            lower_col = f'{sensor}_Lower'
            upper_col = f'{sensor}_Upper'
            
            if lower_col in unit_data.columns and unit_data[lower_col].notna().any():
                fig.add_trace(
                    go.Scatter(
                        x=unit_data['Fecha'],
                        y=unit_data[lower_col],
                        mode='lines',
                        name='Límite Inferior',
                        legendgroup='limits',
                        showlegend=(idx == 1),
                        line=dict(color='red', width=2, dash='dash'),
                        hovertemplate='Límite Inferior: %{y:.2f}<extra></extra>'
                    ),
                    row=idx,
                    col=1
                )
            
            if upper_col in unit_data.columns and unit_data[upper_col].notna().any():
                fig.add_trace(
                    go.Scatter(
                        x=unit_data['Fecha'],
                        y=unit_data[upper_col],
                        mode='lines',
                        name='Límite Superior',
                        legendgroup='limits',
                        showlegend=(idx == 1),
                        line=dict(color='red', width=2, dash='dash'),
                        hovertemplate='Límite Superior: %{y:.2f}<extra></extra>'
                    ),
                    row=idx,
                    col=1
                )
            
            # Add alert time marker
            y_min = unit_data[sensor].min()
            y_max = unit_data[sensor].max()
            
            if lower_col in unit_data.columns and unit_data[lower_col].notna().any():
                y_min = min(y_min, unit_data[lower_col].min())
            if upper_col in unit_data.columns and unit_data[upper_col].notna().any():
                y_max = max(y_max, unit_data[upper_col].max())
            
            if pd.notna(y_min) and pd.notna(y_max):
                y_range = y_max - y_min if y_max != y_min else 1
                y_extended_min = y_min - (0.1 * y_range)
                y_extended_max = y_max + (0.1 * y_range)
                
                fig.add_trace(
                    go.Scatter(
                        x=[alert_time, alert_time],
                        y=[y_extended_min, y_extended_max],
                        mode='lines',
                        name='⚠️ Alerta',
                        legendgroup='alert',
                        showlegend=(idx == 1),
                        line=dict(color='orange', width=3),
                        hovertemplate=f"Momento de Alerta: {alert_time}<extra></extra>"
                    ),
                    row=idx,
                    col=1
                )
        
        # Update layout
        fig.update_layout(
            title={
                'text': f'Análisis de Tendencias - {unit_id}',
                'x': 0.5,
                'xanchor': 'center',
                'font': dict(size=16, color='#2c3e50')
            },
            height=300 * len(sensor_columns),
            template='plotly_white',
            hovermode='x unified',
            margin=dict(l=60, r=20, t=50, b=40)
        )
        
        # Update axes
        fig.update_xaxes(
            title_text='Hora',
            showgrid=True,
            gridwidth=1,
            gridcolor='#ecf0f1',
            row=len(sensor_columns),
            col=1
        )
        
        for i in range(1, len(sensor_columns) + 1):
            fig.update_yaxes(
                title_text='Valor',
                showgrid=True,
                gridwidth=1,
                gridcolor='#ecf0f1',
                row=i,
                col=1
            )
        
        logger.info(f"Created sensor trends chart with {len(sensor_columns)} sensors")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating sensor trends chart: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_gps_route_map(
    telemetry_values: pd.DataFrame,
    unit_id: str,
    alert_time: datetime,
    window_start: datetime,
    window_end: datetime,
    mapbox_token: str
) -> go.Figure:
    """
    **DEPRECATED**: Use create_gps_route_map_golden() instead.
    
    Old implementation: Create GPS route map with alert location.
    This function loads from silver layer and performs filtering operations.
    
    Args:
        telemetry_values: DataFrame with GPS columns (GPSLat, GPSLon, Fecha)
        unit_id: Unit identifier
        alert_time: Alert timestamp
        window_start: Start of time window
        window_end: End of time window
        mapbox_token: Mapbox access token
    
    Returns:
        Plotly Figure with GPS map
    """
    if telemetry_values.empty:
        logger.warning("Cannot create GPS map: empty telemetry values")
        return go.Figure().add_annotation(
            text="No GPS data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Filter data
        unit_data = telemetry_values[
            (telemetry_values['Unit'] == unit_id) &
            (telemetry_values['Fecha'] >= window_start) &
            (telemetry_values['Fecha'] <= window_end)
        ].copy()
        
        gps_data = unit_data.dropna(subset=['GPSLat', 'GPSLon']).copy()
        
        if gps_data.empty:
            logger.warning("No GPS data in time window")
            return go.Figure().add_annotation(
                text="No GPS data in time window",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
        
        # Normalize time for color gradient
        time_min = gps_data['Fecha'].min()
        time_max = gps_data['Fecha'].max()
        
        if time_max > time_min:
            gps_data['TimeNorm'] = (gps_data['Fecha'] - time_min) / (time_max - time_min)
        else:
            gps_data['TimeNorm'] = 0.5
        
        # Create map
        fig = go.Figure()
        
        # Add route line
        fig.add_trace(go.Scattermapbox(
            lat=gps_data['GPSLat'],
            lon=gps_data['GPSLon'],
            mode='lines',
            line=dict(width=2, color='rgba(100, 100, 100, 0.5)'),
            showlegend=False,
            hoverinfo='skip'
        ))
        
        # Add colored points
        fig.add_trace(go.Scattermapbox(
            lat=gps_data['GPSLat'],
            lon=gps_data['GPSLon'],
            mode='markers',
            marker=dict(
                size=10,
                color=gps_data['TimeNorm'],
                colorscale='Reds',
                showscale=False
            ),
            showlegend=False,
            text=gps_data['Fecha'].dt.strftime('%H:%M:%S'),
            hovertemplate='Hora: %{text}<extra></extra>'
        ))
        
        # Add alert marker
        alert_idx = (gps_data['Fecha'] - alert_time).abs().argmin()
        alert_point = gps_data.iloc[alert_idx]
        
        fig.add_trace(go.Scattermapbox(
            lat=[alert_point['GPSLat']],
            lon=[alert_point['GPSLon']],
            mode='markers',
            marker=dict(
                size=25,
                color='black',
                symbol='marker'
            ),
            showlegend=False,
            text=[f"⚠️ Alerta: {alert_time.strftime('%H:%M:%S')}"],
            hovertemplate='%{text}<extra></extra>'
        ))
        
        fig.update_layout(
            mapbox=dict(
                accesstoken=mapbox_token,
                style="satellite-streets",
                center=dict(
                    lat=gps_data['GPSLat'].mean(),
                    lon=gps_data['GPSLon'].mean()
                ),
                zoom=14
            ),
            title='Ruta GPS - Vista Satelital',
            height=600,
            margin=dict(l=0, r=0, t=40, b=0),
            showlegend=False
        )
        
        logger.info(f"Created GPS route map with {len(gps_data)} points")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating GPS route map: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_oil_radar_chart(oil_report: pd.Series, essay_cols: List[str]) -> go.Figure:
    """
    Create radar chart showing oil essay levels.
    
    Args:
        oil_report: Series with oil report data
        essay_cols: List of essay column names (ending with _ppm)
    
    Returns:
        Plotly Figure with radar chart
    """
    # Check if data is available (Series doesn't have .empty attribute)
    if oil_report is None or len(oil_report) == 0 or not essay_cols:
        logger.warning("Cannot create oil radar chart: empty data or no essay columns")
        return go.Figure().add_annotation(
            text="No oil data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        fig = go.Figure()
        
        # Get values for each essay column
        r_values = [float(oil_report.get(col, 0)) if pd.notna(oil_report.get(col, 0)) else 0 for col in essay_cols]
        theta_values = [col.replace('_ppm', '').replace('_', ' ').title() for col in essay_cols]
        
        # Calculate max value for scale (ensure at least 1 for visibility)
        max_value = max(r_values) if max(r_values) > 0 else 1
        
        # Add actual values
        fig.add_trace(go.Scatterpolar(
            r=r_values,
            theta=theta_values,
            fill='toself',
            name='Valores Actuales',
            line_color='#3498db',
            hovertemplate='<b>%{theta}</b><br>Valor: %{r:.2f} ppm<extra></extra>'
        ))
        
        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, max_value * 1.2]
                )
            ),
            title='Análisis de Aceite - Niveles de Elementos',
            height=500,
            showlegend=True
        )
        
        logger.info(f"Created oil radar chart successfully with {len(essay_cols)} essays")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating oil radar chart: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def _first_signal_key(trigger_var) -> Optional[str]:
    """Return the raw (untranslated) code for only the *first* Señal/Variable
    on an alert row's ``Trigger_Var``.

    ``Trigger_Var`` is a real Golden-layer column but isn't uniform: Capstone
    stores a bare scalar code, CDA/Emin store a string-serialized Python list
    (mixed telemetry+tribology alerts can carry several signals in one row).
    One alert must size exactly one treemap leaf - so only the first value is
    kept and the rest are intentionally dropped here, rather than exploding
    one alert into multiple leaves.
    """
    if trigger_var is None or (not isinstance(trigger_var, (list, tuple, set)) and pd.isna(trigger_var)):
        return None
    parsed = trigger_var
    if isinstance(parsed, str):
        try:
            parsed = ast.literal_eval(parsed)
        except (ValueError, SyntaxError):
            pass
    if isinstance(parsed, (list, tuple, set)):
        parsed = next(iter(parsed), None)
    if parsed is None:
        return None
    signal_key = str(parsed).strip()
    return signal_key or None


def _first_signal_display(trigger_var) -> Optional[str]:
    """Return the Spanish display label for `_first_signal_key`."""
    key = _first_signal_key(trigger_var)
    if key is None:
        return None
    return FEATURE_NAMES_ES.get(key, key)


# Spanish "Familia" labels for the `functional_group` identifiers a client's
# config/features/{client}.yaml can define. These identifiers are internal
# engineering names and must never reach the UI directly; unmapped groups
# (future clients) fall back to an auto-formatted label in
# `_functional_group_label` rather than blocking on this table.
FUNCTIONAL_GROUP_LABELS_ES = {
    'engine_core': 'Motor',
    'coolant': 'Refrigerante',
    'ecu_temperature': 'Temperatura ECU',
    'oil_temperature': 'Temperatura de aceite',
    'intake_temperature': 'Temperatura de admisión',
    'egt': 'Gases de escape (EGT)',
    'oil_pressure': 'Presión de aceite',
    'post_filter_oil_pressure': 'Presión de aceite post-filtro',
    'intake_manifold_pressure': 'Presión del múltiple de admisión',
    'crankcase_pressure': 'Presión del cárter',
    'turbocharger_temperature': 'Temperatura del turbocompresor',
    'turbocharger_speed': 'Velocidad del turbocompresor',
    'fan': 'Ventilador',
}


def _functional_group_label(group_key: str) -> str:
    """Spanish display label for a functional_group id, with a readable
    auto-formatted fallback so a future client's config never leaks a raw
    snake_case identifier into the UI."""
    label = FUNCTIONAL_GROUP_LABELS_ES.get(group_key)
    if label:
        return label
    return group_key.replace('_', ' ').strip().capitalize()


_IDENTIFIER_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
# Function/operator names that can appear in a `derived` formula string but
# are never themselves signal identifiers.
_DERIVED_FORMULA_KEYWORDS = {'abs', 'min', 'max', 'round'}


@lru_cache(maxsize=8)
def _load_functional_group_map(client: str) -> Dict[str, str]:
    """Map every raw signal code a client's alerts can carry in
    ``Trigger_Var`` (a feature's ``source_column``, its own ``name``, or a
    bare identifier referenced inside a ``derived`` formula) to that
    feature's ``functional_group``.

    Generic across clients: any ``config/features/{client}.yaml`` matching
    the ``features: [{name, source_column?, derived?, functional_group}]``
    shape works, not just Capstone's. Returns {} when the client has no such
    config file - callers treat that as "no functional_group mapping
    available" and fall back to the Sistema-based treemap.
    """
    path = Path('config/features') / f'{client}.yaml'
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            config = yaml.safe_load(handle) or {}
    except Exception as e:
        logger.warning(f"Could not load feature config for client '{client}': {e}")
        return {}

    mapping: Dict[str, str] = {}
    all_features = list(config.get('features') or []) + list(config.get('diagnostic_features') or [])
    for feature in all_features:
        group = feature.get('functional_group')
        if not group:
            continue
        name = feature.get('name')
        if name:
            mapping.setdefault(name, group)
        source_column = feature.get('source_column')
        if source_column:
            mapping.setdefault(source_column, group)
        derived = feature.get('derived')
        if derived:
            # A `derived` formula (e.g. "abs(egt_lb_c - egt_rb_c)") can
            # reference raw signal columns that have no feature entry of
            # their own, yet Trigger_Var can still point at them directly.
            for token in _IDENTIFIER_RE.findall(str(derived)):
                if token in _DERIVED_FORMULA_KEYWORDS:
                    continue
                mapping.setdefault(token, group)
    return mapping


def _treemap_root_colors(root_labels) -> Dict[str, str]:
    """Assign a stable color per treemap root label. Known systems keep the
    shared SISTEMA_COLORS palette; unrecognized roots (Familia labels, or a
    future client's system names) cycle a qualitative palette instead of all
    collapsing onto one fallback color."""
    palette = plotly.colors.qualitative.Set2
    colors: Dict[str, str] = {}
    next_index = 0
    for label in sorted(set(root_labels)):
        if label in SISTEMA_COLORS:
            colors[label] = SISTEMA_COLORS[label]
            continue
        colors[label] = palette[next_index % len(palette)]
        next_index += 1
    return colors


def create_system_signal_treemap(alerts_df: pd.DataFrame, client: Optional[str] = None) -> go.Figure:
    """
    Create a two-level treemap of alerts, area sized by alert count.

    Multi-system clients (2+ distinct ``sistema`` values in the filtered
    data): Sistema -> Señal/Variable, as before.

    Single-system clients: a single "Sistema" root tile wastes roughly half
    the treemap on a grouping that no longer distinguishes anything, so when
    ``config/features/{client}.yaml`` maps the first signal of each alert to
    a ``functional_group``, use Familia -> Señal/Variable instead. This is
    generic (driven entirely by the config file's shape, not a Capstone
    special-case) and falls back to Sistema -> Señal/Variable - never
    fabricating a grouping - when no client config or mapping is available.

    Each alert contributes to exactly one leaf either way: when
    ``Trigger_Var`` carries several signals, only the first is used (see
    `_first_signal_key`), so the treemap's total area always equals the
    total alert count - no alert is double-counted.

    Args:
        alerts_df: DataFrame with columns ['sistema', 'Trigger_Var']
        client: Client identifier, used to look up config/features/{client}.yaml
            for the single-system Familia fallback. Optional - omitting it
            (or having no matching config) keeps the Sistema-based treemap.

    Returns:
        Plotly Figure with a go.Treemap
    """
    if alerts_df.empty:
        logger.warning("Cannot create system/signal treemap: empty dataframe")
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )

    try:
        frame = alerts_df.copy()
        frame['_system_display'] = frame['sistema'].map(translate_system_label)
        trigger_var = frame['Trigger_Var'] if 'Trigger_Var' in frame.columns else pd.Series(None, index=frame.index)
        frame['_signal_key'] = trigger_var.map(_first_signal_key)
        frame['_signal_display'] = frame['_signal_key'].map(
            lambda key: FEATURE_NAMES_ES.get(key, key) if key else None
        ).fillna('Sin señal registrada')

        systems_present = frame['_system_display'].dropna().unique()
        group_map = {}
        if client and len(systems_present) <= 1:
            group_map = _load_functional_group_map(str(client).strip().lower())

        use_family = bool(group_map)
        if use_family:
            frame['_root_display'] = frame['_signal_key'].map(
                lambda key: _functional_group_label(group_map[key]) if key and key in group_map else None
            )
            frame['_root_display'] = frame['_root_display'].fillna('Sin familia')
            root_dimension = 'Familia'
        else:
            frame['_root_display'] = frame['_system_display']
            root_dimension = 'Sistema'

        total = len(frame)
        leaves = frame.groupby(['_root_display', '_signal_display']).size().reset_index(name='Count')
        leaves['Pct'] = (leaves['Count'] / total * 100) if total else 0.0
        branches = leaves.groupby('_root_display')['Count'].sum().reset_index()
        branches['Pct'] = (branches['Count'] / total * 100) if total else 0.0
        # Familia mode still needs each root's owning system for click-to-filter
        # (customdata) and hover context, even though it's constant here.
        root_system = frame.groupby('_root_display')['_system_display'].first()
        root_colors = _treemap_root_colors(branches['_root_display'])

        ids, labels, parents, values, colors, hover_text, system_values = [], [], [], [], [], [], []
        for _, row in branches.iterrows():
            root = row['_root_display']
            system = root_system.get(root, root)
            ids.append(root)
            labels.append(root)
            parents.append('')
            values.append(int(row['Count']))
            colors.append(root_colors.get(root, PARETO_BAR_COLOR))
            system_values.append(system)
            hover_text.append(
                f"<b>{root_dimension}:</b> {root}<br>"
                f"<b>Alertas:</b> {int(row['Count'])}<br>"
                f"<b>Porcentaje:</b> {row['Pct']:.1f}%"
            )
        for _, row in leaves.iterrows():
            root = row['_root_display']
            signal = row['_signal_display']
            system = root_system.get(root, root)
            ids.append(f'{root}||{signal}')
            labels.append(signal)
            parents.append(root)
            values.append(int(row['Count']))
            colors.append(root_colors.get(root, PARETO_BAR_COLOR))
            system_values.append(system)
            hover_text.append(
                f"<b>{root_dimension}:</b> {root}<br>"
                f"<b>Señal/Variable:</b> {signal}<br>"
                f"<b>Alertas:</b> {int(row['Count'])}<br>"
                f"<b>Porcentaje:</b> {row['Pct']:.1f}%"
            )

        fig = go.Figure(
            go.Treemap(
                ids=ids,
                labels=labels,
                parents=parents,
                values=values,
                branchvalues='total',
                marker=dict(colors=colors),
                customdata=system_values,
                hovertext=hover_text,
                hoverinfo='text',
                texttemplate='%{label}<br>%{value}',
                textfont=dict(size=12),
                maxdepth=2,
                pathbar=dict(visible=True, thickness=18),
            )
        )
        fig.update_layout(
            template='plotly_white',
            height=ALERTS_CHART_HEIGHT,
            margin=dict(l=5, r=5, t=5, b=5),
        )
        logger.info(f"Created system/signal treemap successfully (root dimension: {root_dimension})")
        return fig

    except Exception as e:
        logger.error(f"Error creating system/signal treemap: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )

def _split_gap_segments(df: pd.DataFrame, time_col: str) -> List[pd.DataFrame]:
    """Split a time-sorted dataframe into contiguous chunks wherever the gap
    between consecutive samples exceeds ~3x the series' median sampling
    interval. Used so real data gaps render as a visible break in the line
    instead of a straight connector implying data that doesn't exist.
    """
    if len(df) < 2:
        return [df]
    deltas = df[time_col].diff().dt.total_seconds()
    median_interval = deltas.iloc[1:].median()
    if not median_interval or median_interval <= 0:
        return [df]
    gap_threshold = median_interval * 3
    segment_id = (deltas > gap_threshold).cumsum()
    return [group for _, group in df.groupby(segment_id)]


# Main signal line style (REQ-AD-02): gray, reduced thickness, shared by
# both clients so CDA and Capstone render identically (REQ-AD-01).
SIGNAL_LINE_COLOR = '#95a5a6'
SIGNAL_LINE_WIDTH = 1.3

# Limit lines must stand out against the (now thin, gray) signal line rather
# than blend in with it.
LIMIT_LINE_WIDTH = 3

# Trigger emphasis uses a color reserved for "this is the panel that
# matters" that doesn't collide with any state/limit semantic (green/
# orange/gray/red/purple), so highlighting the trigger never reads as an
# upper-limit cue.
TRIGGER_ACCENT_COLOR = '#2980b9'

# ================================
# NEW GOLDEN LAYER CHART FUNCTIONS
# ================================

def create_sensor_trends_chart_golden(
    alert_data: pd.DataFrame,
    feature_names: List[str],
    unit_id: str,
    alert_time: datetime,
    feature_name_map: Optional[Dict[str, str]] = None,
    client: Optional[str] = None
) -> go.Figure:
    """
    Create multi-panel time series chart using pre-processed golden layer data.
    
    Args:
        alert_data: DataFrame with alert data from golden layer
        feature_names: List of feature names to plot
        unit_id: Unit identifier
        alert_time: Alert timestamp
        feature_name_map: Dictionary mapping feature codes to Spanish names
    
    Returns:
        Plotly Figure with subplots (one per sensor)
    """
    if alert_data.empty or not feature_names:
        logger.warning("Cannot create sensor trends chart: empty data or no features")
        return go.Figure().add_annotation(
            text="No sensor data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    try:
        is_capstone = str(client or '').strip().upper() == 'CAPSTONE'
        # Filter data to M1 minutes before and M2 minutes after alert
        M1 = 90  # minutes before alert
        M2 = 10   # minutes after alert
        time_window_start = alert_time - timedelta(minutes=M1)
        time_window_end = alert_time + timedelta(minutes=M2)
        
        alert_data_filtered = alert_data[
            (alert_data['TimeStart'] >= time_window_start) &
            (alert_data['TimeStart'] <= time_window_end)
        ].copy()
        
        if alert_data_filtered.empty:
            logger.warning(f"No data in time window [{time_window_start}, {time_window_end}]")
            return go.Figure().add_annotation(
                text="No sensor data in time window",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
        
        # Use filtered data for plotting
        alert_data = alert_data_filtered

        # W34-06: the window above compares in UTC-naive (unchanged) — this
        # is the last point that matters. From here on the axis itself is
        # what a person reads, so it — and alert_time, which everything
        # below measures itself against (the highlight box, the trigger
        # lookup by nearest time) — shift to local wall-clock time together.
        # A fixed offset shift does not change relative deltas (gap
        # detection, the +/-30s highlight box width), so nothing downstream
        # needs to know this happened.
        alert_data = alert_data.copy()
        alert_data['TimeStart'] = to_local_naive(alert_data['TimeStart'])
        alert_time = to_local_naive(alert_time)

        # REQ-AD-03: the trigger panel is emphasized by *position* (always
        # first) plus a stronger title -- resolved once, up front.
        trigger_feature = None
        if 'Trigger' in alert_data.columns and not alert_data['Trigger'].empty:
            raw_trigger = alert_data['Trigger'].iloc[0]
            if pd.notna(raw_trigger):
                trigger_feature = str(raw_trigger).strip().casefold()

        # Resolve each panel's columns (incl. Capstone alias fallback) up
        # front so both the ordering below and the plotting loop share the
        # same resolved column names.
        panel_specs = []
        for feature in feature_names:
            value_col = f'{feature}_Value'
            upper_col = f'{feature}_Upper_Limit'
            lower_col = f'{feature}_Lower_Limit'
            display_name = feature_name_map.get(feature, feature) if feature_name_map else feature
            if is_capstone:
                # Capstone may expose the same context signal under the
                # legacy CDA aliases. Prefer the canonical ETL column, but
                # fall back to the alias when the canonical series is empty.
                alias = {'engine_speed_rpm': 'EngSpd', 'engine_load_pct': 'EngLoad'}.get(feature)
                if alias:
                    canonical_has_values = (
                        value_col in alert_data.columns
                        and pd.to_numeric(alert_data[value_col], errors='coerce').notna().any()
                    )
                    if not canonical_has_values and f'{alias}_Value' in alert_data.columns:
                        value_col = f'{alias}_Value'
                        upper_col = f'{alias}_Upper_Limit'
                        lower_col = f'{alias}_Lower_Limit'
            is_trigger = (
                trigger_feature is not None
                and trigger_feature == str(feature).strip().casefold()
            )
            title = f'<b>GATILLO · {display_name}</b>' if is_trigger else display_name

            panel_specs.append(dict(
                feature=feature,
                value_col=value_col,
                upper_col=upper_col,
                lower_col=lower_col,
                display_name=display_name,
                is_trigger=is_trigger,
                title=title,
            ))

        # Emphasize the trigger through position: it always renders as the
        # first time series, ahead of the remaining signals in their
        # original order -- no extra chart decoration needed to spot it.
        panel_specs.sort(key=lambda spec: not spec['is_trigger'])

        subplot_titles = [spec['title'] for spec in panel_specs]

        # Plotly limits vertical_spacing to 1 / (rows - 1). Charts can expose
        # many mapped signals, so keep spacing tight to fit more signals in
        # the first viewport, regardless of client (REQ-AD-01).
        panel_count = len(panel_specs)
        vertical_spacing = 0.1 if panel_count <= 1 else min(0.035, 0.85 / (panel_count - 1))
        fig = make_subplots(
            rows=panel_count,
            cols=1,
            shared_xaxes=True,
            subplot_titles=subplot_titles,
            vertical_spacing=vertical_spacing
        )
        # Only the subplot-title annotations exist at this point; anything
        # added later (e.g. the "Alerta" time labels) must not be swept up
        # by the title-styling loop further down.
        title_annotation_count = len(fig['layout']['annotations'])

        limit_legend_shown = False

        # Plot each feature
        for idx, spec in enumerate(panel_specs, 1):
            feature = spec['feature']
            value_col = spec['value_col']
            upper_col = spec['upper_col']
            lower_col = spec['lower_col']
            display_name = spec['display_name']
            is_trigger_feature = spec['is_trigger']

            if value_col not in alert_data.columns:
                logger.warning("Skipping feature without value column: %s", feature)
                continue
            # One continuous signal per variable, rendered identically for
            # every client (REQ-AD-01). State is retained in hover metadata
            # and represented via explicit legend swatches below.
            value_columns = ['TimeStart', value_col]
            if 'State' in alert_data.columns:
                value_columns.append('State')
            value_data = alert_data[value_columns].copy()
            value_data[value_col] = pd.to_numeric(value_data[value_col], errors='coerce')
            value_data = value_data.dropna(subset=['TimeStart', value_col]).sort_values('TimeStart')
            if value_data.empty:
                continue
            if 'State' not in value_data.columns:
                value_data['State'] = ''
            value_data['_state_label'] = value_data['State'].map(
                lambda state: _state_label(state) if str(state).strip() else ''
            )
            value_data['_state_color'] = value_data['State'].map(
                lambda state: _state_color(state) if str(state).strip() else SIGNAL_LINE_COLOR
            )

            # REQ-AD-03: the trigger panel keeps the same state palette but
            # renders with a heavier line/marker so it reads as "the panel
            # that matters" without recoloring the signal itself.
            line_width = SIGNAL_LINE_WIDTH * 1.8 if is_trigger_feature else SIGNAL_LINE_WIDTH
            marker_size = 8 if is_trigger_feature else 6
            marker_line_width = 1.5 if is_trigger_feature else 1

            # REQ-AD-02: break the line at real time gaps instead of
            # connecting them, by rendering one trace per contiguous segment.
            for segment in _split_gap_segments(value_data, 'TimeStart'):
                fig.add_trace(
                    go.Scatter(
                        x=segment['TimeStart'],
                        y=segment[value_col],
                        mode='lines+markers',
                        name=display_name,
                        showlegend=False,
                        customdata=segment['_state_label'].to_numpy(),
                        marker=dict(
                            size=marker_size,
                            color=segment['_state_color'].to_numpy(),
                            line=dict(width=marker_line_width, color='white')
                        ),
                        line=dict(color=SIGNAL_LINE_COLOR, width=line_width),
                        hovertemplate=(
                            f'<b>{display_name}</b><br>' +
                            'Hora: %{x|%d/%m/%Y %H:%M:%S}<br>' +
                            'Valor: %{y:.2f}<br>' +
                            'Estado: %{customdata}<br>' +
                            '<extra></extra>'
                        )
                    ),
                    row=idx,
                    col=1
                )

            # Highlight rectangle around the alert moment, only on the panel
            # of the feature that actually triggered the alert -- 30s
            # before/after the alert timestamp on the x-axis, and (alert
            # value +/- 1) on the y-axis. Uses the trigger accent color
            # (blue), never red, so it can't be mistaken for the
            # upper-limit semantic.
            if is_trigger_feature:
                time_deltas = (value_data['TimeStart'] - alert_time).abs()
                nearest_idx = time_deltas.idxmin()
                alert_value = value_data.loc[nearest_idx, value_col]
                if pd.notna(alert_value):
                    fig.add_shape(
                        type='rect',
                        x0=alert_time - timedelta(seconds=30),
                        x1=alert_time + timedelta(seconds=30),
                        y0=alert_value - 1,
                        y1=alert_value + 1,
                        line=dict(color=TRIGGER_ACCENT_COLOR, width=3),
                        fillcolor='rgba(41, 128, 185, 0.2)',
                        layer='above',
                        row=idx,
                        col=1
                    )
            # Plot limits (SECONDARY PRIORITY - Visually lighter), also
            # gap-segmented so a missing limit window doesn't draw a
            # straight connector across it.
            for limit_col, limit_label, dash_style in (
                (lower_col, 'Límite Inferior', 'dash'),
                (upper_col, 'Límite Superior', 'dash'),
            ):
                if limit_col not in alert_data.columns or not alert_data[limit_col].notna().any():
                    continue
                limit_data = alert_data[['TimeStart', limit_col]].dropna(subset=[limit_col]).sort_values('TimeStart')
                for segment in _split_gap_segments(limit_data, 'TimeStart'):
                    fig.add_trace(
                        go.Scatter(
                            x=segment['TimeStart'],
                            y=segment[limit_col],
                            mode='lines',
                            name='Límite',
                            legendgroup='limits',
                            showlegend=not limit_legend_shown,
                            line=dict(
                                color='rgba(231, 76, 60, 0.4)',
                                width=LIMIT_LINE_WIDTH,
                                dash=dash_style
                            ),
                            hovertemplate=(
                                limit_label + '<br>' +
                                'Hora: %{x|%d/%m/%Y %H:%M:%S}<br>' +
                                'Valor: %{y:.2f}<br>' +
                                '<extra></extra>'
                            )
                        ),
                        row=idx,
                        col=1
                    )
                    limit_legend_shown = True

        # Add state swatches after the real sensor traces so they cannot
        # interfere with the first subplot's data rendering (both clients,
        # REQ-AD-01).
        state_values = alert_data.get(
            'State', pd.Series(index=alert_data.index, dtype='object')
        ).fillna('').astype(str)
        seen_states = []
        for raw_state in state_values.tolist():
            if raw_state and raw_state not in seen_states:
                seen_states.append(raw_state)
        for raw_state in reversed(seen_states):
            state_label = _state_label(raw_state)
            fig.add_trace(
                go.Scatter(
                    x=[None],
                    y=[None],
                    mode='markers',
                    name=state_label,
                    legendgroup=raw_state,
                    marker=dict(
                        size=8,
                        color=_state_color(raw_state),
                        line=dict(width=1, color='white')
                    ),
                    hoverinfo='skip',
                    showlegend=True
                ),
                row=1,
                col=1
            )

        # Update layout with proper spacing and horizontal legend at the
        # bottom (below the last subplot's x-axis labels). Compact
        # per-panel height/margins so more signals fit in the first
        # viewport, while staying readable for markers and hover targets.
        fig.update_layout(
            height=150 + 130 * panel_count,
            template='plotly_white',
            showlegend=True,  # Show legend for state colors and limits
            legend=dict(
                orientation='h',  # Horizontal orientation
                traceorder='reversed',
                yanchor='top',
                y=-0.06,
                xanchor='center',
                x=0.5,
                entrywidth=90,
                entrywidthmode='pixels',
                font=dict(size=10),
                bgcolor='rgba(255, 255, 255, 0.9)',
                bordercolor='#e0e0e0',
                borderwidth=1
            ),
            margin=dict(l=55, r=25, t=30, b=60),
            hovermode='x unified',
        )

        # The alert-context header (above the card) and subplot titles
        # identify the chart; avoid a second global title covering the
        # first panel or the legend (both clients, REQ-AD-01).
        fig.layout.title = None

        # Add alert time vertical lines as shapes (full height in each
        # subplot), each carrying a visible "Alerta" label so the reference
        # is unambiguous on every panel.
        for idx in range(1, panel_count + 1):
            xref = 'x' if idx == 1 else f'x{idx}'
            yref = 'y' if idx == 1 else f'y{idx}'
            fig.add_shape(
                type='line',
                x0=alert_time,
                x1=alert_time,
                y0=0,
                y1=1,
                yref=f'{yref} domain',
                line=dict(color='rgba(128, 128, 128, 0.6)', width=2.5, dash='dot'),
                row=idx,
                col=1
            )
            fig.add_annotation(
                x=alert_time,
                y=1,
                xref=xref,
                yref=f'{yref} domain',
                text='Alerta',
                showarrow=False,
                xanchor='left',
                yanchor='top',
                font=dict(size=9, color='#7f8c8d', family='Arial, sans-serif'),
                bgcolor='rgba(255, 255, 255, 0.75)',
                borderpad=1
            )

        # Update subplot backgrounds for better separation. Trigger
        # emphasis comes from position (first panel) and the title, not
        # from a per-panel highlight, so every panel shares the same
        # subtle background.
        for idx in range(1, panel_count + 1):
            xref = 'x' if idx == 1 else f'x{idx}'
            yref = 'y' if idx == 1 else f'y{idx}'

            fig.add_shape(
                type='rect',
                xref=f'{xref} domain',
                yref=f'{yref} domain',
                x0=0, x1=1,
                y0=0, y1=1,
                fillcolor='rgba(248, 249, 250, 0.5)',
                layer='below',
                line_width=0,
                row=idx,
                col=1
            )

        # Update x and y axes for better readability
        fig.update_xaxes(
            showgrid=True,
            gridwidth=1,
            gridcolor='rgba(220, 220, 220, 0.5)',
            showline=True,
            linewidth=1,
            linecolor='#e0e0e0'
        )
        
        fig.update_yaxes(
            showgrid=True,
            gridwidth=1,
            gridcolor='rgba(220, 220, 220, 0.5)',
            showline=True,
            linewidth=1,
            linecolor='#e0e0e0',
            title_font=dict(size=11)
        )
        
        # Style subplot titles (annotations). Only the first
        # `title_annotation_count` annotations are subplot titles -- the
        # "Alerta" time labels added above keep their own smaller styling
        # and must not be swept up here. The trigger panel gets a bolder,
        # accent-colored title (REQ-AD-03: stronger title).
        for i, annotation in enumerate(fig['layout']['annotations'][:title_annotation_count]):
            is_trigger = panel_specs[i]['is_trigger']
            annotation['font'] = (
                dict(size=14, color=TRIGGER_ACCENT_COLOR, family='Arial, sans-serif')
                if is_trigger
                else dict(size=12, color='#2c3e50', family='Arial, sans-serif')
            )
            annotation['xanchor'] = 'center'
            annotation['yanchor'] = 'bottom'

        logger.info(f"Created sensor trends chart (golden layer) with {len(feature_names)} features")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating sensor trends chart (golden layer): {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_gps_route_map_golden(
    alert_data: pd.DataFrame,
    unit_id: str,
    alert_time: datetime,
    mapbox_token: str
) -> go.Figure:
    """
    Create GPS route map using pre-processed golden layer data.
    
    Args:
        alert_data: DataFrame with GPS data from golden layer
        unit_id: Unit identifier
        alert_time: Alert timestamp
        mapbox_token: Mapbox access token
    
    Returns:
        Plotly Figure with GPS map
    """
    if alert_data.empty:
        logger.warning("Cannot create GPS map: empty data")
        return go.Figure().add_annotation(
            text="No GPS data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Filter data to M1 minutes before alert (GPS shows route only up to alert time)
        M1 = 90  # minutes before alert
        time_window_start = alert_time - timedelta(minutes=M1)
        
        alert_data_filtered = alert_data[
            (alert_data['TimeStart'] >= time_window_start) &
            (alert_data['TimeStart'] <= alert_time)
        ].copy()
        alert_data_filtered.sort_values('TimeStart', inplace=True)
        
        # Filter GPS data
        gps_data = alert_data_filtered.dropna(subset=['GPSLat', 'GPSLon']).copy()
        
        if gps_data.empty:
            logger.warning("No GPS data with valid coordinates")
            return go.Figure().add_annotation(
                text="No GPS data with valid coordinates",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
        
        # Normalize time for color gradient
        time_min = gps_data['TimeStart'].min()
        time_max = gps_data['TimeStart'].max()
        
        if time_max > time_min:
            gps_data['TimeNorm'] = (gps_data['TimeStart'] - time_min) / (time_max - time_min)
        else:
            gps_data['TimeNorm'] = 0.5
        
        # Create map
        fig = go.Figure()
        
        # Add route line with subtle gray color for better contrast against satellite background
        fig.add_trace(go.Scattermapbox(
            lat=gps_data['GPSLat'],
            lon=gps_data['GPSLon'],
            mode='lines',
            line=dict(width=2, color='rgba(100, 100, 100, 0.5)'),
            showlegend=False,
            hoverinfo='skip'
        ))
        
        # Find alert point (closest to alert_time)
        alert_idx = (gps_data['TimeStart'] - alert_time).abs().argmin()
        alert_point = gps_data.iloc[alert_idx]
        
        # Add all non-alert points with single blue color (use boolean masking to avoid index issues)
        alert_point_index = gps_data.index[alert_idx]
        non_alert_gps = gps_data[gps_data.index != alert_point_index]
        if not non_alert_gps.empty:
            fig.add_trace(go.Scattermapbox(
                lat=non_alert_gps['GPSLat'],
                lon=non_alert_gps['GPSLon'],
                mode='markers',
                marker=dict(
                    size=10,
                    color="#ea6648",  # Light red color for non-alert points
                ),
                showlegend=False,
                # W34-06: local wall-clock time in the hover text. The map
                # has no time axis to keep visually aligned (unlike the
                # sensor-trends chart), so converting only at the display
                # site here is enough — the windowing/closest-point math
                # above stays in UTC-naive, unchanged.
                text=to_local_naive(non_alert_gps['TimeStart']).dt.strftime('%H:%M:%S'),
                hovertemplate='Hora: %{text}<extra></extra>'
            ))
        
        # Add white border circle first (bottom layer) for alert point
        fig.add_trace(go.Scattermapbox(
            lat=[alert_point['GPSLat']],
            lon=[alert_point['GPSLon']],
            mode='markers',
            marker=dict(
                size=35,
                color='white',
                opacity=0.9,
                symbol='circle',
                allowoverlap=True
            ),
            showlegend=False,
            hoverinfo='skip'
        ))
        
        # Add red circle on top for alert point
        fig.add_trace(go.Scattermapbox(
            lat=[alert_point['GPSLat']],
            lon=[alert_point['GPSLon']],
            mode='markers',
            marker=dict(
                size=25,
                color='red',
                symbol='circle',
                allowoverlap=True
            ),
            showlegend=False,
            text=[f"⚠️ Alerta: {to_local_naive(alert_time).strftime('%H:%M:%S')}"],
            hovertemplate='%{text}<extra></extra>'
        ))
        
        fig.update_layout(
            mapbox=dict(
                accesstoken=mapbox_token,
                style="satellite-streets",
                center=dict(
                    lat=gps_data['GPSLat'].mean(),
                    lon=gps_data['GPSLon'].mean()
                ),
                zoom=14
            ),
            title=None,
            height=600,
            margin=dict(l=0, r=0, t=10, b=0),
            showlegend=False
        )
        
        logger.info(f"Created GPS route map (golden layer) with {len(gps_data)} points")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating GPS route map (golden layer): {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def _first_numeric_context_value(alert_point: pd.Series, column_names: List[str]) -> Optional[float]:
    """Return the first non-null numeric context value from candidate columns."""
    for column_name in column_names:
        if column_name not in alert_point.index:
            continue

        raw_value = alert_point[column_name]
        if pd.isna(raw_value):
            continue

        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            logger.warning(
                "Ignoring non-numeric context value in %s: %r",
                column_name,
                raw_value,
            )
            continue

        if pd.notna(value):
            logger.info("Found context value in column: %s with value: %s", column_name, value)
            return value

    return None


def create_context_kpis_cards_golden(
    alert_data: pd.DataFrame,
    alert_time: pd.Timestamp,
    trigger: str
) -> dbc.Row:
    """
    Create KPI cards using pre-processed golden layer data.
    Shows 4 KPIs: Elevación, Carga (Payload), Carga de Motor, Velocidad de Motor.
    
    Args:
        alert_data: DataFrame with golden layer data
        alert_time: Alert timestamp
        trigger: Trigger feature name
    
    Returns:
        Bootstrap Row with 4 KPI cards
    """
    if alert_data.empty:
        return dbc.Alert("No hay datos de contexto disponibles", color="info")
    
    try:
        # Sort by time
        alert_data = alert_data.sort_values('TimeStart').reset_index(drop=True)
        
        # Find point closest to alert time
        alert_data['time_diff'] = abs((alert_data['TimeStart'] - alert_time).dt.total_seconds())
        alert_idx = alert_data['time_diff'].idxmin()
        alert_point = alert_data.iloc[alert_idx]
        
        # KPI 1: Elevación
        elevation_status = "➡️ Plano"
        elevation_color = "secondary"
        
        if 'GPSElevation' in alert_data.columns:
            before_data = alert_data[alert_data['TimeStart'] < alert_time]
            after_data = alert_data[alert_data['TimeStart'] >= alert_time]
            
            if not before_data.empty and not after_data.empty:
                elevation_before = before_data['GPSElevation'].tail(5).mean()
                elevation_after = after_data['GPSElevation'].head(5).mean()
                
                if pd.notna(elevation_before) and pd.notna(elevation_after):
                    gradient = (elevation_after - elevation_before) / 5
                    
                    if gradient > 0.05:
                        elevation_status = "⬆️ Subiendo"
                        elevation_color = "info"
                    elif gradient < -0.05:
                        elevation_status = "⬇️ Bajando"
                        elevation_color = "warning"
        
        # KPI 2: Carga (Payload)
        payload_value = alert_point.get('Payload_Value', 'N/A')
        if pd.isna(payload_value):
            payload_value = 'N/A'
        else:
            # Round to 0 decimals if numeric
            try:
                payload_value = f"{float(payload_value):.0f} t"
            except:
                pass
        payload_status = f"📦 {payload_value}"
        payload_color = "primary"
        
        # KPI 3: Carga de Motor (EngLoad)
        engine_load = "N/A"
        load_color = "secondary"
        
        # Log available columns for debugging
        logger.info(f"Available columns for KPI: {list(alert_point.index)[:10]}...")  # First 10 columns
        
        # Capstone publishes canonical snake_case signals and may also carry
        # the legacy aliases. Prefer the canonical contract, while retaining
        # the aliases used by the CDA golden layer.
        engload_cols = [
            'engine_load_pct_Value',
            'EngLoad_Value',
            'engine_load_pct',
            'EngLoad',
            'Engine Load',
            'EngineLoad',
        ]
        engload_value = _first_numeric_context_value(alert_point, engload_cols)
        
        if engload_value is not None:
            engine_load = f"⚙️ {engload_value:.0f}%"
            
            # Color based on load level
            if engload_value < 50:
                load_color = "success"
            elif engload_value < 80:
                load_color = "warning"
            else:
                load_color = "danger"
        else:
            logger.warning("EngLoad_Value not found in data or is NaN")
        
        # KPI 4: Velocidad de Motor (EngSpd)
        engine_rpm = "N/A"
        rpm_color = "success"
        
        rpm_value = _first_numeric_context_value(
            alert_point,
            [
                'engine_speed_rpm_Value',
                'EngSpd_Value',
                'engine_speed_rpm',
                'EngSpd',
            ],
        )
        if rpm_value is not None:
            engine_rpm = f"🏎️ {rpm_value:.0f} RPM"
        
        # Create 4 KPI cards in vertical layout (1 column x 4 rows)
        return html.Div([
            # Row 1: Elevación
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H6("Elevación", className="text-muted mb-2 text-uppercase", 
                                   style={'fontSize': '0.85rem'}),
                            html.H5(elevation_status, className=f"text-{elevation_color} mb-0")
                        ])
                    ], color=elevation_color, outline=True, className="text-center")
                ], md=12)
            ], className="mb-3"),
            
            # Row 2: Carga
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H6("Carga", className="text-muted mb-2 text-uppercase",
                                   style={'fontSize': '0.85rem'}),
                            html.H5(payload_status, className=f"text-{payload_color} mb-0")
                        ])
                    ], color=payload_color, outline=True, className="text-center")
                ], md=12)
            ], className="mb-3"),
            
            # Row 3: Carga de Motor
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H6("Carga de Motor", className="text-muted mb-2 text-uppercase",
                                   style={'fontSize': '0.85rem'}),
                            html.H5(engine_load, className=f"text-{load_color} mb-0")
                        ])
                    ], color=load_color, outline=True, className="text-center")
                ], md=12)
            ], className="mb-3"),
            
            # Row 4: Velocidad Motor
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H6("Velocidad Motor", className="text-muted mb-2 text-uppercase",
                                   style={'fontSize': '0.85rem'}),
                            html.H5(engine_rpm, className=f"text-{rpm_color} mb-0")
                        ])
                    ], color=rpm_color, outline=True, className="text-center")
                ], md=12)
            ])
        ])
    
    except Exception as e:
        logger.error(f"Error creating context KPIs (golden): {e}")
        return dbc.Alert(f"Error al crear KPIs de contexto: {str(e)}", color="danger")