"""
Lab Compliance callbacks — July 2026 v4.

KPIs: Transit Time (labDate - sampleDate), Lab Time (reportDate - labDate).
Edge case: if Lab Time has no positive values → use Diagnostic Time (reportDate - sampleDate).
Visualization: Weekly grouped bar chart.

Date Filtering: Uses reportDate as the primary date reference for period selection.
Records without valid reportDate are excluded from filtered results.
"""

from dash import callback, Input, Output, State, no_update
import pandas as pd
import plotly.graph_objects as go
from config.settings import get_settings
from src.data.loaders import load_oil_classified
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _load_compliance_data(client: str) -> pd.DataFrame:
    """
    Load data and compute Transit Time and Lab Time.

    Returns DataFrame with: sampleDate, labDate, reportDate, unitId,
                            transit_time, lab_time, diagnostic_time
    """
    if not client:
        return pd.DataFrame()

    # Reuse the process-local, defensive-copy loader shared by Aceite,
    # Alertas and General.  Compliance is callback-heavy (date range, KPI,
    # weekly chart and unit chart) and used to parse the same Parquet once per
    # callback.
    df = load_oil_classified(client)
    if df.empty:
        return pd.DataFrame()

    df['sampleDate'] = pd.to_datetime(df['sampleDate'], errors='coerce', utc=True).dt.tz_localize(None)

    if 'labDate' in df.columns:
        df['labDate'] = pd.to_datetime(df['labDate'], errors='coerce', utc=True).dt.tz_localize(None)
    else:
        df['labDate'] = pd.NaT

    if 'reportDate' in df.columns:
        df['reportDate'] = pd.to_datetime(df['reportDate'], errors='coerce', utc=True).dt.tz_localize(None)
    else:
        df['reportDate'] = pd.NaT

    # Need at least sampleDate
    df = df.dropna(subset=['sampleDate'])

    # Transit Time = labDate - sampleDate (may be NaN if labDate missing)
    df['transit_time'] = (df['labDate'] - df['sampleDate']).dt.days
    # Lab Time = reportDate - labDate (may be NaN)
    df['lab_time'] = (df['reportDate'] - df['labDate']).dt.days
    # Diagnostic Time = reportDate - sampleDate (fallback)
    df['diagnostic_time'] = (df['reportDate'] - df['sampleDate']).dt.days

    cols = ['sampleDate', 'labDate', 'reportDate', 'unitId',
            'transit_time', 'lab_time', 'diagnostic_time']
    return df[[c for c in cols if c in df.columns]].copy()


def _has_positive_lab_time(df: pd.DataFrame) -> bool:
    """Check if Lab Time has any positive values."""
    if 'lab_time' not in df.columns:
        return False
    valid = df['lab_time'].dropna()
    return (valid > 0).any()


# ========================================
# DATE RANGE INITIALIZATION
# ========================================
@callback(
    [Output('lab-compliance-date-range', 'min_date_allowed'),
     Output('lab-compliance-date-range', 'max_date_allowed'),
     Output('lab-compliance-date-range', 'start_date'),
     Output('lab-compliance-date-range', 'end_date')],
    [Input('oil-internal-tabs', 'value'),
     Input('client-selector', 'value')]
)
def init_date_range(active_tab, client):
    if active_tab != 'lab-compliance' or not client:
        return no_update, no_update, no_update, no_update

    df = _load_compliance_data(client)
    if df.empty:
        return no_update, no_update, no_update, no_update

    # Use reportDate for date range initialization
    df_with_report_date = df.dropna(subset=['reportDate'])
    if df_with_report_date.empty:
        return no_update, no_update, no_update, no_update

    min_d = df_with_report_date['reportDate'].min().date()
    max_d = df_with_report_date['reportDate'].max().date()
    start = max(min_d, (pd.Timestamp(max_d) - pd.DateOffset(months=6)).date())
    return min_d, max_d, start, max_d


# ========================================
# KPI CARDS
# ========================================
@callback(
    [Output('lab-kpi-1-title', 'children'),
     Output('lab-kpi-1-value', 'children'),
     Output('lab-kpi-2-title', 'children'),
     Output('lab-kpi-2-value', 'children'),
     Output('lab-kpi-total-samples', 'children')],
    [Input('lab-compliance-date-range', 'start_date'),
     Input('lab-compliance-date-range', 'end_date'),
     Input('client-selector', 'value')],
    [State('oil-internal-tabs', 'value')]
)
def update_kpis(start_date, end_date, client, active_tab):
    defaults = ("Tiempo de Tránsito Prom.", "—", "Tiempo de Laboratorio Prom.", "—", "—")
    if active_tab != 'lab-compliance' or not client:
        return defaults

    df = _load_compliance_data(client)
    if df.empty:
        return defaults

    # Filter by reportDate instead of sampleDate
    # Drop records without valid reportDate
    df = df.dropna(subset=['reportDate'])
    if start_date:
        df = df[df['reportDate'] >= pd.Timestamp(start_date)]
    if end_date:
        df = df[df['reportDate'] <= pd.Timestamp(end_date)]
    if df.empty:
        return defaults

    total = str(len(df))
    use_split = _has_positive_lab_time(df)

    if use_split:
        transit_avg = df['transit_time'].dropna().mean()
        lab_avg = df['lab_time'].dropna().mean()
        return ("Tiempo de Tránsito Prom.", f"{transit_avg:.1f}" if pd.notna(transit_avg) else "—",
                "Tiempo de Laboratorio Prom.", f"{lab_avg:.1f}" if pd.notna(lab_avg) else "—",
                total)
    else:
        diag_avg = df['diagnostic_time'].dropna().mean()
        return ("Tiempo Diagnóstico Prom.", f"{diag_avg:.1f}" if pd.notna(diag_avg) else "—",
                "(Lab Time no disponible)", "—",
                total)


# ========================================
# WEEKLY BAR CHART
# ========================================
@callback(
    [Output('lab-compliance-weekly-chart', 'figure'),
     Output('lab-weekly-chart-title', 'children')],
    [Input('lab-compliance-date-range', 'start_date'),
     Input('lab-compliance-date-range', 'end_date'),
     Input('client-selector', 'value')],
    [State('oil-internal-tabs', 'value')]
)
def update_weekly_chart(start_date, end_date, client, active_tab):
    empty = _empty_fig("Sin datos disponibles")
    default_title = "Comparación Semanal"

    if active_tab != 'lab-compliance' or not client:
        return empty, default_title

    df = _load_compliance_data(client)
    if df.empty:
        return empty, default_title

    # Filter by reportDate instead of sampleDate
    # Drop records without valid reportDate
    df = df.dropna(subset=['reportDate'])
    if start_date:
        df = df[df['reportDate'] >= pd.Timestamp(start_date)]
    if end_date:
        df = df[df['reportDate'] <= pd.Timestamp(end_date)]
    if df.empty:
        return empty, default_title

    # Group by reportDate week for weekly aggregation
    df['week'] = df['reportDate'].dt.to_period('W').apply(lambda r: r.start_time)
    use_split = _has_positive_lab_time(df)

    fig = go.Figure()

    if use_split:
        weekly = df.groupby('week').agg(
            transit=('transit_time', 'mean'),
            lab=('lab_time', 'mean')
        ).reset_index()

        fig.add_trace(go.Bar(
            x=weekly['week'], y=weekly['transit'],
            name='Tiempo de Tránsito', marker_color='#0d6efd',
            text=weekly['transit'], texttemplate='%{text:.1f}',
            textposition='inside', insidetextanchor='end',
            textfont=dict(color='white', size=10)
        ))
        fig.add_trace(go.Bar(
            x=weekly['week'], y=weekly['lab'],
            name='Tiempo de Laboratorio', marker_color='#6610f2',
            text=weekly['lab'], texttemplate='%{text:.1f}',
            textposition='inside', insidetextanchor='end',
            textfont=dict(color='white', size=10)
        ))
        title = "Comparación Semanal: Tiempo de Tránsito vs Tiempo de Laboratorio"
    else:
        weekly = df.groupby('week').agg(
            diagnostic=('diagnostic_time', 'mean')
        ).reset_index()

        fig.add_trace(go.Bar(
            x=weekly['week'], y=weekly['diagnostic'],
            name='Tiempo Diagnóstico', marker_color='#fd7e14',
            text=weekly['diagnostic'], texttemplate='%{text:.1f}',
            textposition='inside', insidetextanchor='end',
            textfont=dict(color='white', size=10)
        ))
        title = "Evolución Semanal: Tiempo Diagnóstico (reportDate - sampleDate)"

    threshold_days = get_settings().get_lab_compliance_threshold_days(client)
    fig.add_hline(
        y=threshold_days,
        line=dict(color='#dc3545', width=1.5, dash='dash'),
        annotation_text=f"Umbral de cumplimiento ({threshold_days:g} días)",
        annotation_position="top left",
        annotation_font=dict(size=10, color='#dc3545'),
    )

    fig.update_layout(
        barmode='group',
        xaxis_title="Semana",
        yaxis_title="Días (promedio)",
        template="plotly_white",
        margin=dict(l=40, r=20, t=30, b=40),
        legend=dict(orientation='h', yanchor='bottom', y=1.02, xanchor='center', x=0.5)
    )

    return fig, title


# ========================================
# UNIT DISTRIBUTION CHART
# ========================================
@callback(
    Output('lab-compliance-unit-chart', 'figure'),
    [Input('lab-compliance-date-range', 'start_date'),
     Input('lab-compliance-date-range', 'end_date'),
     Input('client-selector', 'value')],
    [State('oil-internal-tabs', 'value')]
)
def update_unit_chart(start_date, end_date, client, active_tab):
    empty = _empty_fig("Sin datos disponibles")
    if active_tab != 'lab-compliance' or not client:
        return empty

    df = _load_compliance_data(client)
    if df.empty:
        return empty

    # Filter by reportDate instead of sampleDate
    # Drop records without valid reportDate
    df = df.dropna(subset=['reportDate'])
    if start_date:
        df = df[df['reportDate'] >= pd.Timestamp(start_date)]
    if end_date:
        df = df[df['reportDate'] <= pd.Timestamp(end_date)]
    if df.empty:
        return empty

    use_split = _has_positive_lab_time(df)

    if use_split:
        col = 'transit_time'
        ylabel = "Demora Tránsito Prom. (días)"
    else:
        col = 'diagnostic_time'
        ylabel = "Demora Diagnóstico Prom. (días)"

    by_unit = df.groupby('unitId')[col].mean().dropna().sort_values(ascending=False).head(20)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=by_unit.index, y=by_unit.values,
        marker_color='#0d6efd',
        text=by_unit.values, texttemplate='%{text:.1f}',
        textposition='inside', insidetextanchor='end',
        textfont=dict(color='white', size=10)
    ))

    threshold_days = get_settings().get_lab_compliance_threshold_days(client)
    fig.add_hline(
        y=threshold_days,
        line=dict(color='#dc3545', width=1.5, dash='dash'),
        annotation_text=f"Umbral de cumplimiento ({threshold_days:g} días)",
        annotation_position="top left",
        annotation_font=dict(size=10, color='#dc3545'),
    )

    fig.update_layout(
        xaxis_title="Unidad",
        yaxis_title=ylabel,
        template="plotly_white",
        margin=dict(l=40, r=20, t=30, b=60)
    )
    return fig


def _empty_fig(text: str) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(
        template="plotly_white",
        margin=dict(l=40, r=20, t=30, b=40)
    )
    fig.add_annotation(text=text, xref="paper", yref="paper",
                       x=0.5, y=0.5, showarrow=False,
                       font=dict(size=16, color="gray"))
    return fig
