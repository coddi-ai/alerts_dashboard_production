"""
Predictive Component Page - Unified page per component with internal tabs (Resumen / Evidencia).
"""

from dash import html, dcc
from dashboard.components.predictive_config import get_failure_mode_options
from dashboard.tabs.tab_predictive_overview import (
    _discover_components,
    _load_component_data as _load_overview_data,
    _render_component_overview,
)
from dashboard.tabs.tab_predictive_evidence import (
    _load_component_data as _load_evidence_data,
)
from src.utils.logger import get_logger

logger = get_logger(__name__)

# Component icon map
COMPONENT_ICONS = {
    "motor": "fas fa-cog",
    "transmision": "fas fa-exchange-alt",
}


def layout(client: str, component: str):
    """
    Render the unified predictive page for a specific component.
    Contains internal tabs: Resumen (overview) and Evidencia (evidence).
    """
    components = _discover_components(client)
    filepath = components.get(component)

    if not filepath:
        return html.Div([
            html.Div([
                html.I(className="fas fa-brain me-3"),
                f"Predictivo — {component.title()}"
            ], className="page-title", style={"display": "flex", "alignItems": "center"}),
            html.P(f"No hay datos predictivos disponibles para {component}.",
                   className="text-muted", style={"padding": "40px", "textAlign": "center"})
        ])

    # Load overview data
    df_ov, df_latest, prev_ranking = _load_overview_data(filepath, component)

    # Build overview content
    if df_latest is not None and not df_latest.empty:
        overview_content = _render_component_overview(df_latest, prev_ranking, component, client)
    else:
        overview_content = html.P(f"No hay datos de resumen para {component}.",
                                  className="text-muted text-center", style={"padding": "40px"})

    # Load evidence data for initial render
    df_ev, df_ev_latest = _load_evidence_data(filepath, component)
    units = sorted(df_ev["Unit"].unique()) if df_ev is not None else []
    failure_mode_options = get_failure_mode_options(component)

    # Build evidence content (interactive - populated by callbacks)
    evidence_content = html.Div([
        # Unit selector
        html.Div([
            html.Div([
                dcc.Dropdown(
                    id="predictive-ev-unit",
                    options=[{"label": u, "value": u} for u in units],
                    value=units[0] if units else None,
                    clearable=False,
                    className="ev-unit-dropdown",
                ),
            ], className="ev-unit-selector"),
        ], className="ev-page-header"),

        # Unit banner
        html.Div(id="predictive-ev-unit-banner", style={"marginTop": "1rem"}),

        # KPIs and fleet (updated by callback)
        html.Div(id="predictive-ev-initial-content", className="mt-4"),

        # Failure mode selector
        html.Div([
            html.Div([
                html.H5([html.I(className="fas fa-cogs me-2"), "Seleccionar Modo de Falla"], className="mb-2"),
                html.P("Elige un modo de falla para ver evidencia detallada de aceite y telemetría",
                       className="text-muted mb-2", style={"fontSize": "12px"}),
            ]),
            dcc.Dropdown(
                id="predictive-ev-failure-mode",
                options=failure_mode_options,
                value=None,
                clearable=False,
                className="ev-unit-dropdown",
                style={"marginTop": "8px"}
            ),
        ], className="card shadow-sm", style={"marginBottom": "1.5rem", "padding": "16px"}),

        # Detailed evidence (updated by callback)
        html.Div(id="predictive-ev-detailed-content"),
    ])

    icon = COMPONENT_ICONS.get(component, "fas fa-microchip")

    return html.Div([
        # Page header
        html.Div([
            html.Div([
                html.I(className=f"{icon} me-2"),
                f"Predictivo — {component.title()}"
            ], className="page-title", style={"display": "flex", "alignItems": "center"}),
            html.Div(f"Análisis predictivo de condición — {component}", className="page-subtitle"),
        ], style={"marginBottom": "16px"}),

        # Internal tabs: Resumen / Evidencia
        dcc.Tabs(
            id='predictive-component-internal-tabs',
            value='resumen',
            children=[
                dcc.Tab(label='  Resumen', value='resumen',
                        className='custom-tab', selected_className='custom-tab--selected'),
                dcc.Tab(label='  Evidencia', value='evidencia',
                        className='custom-tab', selected_className='custom-tab--selected'),
            ],
            className='mb-4'
        ),

        # Tab content area (switched by callback)
        html.Div(id='predictive-component-tab-content', children=overview_content),

        # Hidden stores
        dcc.Store(id="predictive-ev-client-store", data=client),
        dcc.Store(id="predictive-ev-component-store", data=component),
        # Store the pre-rendered overview so the callback can restore it without re-computing
        dcc.Store(id="predictive-overview-cache", data="cached"),
    ], className="overview-container")
