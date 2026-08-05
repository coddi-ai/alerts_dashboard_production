"""
Chart components for the admin "Registro de usuarios" view.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Fixed categorical color order (never cycled) for deploy_status values.
DEPLOY_STATUS_COLORS = {
    'production': '#2a78d6',
    'staging': '#eb6834',
    'development': '#1baf7a',
    'unknown': '#898781',
}


def create_login_events_chart(counts_df: pd.DataFrame) -> go.Figure:
    """
    Create horizontal bar chart of login event counts per user, grouped by deploy_status.

    Args:
        counts_df: DataFrame with columns ['username', 'deploy_status', 'count'].

    Returns:
        Plotly Figure with horizontal bar chart.
    """
    if counts_df.empty:
        logger.info("No login events available for user registry chart")
        return go.Figure().add_annotation(
            text="No hay eventos de inicio de sesión registrados",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )

    fig = px.bar(
        counts_df,
        y='username',
        x='count',
        color='deploy_status',
        orientation='h',
        title=None,
        template='plotly_white',
        height=max(400, 30 * counts_df['username'].nunique()),
        labels={'count': 'Número de inicios de sesión', 'username': 'Usuario', 'deploy_status': 'Ambiente'},
        color_discrete_map=DEPLOY_STATUS_COLORS,
    )
    fig.update_layout(
        yaxis={'categoryorder': 'total ascending'},
        showlegend=True,
        legend=dict(
            title='Ambiente',
            orientation='h',
            x=1,
            y=1.08,
            xanchor='right',
            yanchor='bottom',
            font=dict(size=11),
        ),
        hovermode='closest',
    )

    logger.info("Created user registry login events chart successfully")
    return fig
