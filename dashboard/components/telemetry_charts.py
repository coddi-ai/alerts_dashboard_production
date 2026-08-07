"""
Chart components for Telemetry Health Dashboard.

Plotly figure builders for fleet heatmap and signal time series cards.
"""

import pandas as pd
import numpy as np
import yaml
from pathlib import Path
from typing import Optional, Dict
from functools import lru_cache

import plotly.graph_objects as go
from plotly.subplots import make_subplots

STATUS_COLORS = {
    'Normal': '#2ecc71',
    'Alerta': '#f39c12',
    'Anormal': '#e74c3c',
    'InsufficientData': '#95a5a6'
}

# Defined once in src/charts/signals.py so this tab, the alerts tab and Campbell AI
# all use the same code -> Spanish description; re-exported here for existing
# importers (translate_signal() below).
from src.charts.signals import SIGNAL_LABELS as SIGNAL_TRANSLATION

TREND_TRANSLATION = {
    'worsening': 'En deterioro',
    'improving': 'Mejorando',
    'drifting': 'Con deriva',
    'stable': 'Estable',
}

# English → Spanish system name translation
SYSTEM_TRANSLATION = {
    'Engine': 'Motor',
    'Transmission': 'Transmisión',
    'Brakes': 'Frenos',
    'Steering': 'Dirección',
}


def translate_system(name: str) -> str:
    """Translate system name from English to Spanish."""
    return SYSTEM_TRANSLATION.get(name, name)


def translate_signal(name: str, fallback: Optional[str] = None) -> str:
    """Return the client-facing Spanish name for a technical signal."""
    return SIGNAL_TRANSLATION.get(name, SIGNAL_TRANSLATION.get(fallback, fallback or name))


def translate_trend(name: str) -> str:
    """Translate materialized trend interpretations for the report UI."""
    return TREND_TRANSLATION.get(str(name), str(name or '-'))


@lru_cache(maxsize=1)
def load_signal_registry(client: str = 'cda') -> Dict[str, str]:
    """Load signal registry and return name → display_name mapping."""
    path = Path(f'data/telemetry/config/{client}/signal_registry.yaml')
    if not path.exists():
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return {
        s['name']: translate_signal(s['name'], s.get('display_name'))
        for s in data.get('signals', [])
        if s.get('name')
    }


def _empty_figure(message: str = "Sin datos disponibles") -> go.Figure:
    """Create an empty figure with a centered message."""
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper", yref="paper",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=14, color='gray')
    )
    fig.update_layout(xaxis=dict(visible=False), yaxis=dict(visible=False), height=300)
    return fig


def build_fleet_heatmap(system_health_df: pd.DataFrame, unit_health_df: pd.DataFrame) -> go.Figure:
    """
    Build system health heatmap (Units rows × Systems cols) with unit status column.

    Sorted by priority score (worst at top). Includes overall_status as last column.
    """
    if system_health_df.empty:
        return _empty_figure("Sin datos de sistemas disponibles")

    # Join priority and status for sorting
    priority_map = {}
    status_map_units = {}
    if not unit_health_df.empty:
        if 'priority_score' in unit_health_df.columns:
            priority_map = unit_health_df.set_index('unit')['priority_score'].to_dict()
        if 'overall_status' in unit_health_df.columns:
            status_map_units = unit_health_df.set_index('unit')['overall_status'].to_dict()

    # Translate system names
    df = system_health_df.copy()
    df['system_es'] = df['system'].map(translate_system)

    # Keep the materialized score only for ordering upstream. The client sees
    # the existing health state, not the internal numerical score.
    status_map_sys = df.pivot_table(
        index='unit', columns='system_es', values='system_status', aggfunc='first'
    )
    status_numeric = {'InsufficientData': 0, 'Normal': 1, 'Alerta': 2, 'Anormal': 3}
    pivot = status_map_sys.map(lambda value: status_numeric.get(value, 0))

    # Sort by priority (descending = worst at top)
    pivot['_priority'] = pivot.index.map(lambda u: priority_map.get(u, 0))
    pivot = pivot.sort_values('_priority', ascending=False).drop(columns='_priority')

    # Add Estado column using the same categorical scale as system cells.
    status_numeric = {'InsufficientData': 0, 'Normal': 1, 'Alerta': 2, 'Anormal': 3}
    pivot['Estado'] = pivot.index.map(
        lambda u: status_numeric.get(status_map_units.get(u, 'Normal'), 0)
    )

    # Build custom hover text
    hover_text = []
    for unit in pivot.index:
        row_hover = []
        for sys in pivot.columns:
            if sys == 'Estado':
                unit_status = status_map_units.get(unit, 'Normal')
                row_hover.append(f"<b>{unit}</b><br>Estado General: {unit_status}")
            else:
                status = status_map_sys.loc[unit, sys] if unit in status_map_sys.index and sys in status_map_sys.columns else ''
                row_hover.append(
                    f"<b>{unit}</b> — {sys}<br>Estado: {status}"
                    if pd.notna(pivot.loc[unit, sys]) else ""
                )
        hover_text.append(row_hover)

    # Semantic color scale (soft, professional)
    z_values = pivot.values
    colorscale = [
        [0.00, '#95a5a6'],
        [0.01, '#95a5a6'],
        [0.34, '#f0fff4'],
        [0.35, '#f0fff4'],
        [0.67, '#fef3cd'],
        [0.68, '#fef3cd'],
        [1.00, '#f8d7da'],
    ]

    fig = go.Figure(data=go.Heatmap(
        z=z_values,
        x=pivot.columns.tolist(),
        y=pivot.index.tolist(),
        colorscale=colorscale,
        zmin=0,
        zmax=3,
        texttemplate='%{text}',
        text=pivot.map(lambda value: {0: 'Sin evidencia', 1: 'Normal', 2: 'Alerta', 3: 'Anormal'}.get(value, '')).values,
        textfont=dict(size=11, color='#1a252f'),
        hovertext=hover_text,
        hoverinfo='text',
        xgap=2,
        ygap=2,
        colorbar=dict(
            title=dict(text="Estado", font=dict(size=11)),
            thickness=12,
            len=0.9,
            tickvals=[0, 1, 2, 3],
            ticktext=["Sin evidencia", "Normal", "Alerta", "Anormal"],
            tickfont=dict(size=10),
        )
    ))

    fig.update_layout(
        height=max(280, 48 * len(pivot)),
        margin=dict(t=10, b=30, l=70, r=60),
        xaxis=dict(side='top', tickangle=0, tickfont=dict(size=12, color='#1a252f')),
        yaxis=dict(autorange='reversed', tickfont=dict(size=11, color='#1a252f')),
        plot_bgcolor='white',
        paper_bgcolor='white',
    )
    return fig


def build_heatmap_insights(system_health_df: pd.DataFrame, unit_health_df: pd.DataFrame) -> dict:
    """
    Extract insight KPIs for the heatmap header.

    Returns dict with client-facing status insights. Internal scores are not
    returned for display.
    """
    insights = {
        'most_risky_unit': '-',
        'most_critical_system': '-',
        'most_critical_status': '-',
    }

    if unit_health_df.empty:
        return insights

    # Most risky unit
    top_unit = unit_health_df.sort_values('priority_score', ascending=False).iloc[0]
    insights['most_risky_unit'] = top_unit['unit']

    # Most critical system (highest system_score)
    if not system_health_df.empty:
        top_sys = system_health_df.sort_values('system_score', ascending=False).iloc[0]
        insights['most_critical_system'] = translate_system(top_sys['system'])
        insights['most_critical_status'] = top_sys.get('system_status', '-')

    return insights


def build_signal_timeseries_card(
    signal_name: str,
    raw_df: pd.DataFrame,
    limits_df: pd.DataFrame,
    trend_df: pd.DataFrame,
    unit: Optional[str] = None,
    events_df: Optional[pd.DataFrame] = None,
) -> go.Figure:
    """
    Build time series figure for a single signal.

    Includes the existing signal series, baseline limits and significant trend.
    Materialized event intervals are added as presentation overlays; no new
    anomaly or risk calculation is performed here.

    Args:
        signal_name: Column name in raw_df
        raw_df: Silver telemetry filtered to one unit
        limits_df: Limits/baselines with Unit/Signal/EstadoMaquina/P2/P5/P95/P98
        trend_df: Trend results for this unit+signal
        unit: Unit identifier for limits lookup
        events_df: Materialized events for the selected unit/signal.
    """
    if raw_df.empty or signal_name not in raw_df.columns:
        return _empty_figure(f"Sin datos para {signal_name}")

    required = [col for col in ('Fecha', signal_name) if col in raw_df.columns]
    if len(required) < 2:
        return _empty_figure(f"Sin datos para {signal_name}")
    df = raw_df[required].dropna(subset=[signal_name]).copy()
    df['Fecha'] = pd.to_datetime(df['Fecha'], errors='coerce')
    df = df.dropna(subset=['Fecha']).sort_values('Fecha')

    if df.empty:
        return _empty_figure(f"Sin datos válidos para {signal_name}")

    # Calculate on the full materialized series, then thin only plotted points
    # to keep the browser responsive for the multi-week silver window.
    # Use a time-based window so the 120-minute label remains correct with gaps.
    df = df.set_index('Fecha')
    df['rolling_mean'] = df[signal_name].rolling('120min', min_periods=5).mean()
    df = df.reset_index()
    max_points = 6000
    step = max(1, int(len(df) / max_points))
    plot_df = df.iloc[::step].copy()

    fig = go.Figure()

    # Keep the raw trace visible so excursions can be compared with the
    # existing rolling mean and limits.
    fig.add_trace(go.Scatter(
        x=plot_df['Fecha'],
        y=plot_df[signal_name],
        mode='lines',
        name='Valor de la señal',
        line=dict(color='#8c9aa6', width=1),
        opacity=0.55,
        hovertemplate='%{x}<br>Valor: %{y:.2f}<extra></extra>'
    ))

    # Main signal line (rolling mean)
    fig.add_trace(go.Scatter(
        x=plot_df['Fecha'],
        y=plot_df['rolling_mean'],
        mode='lines',
        name='Media móvil 30min',
        line=dict(color='#2c3e50', width=1.5),
        hovertemplate='%{x}<br>Valor: %{y:.2f}<extra></extra>'
    ))

    fig.data[-1].name = 'Media móvil 120 min'

    # Event/anomaly overlays use only the existing event labels and periods.
    event_windows, anomaly_count, event_count = _event_windows(events_df, signal_name)
    raw_start, raw_end = df['Fecha'].min(), df['Fecha'].max()
    event_windows = [
        {**window, 'start': max(window['start'], raw_start), 'end': min(window['end'], raw_end)}
        for window in event_windows
        if window['end'] >= raw_start and window['start'] <= raw_end
    ]
    event_colors = {
        'anomaly': ('#c1121f', 'Anomal\u00eda'),
        'event': ('#f59e0b', 'Evento'),
    }
    # Build all event windows in one layout update. Calling add_vrect once per
    # window causes Plotly to revalidate the complete figure hundreds of times
    # when a signal has many materialized episodes.
    event_shapes = []
    for window in event_windows:
        color, _ = event_colors[window['kind']]
        event_shapes.append({
            'type': 'rect',
            'xref': 'x',
            'yref': 'paper',
            'x0': window['start'],
            'x1': window['end'],
            'y0': 0,
            'y1': 1,
            'fillcolor': color,
            'opacity': 0.14 if window['kind'] == 'event' else 0.2,
            'line': {'color': color, 'width': 1},
            'layer': 'below',
        })
    if event_shapes:
        fig.update_layout(shapes=event_shapes)
    # Mark materialized samples so short episodes remain visible when the
    # chart starts with a multi-week range. Counts stay in the signal KPI table,
    # not in this legend.
    plot_times = pd.DatetimeIndex(plot_df['Fecha'])
    for kind in ('anomaly', 'event'):
        color, label = event_colors[kind]
        windows = [window for window in event_windows if window['kind'] == kind]
        if windows and len(plot_times):
            # Convert intervals into a boolean coverage mask with cumulative
            # boundaries.  This avoids filtering the complete plotted series
            # once per event window when a signal has many episodes.
            starts = plot_times.searchsorted(
                pd.to_datetime([window['start'] for window in windows]), side='left'
            )
            ends = plot_times.searchsorted(
                pd.to_datetime([window['end'] for window in windows]), side='right'
            )
            diff = np.zeros(len(plot_times) + 1, dtype=np.int32)
            for start_idx, end_idx in zip(starts, ends):
                diff[start_idx] += 1
                diff[end_idx] -= 1
            point_mask = np.cumsum(diff[:-1]) > 0
            point_df = plot_df.loc[point_mask, ['Fecha', signal_name]].rename(
                columns={signal_name: 'value'}
            )
        else:
            point_df = pd.DataFrame()
        if not point_df.empty:
            fig.add_trace(go.Scatter(
                x=point_df['Fecha'], y=point_df['value'], mode='markers', name=label,
                marker=dict(size=6, color=color, symbol='square', line=dict(width=0.5, color='white')),
                hovertemplate=f'{label}<br>%{{x}}<br>Valor: %{{y:.2f}}<extra></extra>',
            ))

    latest_observed = df['Fecha'].max()
    # Open on the longest materialized episode: this chart exists to show signal
    # evidence, and defaulting to the latest three days hides an episode that
    # happened earlier. Fall back to that recent window when there is no episode.
    # The range selector can still expand the view either way.
    episode_start = _max_episode_start(events_df, signal_name)
    recent_start = max(df['Fecha'].min(), latest_observed - pd.Timedelta(days=3))
    if episode_start is not None and df['Fecha'].min() <= episode_start <= latest_observed:
        initial_start = episode_start
    else:
        initial_start = recent_start

    # Limits reference lines (from limits or baselines)
    if not limits_df.empty and unit:
        # Support both column naming conventions
        unit_col = 'Unit' if 'Unit' in limits_df.columns else 'unit'
        signal_col = 'Signal' if 'Signal' in limits_df.columns else 'signal'
        state_col = 'EstadoMaquina' if 'EstadoMaquina' in limits_df.columns else 'state'

        bl = limits_df[
            (limits_df[unit_col] == unit) &
            (limits_df[signal_col] == signal_name)
        ]
        # Prefer 'Operacional' states (match prefix or exact)
        if not bl.empty:
            op_mask = bl[state_col].astype(str).str.startswith('Operacional') if state_col in bl.columns else pd.Series(False, index=bl.index)
            if op_mask.any():
                bl = bl[op_mask]
            # If multiple operational states, take the one with highest sample_count
            if len(bl) > 1 and 'sample_count' in bl.columns:
                bl = bl.sort_values('sample_count', ascending=False)
            bl_row = bl.iloc[0]
            x_range = [df['Fecha'].min(), df['Fecha'].max()]

            if 'P95' in bl_row.index and pd.notna(bl_row['P95']):
                fig.add_trace(go.Scatter(
                    x=x_range, y=[bl_row['P95']] * 2,
                    mode='lines', name='P95',
                    line=dict(color='#9bbbd0', dash='dash', width=1),
                    legendrank=3,
                    showlegend=True
                ))
            if 'P98' in bl_row.index and pd.notna(bl_row['P98']):
                fig.add_trace(go.Scatter(
                    x=x_range, y=[bl_row['P98']] * 2,
                    mode='lines', name='P98',
                    line=dict(color='#527d9c', dash='dash', width=1),
                    legendrank=4,
                    showlegend=True
                ))
            if 'P5' in bl_row.index and pd.notna(bl_row['P5']):
                fig.add_trace(go.Scatter(
                    x=x_range, y=[bl_row['P5']] * 2,
                    mode='lines', name='P5',
                    line=dict(color='#b8cad8', dash='dash', width=1),
                    legendrank=2,
                    showlegend=True
                ))
            if 'P2' in bl_row.index and pd.notna(bl_row['P2']):
                fig.add_trace(go.Scatter(
                    x=x_range, y=[bl_row['P2']] * 2,
                    mode='lines', name='P2',
                    line=dict(color='#789bb5', dash='dash', width=1),
                    legendrank=1,
                    showlegend=True
                ))

    # Trend line overlay (if significant worsening trend)
    if not trend_df.empty:
        sig_trends = trend_df[
            (trend_df['is_significant'] == True) &
            (trend_df['is_good_fit'] == True)
        ]
        if not sig_trends.empty:
            best = sig_trends.sort_values('r2', ascending=False).iloc[0]
            interp = best.get('trend_interpretation', '')
            color = '#e74c3c' if interp == 'worsening' else '#2ecc71'
            if 'start_time' in best.index and 'end_time' in best.index:
                trend_start = pd.to_datetime(best['start_time'])
                trend_end = pd.to_datetime(best['end_time'])
                x_trend = [trend_start, trend_end]
                slope = best['slope_per_day']
                days = (trend_end - trend_start).total_seconds() / 86400
                y_start = df['rolling_mean'].dropna().iloc[0] if len(df['rolling_mean'].dropna()) > 0 else 0
                y_trend = [y_start, y_start + slope * days]
                fig.add_trace(go.Scatter(
                    x=x_trend, y=y_trend,
                    mode='lines',
                    name=f'Tendencia ({translate_trend(interp)})',
                    line=dict(color=color, dash='dot', width=2)
                ))

    values = pd.to_numeric(df[signal_name], errors='coerce').dropna()
    p1 = float(values.quantile(0.01)) if not values.empty else None
    p99 = float(values.quantile(0.99)) if not values.empty else None
    if p1 is not None and p99 is not None:
        spread = p99 - p1 if p99 > p1 else max(abs(p99), 1.0)
        y_range = [p1 - spread * 0.05, p99 + spread * 0.05]
    else:
        y_range = None

    fig.update_layout(
        # La serie es la evidencia principal: reservamos una altura amplia
        # para que las excursiones, limites y ventanas de eventos sean legibles.
        height=620,
        margin=dict(t=88, b=72, l=55, r=20),
        xaxis_title="",
        xaxis=dict(
            range=[initial_start, latest_observed] if initial_start is not None else None,
            autorange=False if initial_start is not None else True,
            rangeslider=dict(visible=True, thickness=0.08),
            rangeselector=dict(
                buttons=[
                    dict(count=7, label='Última semana', step='day', stepmode='backward'),
                    dict(count=14, label='Últimas 2 semanas', step='day', stepmode='backward'),
                    dict(count=1, label='Último mes', step='month', stepmode='backward'),
                ],
                x=0,
                y=1.16,
                xanchor='left',
            ),
        ),
        yaxis_title="Valor",
        yaxis=dict(range=y_range, autorange=y_range is None),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        hovermode='x unified'
    )
    overlay_summary = (
        f"Anomalías: {anomaly_count} · Eventos: {event_count}"
        if anomaly_count or event_count else "Sin anomalías ni eventos registrados"
    )
    fig.add_annotation(
        xref='paper', yref='paper', x=0, y=1.22,
        text=overlay_summary, showarrow=False, xanchor='left',
        font=dict(size=11, color='#495057'),
        bgcolor='#f8f9fa', bordercolor='#dee2e6', borderwidth=1,
    )
    fig.layout.annotations = []
    return fig


def _event_windows(events_df: Optional[pd.DataFrame], signal_name: str):
    """Return merged display windows and counts for materialized events."""
    if events_df is None or events_df.empty:
        return [], 0, 0
    events = events_df.copy()
    signal_col = 'signal' if 'signal' in events.columns else 'feature'
    if signal_col in events.columns:
        expected = str(signal_name).strip().casefold()
        events = events[events[signal_col].astype(str).str.strip().str.casefold() == expected]
    if events.empty or 'start_time' not in events.columns:
        return [], 0, 0
    events['start'] = pd.to_datetime(events['start_time'], errors='coerce')
    end_source = events['end_time'] if 'end_time' in events.columns else events['start_time']
    events['end'] = pd.to_datetime(end_source, errors='coerce')
    events['end'] = events['end'].fillna(events['start'])
    events = events.dropna(subset=['start']).sort_values('start')
    if events.empty:
        return [], 0, 0

    binary_labels = events.get(
        'event_type_binary', pd.Series('', index=events.index)
    ).fillna('').astype(str)
    weighted_labels = events.get(
        'event_type_weighted', pd.Series('', index=events.index)
    ).fillna('').astype(str)
    # Vectorized classification avoids a Python-level apply over potentially
    # hundreds of thousands of materialized episodes.
    events['kind'] = np.where(
        binary_labels.str.cat(weighted_labels, sep=' ').str.contains('anomal', case=False, na=False),
        'anomaly',
        'event',
    )
    anomaly_count = int((events['kind'] == 'anomaly').sum())
    event_count = int((events['kind'] == 'event').sum())
    windows = []
    # Merge touching intervals by type to keep the plot legible while retaining
    # the total event counts in the legend and annotation.
    for event_kind, group in events.groupby('kind', sort=False):
        current = None
        for row in group.sort_values('start').itertuples(index=False):
            start, end = row.start, row.end
            if current is None or start > current['end'] + pd.Timedelta(minutes=2):
                if current is not None:
                    windows.append(current)
                current = {'start': start, 'end': end, 'kind': event_kind}
            else:
                current['end'] = max(current['end'], end)
        if current is not None:
            windows.append(current)
    return sorted(windows, key=lambda item: item['start']), anomaly_count, event_count


def _max_episode_start(events_df: Optional[pd.DataFrame], signal_name: str):
    """Get the start of the longest existing episode for the selected signal."""
    if events_df is None or events_df.empty or 'start_time' not in events_df.columns:
        return None
    events = events_df.copy()
    signal_col = 'signal' if 'signal' in events.columns else 'feature'
    if signal_col in events.columns:
        expected = str(signal_name).strip().casefold()
        events = events[events[signal_col].astype(str).str.strip().str.casefold() == expected]
    if events.empty:
        return None
    duration_col = 'duration_minutes' if 'duration_minutes' in events.columns else None
    if duration_col:
        events = events.sort_values(duration_col, ascending=False, na_position='last')
    start = pd.to_datetime(events.iloc[0].get('start_time'), errors='coerce')
    return None if pd.isna(start) else start
