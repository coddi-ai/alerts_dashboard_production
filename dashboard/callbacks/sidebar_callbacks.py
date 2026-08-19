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

    # Toggle the persisted collapsed flag on button click. Clientside so the
    # sidebar hides/shows instantly with no server round-trip.
    app.clientside_callback(
        """
        function(n_clicks, collapsed) {
            if (!n_clicks) {
                throw window.dash_clientside.PreventUpdate;
            }
            return !collapsed;
        }
        """,
        Output("sidebar-collapsed-store", "data"),
        Input("sidebar-toggle-btn", "n_clicks"),
        State("sidebar-collapsed-store", "data"),
    )

    # Apply the persisted flag to #dashboard-shell as a class - all visual
    # effects of collapsing (sidebar width, content margin, toggle button
    # position/icon) are pure CSS off '.sidebar-collapsed'
    # (see dashboard/assets/custom_layout.css). Runs on load too, so a
    # previously-collapsed preference is restored immediately.
    app.clientside_callback(
        """
        function(collapsed) {
            return collapsed ? "sidebar-collapsed" : "";
        }
        """,
        Output("dashboard-shell", "className"),
        Input("sidebar-collapsed-store", "data"),
    )
