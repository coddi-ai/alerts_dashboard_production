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

SIGNAL_TRANSLATION = {
    'EngCoolTemp': 'Temperatura del refrigerante del motor',
    'EngOilPres': 'Presión de aceite del motor',
    'EngOilFltr': 'Filtro de aceite del motor',
    'EngSpd': 'Velocidad del motor',
    'TCOutTemp': 'Temperatura de salida del turbocompresor',
    'RAftrclrTemp': 'Temperatura del posenfriador derecho',
    'LtExhTemp': 'Temperatura de escape izquierda',
    'RtExhTemp': 'Temperatura de escape derecha',
    'RtLtExhTemp': 'Diferencia de temperatura de escape (derecha-izquierda)',
    'AirFltr': 'Restricción del filtro de aire',
    'CnkcasePres': 'Presión del cárter',
    'CompInPres1': 'Presión de entrada del compresor 1',
    'CompInPres2': 'Presión de entrada del compresor 2',
    'TrboInPres': 'Presión de entrada del turbocompresor',
    'TrboOutPres': 'Presión de salida del turbocompresor',
    'TrnLubeTemp': 'Temperatura del aceite de transmisión',
    'LckupSlip': 'Deslizamiento del embrague de bloqueo',
    'TrnSlip': 'Deslizamiento de la transmisión',
    'TrnGear': 'Marcha de la transmisión',
    'GearSelect': 'Selección de marcha',
    'DiffTemp': 'Temperatura del diferencial',
    'DiffLubePres': 'Presión de lubricación del diferencial',
    'LtFBrkTemp': 'Temperatura del freno delantero izquierdo',
    'RtFBrkTemp': 'Temperatura del freno delantero derecho',
    'LtRBrkTemp': 'Temperatura del freno trasero izquierdo',
    'RtRBrkTemp': 'Temperatura del freno trasero derecho',
    'StrgOilTemp': 'Temperatura del aceite de dirección',
}

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
    df['rolling_mean'] = df[signal_name].rolling(window=30, min_periods=5).mean()
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

    # Event/anomaly overlays use only the existing event labels and periods.
    event_windows, anomaly_count, event_count = _event_windows(events_df, signal_name)
    event_colors = {
        'anomaly': ('#dc3545', 'Anomalía'),
        'event': ('#fd7e14', 'Evento'),
    }
    for window in event_windows:
        color, _ = event_colors[window['kind']]
        fig.add_vrect(
            x0=window['start'],
            x1=window['end'],
            fillcolor=color,
            opacity=0.14 if window['kind'] == 'event' else 0.2,
            line=dict(color=color, width=1),
            layer='below',
        )
    for kind, count in (('anomaly', anomaly_count), ('event', event_count)):
        if count:
            color, label = event_colors[kind]
            fig.add_trace(go.Scatter(
                x=[None], y=[None], mode='markers', name=f'{label} ({count})',
                marker=dict(size=9, color=color, symbol='square'),
                hoverinfo='skip',
            ))

    latest_observed = df['Fecha'].max()
    max_episode_start = _max_episode_start(events_df, signal_name)
    initial_start = max_episode_start if max_episode_start is not None else df['Fecha'].min()
    if initial_start is not None and latest_observed is not None and initial_start > latest_observed:
        initial_start = df['Fecha'].min()

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
                    line=dict(color='#f39c12', dash='dash', width=1),
                    showlegend=True
                ))
            if 'P98' in bl_row.index and pd.notna(bl_row['P98']):
                fig.add_trace(go.Scatter(
                    x=x_range, y=[bl_row['P98']] * 2,
                    mode='lines', name='P98',
                    line=dict(color='#e74c3c', dash='dash', width=1),
                    showlegend=True
                ))
            if 'P5' in bl_row.index and pd.notna(bl_row['P5']):
                fig.add_trace(go.Scatter(
                    x=x_range, y=[bl_row['P5']] * 2,
                    mode='lines', name='P5',
                    line=dict(color='#f39c12', dash='dash', width=1),
                    showlegend=True
                ))
            if 'P2' in bl_row.index and pd.notna(bl_row['P2']):
                fig.add_trace(go.Scatter(
                    x=x_range, y=[bl_row['P2']] * 2,
                    mode='lines', name='P2',
                    line=dict(color='#e74c3c', dash='dash', width=1),
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

    fig.update_layout(
        height=280,
        margin=dict(t=58, b=40, l=50, r=20),
        xaxis_title="",
        xaxis=dict(
            range=[initial_start, latest_observed] if initial_start is not None else None,
            autorange=False if initial_start is not None else True,
        ),
        yaxis_title="Valor",
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
    return fig


def _event_windows(events_df: Optional[pd.DataFrame], signal_name: str):
    """Return merged display windows and counts for materialized events."""
    if events_df is None or events_df.empty:
        return [], 0, 0
    events = events_df.copy()
    signal_col = 'signal' if 'signal' in events.columns else 'feature'
    if signal_col in events.columns:
        events = events[events[signal_col].astype(str) == str(signal_name)]
    if events.empty or 'start_time' not in events.columns:
        return [], 0, 0
    events['start'] = pd.to_datetime(events['start_time'], errors='coerce')
    end_source = events['end_time'] if 'end_time' in events.columns else events['start_time']
    events['end'] = pd.to_datetime(end_source, errors='coerce')
    events['end'] = events['end'].fillna(events['start'])
    events = events.dropna(subset=['start']).sort_values('start')
    if events.empty:
        return [], 0, 0

    def kind(row):
        labels = f"{row.get('event_type_binary', '')} {row.get('event_type_weighted', '')}".lower()
        return 'anomaly' if 'anomal' in labels else 'event'

    events['kind'] = events.apply(kind, axis=1)
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
        events = events[events[signal_col].astype(str) == str(signal_name)]
    if events.empty:
        return None
    duration_col = 'duration_minutes' if 'duration_minutes' in events.columns else None
    if duration_col:
        events = events.sort_values(duration_col, ascending=False, na_position='last')
    start = pd.to_datetime(events.iloc[0].get('start_time'), errors='coerce')
    return None if pd.isna(start) else start
