"""
Admin-only callbacks (login events chart for "Registro de usuarios").
"""

import dash
from dash import Input, Output, State
import plotly.graph_objects as go

from dashboard.auth import is_admin
from dashboard.components.user_registry_charts import create_login_events_chart
from src.data.auth_events_repository import (
    get_login_counts_by_user_and_status,
    list_login_events,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


def register_admin_callbacks(app: dash.Dash) -> None:
    """Register admin-view data-loading callbacks."""

    @app.callback(
        Output("user-registry-login-events-chart", "figure"),
        Input("user-registry-page-load", "data"),
        State("user-info-store", "data"),
    )
    def load_user_registry_chart(_page_load, user_data):
        # Defense in depth: the route guard already redirects non-admin
        # users away from this page before this callback can fire.
        if not user_data or not is_admin(user_data):
            logger.warning("Blocked non-admin access to user registry chart data")
            return go.Figure()

        events_df = list_login_events()
        counts_df = get_login_counts_by_user_and_status(events_df)
        return create_login_events_chart(counts_df)
