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


@lru_cache(maxsize=1)
def load_signal_registry(client: str = 'cda') -> Dict[str, str]:
    """Load signal registry and return name → display_name mapping."""
    path = Path(f'data/telemetry/config/{client}/signal_registry.yaml')
    if not path.exists():
        return {}
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)
    return {s['name']: s['display_name'] for s in data.get('signals', [])}


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

    # Pivot: units as rows, systems (spanish) as columns, values = system_score
    pivot = df.pivot_table(
        index='unit', columns='system_es', values='system_score', aggfunc='first'
    )

    # Sort by priority (descending = worst at top)
    pivot['_priority'] = pivot.index.map(lambda u: priority_map.get(u, 0))
    pivot = pivot.sort_values('_priority', ascending=False).drop(columns='_priority')

    # Add Estado column (mapped to numeric for color: Anormal=90, Alerta=50, Normal=10)
    status_numeric = {'Anormal': 90, 'Alerta': 50, 'Normal': 10, 'InsufficientData': 5}
    pivot['Estado'] = pivot.index.map(
        lambda u: status_numeric.get(status_map_units.get(u, 'Normal'), 10)
    )

    # Map scores to status text for hover
    status_map_sys = df.pivot_table(
        index='unit', columns='system_es', values='system_status', aggfunc='first'
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
                score = pivot.loc[unit, sys]
                status = status_map_sys.loc[unit, sys] if unit in status_map_sys.index and sys in status_map_sys.columns else ''
                row_hover.append(
                    f"<b>{unit}</b> — {sys}<br>Estado: {status}<br>Risk Score: {score:.1f}"
                    if pd.notna(score) else ""
                )
        hover_text.append(row_hover)

    # Semantic color scale (soft, professional)
    z_values = pivot.values
    colorscale = [
        [0.00, '#f0fff4'],   # very low risk — pale green
        [0.20, '#c6f6d5'],   # low — soft green
        [0.40, '#fefcbf'],   # moderate — soft yellow
        [0.60, '#fed7aa'],   # elevated — soft orange
        [0.80, '#feb2b2'],   # high — soft red
        [1.00, '#dc3545'],   # critical — danger red
    ]

    fig = go.Figure(data=go.Heatmap(
        z=z_values,
        x=pivot.columns.tolist(),
        y=pivot.index.tolist(),
        colorscale=colorscale,
        zmin=0,
        zmax=100,
        texttemplate='%{z:.1f}',
        textfont=dict(size=11, color='#1a252f'),
        hovertext=hover_text,
        hoverinfo='text',
        xgap=2,
        ygap=2,
        colorbar=dict(
            title=dict(text="Risk Score", font=dict(size=11)),
            thickness=12,
            len=0.9,
            tickvals=[0, 20, 40, 60, 80, 100],
            ticktext=["0", "20", "40", "60", "80", "100"],
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

    Returns dict with: most_risky_unit, most_critical_system, max_score
    """
    insights = {
        'most_risky_unit': '-',
        'most_critical_system': '-',
        'max_score': 0.0,
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
        insights['max_score'] = round(top_sys['system_score'], 1)

    return insights


def build_signal_timeseries_card(
    signal_name: str,
    raw_df: pd.DataFrame,
    limits_df: pd.DataFrame,
    trend_df: pd.DataFrame,
    unit: Optional[str] = None
) -> go.Figure:
    """
    Build time series figure for a single signal.

    Includes:
    - 30-min rolling mean (blue line)
    - P95/P98 limits (dashed orange/red horizontal lines)
    - P5/P2 limits (dashed orange/red for low risk)
    - Trend regression line (if significant)

    Args:
        signal_name: Column name in raw_df
        raw_df: Silver telemetry filtered to one unit
        limits_df: Limits/baselines with Unit/Signal/EstadoMaquina/P2/P5/P95/P98
        trend_df: Trend results for this unit+signal
        unit: Unit identifier for limits lookup
    """
    if raw_df.empty or signal_name not in raw_df.columns:
        return _empty_figure(f"Sin datos para {signal_name}")

    df = raw_df[['Fecha', signal_name, 'Estado']].dropna(subset=[signal_name]).copy()
    df = df.sort_values('Fecha')

    if df.empty:
        return _empty_figure(f"Sin datos válidos para {signal_name}")

    # 30-min rolling mean
    df['rolling_mean'] = df[signal_name].rolling(window=30, min_periods=5).mean()

    fig = go.Figure()

    # Main signal line (rolling mean)
    fig.add_trace(go.Scatter(
        x=df['Fecha'],
        y=df['rolling_mean'],
        mode='lines',
        name='Media móvil 30min',
        line=dict(color='#2c3e50', width=1.5),
        hovertemplate='%{x}<br>Valor: %{y:.2f}<extra></extra>'
    ))

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
            op_mask = bl[state_col].str.startswith('Operacional')
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
                x_trend = [best['start_time'], best['end_time']]
                slope = best['slope_per_day']
                days = (best['end_time'] - best['start_time']).total_seconds() / 86400
                y_start = df['rolling_mean'].dropna().iloc[0] if len(df['rolling_mean'].dropna()) > 0 else 0
                y_trend = [y_start, y_start + slope * days]
                fig.add_trace(go.Scatter(
                    x=x_trend, y=y_trend,
                    mode='lines',
                    name=f'Tendencia ({interp})',
                    line=dict(color=color, dash='dot', width=2)
                ))

    fig.update_layout(
        height=280,
        margin=dict(t=30, b=40, l=50, r=20),
        xaxis_title="",
        yaxis_title="Valor",
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1),
        hovermode='x unified'
    )
    return fig
