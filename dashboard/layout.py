"""
Main layout for Multi-Technical-Alerts dashboard.

Defines the overall application layout and navigation.

Custom CSS for navigation and layout styling is automatically loaded from:
- dashboard/assets/custom_layout.css
"""

from dash import dcc, html
import dash_bootstrap_components as dbc
import dash
import os
from pathlib import Path
from config.settings import get_settings, APP_VERSION
from config.client_services import is_service_enabled
from dashboard.auth import is_admin
from dashboard.services_registry import SERVICE_SECTIONS, SERVICE_LABELS, nav_path as _nav_path


# Component icon map for predictive nav sections
PREDICTIVE_COMPONENT_ICONS = {
    "motor": "fas fa-cog",
    "transmision": "fas fa-exchange-alt",
}


def _campbell_ai_enabled() -> bool:
    """Keep the new navigation entry behind an environment feature flag."""
    return os.getenv("CAMPBELL_AI_ENABLED", "true").strip().lower() in {
        "1", "true", "yes", "on"
    }


def _discover_predictive_components(client: str) -> list:
    """Discover available predictive component CSVs for a client."""
    settings = get_settings()
    data_dir = Path(settings.data_root) / "predictive" / "golden" / client
    if not data_dir.exists():
        return []
    return sorted([f.replace(".csv", "") for f in os.listdir(data_dir) if f.endswith(".csv")])


def create_login_page() -> dbc.Container:
    """
    Create redesigned login page with improved spacing, logo visibility, and form usability.

    Returns:
        Bootstrap container with professional login form
    """
    return dbc.Container([
        dbc.Row([
            dbc.Col([
                # Login card with integrated branding
                dbc.Card([
                    dbc.CardBody([
                        # Branding section
                        html.Div([
                            html.Div(
                                html.Img(
                                    src="https://raw.githubusercontent.com/coddi-ai/tds_alerts_dashboard/refs/heads/dev/dashboard/assets/logo.svg",
                                    style={
                                        "height": "64px",
                                        "width": "auto",
                                        "padding": "8px 16px",
                                        "backgroundColor": "white",
                                        "borderRadius": "8px",
                                        "border": "2px solid #e0e0e0",
                                        "boxShadow": "0 2px 8px rgba(0,0,0,0.08)"
                                    }
                                ),
                                className="text-center"
                            ),
                            html.H3(
                                "Plataforma de Monitoreo Multi-Técnica",
                                className="text-center mt-3 mb-1",
                                style={"fontWeight": "600", "color": "#1a252f", "fontSize": "1.4rem"}
                            ),
                            # html.P(
                            #     "Technical Alerts Dashboard",
                            #     className="text-center mb-0 text-muted",
                            #     style={"fontSize": "0.9rem"}
                            # )
                        ], style={
                            "padding": "32px 32px 24px 32px",
                            "borderBottom": "2px solid #f0f0f0",
                            "backgroundColor": "#fafafa"
                        }),
                        
                        # Login form section
                        html.Div([
                            html.H4(
                                "Iniciar Sesión",
                                className="mb-1 text-center",
                                style={"fontWeight": "600", "fontSize": "1.3rem"}
                            ),
                            # html.P(
                            #     "Enter your credentials to access the platform",
                            #     className="text-center text-muted mb-4",
                            #     style={"fontSize": "0.85rem"}
                            # ),

                            dbc.Alert(
                                id='login-alert',
                                is_open=False,
                                color='danger',
                                duration=4000,
                                className="mb-3"
                            ),

                            # Username field
                            html.Div([
                                html.Label(
                                    "Usuario",
                                    className="form-label fw-500 mb-2",
                                    style={"fontSize": "0.9rem", "color": "#495057"}
                                ),
                                dbc.InputGroup([
                                    dbc.InputGroupText(
                                        html.I(className="fas fa-user"),
                                        style={"backgroundColor": "#f8f9fa"}
                                    ),
                                    dbc.Input(
                                        id='username-input',
                                        placeholder='Ingrese su usuario',
                                        type='text',
                                        style={"fontSize": "0.95rem"},
                                        autoComplete="username"
                                    )
                                ], className="mb-3")
                            ]),

                            # Password field
                            html.Div([
                                html.Label(
                                    "Contraseña",
                                    className="form-label fw-500 mb-2",
                                    style={"fontSize": "0.9rem", "color": "#495057"}
                                ),
                                dbc.InputGroup([
                                    dbc.InputGroupText(
                                        html.I(className="fas fa-lock"),
                                        style={"backgroundColor": "#f8f9fa"}
                                    ),
                                    dbc.Input(
                                        id='password-input',
                                        placeholder='Ingrese su contraseña',
                                        type='password',
                                        style={"fontSize": "0.95rem"},
                                        autoComplete="current-password"
                                    )
                                ], className="mb-4")
                            ]),

                            # Login button with loading state
                            dbc.Button(
                                [
                                    html.I(className="fas fa-sign-in-alt me-2"),
                                    "Iniciar Sesión"
                                ],
                                id='login-button',
                                n_clicks=0,
                                color='primary',
                                size="lg",
                                className='w-100',
                                style={
                                    "fontWeight": "600",
                                    "padding": "12px",
                                    "fontSize": "1rem"
                                }
                            ),
                            
                            # Loading indicator (hidden by default)
                            dbc.Spinner(
                                id="login-spinner",
                                size="sm",
                                color="primary",
                                spinner_style={"display": "none"},
                                spinnerClassName="mt-3 text-center"
                            )
                        ], style={"padding": "32px"})
                    ], style={"padding": "0"})
                ], className='shadow-lg', style={
                    "borderRadius": "12px",
                    "border": "none",
                    "overflow": "hidden"
                })
            ], width=12, lg=5, xl=4, className='mx-auto')
        ], className="align-items-center min-vh-100"),

        # Version footnote, bottom-left of the screen
        html.Div(
            f"v{APP_VERSION}",
            style={
                "position": "fixed",
                "bottom": "12px",
                "left": "16px",
                "color": "rgba(255, 255, 255, 0.5)",
                "fontSize": "0.75rem"
            }
        )
    ], fluid=True, style={
        "background": "#00173b",
        "minHeight": "100vh"
    })

def create_navbar(user_data: dict, available_clients: list[str] = None) -> html.Div:
    """
    Create redesigned navbar with improved logo visibility, client selector, and professional styling.
    
    Args:
        user_data: User information dictionary
        available_clients: List of clients user has access to
    
    Returns:
        Modern header with integrated global controls
    """
    if available_clients is None:
        available_clients = user_data.get('clients', [])
    
    return html.Div([
        # Main header bar
        html.Div([
            dbc.Container([
                dbc.Row([
                    # Logo and brand section
                    dbc.Col([
                        html.Div([
                            # CODDI Logo
                            html.Img(
                                src='https://raw.githubusercontent.com/coddi-ai/tds_alerts_dashboard/refs/heads/dev/dashboard/assets/logo.svg',
                                style={
                                    "height": "48px",
                                    "width": "auto",
                                    "padding": "4px 12px",
                                    "backgroundColor": "white",
                                    "borderRadius": "6px",
                                    "boxShadow": "0 2px 4px rgba(0,0,0,0.1)"
                                }
                            ),
                            # Client Logo (dynamically loaded)
                            html.Img(
                                id='client-logo-img',
                                src='',
                                alt='',  # Empty alt to prevent text showing on error
                                style={
                                    "height": "48px",
                                    "width": "auto",
                                    "maxWidth": "120px",
                                    "padding": "4px 12px",
                                    "marginLeft": "12px",
                                    "display": "none"  # Hidden by default, shown when logo loads successfully
                                }
                            ),
                            # Platform title
                            html.Div([
                                html.H5(
                                    "Plataforma de Monitoreo Multi-Técnica",
                                    className="mb-0 text-white",
                                    style={"fontWeight": "600", "letterSpacing": "-0.3px"}
                                ),
                                html.Small(
                                    "Technical Alerts Dashboard",
                                    className="text-white-50",
                                    style={"fontSize": "0.8rem"}
                                )
                            ], className="ms-3")
                        ], className="d-flex align-items-center")
                    ], width="auto"),
                    
                    # Client selector - Compact global control
                    dbc.Col([
                        html.Div([
                            html.Span(
                                [html.I(className="fas fa-building me-2", style={"fontSize": "0.75rem"}), "Cliente:"],
                                className="text-white-50 me-2",
                                style={"fontSize": "0.75rem", "fontWeight": "400"}
                            ),
                            dcc.Dropdown(
                                id='client-selector',
                                options=[{'label': client, 'value': client} for client in available_clients],
                                value=available_clients[0] if available_clients else None,
                                clearable=False,
                                style={
                                    "width": "140px",
                                    "fontSize": "0.85rem"
                                },
                                className="client-compact-selector"
                            )
                        ], className="d-flex align-items-center")
                    ], width="auto", className="ms-auto me-4"),
                    
                    # User info section
                    dbc.Col([
                        html.Div([
                            html.Div([
                                html.I(className="fas fa-user-circle fa-lg me-2 text-white-50"),
                                html.Div([
                                    html.Div(
                                        user_data.get('username', 'Unknown'),
                                        className="text-white",
                                        style={"fontSize": "0.9rem", "fontWeight": "500"}
                                    ),
                                    html.Div(
                                        user_data.get('role', 'N/A').title(),
                                        className="text-white-50",
                                        style={"fontSize": "0.75rem"}
                                    )
                                ])
                            ], className="d-flex align-items-center me-3"),
                            html.Div(
                                style={"width": "1px", "height": "40px", "backgroundColor": "rgba(255,255,255,0.2)"},
                                className="me-3"
                            ),
                            dbc.Button(
                                [html.I(className="fas fa-sign-out-alt me-2"), "Cerrar Sesión"],
                                id='logout-button',
                                color="danger",
                                size="sm",
                                className="px-3",
                                style={"fontWeight": "500"},
                                n_clicks=0
                            )
                        ], className="d-flex align-items-center")
                    ], width="auto")
                ], align="center", className="g-0 py-3")
            ], fluid=True)
        ], style={
            "backgroundColor": "#1a252f",
            "borderBottom": "3px solid #3498db",
            "boxShadow": "0 2px 8px rgba(0,0,0,0.15)",
            "position": "fixed",
            "top": 0,
            "left": 0,
            "right": 0,
            "zIndex": 1000,
            "height": "80px"
        })
    ])


def create_placeholder_content(section_name: str) -> html.Div:
    """
    Create placeholder content for sections under development.
    
    Args:
        section_name: Name of the section being developed
    
    Returns:
        Placeholder div with "In Progress" message
    """
    return html.Div([
        dbc.Card([
            dbc.CardBody([
                html.Div([
                    html.I(className="fas fa-tools fa-3x mb-3 text-muted"),
                    html.H3("En Desarrollo", className="text-muted"),
                    html.P(
                        f"Estamos trabajando en la sección {section_name}.",
                        className="text-muted mb-2"
                    ),
                    html.P(
                        "Esta funcionalidad estará disponible pronto.",
                        className="text-muted small"
                    )
                ], className="text-center py-5")
            ])
        ])
    ], className="mt-4")


def build_navigation_items(selected_client: str, user_data: dict) -> list:
    """
    Build the nav-section/subsection data for the CURRENTLY SELECTED client.

    Visibility is keyed on the active client (not "any client the user has"),
    so it always matches exactly what dashboard/callbacks/access_control_callbacks.py
    will actually let the user reach - a disabled service is never shown, and
    switching clients in the navbar updates this immediately (see
    dashboard/callbacks/sidebar_callbacks.py, which re-renders on
    client-selector change).
    """
    def _enabled(service_id: str) -> bool:
        # Campbell AI additionally sits behind a global kill switch, on top of
        # the per-client service registry - so it can be pulled everywhere
        # (e.g. an OpenAI outage) without editing client_services.yaml.
        if service_id == "agents-campbell-ai" and not _campbell_ai_enabled():
            return False
        return is_service_enabled(selected_client, service_id)

    user_has_predictive_access = _enabled('predictive')

    # Use statically-known component list for navigation (data availability checked at runtime)
    predictive_nav_components = list(PREDICTIVE_COMPONENT_ICONS.keys()) if user_has_predictive_access else []

    # Build navigation from the central services registry, keeping only the
    # services enabled for the selected client - a disabled service is
    # omitted entirely, never shown as an inactive tab. A section with zero
    # visible services is skipped. Predictive is spliced in after
    # 'monitoring' (its historical position) since its subsections are
    # discovered dynamically rather than listed in SERVICE_SECTIONS. Campbell
    # AI's own global kill switch is folded into _enabled() above, so its
    # 'agents' section is omitted the same way a disabled client service is.
    navigation_items = []
    for section_def in SERVICE_SECTIONS:
        subsections = [
            {'id': service_id, 'label': SERVICE_LABELS[service_id]}
            for service_id in section_def['services']
            if _enabled(service_id)
        ]
        if subsections:
            navigation_items.append({
                'section': section_def['section'],
                'label': section_def['label'],
                'icon': section_def['icon'],
                'subsections': subsections,
            })

        if section_def['section'] == 'monitoring' and user_has_predictive_access:
            navigation_items.append({
                'section': 'predictive',
                'label': 'Predictivo',
                'icon': 'fas fa-brain',
                'subsections': [
                    {'id': f'predictive-{comp}', 'label': comp.title()}
                    for comp in predictive_nav_components
                ]
            })

    # Admin section: controlled by role, independent of client service availability.
    if is_admin(user_data):
        navigation_items.append({
            'section': 'admin',
            'label': 'Administración',
            'icon': 'fas fa-cog',
            'subsections': [
                {'id': 'admin-main', 'label': 'Administración'},
                {'id': 'admin-user-registry', 'label': 'Registro de usuarios'},
            ]
        })

    return navigation_items


def build_menu_items(navigation_items: list) -> list:
    """Render navigation_items (see build_navigation_items) into sidebar components."""
    menu_items = []
    for section in navigation_items:
        # Section header - improved typography and spacing
        menu_items.append(
            html.Div([
                html.I(
                    className=f"{section['icon']} me-3",
                    style={"fontSize": "1.1rem"}
                ),
                html.Span(
                    section['label'],
                    style={
                        "fontWeight": "600",
                        "fontSize": "0.95rem",
                        "letterSpacing": "0.3px",
                        "textTransform": "uppercase"
                    }
                )
            ],
            className="text-white mb-3 mt-4 pb-2",
            style={"borderBottom": "2px solid rgba(255,255,255,0.1)"}
            )
        )

        # Subsections - improved interaction states
        for subsection in section['subsections']:
            menu_items.append(
                dbc.NavLink(
                    [
                        html.I(className="fas fa-chevron-right me-2 nav-chevron", style={"fontSize": "0.7rem"}),
                        subsection['label']
                    ],
                    href=dash.get_relative_path(_nav_path(subsection['id'])),
                    active="exact",
                    className="nav-menu-item text-start w-100 mb-1 px-3 py-2",
                    style={
                        "textDecoration": "none",
                        "fontSize": "0.9rem",
                        "color": "rgba(255,255,255,0.7)",
                        "borderRadius": "6px",
                        "transition": "all 0.2s ease",
                        "fontWeight": "400"
                    }
                )
            )
    return menu_items


def create_main_dashboard(user_data: dict) -> html.Div:
    """
    Create main dashboard layout with redesigned navigation and unified shell.

    Args:
        user_data: User information dictionary

    Returns:
        Professional dashboard layout with full-height sidebar and integrated header
    """
    # Get clients user has access to
    available_clients = user_data.get('clients', [])

    # Initial render uses the client-selector's own default (its first
    # option) - dashboard/callbacks/sidebar_callbacks.py takes over from
    # here and re-renders #sidebar-nav-menu whenever the selector changes.
    default_client = available_clients[0] if available_clients else None
    navigation_items = build_navigation_items(default_client, user_data)
    menu_items = build_menu_items(navigation_items)

    # Full-height sidebar with no gaps
    left_menu = html.Div([
        # Sidebar header
        html.Div([
            html.Div([
                html.I(className="fas fa-bars me-3", style={"fontSize": "1.2rem"}),
                html.Span(
                    "Navigation",
                    style={
                        "fontSize": "1.1rem",
                        "fontWeight": "700",
                        "letterSpacing": "0.5px"
                    }
                )
            ], className="text-white d-flex align-items-center")
        ], style={
            "padding": "24px 20px",
            "backgroundColor": "rgba(0,0,0,0.2)",
            "borderBottom": "2px solid rgba(255,255,255,0.1)"
        }),

        # Menu items container - re-rendered by dashboard/callbacks/sidebar_callbacks.py
        # whenever client-selector changes, so it always reflects the
        # currently selected client's enabled services.
        html.Div(
            id='sidebar-nav-menu',
            children=menu_items,
            className="p-3 sidebar-menu",
            style={"overflowY": "auto", "height": "calc(100vh - 142px)"}
        )
    ], id='app-sidebar', style={
        "width": "260px",
        "backgroundColor": "#2c3e50",
        "height": "100vh",
        "position": "fixed",
        "left": 0,
        "top": "80px",
        "boxShadow": "2px 0 8px rgba(0,0,0,0.1)",
        "zIndex": 999
    })

    # Floating toggle button - lives outside the sidebar so it stays
    # reachable (to re-expand) even while the sidebar is collapsed. Its
    # position and icon direction are driven purely by CSS off the
    # 'sidebar-collapsed' class on #dashboard-shell (see
    # dashboard/assets/custom_layout.css), toggled by the clientside
    # callback in dashboard/callbacks/sidebar_callbacks.py.
    sidebar_toggle_button = html.Button(
        html.I(id='sidebar-toggle-icon', className="fas fa-chevron-left"),
        id='sidebar-toggle-btn',
        title='Ocultar/mostrar menú de navegación',
        n_clicks=0,
        className='sidebar-toggle-btn'
    )

    # Content area with proper spacing from header and sidebar
    content_area = html.Div([
        # Routed page content
        dash.page_container
    ], id='app-content-wrapper', style={
        "marginLeft": "260px",
        "marginTop": "80px",
        "padding": "28px",
        "backgroundColor": "#f8f9fa",
        "minHeight": "calc(100vh - 80px)"
    })

    return html.Div([
        create_navbar(user_data, available_clients),
        left_menu,
        sidebar_toggle_button,
        content_area
    ], id='dashboard-shell')


def create_app_layout() -> html.Div:
    """
    Create the complete application layout.
    
    Returns:
        Root layout with stores and page content
    """
    return html.Div([
        # Store user info (initialized to None to trigger initial callback)
        dcc.Store(id='user-info-store', storage_type='session', data=None),

        # Session-scoped operator name for ERP notice validation (Validación de Avisos)
        dcc.Store(id='erp-validator-operator-store', storage_type='session', data=None),

        # Store navigation state for cross-page navigation
        dcc.Store(id='navigation-state', storage_type='memory', data=None),
        
        # Store for active tab
        dcc.Store(id='active-tab-store', storage_type='memory', data=None),
        
        # Store for alerts internal navigation
        dcc.Store(id='alerts-navigation-state', storage_type='memory', data=None),

        # Sidebar collapsed/expanded preference - persisted across page
        # navigation and browser sessions (see dashboard/callbacks/sidebar_callbacks.py).
        dcc.Store(id='sidebar-collapsed-store', storage_type='local', data=False),

        # Page content (initialized with login page, will be replaced by callback)
        html.Div(id='page-content', children=create_login_page())
    ])
