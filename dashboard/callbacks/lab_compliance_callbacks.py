"""
Callbacks for the Laboratory Compliance KPIs tab.

Handles:
- Date range initialization from available data
- KPI card calculations (within/outside deadline, average delay)
- Weekly evolution chart of average laboratory delay
- Distribution of samples outside deadline by unit
"""

from dash import callback, Input, Output, State, no_update
import pandas as pd
import plotly.graph_objects as go
from config.settings import get_settings
from src.utils.file_utils import safe_read_parquet
from src.utils.logger import get_logger

logger = get_logger(__name__)

DEADLINE_DAYS = 2


def _load_lab_compliance_data(client: str) -> pd.DataFrame:
    """
    Load classified reports and compute lab delay.

    Returns DataFrame with columns: sampleDate, labDate, unitId, lab_delay_days, within_deadline
    Only includes rows where both dates are valid.
    """
    if not client:
        return pd.DataFrame()

    settings = get_settings()
    reports_path = settings.get_classified_reports_path(client.lower())

    if not reports_path.exists():
        logger.warning(f"Classified reports not found: {reports_path}")
        return pd.DataFrame()

    df = safe_read_parquet(reports_path)
    if df.empty:
        return pd.DataFrame()

    # Ensure datetime types
    df['sampleDate'] = pd.to_datetime(df['sampleDate'], errors='coerce')
    df['labDate'] = pd.to_datetime(df['labDate'], errors='coerce')

    # Filter out rows with missing dates
    df = df.dropna(subset=['sampleDate', 'labDate'])

    if df.empty:
        return pd.DataFrame()

    # Calculate lab delay in days
    df['lab_delay_days'] = (df['labDate'] - df['sampleDate']).dt.days
    df['within_deadline'] = df['lab_delay_days'] <= DEADLINE_DAYS

    return df[['sampleDate', 'labDate', 'unitId', 'lab_delay_days', 'within_deadline']].copy()


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
def init_lab_compliance_date_range(active_tab, client):
    """Initialize date picker range based on available data."""
    if active_tab != 'lab-compliance' or not client:
        return no_update, no_update, no_update, no_update

    df = _load_lab_compliance_data(client)
    if df.empty:
        return no_update, no_update, no_update, no_update

    min_date = df['sampleDate'].min().date()
    max_date = df['sampleDate'].max().date()

    # Default: last 6 months
    default_start = max(min_date, (pd.Timestamp(max_date) - pd.DateOffset(months=6)).date())

    return min_date, max_date, default_start, max_date


# ========================================
# KPI CARDS
# ========================================

@callback(
    [Output('lab-compliance-within-deadline', 'children'),
     Output('lab-compliance-outside-deadline', 'children'),
     Output('lab-compliance-avg-delay', 'children')],
    [Input('lab-compliance-date-range', 'start_date'),
     Input('lab-compliance-date-range', 'end_date'),
     Input('client-selector', 'value')],
    [State('oil-internal-tabs', 'value')]
)
def update_lab_compliance_kpis(start_date, end_date, client, active_tab):
    """Update KPI cards based on date range selection."""
    if active_tab != 'lab-compliance' or not client:
        return "—", "—", "—"

    df = _load_lab_compliance_data(client)
    if df.empty:
        return "0", "0", "—"

    # Apply date filter
    if start_date:
        df = df[df['sampleDate'] >= pd.Timestamp(start_date)]
    if end_date:
        df = df[df['sampleDate'] <= pd.Timestamp(end_date)]

    if df.empty:
        return "0", "0", "—"

    within = df['within_deadline'].sum()
    outside = (~df['within_deadline']).sum()
    avg_delay = df['lab_delay_days'].mean()

    return str(int(within)), str(int(outside)), f"{avg_delay:.1f}"


# ========================================
# WEEKLY EVOLUTION CHART
# ========================================

@callback(
    Output('lab-compliance-weekly-chart', 'figure'),
    [Input('lab-compliance-date-range', 'start_date'),
     Input('lab-compliance-date-range', 'end_date'),
     Input('client-selector', 'value')],
    [State('oil-internal-tabs', 'value')]
)
def update_weekly_evolution_chart(start_date, end_date, client, active_tab):
    """Update weekly trend chart of average lab delay."""
    empty_fig = go.Figure()
    empty_fig.update_layout(
        xaxis_title="Semana",
        yaxis_title="Demora Promedio (días)",
        template="plotly_white",
        margin=dict(l=40, r=20, t=30, b=40)
    )
    empty_fig.add_annotation(
        text="Sin datos disponibles",
        xref="paper", yref="paper",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=16, color="gray")
    )

    if active_tab != 'lab-compliance' or not client:
        return empty_fig

    df = _load_lab_compliance_data(client)
    if df.empty:
        return empty_fig

    # Apply date filter
    if start_date:
        df = df[df['sampleDate'] >= pd.Timestamp(start_date)]
    if end_date:
        df = df[df['sampleDate'] <= pd.Timestamp(end_date)]

    if df.empty:
        return empty_fig

    # Aggregate by week
    df['week'] = df['sampleDate'].dt.to_period('W').apply(lambda r: r.start_time)
    weekly = df.groupby('week')['lab_delay_days'].mean().reset_index()
    weekly.columns = ['week', 'avg_delay']

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=weekly['week'],
        y=weekly['avg_delay'],
        mode='lines+markers',
        name='Demora Promedio',
        line=dict(color='#0d6efd', width=2),
        marker=dict(size=5)
    ))

    # Add deadline reference line
    fig.add_hline(
        y=DEADLINE_DAYS,
        line_dash="dash",
        line_color="red",
        annotation_text=f"Plazo ({DEADLINE_DAYS} días)",
        annotation_position="top right"
    )

    fig.update_layout(
        xaxis_title="Semana",
        yaxis_title="Demora Promedio (días)",
        template="plotly_white",
        margin=dict(l=40, r=20, t=30, b=40),
        showlegend=False
    )

    return fig


# ========================================
# DISTRIBUTION BY UNIT CHART
# ========================================

@callback(
    Output('lab-compliance-unit-chart', 'figure'),
    [Input('lab-compliance-date-range', 'start_date'),
     Input('lab-compliance-date-range', 'end_date'),
     Input('client-selector', 'value')],
    [State('oil-internal-tabs', 'value')]
)
def update_unit_distribution_chart(start_date, end_date, client, active_tab):
    """Update bar chart of samples outside deadline by unit."""
    empty_fig = go.Figure()
    empty_fig.update_layout(
        xaxis_title="Unidad",
        yaxis_title="Muestras Fuera de Plazo",
        template="plotly_white",
        margin=dict(l=40, r=20, t=30, b=40)
    )
    empty_fig.add_annotation(
        text="Sin datos disponibles",
        xref="paper", yref="paper",
        x=0.5, y=0.5, showarrow=False,
        font=dict(size=16, color="gray")
    )

    if active_tab != 'lab-compliance' or not client:
        return empty_fig

    df = _load_lab_compliance_data(client)
    if df.empty:
        return empty_fig

    # Apply date filter
    if start_date:
        df = df[df['sampleDate'] >= pd.Timestamp(start_date)]
    if end_date:
        df = df[df['sampleDate'] <= pd.Timestamp(end_date)]

    # Only samples outside deadline
    df_outside = df[~df['within_deadline']]

    if df_outside.empty:
        empty_fig.data = []
        empty_fig.layout.annotations = []
        empty_fig.add_annotation(
            text="Todas las muestras dentro de plazo",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16, color="green")
        )
        return empty_fig

    # Count by unit, top 20
    unit_counts = df_outside.groupby('unitId').size().reset_index(name='count')
    unit_counts = unit_counts.sort_values('count', ascending=False).head(20)

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=unit_counts['unitId'],
        y=unit_counts['count'],
        marker_color='#dc3545'
    ))

    fig.update_layout(
        xaxis_title="Unidad",
        yaxis_title="Muestras Fuera de Plazo",
        template="plotly_white",
        margin=dict(l=40, r=20, t=30, b=60),
        xaxis_tickangle=-45
    )

    return fig
