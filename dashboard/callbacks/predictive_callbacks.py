"""
Predictive callbacks - handles internal tab switching and evidence interactivity.
"""

from dash import html, dcc, Input, Output, State, no_update
import pandas as pd
from src.utils.logger import get_logger
from config.settings import get_settings
from src.data.loaders import get_latest_component_hours
from dashboard.components.predictive_config import (
    get_failure_modes_dict,
    get_failure_mode_options,
)
from dashboard.tabs.tab_predictive_overview import (
    _discover_components,
    _load_component_data as _load_overview_component,
    _render_component_overview,
    _failure_table,
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

            df, df_latest, prev_ranking = _load_overview_component(filepath, component, client)
            if df_latest is None or df_latest.empty:
                return html.P(f"No hay datos disponibles para {component}.", className="text-muted text-center")

            return _render_component_overview(df_latest, prev_ranking, component, client, df=df)

        else:
            # Render evidence shell (interactive parts handled by other callbacks)
            components = _discover_components(client)
            filepath = components.get(component)
            if not filepath:
                return html.P(f"No hay datos para {component}.", className="text-muted text-center")

            df, df_latest = _load_evidence_component(filepath, component, client)
            units = sorted(df["Unit"].unique()) if df is not None else []
            failure_mode_options = get_failure_mode_options(component, client)

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
    # OVERVIEW: Sort failure mode table by selected period
    # ══════════════════════════════════════════════════════════════════════════

    @app.callback(
        Output("predictive-fm-table-container", "children"),
        Input("predictive-fm-sort-selector", "value"),
        State("predictive-ev-client-store", "data"),
        State("predictive-ev-component-store", "data"),
        prevent_initial_call=True,
    )
    def sort_failure_mode_table(sort_col, client, component):
        """Re-sort and re-render the failure mode table based on selected period."""
        if not sort_col or not client or not component:
            return no_update

        components = _discover_components(client)
        filepath = components.get(component)
        if not filepath:
            return no_update

        df, df_latest, _ = _load_overview_component(filepath, component, client)
        if df_latest is None or df_latest.empty:
            return no_update

        failure_modes = get_failure_modes_dict(component, client)

        # Classify status (same logic as _render_component_overview)
        # Saludable: avg_ranking_30d < 30 AND max_fm_30d < 50
        # Alerta: 30 <= avg_ranking_30d < 60 OR 50 <= max_fm_30d < 80
        # Crítico: avg_ranking_30d >= 60 OR max_fm_30d >= 80
        latest = df_latest.copy()
        latest["status"] = "Saludable"
        latest.loc[
            (latest["avg_ranking_30d"] >= 30) | (latest["max_fm_30d"] >= 50),
            "status",
        ] = "Alerta"
        latest.loc[
            (latest["avg_ranking_30d"] >= 60) | (latest["max_fm_30d"] >= 80),
            "status",
        ] = "Crítica"

        # Sort by selected column descending (use 30d version for failure modes)
        fm_keys = list(failure_modes.keys())
        actual_sort_col = f"{sort_col}_30d" if sort_col in fm_keys and f"{sort_col}_30d" in latest.columns else sort_col
        if actual_sort_col in latest.columns:
            sorted_df = latest.sort_values(actual_sort_col, ascending=False)
        else:
            sorted_df = latest.sort_values("avg_ranking_30d", ascending=False)

        return _failure_table(sorted_df, sort_col, failure_modes)

    # ══════════════════════════════════════════════════════════════════════════
    # EVIDENCE: Unit banner
    # ══════════════════════════════════════════════════════════════════════════

    @app.callback(
        Output("predictive-ev-unit-banner", "children"),
        Input("predictive-ev-unit", "value"),
        State("predictive-ev-client-store", "data"),
        State("predictive-ev-component-store", "data"),
    )
    def update_unit_banner(selected_unit, client, component):
        if not selected_unit:
            return None

        # Load data to get status context
        ranking_text = ""
        status_text = ""
        status_color = "#667eea"
        if client and component:
            components = _discover_components(client)
            filepath = components.get(component)
            if filepath:
                _, df_latest = _load_evidence_component(filepath, component, client)
                if df_latest is not None and not df_latest.empty:
                    row = df_latest[df_latest["Unit"] == selected_unit]
                    if not row.empty:
                        row = row.iloc[0]
                        ranking_val = float(row.get("ranking", 0))
                        avg_30d = float(row.get("avg_ranking_30d", ranking_val))
                        max_fm = float(row.get("max_fm_30d", 0))
                        ranking_text = f"{ranking_val:.0f}/100"
                        # Status: Crítico >= 60 OR max_fm >= 80
                        #         Alerta >= 30 OR max_fm >= 50
                        if avg_30d >= 60 or max_fm >= 80:
                            status_text = "Crítica"
                            status_color = "#e24b4a"
                        elif avg_30d >= 30 or max_fm >= 50:
                            status_text = "Alerta"
                            status_color = "#ef9f27"
                        else:
                            status_text = "Saludable"
                            status_color = "#1d9e75"

        component_label = (component or "").title()

        # ── Load component horómetro (at last evidence date) ──
        horometro_text = "—"
        horometro_date = ""
        if client and component:
            settings = get_settings()
            allowed = [c.upper() for c in settings.component_hours_allowed_clients]
            if client.upper() in allowed:
                comp_hours_file = settings.get_component_hours_path(client.lower())
                if comp_hours_file.exists():
                    try:
                        from src.data.loaders import load_component_hours
                        import re as _re
                        all_hours = load_component_hours(comp_hours_file)
                        if not all_hours.empty:
                            # Normalize unit IDs (T_09 vs T_9)
                            def _norm_uid(uid):
                                m = _re.match(r'^([A-Za-z]+_)0*(\d+)$', str(uid))
                                return f"{m.group(1)}{m.group(2)}" if m else str(uid)

                            unit_norm = _norm_uid(selected_unit)
                            all_hours['_uid_norm'] = all_hours['unitId'].apply(_norm_uid)

                            # Get last evidence date
                            components_map = _discover_components(client)
                            filepath = components_map.get(component)
                            last_ev_date = None
                            if filepath:
                                df_ev, _ = _load_evidence_component(filepath, component, client)
                                if df_ev is not None:
                                    df_ev_unit = df_ev[df_ev["Unit"] == selected_unit]
                                    if not df_ev_unit.empty:
                                        last_ev_date = df_ev_unit["Fecha"].max()

                            unit_hours = all_hours[
                                (all_hours['_uid_norm'] == unit_norm) &
                                (all_hours['componentName'] == component)
                            ].copy()

                            if not unit_hours.empty and last_ev_date is not None:
                                unit_hours['date_diff'] = abs(unit_hours['sampleDate'] - last_ev_date)
                                closest = unit_hours.sort_values('date_diff').iloc[0]
                                hrs = closest['componentHours_cleaned']
                                date_val = closest['sampleDate']
                                if pd.notna(hrs):
                                    horometro_text = f"{hrs:,.0f} hrs"
                                if pd.notna(date_val):
                                    horometro_date = pd.to_datetime(date_val).strftime('%d %b %Y')
                            elif not unit_hours.empty:
                                latest_row = unit_hours.sort_values('sampleDate').iloc[-1]
                                hrs = latest_row['componentHours_cleaned']
                                if pd.notna(hrs):
                                    horometro_text = f"{hrs:,.0f} hrs"
                    except Exception as e:
                        logger.warning(f"Could not load component hours for banner: {e}")

        return html.Div([
            html.Div([
                html.Div([
                    # Unit icon and name
                    html.Div([
                        html.I(className="fas fa-truck", style={"fontSize": "28px"}),
                    ], style={"marginRight": "16px"}),
                    html.Div([
                        html.Div("Unidad en Análisis", style={
                            "fontSize": "11px", "fontWeight": "500",
                            "textTransform": "uppercase", "letterSpacing": "0.5px",
                            "opacity": "0.8", "marginBottom": "2px"
                        }),
                        html.Div(selected_unit, style={
                            "fontSize": "32px", "fontWeight": "700", "letterSpacing": "-0.5px",
                            "lineHeight": "1.1"
                        }),
                        html.Div(f"Componente: {component_label}", style={
                            "fontSize": "12px", "opacity": "0.8", "marginTop": "2px"
                        }),
                    ]),
                ], style={"display": "flex", "alignItems": "center"}),
                # Status badges on the right (ranking + horómetro + estado)
                html.Div([
                    # Horómetro badge
                    html.Div([
                        html.Div("Horómetro", style={
                            "fontSize": "10px", "textTransform": "uppercase",
                            "letterSpacing": "0.5px", "opacity": "0.8", "marginBottom": "4px"
                        }),
                        html.Div(horometro_text, style={
                            "fontSize": "20px", "fontWeight": "700"
                        }),
                        html.Div(horometro_date, style={
                            "fontSize": "9px", "opacity": "0.7", "marginTop": "2px"
                        }) if horometro_date else None,
                    ], style={"textAlign": "center", "marginRight": "20px"}),
                    # Ranking badge
                    html.Div([
                        html.Div("Ranking Actual", style={
                            "fontSize": "10px", "textTransform": "uppercase",
                            "letterSpacing": "0.5px", "opacity": "0.8", "marginBottom": "4px"
                        }),
                        html.Div(ranking_text, style={
                            "fontSize": "24px", "fontWeight": "700"
                        }),
                    ], style={"textAlign": "center", "marginRight": "20px"}),
                    html.Div([
                        html.Div("Estado", style={
                            "fontSize": "10px", "textTransform": "uppercase",
                            "letterSpacing": "0.5px", "opacity": "0.8", "marginBottom": "4px"
                        }),
                        html.Span(status_text, style={
                            "background": "rgba(255,255,255,0.2)",
                            "padding": "4px 12px", "borderRadius": "12px",
                            "fontSize": "13px", "fontWeight": "600",
                            "border": "1px solid rgba(255,255,255,0.4)"
                        }),
                    ], style={"textAlign": "center"}),
                ], style={"display": "flex", "alignItems": "center"}),
            ], style={
                "display": "flex", "justifyContent": "space-between", "alignItems": "center"
            })
        ], style={
            "background": f"linear-gradient(135deg, {status_color} 0%, {status_color}dd 100%)",
            "color": "white", "padding": "20px 28px", "borderRadius": "12px",
            "boxShadow": f"0 4px 12px {status_color}44", "marginBottom": "1.5rem"
        })

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

        df, df_latest = _load_evidence_component(filepath, component, client)
        if df is None:
            return html.Div(html.P("No hay datos disponibles.", className="text-muted text-center", style={"padding": "40px"}))

        return render_initial_content(selected_unit, df, df_latest, component, client)

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

        df, df_latest = _load_evidence_component(filepath, component, client)
        if df is None or df_latest is None:
            return no_update

        failure_modes = get_failure_modes_dict(component, client)
        row = df_latest[df_latest["Unit"] == selected_unit]
        if row.empty:
            return list(failure_modes.keys())[0] if failure_modes else None

        row = row.iloc[0]
        fm_keys = list(failure_modes.keys())
        fm_scores = {k: float(row[f"{k}_30d"]) if f"{k}_30d" in row.index and pd.notna(row[f"{k}_30d"]) else 0.0 for k in fm_keys}
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

        df, df_latest = _load_evidence_component(filepath, component, client)
        if df is None:
            return html.Div(html.P("No hay datos disponibles.", className="text-muted text-center", style={"padding": "40px"}))

        return render_detailed_evidence(selected_unit, df, df_latest, selected_failure_mode, component, client)

    # ══════════════════════════════════════════════════════════════════════════
    # EVIDENCE: Oil chart update (when user changes variable selection)
    # ══════════════════════════════════════════════════════════════════════════

    @app.callback(
        Output("predictive-oil-chart-container", "children"),
        Input("predictive-oil-var-selector", "value"),
        State("predictive-oil-range-store", "data"),
        State("predictive-ev-unit", "value"),
        State("predictive-ev-client-store", "data"),
        State("predictive-ev-component-store", "data"),
        prevent_initial_call=False,
    )
    def update_oil_chart(selected_vars, oil_range, selected_unit, client, component):
        """Update oil timeseries chart based on user-selected variables."""
        from dashboard.components.predictive_charts import create_oil_timeseries_90d
        from dashboard.components.predictive_config import OIL_LABELS, OIL_THRESHOLDS

        if not selected_vars or not selected_unit or not client or not component:
            return html.P("Seleccione al menos una variable de aceite.",
                         className="text-muted", style={"fontSize": "13px", "padding": "20px", "textAlign": "center"})

        # Resolve per-client label/threshold dicts (fallback to cda if missing)
        _ckey = (client or "cda").lower()
        oil_labels = OIL_LABELS.get(_ckey, OIL_LABELS["cda"])
        oil_thresholds = OIL_THRESHOLDS.get(_ckey, OIL_THRESHOLDS["cda"])

        components = _discover_components(client)
        filepath = components.get(component)
        if not filepath:
            return html.P("No hay datos disponibles.", className="text-muted")

        df, _ = _load_evidence_component(filepath, component, client)
        if df is None:
            return html.P("No hay datos disponibles.", className="text-muted")

        df_unit = df[df["Unit"] == selected_unit].sort_values("Fecha")
        if df_unit.empty:
            return html.P("No hay datos para esta unidad.", className="text-muted")

        # Always pass thresholds — the chart function shows limit lines when len(vars)==1
        fig = create_oil_timeseries_90d(
            df_unit, selected_vars, oil_labels,
            oil_thresholds=oil_thresholds,
            oil_range=oil_range,
        )

        if fig:
            return dcc.Graph(figure=fig, config={"displayModeBar": False})
        return html.P("No hay suficientes datos históricos.", className="text-muted", style={"fontSize": "13px"})