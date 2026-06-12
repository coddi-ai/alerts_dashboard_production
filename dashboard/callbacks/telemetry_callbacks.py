"""
Telemetry Health Dashboard Callbacks.

Handles:
- Internal tab switching (Fleet Overview ↔ Unit Detail)
- Fleet Overview: KPIs, heatmap, donut, priority table, AI assessments
- Unit Detail: Unit selector, system table, signal table, signal cards
- Navigation from fleet table row click → unit detail
"""

import pandas as pd
import json
from datetime import datetime, timedelta
from dash import callback, Input, Output, State, no_update, html, dcc
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from src.data.loaders import (
    load_telemetry_unit_health,
    load_telemetry_system_health,
    load_telemetry_deviation_results,
    load_telemetry_events,
    load_telemetry_trends,
    load_telemetry_baselines,
    load_silver_telemetry_week,
)
from dashboard.components.telemetry_charts import (
    build_fleet_donut,
    build_fleet_heatmap,
    build_signal_timeseries_card,
    STATUS_COLORS,
)
from dashboard.components.telemetry_tables import (
    build_fleet_priority_table,
    build_system_risk_table,
    build_signal_overview_table,
    build_signal_kpi,
)
from dashboard.tabs.tab_telemetry_fleet import create_telemetry_fleet_layout
from dashboard.tabs.tab_telemetry_unit_detail import create_telemetry_unit_detail_layout

from src.utils.logger import get_logger

logger = get_logger(__name__)


# ===================================================================
# TAB SWITCHING
# ===================================================================

@callback(
    Output('telemetry-health-tab-content', 'children'),
    Input('telemetry-health-tabs', 'value')
)
def render_telemetry_health_tab(active_tab):
    """Render the appropriate internal tab content."""
    if active_tab == 'fleet-overview':
        return create_telemetry_fleet_layout()
    elif active_tab == 'unit-detail':
        return create_telemetry_unit_detail_layout()
    return html.Div("Selección inválida")


# ===================================================================
# FLEET OVERVIEW CALLBACKS
# ===================================================================

@callback(
    [
        Output('telemetry-fleet-kpi-row', 'children'),
        Output('telemetry-fleet-heatmap', 'figure'),
        Output('telemetry-fleet-donut', 'figure'),
        Output('telemetry-fleet-priority-table', 'data'),
        Output('telemetry-fleet-ai-table', 'children'),
    ],
    Input('telemetry-health-tabs', 'value'),
    State('client-selector', 'value'),
)
def update_fleet_overview(active_tab, client):
    """Load and display fleet overview data."""
    if active_tab != 'fleet-overview' or not client:
        raise PreventUpdate

    try:
        unit_health = load_telemetry_unit_health(client)
        system_health = load_telemetry_system_health(client)

        if unit_health.empty:
            empty_msg = html.Div([
                dbc.Alert([
                    html.I(className="fas fa-exclamation-triangle me-2"),
                    "No hay datos de salud de flota disponibles."
                ], color="warning")
            ])
            return empty_msg, {}, {}, [], empty_msg

        # --- KPI Cards ---
        total = len(unit_health)
        normal = int((unit_health['overall_status'] == 'Normal').sum())
        alerta = int((unit_health['overall_status'] == 'Alerta').sum())
        anormal = int((unit_health['overall_status'] == 'Anormal').sum())

        kpi_row = dbc.Row([
            _kpi_card("Total Unidades", total, "fas fa-truck", "info", "#f0f8ff"),
            _kpi_card("Normal", normal, "fas fa-check-circle", "success", "#f0fff4"),
            _kpi_card("Alerta", alerta, "fas fa-exclamation-circle", "warning", "#fffcf0"),
            _kpi_card("Anormal", anormal, "fas fa-times-circle", "danger", "#fff5f5"),
        ], className="g-3 mb-4")

        # --- Heatmap ---
        heatmap_fig = build_fleet_heatmap(system_health, unit_health)

        # --- Donut ---
        donut_fig = build_fleet_donut(unit_health)

        # --- Priority Table ---
        table_data = build_fleet_priority_table(unit_health)

        # --- AI Assessment Table ---
        ai_table = _build_ai_assessment_section(unit_health)

        return kpi_row, heatmap_fig, donut_fig, table_data, ai_table

    except Exception as e:
        logger.error(f"Error in fleet overview: {e}")
        error_msg = dbc.Alert(f"Error cargando datos: {e}", color="danger")
        return error_msg, {}, {}, [], error_msg


# ===================================================================
# FLEET TABLE ROW CLICK → NAVIGATE TO UNIT DETAIL
# ===================================================================

@callback(
    Output('telemetry-health-tabs', 'value', allow_duplicate=True),
    Output('telemetry-detail-unit-selector', 'value', allow_duplicate=True),
    Input('telemetry-fleet-priority-table', 'selected_rows'),
    State('telemetry-fleet-priority-table', 'data'),
    prevent_initial_call=True
)
def navigate_to_unit_detail(selected_rows, table_data):
    """Navigate to unit detail tab when fleet row is clicked."""
    if not selected_rows or not table_data:
        raise PreventUpdate

    row_idx = selected_rows[0]
    if row_idx >= len(table_data):
        raise PreventUpdate

    unit = table_data[row_idx].get('unit')
    if not unit:
        raise PreventUpdate

    return 'unit-detail', unit


# ===================================================================
# UNIT DETAIL CALLBACKS
# ===================================================================

@callback(
    Output('telemetry-detail-unit-selector', 'options'),
    Input('telemetry-health-tabs', 'value'),
    State('client-selector', 'value'),
)
def populate_unit_selector(active_tab, client):
    """Populate unit dropdown with available units sorted by priority."""
    if active_tab != 'unit-detail' or not client:
        raise PreventUpdate

    unit_health = load_telemetry_unit_health(client)
    if unit_health.empty:
        return []

    unit_health = unit_health.sort_values('priority_score', ascending=False)
    return [{'label': row['unit'], 'value': row['unit']} for _, row in unit_health.iterrows()]


@callback(
    [
        Output('telemetry-detail-ai-comment', 'children'),
        Output('telemetry-detail-system-table', 'data'),
        Output('telemetry-detail-system-selector', 'options'),
        Output('telemetry-detail-system-selector', 'value'),
    ],
    Input('telemetry-detail-unit-selector', 'value'),
    State('client-selector', 'value'),
)
def update_unit_detail_header(unit, client):
    """Update AI comment and system table when unit is selected."""
    if not unit or not client:
        raise PreventUpdate

    try:
        unit_health = load_telemetry_unit_health(client)
        system_health = load_telemetry_system_health(client)

        # AI Comment card
        ai_comment = html.Div()
        if not unit_health.empty:
            row = unit_health[unit_health['unit'] == unit]
            if not row.empty and 'executive_summary' in row.columns:
                summary = row.iloc[0].get('executive_summary', '')
                if summary and str(summary) != 'nan':
                    ai_comment = dbc.Card([
                        dbc.CardBody([
                            html.Div([
                                html.I(className="fas fa-robot fa-lg text-primary me-3"),
                                html.Div([
                                    html.Strong("Evaluación IA", className="d-block mb-1"),
                                    html.P(str(summary), className="mb-0",
                                           style={"whiteSpace": "pre-wrap"})
                                ])
                            ], className="d-flex align-items-start")
                        ])
                    ], className="shadow-sm mb-4", style={"borderLeft": "4px solid #3498db"})

        # System table
        system_table_data = build_system_risk_table(system_health, unit)

        # System dropdown options
        system_options = []
        if system_table_data:
            system_options = [
                {'label': row['system'], 'value': row['system']}
                for row in system_table_data
            ]

        # Default to highest-risk system
        default_system = system_table_data[0]['system'] if system_table_data else None

        return ai_comment, system_table_data, system_options, default_system

    except Exception as e:
        logger.error(f"Error updating unit detail: {e}")
        return html.Div(), [], [], None


@callback(
    [
        Output('telemetry-detail-signal-table', 'data'),
        Output('telemetry-detail-signal-cards', 'children'),
    ],
    [
        Input('telemetry-detail-system-selector', 'value'),
        Input('telemetry-detail-unit-selector', 'value'),
    ],
    State('client-selector', 'value'),
)
def update_signal_section(system, unit, client):
    """Update signal table and detail cards when system or unit changes."""
    if not unit or not client:
        raise PreventUpdate

    try:
        deviation_df = load_telemetry_deviation_results(client)
        events_df = load_telemetry_events(client)
        trends_df = load_telemetry_trends(client)

        # Signal overview table
        signal_data = build_signal_overview_table(deviation_df, events_df, unit, system)

        # Signal detail cards (time series + KPIs)
        cards = _build_signal_cards(unit, system, client, deviation_df, events_df, trends_df)

        return signal_data, cards

    except Exception as e:
        logger.error(f"Error updating signal section: {e}")
        return [], html.Div()


# ===================================================================
# HELPER FUNCTIONS
# ===================================================================

def _kpi_card(label: str, value, icon: str, color: str, bg_color: str) -> dbc.Col:
    """Create a single KPI card."""
    return dbc.Col([
        dbc.Card([
            dbc.CardBody([
                html.Div([
                    html.I(className=f"{icon} fa-2x text-{color} mb-2"),
                    html.H6(label,
                            className="text-muted text-uppercase mb-2",
                            style={'fontSize': '0.85rem', 'letterSpacing': '0.5px'}),
                    html.H2(f"{value}", className=f"text-{color} mb-0 fw-bold")
                ], className="text-center")
            ])
        ], className="shadow-sm border-0", style={'backgroundColor': bg_color})
    ], md=3)


def _build_ai_assessment_section(unit_health: pd.DataFrame):
    """Build AI assessment cards for all non-normal units."""
    if unit_health.empty or 'executive_summary' not in unit_health.columns:
        return html.P("Sin evaluaciones IA disponibles", className="text-muted")

    cards = []
    for _, row in unit_health.sort_values('priority_score', ascending=False).iterrows():
        status = row.get('overall_status', 'Normal')
        summary = row.get('executive_summary', '')
        unit = row.get('unit', '?')

        if not summary or str(summary) == 'nan':
            summary = "Operando dentro de parámetros normales."

        badge_color = {
            'Normal': 'success', 'Alerta': 'warning',
            'Anormal': 'danger', 'InsufficientData': 'secondary'
        }.get(status, 'secondary')

        cards.append(
            dbc.Card([
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                            html.Strong(unit, className="me-2"),
                            dbc.Badge(status, color=badge_color, pill=True)
                        ], width=2),
                        dbc.Col([
                            html.P(str(summary), className="mb-0 text-muted",
                                   style={"fontSize": "0.9rem"})
                        ], width=10)
                    ], align="center")
                ])
            ], className="mb-2 border-start border-3",
               style={"borderColor": STATUS_COLORS.get(status, '#999') + " !important"})
        )

    return html.Div(cards) if cards else html.P("Sin evaluaciones disponibles", className="text-muted")


def _build_signal_cards(unit, system, client, deviation_df, events_df, trends_df):
    """Build signal detail cards with time series plot + KPI table."""
    if deviation_df.empty:
        return html.Div()

    # Filter deviation for this unit+system and get signals list
    dev = deviation_df[deviation_df['unit'] == unit]
    if system:
        dev = dev[dev['system'] == system]
    if dev.empty:
        return html.Div()

    # Get latest evaluation per signal
    if 'evaluation_date' in dev.columns:
        dev = dev.sort_values('evaluation_date', ascending=False).drop_duplicates(subset=['signal'])
    dev = dev.sort_values('risk_score', ascending=False)

    signals = dev['signal'].tolist()
    if not signals:
        return html.Div()

    # Load raw telemetry (last 4 weeks) for time series plots
    raw_df = _load_recent_telemetry(client, unit, weeks=4)

    # Load baselines
    baseline_df = load_telemetry_baselines(client)

    # Determine model_specification (from deviation data or default)
    model_spec = None
    if 'model_specification' in dev.columns:
        model_spec = dev['model_specification'].iloc[0]

    cards = []
    for signal_name in signals[:10]:  # Limit to top 10 signals
        # Build time series figure
        fig = build_signal_timeseries_card(
            signal_name=signal_name,
            raw_df=raw_df,
            baseline_df=baseline_df,
            trend_df=trends_df[
                (trends_df['unit'] == unit) & (trends_df['signal'] == signal_name)
            ] if not trends_df.empty else pd.DataFrame(),
            model_spec=model_spec
        )

        # Build KPI data
        kpi = build_signal_kpi(signal_name, deviation_df, events_df, trends_df, unit)

        # Get signal status
        sig_row = dev[dev['signal'] == signal_name]
        sig_status = sig_row.iloc[0].get('status', 'Normal') if not sig_row.empty else 'Normal'
        border_color = STATUS_COLORS.get(sig_status, '#95a5a6')

        # Build card: left (chart) + right (KPI table)
        card = dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="fas fa-signal me-2"),
                    signal_name
                ], className="mb-0 d-inline"),
                dbc.Badge(sig_status, color={
                    'Normal': 'success', 'Alerta': 'warning',
                    'Anormal': 'danger'
                }.get(sig_status, 'secondary'), pill=True, className="ms-2")
            ], className="bg-light"),
            dbc.CardBody([
                dbc.Row([
                    # Time series chart (70%)
                    dbc.Col([
                        dcc.Graph(figure=fig, config={'displayModeBar': False})
                    ], lg=8),
                    # KPI Table (30%)
                    dbc.Col([
                        _kpi_table(kpi)
                    ], lg=4)
                ])
            ])
        ], className="shadow-sm mb-3", style={"borderLeft": f"4px solid {border_color}"})

        cards.append(card)

    return html.Div(cards) if cards else html.Div(
        dbc.Alert("No hay señales para mostrar", color="info")
    )


def _kpi_table(kpi: dict) -> html.Div:
    """Render KPI metrics as a small table."""
    rows = [
        ("Total Eventos", kpi.get('total_events', 0)),
        ("Warnings", kpi.get('warnings', 0)),
        ("Episodio Max", f"{kpi.get('longest_episode', 0)} min"),
        ("Tendencia", kpi.get('trend_detected', 'No')),
        ("Dirección", kpi.get('trend_direction', '-')),
        ("Fórmula", kpi.get('trend_formula', '-')),
    ]

    table_rows = []
    for label, value in rows:
        table_rows.append(
            html.Tr([
                html.Td(label, style={"fontWeight": "500", "fontSize": "0.85rem", "padding": "6px 8px"}),
                html.Td(str(value), style={"fontSize": "0.85rem", "padding": "6px 8px", "textAlign": "right"})
            ])
        )

    return html.Table(
        [html.Tbody(table_rows)],
        className="table table-sm table-borderless mb-0",
        style={"marginTop": "20px"}
    )


def _load_recent_telemetry(client: str, unit: str, weeks: int = 4) -> pd.DataFrame:
    """Load recent silver telemetry data for a unit."""
    now = datetime.now()
    all_data = []

    for i in range(weeks):
        target = now - timedelta(weeks=i)
        week_num = target.isocalendar()[1]
        year_num = target.isocalendar()[0]

        week_df = load_silver_telemetry_week(client, week_num, year_num)
        if not week_df.empty:
            unit_df = week_df[week_df['Unit'] == unit]
            if not unit_df.empty:
                all_data.append(unit_df)

    if not all_data:
        return pd.DataFrame()

    combined = pd.concat(all_data, ignore_index=True)
    if 'Fecha' in combined.columns:
        combined = combined.sort_values('Fecha')
    return combined
