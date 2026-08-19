"""
Authentication callbacks for Multi-Technical-Alerts dashboard.
"""

from dash import Input, Output, State, html
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from flask import session as flask_session
from dashboard.auth import (
    IDENTITY_PROOF_FIELD,
    add_identity_proof,
    authenticate_user,
    current_dashboard_user_data,
    resolve_authenticated_username,
    should_process_login,
)
from src.utils.auth_event_logger import log_authentication_event
import logging

logger = logging.getLogger(__name__)


def register_auth_callbacks(app):
    """
    Register authentication-related callbacks.
    
    Args:
        app: Dash application instance
    """
    
    @app.callback(
        [Output('user-info-store', 'data'),
         Output('login-alert', 'children'),
         Output('login-alert', 'is_open')],
        [Input('login-button', 'n_clicks'),
         Input('password-input', 'n_submit')],
        [State('username-input', 'value'),
         State('password-input', 'value')],
        prevent_initial_call=True
    )
    def login(n_clicks, n_submit, username, password):
        """Handle user login from button click or Enter key press."""
        logger.info(f"Login callback triggered - n_clicks: {n_clicks}, n_submit: {n_submit}, username: {username}")
        
        # Check if callback was triggered (either button click or enter key)
        if not should_process_login(n_clicks, n_submit):
            logger.debug("Ignoring login callback without a user action")
            raise PreventUpdate

        if not username or not password:
            flask_session.pop("dashboard_user", None)
        
        if not username or not password:
            logger.warning("Login attempt with empty username or password")
            return None, "Por favor ingrese usuario y contraseña", True
        
        user = authenticate_user(username, password)
        
        if user:
            logger.info(f"Login successful for user: {username}")
            user_clients = user.get('clients') or []
            log_authentication_event(username, client_id=user_clients[0] if user_clients else None)
            flask_session["dashboard_user"] = username
            return add_identity_proof(user), "", False
        else:
            logger.warning(f"Login failed for user: {username}")
            flask_session.pop("dashboard_user", None)
            return None, "Usuario o contraseña inválidos", True
    
    
    @app.callback(
        Output('page-content', 'children'),
        Input('user-info-store', 'data'),
    )
    def display_page(user_data):
        """Display login page or main dashboard based on auth status."""
        username = resolve_authenticated_username(user_data)
        logger.info(
            "Display page callback triggered - authenticated_user: %s",
            username or "none",
        )
        has_identity_proof = bool(
            isinstance(user_data, dict)
            and user_data.get(IDENTITY_PROOF_FIELD)
        )

        if username and not has_identity_proof:
            # La identidad se resolvio pero el navegador no trae el proof firmado. Pasa
            # cuando sessionStorage esta vacio (pestana nueva, enlace directo) o cuando trae
            # datos escritos antes de que el proof existiera -- y ese valor viejo le gana al
            # que siembra el layout. En ambos casos el usuario esta legitimamente autenticado,
            # asi que se reemite el proof desde la sesion en vez de mandar al login a alguien
            # que el servidor ya reconoce.
            #
            # Esto no ablanda el gate. `resolve_authenticated_username` solo devuelve un
            # nombre sin proof cuando la cookie de sesion de Flask es valida, y esa cookie es
            # HttpOnly y va firmada con la misma llave: es la mas fuerte de las dos pruebas,
            # no la mas debil. `current_dashboard_user_data` vuelve a resolver la sesion por
            # su cuenta y devuelve None si no es valida, y entonces el gate manda al login.
            user_data = current_dashboard_user_data()
            has_identity_proof = bool(
                isinstance(user_data, dict)
                and user_data.get(IDENTITY_PROOF_FIELD)
            )

        from dashboard.layout import create_main_dashboard
        
        # When user logs in (user_data is not None), show dashboard
        # When user logs out (user_data is None), the logout callback will trigger a page reload
        if user_data is not None and username and has_identity_proof:
            logger.info("Showing dashboard for user: %s", username)
            return create_main_dashboard(user_data)
        else:
            # User logged out - could show login page or trigger reload
            # For now, we'll rely on the layout's initial page-content
            logger.info("Showing login page")
            from dashboard.layout import create_login_page
            return create_login_page()
    
    
    @app.callback(
        Output('user-info-store', 'data', allow_duplicate=True),
        Output('erp-validator-operator-store', 'data', allow_duplicate=True),
        Input('logout-button', 'n_clicks'),
        prevent_initial_call=True
    )
    def logout(n_clicks):
        """Handle user logout."""
        if not n_clicks:
            # The logout button is inserted dynamically when the dashboard
            # renders after login; Dash fires this callback once for that
            # mount event even with prevent_initial_call=True, since the
            # component didn't exist at the initial page load. Ignore it.
            raise PreventUpdate
        flask_session.clear()
        return None, None
