"""
Authentication callbacks for Multi-Technical-Alerts dashboard.
"""

from dash import Input, Output, State, html
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from dashboard.auth import authenticate_user
from src.utils.auth_logger import log_authentication
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
        if n_clicks is None and n_submit is None:
            logger.warning("Login callback triggered but both n_clicks and n_submit are None")
            raise PreventUpdate
        
        if not username or not password:
            logger.warning("Login attempt with empty username or password")
            return None, "Por favor ingrese usuario y contraseña", True
        
        user = authenticate_user(username, password)
        
        if user:
            logger.info(f"Login successful for user: {username}")
            log_authentication(username, success=True)
            return user, "", False
        else:
            logger.warning(f"Login failed for user: {username}")
            log_authentication(username, success=False)
            return None, "Usuario o contraseña inválidos", True
    
    
    @app.callback(
        Output('page-content', 'children'),
        Input('user-info-store', 'data')
    )
    def display_page(user_data):
        """Display login page or main dashboard based on auth status."""
        logger.info(f"Display page callback triggered - user_data: {user_data}")
        from dashboard.layout import create_main_dashboard
        
        # When user logs in (user_data is not None), show dashboard
        # When user logs out (user_data is None), the logout callback will trigger a page reload
        if user_data is not None:
            logger.info(f"Showing dashboard for user: {user_data.get('username')}")
            return create_main_dashboard(user_data)
        else:
            # User logged out - could show login page or trigger reload
            # For now, we'll rely on the layout's initial page-content
            logger.info("Showing login page")
            from dashboard.layout import create_login_page
            return create_login_page()
    
    
    @app.callback(
        Output('user-info-store', 'data', allow_duplicate=True),
        Input('logout-button', 'n_clicks'),
        prevent_initial_call=True
    )
    def logout(n_clicks):
        """Handle user logout."""
        return None
