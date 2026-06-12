"""
Chart components for Telemetry Health Dashboard.

Plotly figure builders for fleet heatmap, donut chart, and signal time series cards.
"""

import pandas as pd
import numpy as np
from typing import Optional

import plotly.graph_objects as go
from plotly.subplots import make_subplots

STATUS_COLORS = {
    'Normal': '#2ecc71',
    'Alerta': '#f39c12',
    'Anormal': '#e74c3c',
    'InsufficientData': '#95a5a6'
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


def build_fleet_donut(unit_health_df: pd.DataFrame) -> go.Figure:
    """
    Build fleet status donut chart.

    Args:
        unit_health_df: DataFrame with 'overall_status' column.
    """
    if unit_health_df.empty:
        return _empty_figure()

    counts = unit_health_df['overall_status'].value_counts()
    labels = counts.index.tolist()
    values = counts.values.tolist()
    colors = [STATUS_COLORS.get(s, '#999') for s in labels]

    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=0.55,
        marker=dict(colors=colors),
        textinfo='label+value',
        textposition='auto',
        hovertemplate='%{label}<br>Cantidad: %{value}<br>%{percent}<extra></extra>'
    )])
    fig.update_layout(
        height=350,
        showlegend=True,
        legend=dict(orientation='h', yanchor='bottom', y=-0.15, xanchor='center', x=0.5),
        margin=dict(t=20, b=40, l=20, r=20),
        annotations=[dict(
            text=f"{len(unit_health_df)}<br>Unidades",
            x=0.5, y=0.5, font_size=18, showarrow=False
        )]
    )
    return fig


def build_fleet_heatmap(system_health_df: pd.DataFrame, unit_health_df: pd.DataFrame) -> go.Figure:
    """
    Build system health heatmap (Units rows × Systems cols).

    Sorted by priority score (worst at top).
    """
    if system_health_df.empty:
        return _empty_figure("Sin datos de sistemas disponibles")

    # Join priority for sorting
    priority_map = {}
    if not unit_health_df.empty and 'priority_score' in unit_health_df.columns:
        priority_map = unit_health_df.set_index('unit')['priority_score'].to_dict()

    # Pivot: units as rows, systems as columns, values = system_score
    pivot = system_health_df.pivot_table(
        index='unit', columns='system', values='system_score', aggfunc='first'
    )

    # Sort by priority (descending)
    pivot['_priority'] = pivot.index.map(lambda u: priority_map.get(u, 0))
    pivot = pivot.sort_values('_priority', ascending=False).drop(columns='_priority')

    # Custom colorscale: green (0) → orange (50) → red (100)
    colorscale = [
        [0.0, '#2ecc71'],
        [0.4, '#f1c40f'],
        [0.7, '#f39c12'],
        [1.0, '#e74c3c']
    ]

    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=pivot.columns.tolist(),
        y=pivot.index.tolist(),
        colorscale=colorscale,
        zmin=0,
        zmax=100,
        text=pivot.values.round(1),
        texttemplate='%{text}',
        textfont=dict(size=11),
        hovertemplate='Unidad: %{y}<br>Sistema: %{x}<br>Score: %{z:.1f}<extra></extra>',
        colorbar=dict(title='Risk Score', thickness=15)
    ))
    fig.update_layout(
        height=max(300, 40 * len(pivot)),
        margin=dict(t=20, b=40, l=80, r=20),
        xaxis=dict(side='top', tickangle=0),
        yaxis=dict(autorange='reversed')
    )
    return fig


def build_signal_timeseries_card(
    signal_name: str,
    raw_df: pd.DataFrame,
    baseline_df: pd.DataFrame,
    trend_df: pd.DataFrame,
    model_spec: Optional[str] = None
) -> go.Figure:
    """
    Build time series figure for a single signal.

    Includes:
    - 30-min rolling mean (blue line)
    - P95/P99 limits (dashed orange/red)
    - Trend regression line (if significant)

    Args:
        signal_name: Column name in raw_df
        raw_df: Silver telemetry filtered to one unit (must have 'Fecha', 'Estado')
        baseline_df: Baseline with model_specification/signal/state/P-columns
        trend_df: Trend results filtered for this unit+signal (may be empty)
        model_spec: model_specification for baseline lookup
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

    # Baseline limits (for "Operacional" state)
    if not baseline_df.empty and model_spec:
        bl = baseline_df[
            (baseline_df['model_specification'] == model_spec) &
            (baseline_df['signal'] == signal_name) &
            (baseline_df['state'] == 'Operacional')
        ]
        if not bl.empty:
            bl_row = bl.iloc[0]
            x_range = [df['Fecha'].min(), df['Fecha'].max()]

            if 'P95' in bl_row.index:
                fig.add_trace(go.Scatter(
                    x=x_range, y=[bl_row['P95']] * 2,
                    mode='lines', name='P95',
                    line=dict(color='#f39c12', dash='dash', width=1),
                    showlegend=True
                ))
            if 'P99' in bl_row.index:
                fig.add_trace(go.Scatter(
                    x=x_range, y=[bl_row['P99']] * 2,
                    mode='lines', name='P99',
                    line=dict(color='#e74c3c', dash='dash', width=1),
                    showlegend=True
                ))
            if 'P5' in bl_row.index:
                fig.add_trace(go.Scatter(
                    x=x_range, y=[bl_row['P5']] * 2,
                    mode='lines', name='P5',
                    line=dict(color='#f39c12', dash='dash', width=1),
                    showlegend=False
                ))
            if 'P1' in bl_row.index:
                fig.add_trace(go.Scatter(
                    x=x_range, y=[bl_row['P1']] * 2,
                    mode='lines', name='P1',
                    line=dict(color='#e74c3c', dash='dash', width=1),
                    showlegend=False
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
