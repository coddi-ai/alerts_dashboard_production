"""
Reactive sidebar navigation.

The sidebar's #sidebar-nav-menu is first rendered synchronously (for the
client-selector's default value) in dashboard/layout.py::create_main_dashboard,
then kept in sync here whenever the user switches clients - a disabled
service must disappear from the nav the moment the client that disables it
is selected, not just at login.
"""

import dash
from dash import Input, Output, State
from dash.exceptions import PreventUpdate

from dashboard.layout import build_navigation_items, build_menu_items


def register_sidebar_callbacks(app: dash.Dash) -> None:
    """Register the client-selector-driven sidebar refresh callback."""

    @app.callback(
        Output("sidebar-nav-menu", "children"),
        Input("client-selector", "value"),
        State("user-info-store", "data"),
    )
    def update_sidebar_nav(selected_client, user_data):
        if not user_data:
            raise PreventUpdate

        navigation_items = build_navigation_items(selected_client, user_data)
        return build_menu_items(navigation_items)
