"""
Admin-only callbacks (login events chart for "Registro de usuarios").
"""

import dash
from dash import Input, Output
import plotly.graph_objects as go

from dashboard.components.user_registry_charts import create_login_events_chart
from src.data.auth_events_repository import (
    AuthEventsUnavailableError,
    get_login_counts_by_user_and_status,
    list_login_events,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)


def register_admin_callbacks(app: dash.Dash) -> None:
    """Register admin-view data-loading callbacks."""

    @app.callback(
        Output("user-registry-login-events-chart", "figure"),
        Output("user-registry-load-error", "children"),
        Output("user-registry-load-error", "is_open"),
        Input("user-registry-page-load", "data"),
    )
    def load_user_registry_chart(_page_load):
        # The route guard (access_control_callbacks.py) already keeps
        # non-admin users off this page entirely - reaching this callback
        # means the current user is an admin, so just load the data.
        try:
            events_df = list_login_events()
        except AuthEventsUnavailableError as e:
            logger.error(f"User registry chart: events repository unavailable: {e}")
            return go.Figure(), "No se pudo cargar el registro de inicios de sesión.", True

        counts_df = get_login_counts_by_user_and_status(events_df)
        return create_login_events_chart(counts_df), "", False
