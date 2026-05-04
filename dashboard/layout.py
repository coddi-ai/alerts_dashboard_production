"""
Main layout for Multi-Technical-Alerts dashboard.

Defines the overall application layout and navigation.

Custom CSS for navigation and layout styling is automatically loaded from:
- dashboard/assets/custom_layout.css
"""

from dash import dcc, html
import dash_bootstrap_components as dbc
# Commented tabs - not currently active in navigation
# from dashboard.tabs.tab_limits import create_limits_tab
# from dashboard.tabs.tab_machines import create_machines_tab
# from dashboard.tabs.tab_reports import create_reports_tab
from dashboard.tabs.tab_alerts import create_layout as create_alerts_tab
# from dashboard.tabs.tab_mantenciones_general import layout_mantenciones_general
# from dashboard.tabs.tab_telemetry import create_layout as create_telemetry_tab
from dashboard.tabs.tab_overview_general import create_layout as create_overview_general_tab
from dashboard.tabs.tab_oil import create_layout as create_oil_tab
# from dashboard.tabs.tab_health_index import create_layout as create_health_index_tab
# from dashboard.tabs.tab_menace_control import create_layout as create_menace_control_tab
# from dashboard.tabs.tab_hot_sheet import create_layout as create_hot_sheet_tab


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
        ], className="align-items-center min-vh-100")
    ], fluid=True, style={
        "background": "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
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
                                style={"fontWeight": "500"}
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
                    html.H3("En Progreso", className="text-muted"),
                    html.P(
                        f"La sección {section_name} está actualmente en desarrollo.",
                        className="text-muted mb-2"
                    ),
                    html.P(
                        "Esta funcionalidad estará disponible pronto. Consulte el plan de migración para la línea de tiempo.",
                        className="text-muted small"
                    )
                ], className="text-center py-5")
            ])
        ])
    ], className="mt-4")


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
    
    # Define navigation structure
    navigation_items = [
        {
            'section': 'overview',
            'label': 'Resumen',
            'icon': 'fas fa-tachometer-alt',
            'subsections': [
                {'id': 'overview-general', 'label': 'General', 'tab': create_overview_general_tab}
            ]
        },
        {
            'section': 'monitoring',
            'label': 'Monitoreo',
            'icon': 'fas fa-chart-line',
            'subsections': [
                # {'id': 'monitoring-hot-sheet', 'label': 'Hot Sheet', 'tab': create_hot_sheet_tab},
                {'id': 'monitoring-alerts', 'label': 'Alertas', 'tab': create_alerts_tab},
                # {'id': 'monitoring-menace-control', 'label': 'Control de Amenazas', 'tab': create_menace_control_tab},
                # {'id': 'monitoring-telemetry', 'label': 'Telemetría', 'tab': create_telemetry_tab},
                # {'id': 'monitoring-health-index', 'label': 'Índice de Salud', 'tab': create_health_index_tab},
                # {'id': 'monitoring-mantentions', 'label': 'Mantenciones', 'tab': layout_mantenciones_general},
                {'id': 'monitoring-oil', 'label': 'Aceite', 'tab': create_oil_tab}
            ]
        },
        # {
        #     'section': 'limits',
        #     'label': 'Límites',
        #     'icon': 'fas fa-sliders-h',
        #     'subsections': [
        #         {'id': 'limits-oil', 'label': 'Aceite', 'tab': create_limits_tab}
        #     ]
        # }
    ]
    
    # Build left menu with improved styling
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
                dbc.Button(
                    [
                        html.I(className="fas fa-chevron-right me-2 nav-chevron", style={"fontSize": "0.7rem"}),
                        subsection['label']
                    ],
                    id={'type': 'nav-button', 'index': subsection['id']},
                    color="link",
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
        
        # Menu items container
        html.Div(
            menu_items,
            className="p-3 sidebar-menu",
            style={"overflowY": "auto", "height": "calc(100vh - 142px)"}
        )
    ], style={
        "width": "260px",
        "backgroundColor": "#2c3e50",
        "height": "100vh",
        "position": "fixed",
        "left": 0,
        "top": "80px",
        "boxShadow": "2px 0 8px rgba(0,0,0,0.1)",
        "zIndex": 999
    })
    
    # Content area with proper spacing from header and sidebar
    content_area = html.Div([
        # Dynamic content
        html.Div(id='section-content')
    ], style={
        "marginLeft": "260px",
        "marginTop": "80px",
        "padding": "28px",
        "backgroundColor": "#f8f9fa",
        "minHeight": "calc(100vh - 80px)"
    })
    
    return html.Div([
        create_navbar(user_data, available_clients),
        left_menu,
        content_area,
        
        # Store for active section
        dcc.Store(id='active-section-store', data='overview-general')
    ])


def create_app_layout() -> html.Div:
    """
    Create the complete application layout.
    
    Returns:
        Root layout with stores and page content
    """
    return html.Div([
        # Store user info (initialized to None to trigger initial callback)
        dcc.Store(id='user-info-store', storage_type='session', data=None),
        
        # Store navigation state for cross-page navigation
        dcc.Store(id='navigation-state', storage_type='memory', data=None),
        
        # Store for active tab
        dcc.Store(id='active-tab-store', storage_type='memory', data=None),
        
        # Store for alerts internal navigation
        dcc.Store(id='alerts-navigation-state', storage_type='memory', data=None),
        
        # Page content (initialized with login page, will be replaced by callback)
        html.Div(id='page-content', children=create_login_page())
    ])
