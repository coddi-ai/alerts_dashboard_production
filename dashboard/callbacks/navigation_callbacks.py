"""
Navigation callbacks for multi-section dashboard.

Handles switching between sections and subsections via left menu.
"""

from dash import Input, Output, State, html, callback_context, ClientsideFunction, clientside_callback
from dash.dependencies import ALL
import dash
from pathlib import Path

# Active tabs
from dashboard.tabs.tab_alerts import create_layout as create_alerts_tab
from dashboard.tabs.tab_overview_general import create_layout as create_overview_general_tab
from dashboard.tabs.tab_data_freshness import create_layout as create_data_freshness_tab
from dashboard.tabs.tab_oil import create_layout as create_oil_tab
from dashboard.tabs.tab_telemetry import create_layout as create_telemetry_tab

# Commented tabs - not currently active
# from dashboard.tabs.tab_limits import create_limits_tab
# from dashboard.tabs.tab_machines import create_machines_tab
# from dashboard.tabs.tab_reports import create_reports_tab
# from dashboard.tabs.tab_mantenciones_general import layout_mantenciones_general
# from dashboard.tabs.tab_health_index import create_layout as create_health_index_tab
# from dashboard.tabs.tab_menace_control import create_layout as create_menace_control_tab
# from dashboard.tabs.tab_hot_sheet import create_layout as create_hot_sheet_tab

from dashboard.layout import create_placeholder_content
from config.settings import get_settings
from src.utils.logger import get_logger

logger = get_logger(__name__)


def has_alerts_data(client: str) -> bool:
    """
    Check if a client has alerts data available.
    
    Args:
        client: Client identifier
        
    Returns:
        True if alerts data exists, False otherwise
    """
    try:
        settings = get_settings()
        alerts_path = settings.data_root / "alerts" / "golden" / client.lower()
        
        if not alerts_path.exists():
            logger.warning(f"Alerts path does not exist for client {client}: {alerts_path}")
            return False
        
        # Check for AI-enhanced CSV files first
        csv_files = list(alerts_path.glob("*.csv"))
        ai_files = [f for f in csv_files if '_AI' in f.name.upper()]
        
        has_data = len(csv_files) > 0
        logger.info(f"Client {client} alerts data check: {has_data} (found {len(csv_files)} CSV files, {len(ai_files)} AI files)")
        
        return has_data
    except Exception as e:
        logger.error(f"Error checking alerts data for client {client}: {e}")
        return False


def register_navigation_callbacks(app: dash.Dash) -> None:
    """
    Register callbacks for dashboard navigation.
    
    Args:
        app: Dash application instance
    """
    
    def get_alerts_content(client: str):
        """
        Get alerts content for any client.
        
        Args:
            client: Client identifier (not used directly, alerts tabs get client from callbacks)
            
        Returns:
            Dashboard content (unified alerts tab with internal tabs)
        """
        logger.info(f"Getting alerts content for client={client}")
        logger.info("Creating unified alerts tab with internal tabs")
        return create_alerts_tab()
    
    # Map subsection IDs to their content generators
    SECTION_CONTENT_MAP = {
        'overview-general': create_overview_general_tab,
        'overview-data-freshness': create_data_freshness_tab,
        # 'monitoring-hot-sheet': create_hot_sheet_tab,  # Commented - moved to overview-general
        'monitoring-alerts': lambda client: get_alerts_content(client),
        # 'monitoring-menace-control': create_menace_control_tab,  # Commented - not active
        'monitoring-telemetry': lambda client: create_telemetry_tab(client),
        # 'monitoring-health-index': create_health_index_tab,  # Commented - not active
        # 'monitoring-mantentions': lambda client: layout_mantenciones_general(),  # Commented - not active
        'monitoring-oil': create_oil_tab,
        # Predictive sections are handled dynamically below
        # 'limits-oil': create_limits_tab,  # Commented - not active
        # New placeholder sections
        'integration-sap': lambda: create_placeholder_content('SAP Connection'),
        'reporting-main': lambda: create_placeholder_content('Reportabilidad'),
        'admin-main': lambda: create_placeholder_content('Administración'),
    }

    def _get_predictive_content(active_section, client):
        """
        Handle dynamic predictive section IDs: predictive-{component}.
        Returns content or None if not a predictive section.
        Only serves content for clients in the predictive_allowed_clients list.
        Shows disclaimer if client has no predictive data.
        """
        import re
        match = re.match(r'^predictive-(.+)$', active_section)
        if not match:
            return None

        # Check if the current client is allowed to access predictive
        settings = get_settings()
        predictive_allowed = [c.lower() for c in settings.predictive_allowed_clients]
        if client.lower() not in predictive_allowed:
            logger.warning(
                f"Predictive module accessed by non-allowed client: {client}. "
                f"Allowed: {predictive_allowed}"
            )
            return create_placeholder_content(
                'Predictivo (Solo disponible para CDA)'
            )

        # Check if predictive data exists for this client
        component = match.group(1)
        data_dir = Path(settings.data_root) / "predictive" / "golden" / client.lower()
        component_file = data_dir / f"{component}.csv"

        if not data_dir.exists() or not component_file.exists():
            logger.warning(f"No predictive data found for client {client}, component {component} at {component_file}")
            return html.Div([
                html.Div([
                    html.Div([
                        html.I(className="fas fa-database fa-3x mb-3 text-muted"),
                        html.H4("Sin datos predictivos disponibles", className="text-muted"),
                        html.P(
                            f"No se encontraron datos predictivos de {component.title()} para el cliente {client.upper()}.",
                            className="text-muted mb-2"
                        ),
                        html.P(
                            "Los datos se generarán cuando exista historial suficiente de aceite y telemetría para este componente.",
                            className="text-muted small"
                        )
                    ], className="text-center py-5")
                ], className="card shadow-sm", style={"marginTop": "16px"})
            ])

        from dashboard.tabs.tab_predictive_component import layout as predictive_component_layout
        return predictive_component_layout(client, component)
    
    # Callback 1: Handle button clicks and update store
    @app.callback(
        Output('active-section-store', 'data'),
        [Input({'type': 'nav-button', 'index': ALL}, 'n_clicks')],
        [State('active-section-store', 'data'),
         State({'type': 'nav-button', 'index': ALL}, 'id')],
        prevent_initial_call=True
    )
    def update_active_section(n_clicks_list, current_section, button_ids):
        """
        Update active section when navigation button is clicked.
        """
        ctx = callback_context
        
        if not ctx.triggered:
            return current_section or 'overview-general'
        
        triggered_prop = ctx.triggered[0]['prop_id']
        
        try:
            import json
            id_dict = json.loads(triggered_prop.split('.')[0])
            return id_dict['index']
        except:
            return current_section or 'overview-general'
    
    # Callback 2: Update content and button styles based on active section
    @app.callback(
        [Output('section-content', 'children'),
         Output({'type': 'nav-button', 'index': ALL}, 'className')],
        [Input('active-section-store', 'data'),
         Input('user-info-store', 'data'),
         Input('client-selector', 'value')],
        [State({'type': 'nav-button', 'index': ALL}, 'id')]
    )
    def update_section_content(active_section, user_data, selected_client, button_ids):
        """
        Update content when active section changes.
        
        Args:
            active_section: Currently active section ID
            user_data: User information from session
            selected_client: Client selected in the top-bar dropdown
            button_ids: List of all button IDs
        
        Returns:
            Tuple of (content, button_classes)
        """
        # Default to overview if no section specified
        if not active_section:
            active_section = 'overview-general'
        
        # Use the client-selector dropdown value (respects admin switching clients)
        if selected_client:
            client = selected_client.lower()
            logger.info(f"Using client from client-selector dropdown: {client}")
        elif user_data and 'clients' in user_data and user_data['clients']:
            client = user_data['clients'][0].lower()
            logger.info(f"Using client from user data: {client}")
        else:
            settings = get_settings()
            client = settings.clients[0].lower() if settings.clients else 'cda'
            logger.info(f"Using default client: {client}")
        
        logger.info(f"Updating section content: section={active_section}, client={client}")
        
        # Check if this is a dynamic predictive section first
        predictive_content = _get_predictive_content(active_section, client)
        if predictive_content is not None:
            content = predictive_content
        else:
            # Get content for active section from static map
            content_generator = SECTION_CONTENT_MAP.get(
                active_section,
                lambda c: create_placeholder_content('Unknown Section')
            )
            
            # Call content generator with client parameter
            # Some generators need client, others don't
            try:
                if active_section in ['overview-general',
                                     'overview-data-freshness',
                                     'monitoring-alerts', 
                                     'monitoring-telemetry', 
                                     'monitoring-mantentions']:
                    content = content_generator(client)
                elif active_section in ['integration-sap', 'reporting-main', 'admin-main']:
                    # Placeholder sections don't need client parameter
                    content = content_generator()
                else:
                    content = content_generator()
            except TypeError as e:
                # Fallback if function doesn't accept client parameter
                logger.warning(f"TypeError calling content_generator for {active_section}: {e}")
                try:
                    content = content_generator()
                except:
                    content = create_placeholder_content(f'Error loading {active_section}')
        
        # Update button classes to highlight active button
        button_classes = []
        for button_id in button_ids:
            section_id = button_id['index']
            if section_id == active_section:
                # Active button style
                button_classes.append(
                    "text-start text-white w-100 mb-1 ps-4 active"
                )
            else:
                # Inactive button style
                button_classes.append(
                    "text-start text-white-50 w-100 mb-1 ps-4"
                )
        
        return content, button_classes
    
    # Callback 3: Update client logo when client selector changes
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
