"""
Centralized route guard for the dashboard.

Dash Pages auto-injects `dcc.Location(id="_pages_location", refresh="callback-nav")`
into `dash.page_container` (only present in the DOM once the user is logged
in, since it's nested inside create_main_dashboard). This is the one and
only callback that writes back to its `pathname` - it decides, for every
navigation, whether the requested page can be shown:

- "/" (root) resolves to the client's first enabled service (spec 2.7).
- "/admin/*" requires the admin role, independent of client services.
- any other known service route requires the currently selected client to
  have that service enabled (config/client_services.py::is_service_enabled).

Hiding a nav link is not authorization - this callback is what actually
enforces it against direct URL access, per spec 2.6.
"""

import dash
from dash import Input, Output, State
from dash.exceptions import PreventUpdate

from dashboard.auth import is_admin
from dashboard.services_registry import first_enabled_service_path, resolve_service_id_for_pathname
from config.client_services import is_service_enabled
from src.utils.logger import get_logger

logger = get_logger(__name__)


def register_access_control_callbacks(app: dash.Dash) -> None:
    """Register the centralized route guard callback."""

    @app.callback(
        Output("_pages_location", "pathname"),
        Input("_pages_location", "pathname"),
        State("user-info-store", "data"),
        State("client-selector", "value"),
    )
    def guard_route(pathname, user_data, selected_client):
        if not user_data:
            raise PreventUpdate

        rel_path = dash.strip_relative_path(pathname) or ""
        user_clients = user_data.get("clients", [])
        effective_client = selected_client or (user_clients[0] if user_clients else None)

        def _fallback():
            target = first_enabled_service_path(effective_client)
            return dash.get_relative_path(target) if target else dash.get_relative_path("/sin-servicios")

        if rel_path == "":
            target = first_enabled_service_path(effective_client)
            if target is None:
                return dash.get_relative_path("/sin-servicios")
            return dash.get_relative_path(target)

        if rel_path.startswith("admin"):
            if not is_admin(user_data):
                logger.warning(f"Blocked non-admin access to '{rel_path}' for user {user_data.get('username')}")
                return _fallback()
            raise PreventUpdate

        service_id = resolve_service_id_for_pathname(rel_path)
        if service_id is None:
            # Not a client-service-gated route (e.g. /sin-servicios, unknown path) - leave as-is.
            raise PreventUpdate

        if not is_service_enabled(effective_client, service_id):
            logger.warning(
                f"Blocked access to service '{service_id}' for client '{effective_client}' "
                f"(user {user_data.get('username')})"
            )
            return _fallback()

        raise PreventUpdate
