"""
Predictive callbacks - handles internal tab switching and evidence interactivity.
"""

from dash import html, dcc, Input, Output, State, no_update
import pandas as pd
from src.utils.logger import get_logger
from dashboard.components.predictive_config import (
    get_failure_modes_dict,
    get_failure_mode_options,
)
from dashboard.tabs.tab_predictive_overview import (
    _discover_components,
    _load_component_data as _load_overview_component,
    _render_component_overview,
)
from dashboard.tabs.tab_predictive_evidence import (
    _load_component_data as _load_evidence_component,
    render_initial_content,
    render_detailed_evidence,
)

logger = get_logger(__name__)


def register_callbacks(app):
    """Register predictive callbacks."""

    # ══════════════════════════════════════════════════════════════════════════
    # INTERNAL TAB SWITCHING: Resumen / Evidencia
    # ══════════════════════════════════════════════════════════════════════════

    @app.callback(
        Output("predictive-component-tab-content", "children"),
        Input("predictive-component-internal-tabs", "value"),
        State("predictive-ev-client-store", "data"),
        State("predictive-ev-component-store", "data"),
    )
    def switch_internal_tab(tab_value, client, component):
        if not client or not component:
            return no_update

        if tab_value == 'resumen':
            # Render overview
            components = _discover_components(client)
            filepath = components.get(component)
            if not filepath:
                return html.P(f"No hay datos para {component}.", className="text-muted text-center")

            df, df_latest, prev_ranking = _load_overview_component(filepath, component)
            if df_latest is None or df_latest.empty:
                return html.P(f"No hay datos disponibles para {component}.", className="text-muted text-center")

            return _render_component_overview(df_latest, prev_ranking, component)

        else:
            # Render evidence shell (interactive parts handled by other callbacks)
            components = _discover_components(client)
            filepath = components.get(component)
            if not filepath:
                return html.P(f"No hay datos para {component}.", className="text-muted text-center")

            df, df_latest = _load_evidence_component(filepath, component)
            units = sorted(df["Unit"].unique()) if df is not None else []
            failure_mode_options = get_failure_mode_options(component)

            return html.Div([
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

    # ══════════════════════════════════════════════════════════════════════════
    # EVIDENCE: Unit banner
    # ══════════════════════════════════════════════════════════════════════════

    @app.callback(
        Output("predictive-ev-unit-banner", "children"),
        Input("predictive-ev-unit", "value"),
    )
    def update_unit_banner(selected_unit):
        if not selected_unit:
            return None

        return html.Div([
            html.Div([
                html.Div([
                    html.I(className="fas fa-truck me-3", style={"fontSize": "24px"}),
                    html.Div([
                        html.Div("Unidad Seleccionada", style={
                            "fontSize": "11px", "fontWeight": "500",
                            "textTransform": "uppercase", "letterSpacing": "0.5px",
                            "opacity": "0.8", "marginBottom": "4px"
                        }),
                        html.Div(selected_unit, style={
                            "fontSize": "28px", "fontWeight": "700", "letterSpacing": "-0.5px"
                        })
                    ]),
                ], style={"display": "flex", "alignItems": "center", "gap": "16px"})
            ], style={
                "background": "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
                "color": "white", "padding": "20px 28px", "borderRadius": "12px",
                "boxShadow": "0 4px 12px rgba(102, 126, 234, 0.3)", "marginBottom": "1.5rem"
            })
        ])

    # ══════════════════════════════════════════════════════════════════════════
    # EVIDENCE: KPIs and fleet comparison (when unit changes)
    # ══════════════════════════════════════════════════════════════════════════

    @app.callback(
        Output("predictive-ev-initial-content", "children"),
        Input("predictive-ev-unit", "value"),
        State("predictive-ev-client-store", "data"),
        State("predictive-ev-component-store", "data"),
    )
    def update_initial_content(selected_unit, client, component):
        if not selected_unit or not client or not component:
            return html.Div(html.P("Seleccione una unidad.", className="text-muted text-center", style={"padding": "40px"}))

        components = _discover_components(client)
        filepath = components.get(component)
        if not filepath:
            return html.Div(html.P("No hay datos disponibles.", className="text-muted text-center", style={"padding": "40px"}))

        df, df_latest = _load_evidence_component(filepath, component)
        if df is None:
            return html.Div(html.P("No hay datos disponibles.", className="text-muted text-center", style={"padding": "40px"}))

        return render_initial_content(selected_unit, df, df_latest, component)

    # ══════════════════════════════════════════════════════════════════════════
    # EVIDENCE: Set default failure mode when unit changes
    # ══════════════════════════════════════════════════════════════════════════

    @app.callback(
        Output("predictive-ev-failure-mode", "value"),
        Input("predictive-ev-unit", "value"),
        State("predictive-ev-client-store", "data"),
        State("predictive-ev-component-store", "data"),
    )
    def set_default_failure_mode(selected_unit, client, component):
        if not selected_unit or not client or not component:
            return no_update

        components = _discover_components(client)
        filepath = components.get(component)
        if not filepath:
            return no_update

        df, df_latest = _load_evidence_component(filepath, component)
        if df is None or df_latest is None:
            return no_update

        failure_modes = get_failure_modes_dict(component)
        row = df_latest[df_latest["Unit"] == selected_unit]
        if row.empty:
            return list(failure_modes.keys())[0] if failure_modes else None

        row = row.iloc[0]
        fm_keys = list(failure_modes.keys())
        fm_scores = {k: float(row[k]) if k in row.index and pd.notna(row[k]) else 0.0 for k in fm_keys}
        return max(fm_scores, key=fm_scores.get) if fm_scores else (fm_keys[0] if fm_keys else None)

    # ══════════════════════════════════════════════════════════════════════════
    # EVIDENCE: Detailed evidence (oil + telemetry)
    # ══════════════════════════════════════════════════════════════════════════

    @app.callback(
        Output("predictive-ev-detailed-content", "children"),
        Input("predictive-ev-unit", "value"),
        Input("predictive-ev-failure-mode", "value"),
        State("predictive-ev-client-store", "data"),
        State("predictive-ev-component-store", "data"),
    )
    def update_detailed_evidence(selected_unit, selected_failure_mode, client, component):
        if not selected_unit or not selected_failure_mode or not client or not component:
            return html.Div(html.P("Seleccione una unidad y modo de falla.",
                                   className="text-muted text-center", style={"padding": "40px"}))

        components = _discover_components(client)
        filepath = components.get(component)
        if not filepath:
            return html.Div(html.P("No hay datos disponibles.", className="text-muted text-center", style={"padding": "40px"}))

        df, df_latest = _load_evidence_component(filepath, component)
        if df is None:
            return html.Div(html.P("No hay datos disponibles.", className="text-muted text-center", style={"padding": "40px"}))

        return render_detailed_evidence(selected_unit, df, df_latest, selected_failure_mode, component)
