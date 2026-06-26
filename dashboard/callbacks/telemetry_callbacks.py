"""
Telemetry Health Dashboard Callbacks.

Handles:
- Internal tab switching (Fleet Overview ↔ Unit Detail)
- Fleet Overview: KPIs, heatmap, priority table, AI assessments
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
    load_telemetry_limits,
    load_telemetry_manifest,
    load_silver_telemetry_week,
    load_telemetry_ai_comments,
)
from dashboard.components.telemetry_charts import (
    build_fleet_heatmap,
    build_heatmap_insights,
    build_signal_timeseries_card,
    translate_system,
    load_signal_registry,
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
# REFERENCE DATE INDICATOR
# ===================================================================

@callback(
    Output('telemetry-reference-date', 'children'),
    Input('telemetry-health-tabs', 'value'),
    State('client-selector', 'value'),
)
def update_reference_date(active_tab, client):
    """Show the evaluation week/date the dashboard is referencing."""
    if not client:
        raise PreventUpdate

    manifest = load_telemetry_manifest(client)
    if manifest:
        week = manifest.get('evaluation_week', '?')
        year = manifest.get('evaluation_year', '?')
        ts = manifest.get('execution_timestamp', '')
        date_str = ts[:10] if ts else ''
        return html.Div([
            html.Small([
                html.I(className="fas fa-calendar-alt me-1"),
                f"Semana {week}/{year}"
            ], className="d-block text-muted"),
            html.Small([
                html.I(className="fas fa-sync-alt me-1"),
                f"Actualizado: {date_str}"
            ], className="text-muted") if date_str else html.Span()
        ])
    return html.Small("Sin datos de referencia", className="text-muted")


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
        Output('telemetry-fleet-heatmap-insights', 'children'),
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
            return empty_msg, {}, html.Div(), empty_msg

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

        # --- Heatmap (includes Estado column) ---
        heatmap_fig = build_fleet_heatmap(system_health, unit_health)

        # --- Heatmap insight KPIs ---
        insights = build_heatmap_insights(system_health, unit_health)
        heatmap_insights = dbc.Row([
            dbc.Col([
                html.Div([
                    html.Small("Unidad más riesgosa", className="text-muted d-block"),
                    html.Strong(insights['most_risky_unit'], style={"fontSize": "1.1rem"})
                ], className="text-center")
            ], md=4),
            dbc.Col([
                html.Div([
                    html.Small("Sistema con mayor riesgo", className="text-muted d-block"),
                    html.Strong(insights['most_critical_system'], style={"fontSize": "1.1rem"})
                ], className="text-center")
            ], md=4),
            dbc.Col([
                html.Div([
                    html.Small("Máximo Risk Score", className="text-muted d-block"),
                    html.Strong(f"{insights['max_score']}", className="text-danger",
                                style={"fontSize": "1.1rem"})
                ], className="text-center")
            ], md=4),
        ], className="g-2 py-2 border rounded bg-light")

        # --- AI Assessment Table (sorted by criticality) ---
        ai_table = _build_ai_assessment_section(client, unit_health)

        return kpi_row, heatmap_fig, heatmap_insights, ai_table

    except Exception as e:
        logger.error(f"Error in fleet overview: {e}")
        error_msg = dbc.Alert(f"Error cargando datos: {e}", color="danger")
        return error_msg, {}, html.Div(), error_msg


# ===================================================================
# UNIT DETAIL CALLBACKS
# ===================================================================

@callback(
    [
        Output('telemetry-detail-unit-selector', 'options'),
        Output('telemetry-detail-unit-selector', 'value'),
    ],
    Input('telemetry-health-tabs', 'value'),
    State('client-selector', 'value'),
    State('telemetry-detail-unit-selector', 'value'),
)
def populate_unit_selector(active_tab, client, current_value):
    """Populate unit dropdown with available units sorted by priority.
    Default to most risky unit if no value is currently set."""
    if active_tab != 'unit-detail' or not client:
        raise PreventUpdate

    unit_health = load_telemetry_unit_health(client)
    if unit_health.empty:
        return [], None

    unit_health = unit_health.sort_values('priority_score', ascending=False)
    options = [{'label': row['unit'], 'value': row['unit']} for _, row in unit_health.iterrows()]

    # Keep current value if valid, otherwise default to highest priority
    if current_value and current_value in [o['value'] for o in options]:
        return options, current_value

    default_unit = unit_health.iloc[0]['unit']
    return options, default_unit


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
        deviation_df = load_telemetry_deviation_results(client)

        # AI Comment card — try structured ai_comments first
        ai_comment = html.Div()
        unit_comments = load_telemetry_ai_comments(client, 'unit')

        description = None
        explaining = None
        urgency = None
        recommended_action = None

        if not unit_comments.empty:
            uc_row = unit_comments[unit_comments['unit'] == unit]
            if not uc_row.empty:
                uc = uc_row.iloc[0]
                description = _get_ai_text(uc, 'description')
                explaining = _get_ai_text(uc, 'explaining')
                urgency = uc.get('urgency', '')
                recommended_action = _get_ai_text(uc, 'recommended_action')

        # Fallback to executive_summary (old schema)
        if not description:
            if not unit_health.empty:
                row = unit_health[unit_health['unit'] == unit]
                if not row.empty and 'executive_summary' in row.columns:
                    description = row.iloc[0].get('executive_summary', '')
                    if description and str(description) == 'nan':
                        description = None

        if description:
            # Urgency indicator
            urgency_el = html.Span()
            if urgency and urgency != 'routine':
                urgency_colors = {
                    'monitor': '#17a2b8',
                    'schedule_inspection': '#f39c12',
                    'immediate': '#dc3545'
                }
                urgency_labels = {
                    'monitor': 'Monitorear',
                    'schedule_inspection': 'Programar inspección',
                    'immediate': 'Acción inmediata'
                }
                urgency_el = dbc.Badge(
                    urgency_labels.get(urgency, urgency),
                    style={"backgroundColor": urgency_colors.get(urgency, '#6c757d')},
                    className="ms-2"
                )

            comment_content = [
                html.Strong(str(description), className="d-block mb-1")
            ]
            if explaining:
                comment_content.append(
                    html.P(str(explaining), className="mb-1 text-muted",
                           style={"whiteSpace": "pre-wrap", "fontSize": "0.9rem"})
                )
            if recommended_action and str(recommended_action) != 'nan':
                comment_content.append(
                    html.Small([
                        html.I(className="fas fa-wrench me-1"),
                        html.Strong("Acción: "),
                        str(recommended_action)
                    ], className="text-primary")
                )

            ai_comment = dbc.Card([
                dbc.CardBody([
                    html.Div([
                        html.I(className="fas fa-robot fa-lg text-primary me-3"),
                        html.Div([
                            html.Div([
                                html.Strong("Evaluación IA", className="me-2"),
                                urgency_el
                            ], className="mb-1"),
                            *comment_content
                        ])
                    ], className="d-flex align-items-start")
                ])
            ], className="shadow-sm mb-4", style={"borderLeft": "4px solid #3498db"})

        # System table (pass deviation_df for signal alert counts)
        system_table_data = build_system_risk_table(system_health, unit, deviation_df)

        # System dropdown options (already translated to Spanish)
        system_options = []
        if system_table_data:
            system_options = [
                {'label': row['system'], 'value': row['system']}
                for row in system_table_data
            ]

        # Default to highest-risk system (first in sorted list)
        default_system = system_table_data[0]['system'] if system_table_data else None

        return ai_comment, system_table_data, system_options, default_system

    except Exception as e:
        logger.error(f"Error updating unit detail: {e}", exc_info=True)
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
    if not unit or not system or not client:
        raise PreventUpdate

    try:
        deviation_df = load_telemetry_deviation_results(client)
        events_df = load_telemetry_events(client)
        trends_df = load_telemetry_trends(client)

        logger.info(f"Signal section: unit={unit}, system={system}, "
                    f"dev={len(deviation_df)}, events={len(events_df)}, trends={len(trends_df)}")

        # Load signal registry for display names
        signal_names_map = load_signal_registry(client)

        # Load signal-level AI comments
        signal_comments = load_telemetry_ai_comments(client, 'signal')
        signal_comments_map = {}
        if not signal_comments.empty:
            sc_unit = signal_comments[signal_comments['unit'] == unit]
            if not sc_unit.empty:
                signal_comments_map = sc_unit.set_index('signal').to_dict('index')

        # Build signal table data: signal (display_name) | estado | ai_message
        signal_data = _build_signal_table_data(
            deviation_df, unit, system, signal_names_map, signal_comments_map
        )

        logger.info(f"Signal data rows: {len(signal_data)}")

        # Signal detail cards (time series + KPIs)
        cards = _build_signal_cards(
            unit, system, client, deviation_df, events_df, trends_df,
            signal_names_map, signal_comments_map
        )

        return signal_data, cards

    except Exception as e:
        logger.error(f"Error updating signal section: {e}", exc_info=True)
        return [], html.Div()


# ===================================================================
# HELPER FUNCTIONS
# ===================================================================

def _get_ai_text(data, field: str):
    """Extract AI text field with backward compatibility (comment → description)."""
    if isinstance(data, dict):
        val = data.get(field, '')
        # Backward compat: if looking for 'description' and not found, try 'comment'
        if not val and field == 'description':
            val = data.get('comment', '')
    else:
        val = data.get(field, '') if hasattr(data, 'get') else getattr(data, field, '')
        if not val and field == 'description':
            val = data.get('comment', '') if hasattr(data, 'get') else getattr(data, 'comment', '')
    if val and str(val) != 'nan':
        return str(val)
    return None


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


def _build_ai_assessment_section(client: str, unit_health: pd.DataFrame):
    """Build AI assessment cards using ai_comments/unit_comments or fallback to executive_summary."""
    if unit_health.empty:
        return html.P("Sin evaluaciones IA disponibles", className="text-muted")

    # Try loading structured AI comments first
    unit_comments = load_telemetry_ai_comments(client, 'unit')

    cards = []
    for _, row in unit_health.sort_values('priority_score', ascending=False).iterrows():
        status = row.get('overall_status', 'Normal')
        unit = row.get('unit', '?')

        # Get comment from AI comments table (preferred) or fallback
        description = None
        explaining = None
        urgency = None
        recommended_action = None

        if not unit_comments.empty:
            uc_row = unit_comments[unit_comments['unit'] == unit]
            if not uc_row.empty:
                uc = uc_row.iloc[0]
                description = _get_ai_text(uc, 'description')
                explaining = _get_ai_text(uc, 'explaining')
                urgency = uc.get('urgency', '')
                recommended_action = _get_ai_text(uc, 'recommended_action')

        # Fallback to executive_summary
        if not description:
            description = row.get('executive_summary', '')
            if not description or str(description) == 'nan':
                description = "Operando dentro de parámetros normales."

        badge_color = {
            'Normal': 'success', 'Alerta': 'warning',
            'Anormal': 'danger', 'InsufficientData': 'secondary'
        }.get(status, 'secondary')

        # Urgency badge
        urgency_badge = None
        if urgency and urgency != 'routine':
            urgency_colors = {
                'monitor': 'info',
                'schedule_inspection': 'warning',
                'immediate': 'danger'
            }
            urgency_labels = {
                'monitor': 'Monitorear',
                'schedule_inspection': 'Programar inspección',
                'immediate': 'Acción inmediata'
            }
            urgency_badge = dbc.Badge(
                urgency_labels.get(urgency, urgency),
                color=urgency_colors.get(urgency, 'secondary'),
                pill=True, className="ms-2"
            )

        # Build card content
        card_body_content = [
            dbc.Row([
                dbc.Col([
                    html.Strong(unit, className="me-2"),
                    dbc.Badge(status, color=badge_color, pill=True),
                    urgency_badge if urgency_badge else html.Span()
                ], width=3),
                dbc.Col([
                    html.Strong(str(description), className="d-block",
                                style={"fontSize": "0.9rem"}),
                    html.Small(str(explaining), className="text-muted")
                    if explaining else html.Span()
                ], width=9)
            ], align="center")
        ]

        # Add recommended action if available
        if recommended_action and str(recommended_action) != 'nan':
            card_body_content.append(
                html.Div([
                    html.Small([
                        html.I(className="fas fa-wrench me-1"),
                        str(recommended_action)
                    ], className="text-primary")
                ], className="mt-1 ms-3")
            )

        cards.append(
            dbc.Card([
                dbc.CardBody(card_body_content)
            ], className="mb-2 border-start border-3",
               style={"borderColor": STATUS_COLORS.get(status, '#999') + " !important"})
        )

    return html.Div(cards) if cards else html.P("Sin evaluaciones disponibles", className="text-muted")


def _build_signal_cards(unit, system, client, deviation_df, events_df, trends_df,
                        signal_names_map=None, signal_comments_map=None):
    """Build signal detail cards with AI comment, time series plot + KPI table."""
    if deviation_df.empty:
        return html.Div(dbc.Alert("Sin datos de desviación disponibles", color="info"))

    if signal_names_map is None:
        signal_names_map = load_signal_registry(client)
    if signal_comments_map is None:
        signal_comments_map = {}

    # Reverse-translate system for filtering deviation data (Spanish → English)
    reverse_map = {v: k for k, v in {
        'Engine': 'Motor', 'Transmission': 'Transmisión',
        'Brakes': 'Frenos', 'Steering': 'Dirección'
    }.items()}
    system_en = reverse_map.get(system, system) if system else None

    # Filter deviation for this unit+system and get signals list
    dev = deviation_df[deviation_df['unit'] == unit]
    if system_en:
        dev = dev[dev['system'] == system_en]
    if dev.empty:
        return html.Div(dbc.Alert("Sin señales para el sistema seleccionado", color="info"))

    # Get latest evaluation per signal (use year/week)
    if 'year' in dev.columns and 'week' in dev.columns:
        dev = dev.sort_values(['year', 'week'], ascending=False).drop_duplicates(subset=['signal'])
    dev = dev.sort_values('risk_score', ascending=False)

    signals = dev['signal'].tolist()
    if not signals:
        return html.Div(dbc.Alert("Sin señales disponibles", color="info"))

    logger.info(f"Building signal cards for {len(signals)} signals: {signals[:5]}...")

    # Load raw telemetry (search wider range to find available data)
    raw_df = _load_recent_telemetry(client, unit, weeks=8)
    logger.info(f"Raw telemetry loaded: {len(raw_df)} rows, columns available: {len(raw_df.columns) if not raw_df.empty else 0}")

    # Load limits (falls back to baselines)
    limits_df = load_telemetry_limits(client)

    cards = []
    for signal_name in signals[:10]:  # Limit to top 10 signals
        # Get display name
        display_name = signal_names_map.get(signal_name, signal_name)

        # Build time series figure with limits
        fig = build_signal_timeseries_card(
            signal_name=signal_name,
            raw_df=raw_df,
            limits_df=limits_df,
            trend_df=trends_df[
                (trends_df['unit'] == unit) & (trends_df['signal'] == signal_name)
            ] if not trends_df.empty else pd.DataFrame(),
            unit=unit
        )

        # Build KPI data
        kpi = build_signal_kpi(signal_name, deviation_df, events_df, trends_df, unit)

        # Get signal status
        sig_row = dev[dev['signal'] == signal_name]
        sig_status = sig_row.iloc[0].get('status', 'Normal') if not sig_row.empty else 'Normal'
        border_color = STATUS_COLORS.get(sig_status, '#95a5a6')

        # Signal AI comment (description + explaining)
        ai_comment_el = html.Div()
        sc_info = signal_comments_map.get(signal_name)
        if sc_info:
            desc = _get_ai_text(sc_info, 'description')
            explaining = _get_ai_text(sc_info, 'explaining')
            if desc:
                comment_parts = [
                    html.Strong(str(desc), style={"fontSize": "0.85rem"})
                ]
                if explaining:
                    comment_parts.append(
                        html.P(str(explaining), className="mb-0 mt-1",
                               style={"fontSize": "0.8rem", "color": "#6c757d"})
                    )
                ai_comment_el = html.Div([
                    html.Div([
                        html.I(className="fas fa-robot me-1 text-primary"),
                        *comment_parts
                    ])
                ], className="mb-2 p-2 bg-light rounded")

        # Build card: AI comment + left (chart) + right (KPI table)
        card = dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="fas fa-signal me-2"),
                    display_name
                ], className="mb-0 d-inline"),
                dbc.Badge(sig_status, color={
                    'Normal': 'success', 'Alerta': 'warning',
                    'Anormal': 'danger'
                }.get(sig_status, 'secondary'), pill=True, className="ms-2")
            ], className="bg-light"),
            dbc.CardBody([
                ai_comment_el,
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


def _build_signal_table_data(deviation_df, unit, system, signal_names_map, signal_comments_map):
    """Build simplified signal table: signal (display_name) | estado | ai_message."""
    if deviation_df.empty:
        return []

    # Reverse-translate system
    reverse_map = {'Motor': 'Engine', 'Transmisión': 'Transmission',
                   'Frenos': 'Brakes', 'Dirección': 'Steering'}
    system_en = reverse_map.get(system, system) if system else None

    dev = deviation_df[deviation_df['unit'] == unit].copy()
    if system_en:
        dev = dev[dev['system'] == system_en]
    if dev.empty:
        return []

    # Get latest per signal
    if 'year' in dev.columns and 'week' in dev.columns:
        dev = dev.sort_values(['year', 'week'], ascending=False).drop_duplicates(subset=['signal'])
    dev = dev.sort_values('risk_score', ascending=False)

    rows = []
    for _, row in dev.iterrows():
        sig = row['signal']
        display_name = signal_names_map.get(sig, sig)
        status = row.get('status', 'Normal')

        # Get AI message from comments (description field, fallback to comment)
        ai_msg = '-'
        sc_info = signal_comments_map.get(sig)
        if sc_info:
            desc = _get_ai_text(sc_info, 'description')
            if desc:
                ai_msg = str(desc)

        rows.append({
            'signal': display_name,
            'status': status,
            'ai_message': ai_msg,
        })

    return rows


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
    """Load recent silver telemetry data for a unit.

    Uses the pipeline manifest (latest.json) to anchor on the correct evaluation
    week, then loads backwards from there. Falls back to datetime.now() if
    manifest is unavailable.
    """
    manifest = load_telemetry_manifest(client)

    # Determine anchor point
    if manifest and 'evaluation_week' in manifest and 'evaluation_year' in manifest:
        anchor_week = manifest['evaluation_week']
        anchor_year = manifest['evaluation_year']
        # If manifest provides available weeks, use them directly
        available_weeks = manifest.get('silver_weeks_available', [])
        if available_weeks:
            all_data = []
            for w in sorted(available_weeks, reverse=True)[:weeks]:
                week_df = load_silver_telemetry_week(client, w, anchor_year)
                if not week_df.empty:
                    unit_df = week_df[week_df['Unit'] == unit]
                    if not unit_df.empty:
                        all_data.append(unit_df)
            if all_data:
                combined = pd.concat(all_data, ignore_index=True)
                if 'Fecha' in combined.columns:
                    combined = combined.sort_values('Fecha')
                return combined
    else:
        anchor_week = datetime.now().isocalendar()[1]
        anchor_year = datetime.now().isocalendar()[0]

    # Walk backwards from anchor week
    all_data = []
    from datetime import date
    anchor_date = date.fromisocalendar(anchor_year, anchor_week, 1)

    for i in range(weeks + 4):  # Extra buffer to handle gaps
        target = anchor_date - timedelta(weeks=i)
        week_num = target.isocalendar()[1]
        year_num = target.isocalendar()[0]

        week_df = load_silver_telemetry_week(client, week_num, year_num)
        if not week_df.empty:
            unit_df = week_df[week_df['Unit'] == unit]
            if not unit_df.empty:
                all_data.append(unit_df)
                if len(all_data) >= weeks:
                    break

    if not all_data:
        logger.warning(f"No silver telemetry found for unit={unit} anchored at week {anchor_week}/{anchor_year}")
        return pd.DataFrame()

    combined = pd.concat(all_data, ignore_index=True)
    if 'Fecha' in combined.columns:
        combined = combined.sort_values('Fecha')
    return combined
