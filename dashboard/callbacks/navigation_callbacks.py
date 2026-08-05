"""
Navbar callbacks for multi-section dashboard.

Section routing itself is now handled by Dash Pages (dash.page_container +
dbc.NavLink hrefs in dashboard/layout.py). This module only keeps the
client-logo callback, which reacts to the global client-selector dropdown
and is unrelated to page routing.
"""

from dash import Input, Output
import dash

from src.utils.logger import get_logger

logger = get_logger(__name__)


def register_navigation_callbacks(app: dash.Dash) -> None:
    """
    Register navbar-related callbacks (client logo).

    Args:
        app: Dash application instance
    """

    # Update client logo when client selector changes
    @app.callback(
        [Output('client-logo-img', 'src'),
         Output('client-logo-img', 'style'),
         Output('client-logo-img', 'className')],
        [Input('client-selector', 'value')],
        prevent_initial_call=False
    )
    def update_client_logo(selected_client):
        """
        Update client logo based on selected client.

        Args:
            selected_client: Client selected in the dropdown

        Returns:
            Tuple of (logo_src, logo_style, logo_className)
        """
        if not selected_client:
            # No client selected - hide logo
            return '', {
                "height": "48px",
                "width": "auto",
                "maxWidth": "120px",
                "padding": "4px 12px",
                "marginLeft": "12px",
                "display": "none"
            }, ''

        # Construct logo URL - use GitHub raw content URL for production reliability
        client_lower = selected_client.lower()

        # Try PNG first, fallback to JPEG if needed
        # GitHub raw content URL format for direct image access
        base_url = 'https://raw.githubusercontent.com/coddi-ai/tds_alerts_dashboard/dev/dashboard/logos'
        logo_url = f'{base_url}/{client_lower}.png'

        logger.info(f"Updating client logo for {selected_client}: {logo_url}")

        # Add client-specific class for conditional styling
        # ENEX logo doesn't need white background, others do
        client_class = f'client-logo client-logo-{client_lower}'

        # Return URL, style, and className
        return logo_url, {
            "height": "48px",
            "width": "auto",
            "maxWidth": "120px",
            "padding": "4px 12px",
            "marginLeft": "12px",
            "display": "block"
        }, client_class
