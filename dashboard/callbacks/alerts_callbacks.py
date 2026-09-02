"""
Callbacks for Alerts Dashboard.

Handles all interactivity for the unified alerts view with internal tabs,
interactive filtering, and cross-navigation.
"""

import pandas as pd
from dash import callback, callback_context, clientside_callback, ALL, Input, Output, State, html, dcc, no_update, dash_table
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from datetime import date, datetime, timedelta
import numpy as np
import plotly.graph_objects as go

from src.data.loaders import (
    load_alerts_data,
    load_telemetry_values,
    load_telemetry_states,
    load_telemetry_limits,
    load_telemetry_alerts_metadata,
    load_component_mapping,
    load_feature_names,
    load_telemetry_alert_detail_for_alert,
    load_oil_classified,
    load_maintenance_week,
    load_essays_mapping,
    _data_path,
)
from dashboard.components.alerts_charts import (
    create_alerts_per_unit_chart,
    create_alerts_per_month_chart,
    create_alerts_per_week_chart,
    create_system_signal_treemap,
    create_oil_radar_chart,
    create_sensor_trends_chart_golden,
    create_gps_route_map_golden,
    create_context_kpis_cards_golden
)
from dashboard.components.oil_charts import (
    build_oil_time_series_grid,
    build_oil_radar_view,
)
from dashboard.components.alerts_tables import (
    # W34-03: create_alerts_datatable is a legacy, unused variant of the
    # alerts table (different columns/page size, exposes ID/Fuente as
    # visible columns) — deliberately not imported here. The live table is
    # create_alerts_report_table below. See test_w34_alerts_table.py for the
    # regression guard.
    create_alerts_report_table,
    create_maintenance_display,
    parse_ia_message_sections,
)
from dashboard.components.alerts_report import (
    alert_summary,
    filter_alert_rows,
    prepare_alert_rows,
    translate_alert_component,
    translate_alert_system,
)
from dashboard.components.labels import source_style, light_tint
from dashboard.tabs.tab_alerts_general import (
    create_summary_stats_display,
    create_active_filter_badges,
    create_layout as create_general_layout,
)
from dashboard.tabs.tab_alerts_detail import (
    create_alert_detail_content,
    create_oil_status_display,
    create_layout as create_detail_layout
)
from dashboard.components.source_status import render_service_source_status
from src.utils.logger import get_logger
from src.utils.date_utils import format_local, to_utc_naive
from config.settings import Settings

logger = get_logger(__name__)
settings = Settings()

# Configuration
M1 = 60  # Minutes before alert
M2 = 10  # Minutes after alert
MAPBOX_TOKEN = settings.mapbox_token


def _normalise_alert_identifier(value) -> str:
    """Return an alert identifier in the same text form used by CSV data."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _select_telemetry_alert_data(
    telemetry_golden: pd.DataFrame,
    alert_row: pd.Series,
) -> tuple[pd.DataFrame, list[str], str]:
    """Select detail rows using Capstone's textual telemetry identifiers.

    Detail artifacts may key ``AlertID`` with either the consolidated
    ``TelemetryID`` or ``FusionID``. Both are strings, often with a ``CAP-``
    prefix, so matching must remain textual and must not coerce IDs to ints.
    """
    identifiers = []
    for field in ("TelemetryID", "FusionID"):
        identifier = _normalise_alert_identifier(alert_row.get(field))
        if identifier and identifier not in identifiers:
            identifiers.append(identifier)

    unit_id = _normalise_alert_identifier(alert_row.get("UnitId"))
    if not identifiers or not unit_id:
        return telemetry_golden.iloc[0:0].copy(), identifiers, unit_id

    alert_keys = telemetry_golden["AlertID"].map(_normalise_alert_identifier)
    unit_keys = telemetry_golden["Unit"].map(_normalise_alert_identifier)
    mask = alert_keys.isin(identifiers) & unit_keys.eq(unit_id)
    return telemetry_golden.loc[mask].copy(), identifiers, unit_id


# ========================================
# TAB SWITCHING CALLBACK
# ========================================

@callback(
    Output('alerts-tab-content', 'children'),
    [Input('alerts-internal-tabs', 'value')]
)
def render_tab_content(active_tab):
    """
    Render content for selected internal tab.
    
    Args:
        active_tab: 'general' or 'detail'
    
    Returns:
        Tab content layout
    """
    if active_tab == 'general':
        return create_general_layout()
    elif active_tab == 'detail':
        return create_detail_layout()
    else:
        return html.Div("Tab no encontrado")


# ========================================
# GENERAL TAB CALLBACKS
# ========================================

@callback(
    Output('alerts-source-status', 'children'),
    Input('client-selector', 'value'),
)
def update_alerts_source_status(client):
    if not client:
        return html.Div()
    return render_service_source_status(client, "monitoring-alerts")

@callback(
    [
        Output('alerts-unit-distribution-chart', 'figure'),
        Output('alerts-month-distribution-chart', 'figure'),
        Output('alerts-system-distribution-chart', 'figure'),
        Output('alerts-summary-stats', 'children'),
        Output('alerts-table-container', 'children'),
        Output('alerts-general-filter-summary', 'children'),
        Output('alerts-general-active-filter-badges', 'children'),
        Output('alerts-general-filter-clear-all', 'style'),
    ],
    [
        Input('client-selector', 'value'),
        Input('alerts-date-range-picker', 'start_date'),
        Input('alerts-date-range-picker', 'end_date'),
        Input('alerts-general-active-filters', 'data'),
    ]
)
def update_general_tab(client: str, start_date: str, end_date: str, active_filters: dict):
    """
    Update all components in the General Tab when client changes or filters are applied.

    Args:
        client: Selected client identifier
        start_date, end_date: Date-range picker bounds
        active_filters: Cross-filter selections from clicking the charts
            (keys: 'unit', 'week', 'system'), combined with AND.

    Returns:
        Tuple of (unit_chart, month_chart, system_chart, stats, table, filter_summary,
        badges, clear_all_button_style)
    """
    if not client:
        raise PreventUpdate

    logger.info(f"Loading alerts general view for client: {client}")
    # Load alerts data
    alerts_df = load_alerts_data(client)

    if alerts_df.empty:
        logger.warning(f"No alerts data available for client: {client}")
        empty_fig = {'data': [], 'layout': {'title': 'No data available'}}
        empty_alert = dbc.Alert("No hay datos de alertas disponibles", color="warning")
        return empty_fig, empty_fig, empty_fig, empty_alert, empty_alert, "", [], {'display': 'none'}

    active_filters = active_filters or {}
    badges = create_active_filter_badges(active_filters)
    clear_all_style = {'display': 'inline-block'} if badges else {'display': 'none'}

    try:
        # Apply the same presentation filter set to KPIs, charts and table,
        # combining the date range with any active chart cross-filters (AND).
        unit_filter = [active_filters['unit']] if active_filters.get('unit') else None
        system_filter = [active_filters['system']] if active_filters.get('system') else None
        filtered_df = filter_alert_rows(
            alerts_df, unit=unit_filter, system=system_filter,
            start_date=start_date, end_date=end_date,
        )

        week_value = active_filters.get('week')
        if week_value and not filtered_df.empty:
            week_start = pd.to_datetime(week_value)
            week_end = week_start + pd.Timedelta(days=7)
            filtered_df = filtered_df[(filtered_df['Timestamp'] >= week_start) & (filtered_df['Timestamp'] < week_end)]

        if filtered_df.empty:
            logger.warning("No data after applying filters")
            empty_fig = {'data': [], 'layout': {'title': 'No hay datos con los filtros aplicados'}}
            empty_alert = dbc.Alert("No hay datos con los filtros aplicados", color="info")
            return empty_fig, empty_fig, empty_fig, empty_alert, empty_alert, "No hay alertas para los filtros seleccionados.", badges, clear_all_style

        # Create charts (using filtered data for visualization) - removed trigger_chart
        unit_chart = create_alerts_per_unit_chart(filtered_df)
        month_chart = create_alerts_per_week_chart(filtered_df)
        system_chart = create_system_signal_treemap(filtered_df, client=client)

        # Calculate summary statistics
        summary = alert_summary(filtered_df)
        stats = create_summary_stats_display(summary['total'], summary['units'], mixed_count=summary['mixed'])

        # Create table
        table = create_alerts_report_table(filtered_df)

        latest = format_local(summary['latest'])  # W34-06: local wall-clock time
        filter_summary = f"Mostrando {summary['total']} alertas de {summary['units']} unidades · última alerta: {latest}"
        logger.info(f"General tab updated successfully with {summary['total']} alerts")
        return unit_chart, month_chart, system_chart, stats, table, filter_summary, badges, clear_all_style

    except Exception as e:
        logger.error(f"Error updating general tab: {e}")
        error_fig = {'data': [], 'layout': {'title': f'Error: {str(e)}'}}
        error_alert = dbc.Alert(f"Error al cargar datos: {str(e)}", color="danger")
        return error_fig, error_fig, error_fig, error_alert, error_alert, f"Error: {str(e)}", badges, clear_all_style


@callback(
    Output('alerts-general-active-filters', 'data', allow_duplicate=True),
    [
        Input('alerts-unit-distribution-chart', 'clickData'),
        Input('alerts-month-distribution-chart', 'clickData'),
        Input('alerts-system-distribution-chart', 'clickData'),
        Input({'type': 'alerts-general-filter-chip', 'key': ALL}, 'n_clicks'),
        Input('alerts-general-filter-clear-all', 'n_clicks'),
    ],
    State('alerts-general-active-filters', 'data'),
    prevent_initial_call=True,
)
def update_active_filters(unit_click, week_click, system_click, _chip_clicks, _clear_clicks, current):
    """
    Maintain the shared cross-filter state for the General tab's three charts.

    Clicking a bar/point/slice sets (or, if already active, clears) that
    dimension's filter; multiple dimensions combine with AND. A filter chip's
    own click removes just that dimension; "Limpiar filtros" clears all.
    """
    trigger = callback_context.triggered_id
    current = dict(current or {})

    if trigger == 'alerts-general-filter-clear-all':
        return {}

    if isinstance(trigger, dict) and trigger.get('type') == 'alerts-general-filter-chip':
        current.pop(trigger.get('key'), None)
        return current

    if trigger == 'alerts-unit-distribution-chart':
        # Units sit on the X-axis of the Pareto chart (both the count bars and
        # the cumulative-percentage line share the same category axis).
        points = (unit_click or {}).get('points') or []
        value = points[0].get('x') if points else None
        key = 'unit'
    elif trigger == 'alerts-month-distribution-chart':
        points = (week_click or {}).get('points') or []
        customdata = points[0].get('customdata') if points else None
        value = customdata[0] if customdata else None
        key = 'week'
    elif trigger == 'alerts-system-distribution-chart':
        # The treemap's every node (system tile and señal/variable leaf
        # alike) carries its owning system in customdata, so clicking
        # anywhere in a system's branch filters by that system.
        points = (system_click or {}).get('points') or []
        value = points[0].get('customdata') if points else None
        key = 'system'
    else:
        raise PreventUpdate

    if value is None:
        raise PreventUpdate

    if current.get(key) == value:
        current.pop(key, None)
    else:
        current[key] = value
    return current


@callback(
    Output('alerts-general-active-filters', 'data', allow_duplicate=True),
    Input('client-selector', 'value'),
    prevent_initial_call=True,
)
def reset_active_filters_on_client_change(_client):
    """Drop any chart cross-filter when the client changes, since selections
    (unit/week/system) don't necessarily carry over to a different client."""
    return {}


@callback(
    Output('alerts-general-selected-alert', 'children'),
    Input('alerts-datatable', 'active_cell'),
    State('alerts-datatable', 'derived_virtual_data'),
    prevent_initial_call=True,
)
def render_selected_alert_summary(active_cell, table_data):
    """Show a compact decision summary below the executive table."""
    if not active_cell or not table_data:
        return html.Div()
    index = active_cell.get('row', 0)
    if index >= len(table_data):
        return html.Div()
    row = table_data[index]
    return dbc.Card([
        dbc.CardHeader([
            html.I(className='fas fa-bullseye me-2'),
            f"Resumen de {row.get('ID', '-')}",
        ]),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([html.Small('Unidad', className='text-muted d-block'), html.Strong(row.get('Unidad', '-'))], md=2),
                dbc.Col([html.Small('Sistema', className='text-muted d-block'), html.Strong(row.get('Sistema', '-'))], md=2),
                dbc.Col([html.Small('Fuente', className='text-muted d-block'), html.Strong(row.get('Fuente', '-'))], md=2),
                dbc.Col([html.Small('Evidencia', className='text-muted d-block'), html.Strong(row.get('Evidencia', '-'))], md=6),
            ], className='mb-3'),
            html.Strong(row.get('diagnostico_completo') or row.get('Diagnóstico', 'Sin diagnóstico IA disponible'), className='d-block'),
            html.P(row.get('causa_completa') or 'Sin causa probable registrada', className='text-muted mt-2 mb-1', style={'whiteSpace': 'pre-wrap'}),
            html.Div([
                html.I(className='fas fa-wrench me-1'),
                html.Strong('Acción: '),
                row.get('accion_completa') or row.get('Acción', 'Sin acción recomendada registrada'),
            ], className='text-primary mt-2'),
            dbc.Button([
                html.I(className='fas fa-arrow-right me-1'), 'Ver detalle de la alerta'
            ], id='general-nav-to-detail-button', color='primary', size='sm', className='mt-3'),
        ]),
    ], className='shadow-sm', style={'borderLeft': '4px solid #3498db'})


@callback(
    Output('alerts-selected-alert-id', 'data'),
    Input('alerts-datatable', 'active_cell'),
    State('alerts-datatable', 'derived_virtual_data'),
    prevent_initial_call=True,
)
def store_selected_alert(active_cell, table_data):
    if not active_cell or not table_data:
        raise PreventUpdate
    index = active_cell.get('row', 0)
    if index >= len(table_data):
        raise PreventUpdate
    return table_data[index].get('ID')


@callback(
    [Output('alerts-date-range-picker', 'start_date'),
     Output('alerts-date-range-picker', 'end_date')],
    [Input('alerts-date-range-clear', 'n_clicks')],
    prevent_initial_call=True
)
def clear_date_range(_):
    """Restore the client-facing default of the last four calendar weeks."""
    today = date.today()
    return (today - timedelta(days=27)).isoformat(), today.isoformat()


@callback(
    Output('alert-selector-dropdown', 'options'),
    [Input('client-selector', 'value')]
)
def initialize_alert_dropdown(client: str):
    """
    Initialize alert selector dropdown with all available alerts.
    
    Args:
        client: Selected client identifier
    
    Returns:
        List of dropdown options
    """
    if not client:
        raise PreventUpdate
    
    logger.info(f"Initializing alert dropdown for client: {client}")
    
    alerts_df = load_alerts_data(client)
    
    if alerts_df.empty:
        return []
    
    try:
        # Create dropdown options
        sorted_alerts_df = alerts_df.sort_values('Timestamp', ascending=False).copy()
        # Critical-review follow-up: assign the formatted column once,
        # directly on the frame, instead of a separate Series indexed by
        # `.loc[idx]` inside the loop.
        sorted_alerts_df['_fecha_local'] = format_local(sorted_alerts_df['Timestamp'], fmt='%Y-%m-%d %H:%M')
        options = []
        for _, row in sorted_alerts_df.iterrows():
            # W34-06: local wall-clock time in the dropdown label, matching
            # the table/header/chart.
            label = f"{row['FusionID']} | {row['_fecha_local']} | {row['UnitId']} | {translate_alert_component(row['componente'])}"
            options.append({'label': label, 'value': row['FusionID']})

        logger.info(f"Dropdown initialized with {len(options)} alerts")
        return options
    
    except Exception as e:
        logger.error(f"Error initializing dropdown: {e}")
        return []


# ========================================
# GENERAL TAB NAVIGATION BUTTON CALLBACKS
# ========================================

@callback(
    Output('alerts-navigation-state', 'data'),
    [Input('general-nav-to-detail-button', 'n_clicks')],
    [State('alerts-selected-alert-id', 'data')],
    prevent_initial_call=True
)
def navigate_to_detail_from_general(n_clicks, selected_alert_id):
    """
    Store navigation request from General tab to Detail tab with selected alert.
    Uses store-based pattern to avoid direct output to dynamically rendered component.
    
    Args:
        n_clicks: Number of times button has been clicked
        selected_alert_id: FusionID of selected alert from dropdown
    
    Returns:
        Navigation data dictionary
    """
    logger.info(f"[NAV] BUTTON CALLBACK TRIGGERED! n_clicks={n_clicks}, alert={selected_alert_id}")
    
    if not n_clicks or not selected_alert_id:
        raise PreventUpdate
    
    logger.info(f"[NAV] Storing navigation request to Detail tab with alert: {selected_alert_id}")
    
    # Store navigation data for listener callback to process
    return {
        'target_tab': 'detail',
        'alert_id': selected_alert_id
    }


@callback(
    Output('alerts-internal-tabs', 'value', allow_duplicate=True),
    [Input('alerts-navigation-state', 'data')],
    prevent_initial_call=True
)
def switch_to_detail_tab(nav_data):
    """
    Switch to detail tab when navigation is triggered from general tab button.
    
    Args:
        nav_data: Navigation data from alerts-navigation-state store
    
    Returns:
        Tab value to switch to
    """
    logger.info(f"[NAV] TAB SWITCH LISTENER TRIGGERED: nav_data={nav_data}")
    
    if not nav_data or not nav_data.get('target_tab'):
        raise PreventUpdate
    
    target_tab = nav_data['target_tab']
    logger.info(f"[NAV] Switching to tab: {target_tab}")
    
    return target_tab


@callback(
    Output('alert-selector-dropdown', 'value', allow_duplicate=True),
    [
        Input('alert-selector-dropdown', 'options'),
        Input('alerts-navigation-state', 'data')
    ],
    [State('alerts-internal-tabs', 'value')],
    prevent_initial_call=True
)
def set_alert_from_navigation(dropdown_options, nav_data, active_tab):
    """
    Set the alert dropdown value when navigating from general tab.
    Triggers when dropdown options are populated AND navigation state has data.
    
    Args:
        dropdown_options: Dropdown options (triggers when populated)
        nav_data: Navigation data from alerts-navigation-state store
        active_tab: Currently active internal tab ('general' or 'detail')
    
    Returns:
        Alert ID to select in dropdown
    """
    from dash import callback_context
    
    trigger_info = callback_context.triggered[0] if callback_context.triggered else None
    logger.info(f"[NAV] set_alert_from_navigation called: tab={active_tab}, nav_data={nav_data}, triggered_by={trigger_info}")
    
    # Only apply if we're on detail tab
    if active_tab != 'detail':
        logger.info(f"[NAV] Not on detail tab (current: {active_tab}), skipping")
        raise PreventUpdate
        
    if not nav_data or not nav_data.get('alert_id'):
        logger.info("[NAV] No navigation data or alert_id, skipping")
        raise PreventUpdate
    
    # Only apply if navigation target is detail tab
    if nav_data.get('target_tab') != 'detail':
        logger.info(f"[NAV] Navigation target is not detail (target: {nav_data.get('target_tab')}), skipping")
        raise PreventUpdate
    
    alert_id = nav_data['alert_id']
    logger.info(f"[NAV] Setting dropdown value to: {alert_id}")
    
    return alert_id


# ========================================
# DETAIL TAB FILTER CALLBACKS
# ========================================

@callback(
    [
        Output('detail-filter-unit', 'options'),
        Output('detail-filter-sistema', 'options')
    ],
    [Input('client-selector', 'value')]
)
def populate_detail_filter_options(client: str):
    """
    Populate filter options in detail tab.
    
    Args:
        client: Selected client identifier
    
    Returns:
        Tuple of (unit_options, sistema_options)
    """
    if not client:
        raise PreventUpdate
    
    alerts_df = load_alerts_data(client)
    
    if alerts_df.empty:
        return [], []
    
    try:
        # Unit filter options
        unit_options = [{'label': unit, 'value': unit} for unit in sorted(alerts_df['UnitId'].unique())]
        
        # Sistema filter options
        sistema_options = [
            {'label': translate_alert_system(sistema), 'value': sistema}
            for sistema in sorted(alerts_df['sistema'].unique())
        ]
        
        logger.info(f"Filter options populated: {len(unit_options)} units, {len(sistema_options)} sistemas")
        return unit_options, sistema_options
    
    except Exception as e:
        logger.error(f"Error populating filter options: {e}")
        return [], []


@callback(
    Output('alert-selector-dropdown', 'options', allow_duplicate=True),
    [
        Input('detail-filter-unit', 'value'),
        Input('detail-filter-sistema', 'value'),
        Input('detail-filter-date-from', 'date'),
        Input('detail-filter-tribology', 'value'),
        Input('client-selector', 'value')
    ],
    [State('alert-selector-dropdown', 'value')],
    prevent_initial_call=True
)
def filter_alert_dropdown_by_criteria(units, sistemas, start_date, has_tribology, client, current_value):
    """
    Filter alert dropdown based on selected detail filters.
    Preserves current selection if it's still in the filtered list.

    Args:
        units: Selected units (list)
        sistemas: Selected sistemas (list)
        start_date: "Fecha desde" (W34-05, replaces the telemetry filter) —
            a plain calendar date string (e.g. "2026-08-01") from
            detail-filter-date-from, interpreted as a Chile calendar day.
            Inclusive; None/"" means no lower bound.
        has_tribology: Filter for tribology presence
        client: Selected client
        current_value: Currently selected alert ID

    Returns:
        Filtered alert options
    """
    logger.info(f"filter_alert_dropdown_by_criteria called with current_value={current_value}")

    if not client:
        raise PreventUpdate

    # Check if any filters are actually set
    has_any_filter = any([units, sistemas, start_date, has_tribology])
    if not has_any_filter:
        logger.info("No filters set, skipping filter update")
        raise PreventUpdate

    alerts_df = load_alerts_data(client)

    if alerts_df.empty:
        return []

    try:
        # Apply filters
        filtered_df = alerts_df.copy()

        if units:
            filtered_df = filtered_df[filtered_df['UnitId'].isin(units)]

        if sistemas:
            filtered_df = filtered_df[filtered_df['sistema'].isin(sistemas)]

        # W34-05: "fecha desde" — inclusive, Chile calendar day. The picker
        # gives a naive calendar date the user chose in local terms; its
        # midnight boundary is converted to UTC (Timestamp's own
        # representation, W34-06) before comparing, so the boundary doesn't
        # shift by the 3-4h offset. An invalid/unparseable date degrades to
        # "no lower bound" rather than raising — a broken date filter must
        # not take down the whole dropdown.
        if start_date:
            try:
                start_utc = to_utc_naive(pd.Timestamp(start_date), source_tz="America/Santiago")
                # Critical-review follow-up: Chile's DST transition lands on
                # local midnight, so a boundary date can itself be
                # nonexistent/ambiguous — to_utc_naive returns NaT for that
                # rather than raising, so it needs its own check here (the
                # except below only catches an unparseable date string).
                if pd.isna(start_utc):
                    logger.warning(f"Fecha desde cae en una transición de horario de verano, ignorando filtro: {start_date!r}")
                else:
                    filtered_df = filtered_df[filtered_df['Timestamp'] >= start_utc]
            except (ValueError, TypeError):
                logger.warning(f"Fecha desde inválida, ignorando filtro: {start_date!r}")

        if has_tribology == 'yes':
            filtered_df = filtered_df[filtered_df['has_tribology'] == True]
        elif has_tribology == 'no':
            filtered_df = filtered_df[filtered_df['has_tribology'] == False]

        # Create filtered options
        sorted_filtered_df = filtered_df.sort_values('Timestamp', ascending=False).copy()
        # Critical-review follow-up: assign the formatted column once,
        # directly on the frame, instead of a separate Series indexed by
        # `.loc[idx]` inside the loop.
        sorted_filtered_df['_fecha_local'] = format_local(sorted_filtered_df['Timestamp'], fmt='%Y-%m-%d %H:%M')
        alert_options = []
        for _, row in sorted_filtered_df.iterrows():
            # W34-06: local wall-clock time in the dropdown label, matching
            # the table/header/chart.
            label = f"{row['FusionID']} | {row['_fecha_local']} | {row['UnitId']} | {translate_alert_component(row['componente'])}"
            alert_options.append({'label': label, 'value': row['FusionID']})
        
        logger.info(f"Filtered alerts: {len(alert_options)} options")
        return alert_options
    
    except Exception as e:
        logger.error(f"Error filtering alert dropdown: {e}")
        return []

def _alert_case_header(row: pd.Series) -> html.Div:
    """Render the single client-facing alert summary and its IA analysis."""
    prepared = prepare_alert_rows(pd.DataFrame([row])).iloc[0]
    timestamp = prepared.get('date_display', '-')
    diagnosis = parse_ia_message_sections(row.get('mensaje_ia', ''))
    # W34-04: same (label, color) pair as the table's row-highlight, the
    # color legend and the "Alertas mixtas" KPI card.
    source_label, source_badge_color = source_style(prepared.get('Trigger_type', ''))

    def _analysis_block(title, value, icon, color='light'):
        text = value or 'No disponible'
        return dbc.Col([
            html.Div([
                html.H6([html.I(className=f'fas {icon} me-2'), title], className='mb-2'),
                html.P(text, className='mb-0', style={'whiteSpace': 'pre-wrap', 'lineHeight': '1.5'}),
            ], className=f'p-3 bg-{color} rounded h-100')
        ], md=4)

    return dbc.Card([
        dbc.CardHeader([
            html.I(className='fas fa-fingerprint me-2'),
            html.Strong(f"Alerta {prepared.get('FusionID', '-')}")
        ], className='bg-light'),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([html.Small('Unidad', className='text-muted d-block text-nowrap'), html.Strong(prepared.get('UnitId', '-'))], xs=6, lg=2),
                dbc.Col([html.Small('Sistema', className='text-muted d-block text-nowrap'), html.Strong(prepared.get('system_display', '-'))], xs=6, lg=2),
                dbc.Col([html.Small('Componente', className='text-muted d-block text-nowrap'), html.Strong(prepared.get('component_display', '-'))], xs=6, lg=3),
                dbc.Col([html.Small('Fecha', className='text-muted d-block text-nowrap'), html.Strong(timestamp)], xs=6, lg=3),
                dbc.Col([
                    html.Small('Fuente', className='text-muted d-block text-nowrap'),
                    # Same accent-text-on-tint treatment as the "Alertas
                    # multitécnicas" KPI card (tab_alerts_general.py), not a
                    # solid fill with an implied (and untested) white text
                    # color — one visual rule for SOURCE_STYLE, not two.
                    # Use a plain span instead of dbc.Badge here. Bootstrap's
                    # badge defaults can add a dark secondary background that
                    # makes the source color unreadable (especially for
                    # Telemetría and Multitécnica). This explicit pill keeps
                    # the shared source accent while matching the dashboard's
                    # light, outlined status language.
                    html.Span(source_label, className='alert-source-badge', style={
                        'backgroundColor': light_tint(source_badge_color),
                        'color': source_badge_color,
                        'border': f'1px solid {source_badge_color}',
                        'borderRadius': '999px',
                        'display': 'inline-flex',
                        'alignItems': 'center',
                        'padding': '0.35rem 0.7rem',
                        'fontSize': '0.75rem',
                        'lineHeight': '1.1',
                        'fontWeight': '600',
                        'whiteSpace': 'nowrap',
                    }),
                ], xs=6, lg=2),
            ], className='g-3'),
            html.Div([
                html.Strong('Señal / variable: ', className='text-muted'),
                prepared.get('signal_display', 'Sin señal registrada'),
                html.Span(' · ', className='text-muted'),
                html.Strong('Evidencia: ', className='text-muted'),
                prepared.get('evidence_display', 'Sin evidencia'),
            ], className='mt-3 small'),
            html.H5([
                html.I(className='fas fa-brain me-2'),
                'Analisis inteligente'
            ], className='text-primary mt-4 mb-3 pb-2 border-bottom'),
            dbc.Row([
                _analysis_block('Diagnostico', diagnosis.get('diagnostico'), 'fa-search', 'light'),
                _analysis_block('Causa probable', diagnosis.get('causa_probable'), 'fa-project-diagram', 'light'),
                _analysis_block('Accion recomendada', diagnosis.get('acciones'), 'fa-wrench', 'light'),
            ], className='g-3'),
        ])
    ], className='shadow-sm', style={'borderTop': '3px solid #3498db'})


@callback(
    Output('alert-detail-content', 'children'),
    [
        Input('alert-selector-dropdown', 'value'),
        Input('client-selector', 'value'),
        Input('alerts-navigation-state', 'data')
    ],
    prevent_initial_call=False
)
def update_detail_view(dropdown_value, client, nav_data):
    """
    Update detail view when an alert is selected from dropdown or via navigation.
    
    Args:
        dropdown_value: FusionID selected from dropdown
        client: Selected client identifier
        nav_data: Navigation data from alerts-navigation-state store
    
    Returns:
        Updated detail content layout
    """
    logger.info(f"update_detail_view called: dropdown_value={dropdown_value}, client={client}, nav_data={nav_data}")
    
    if not client:
        logger.warning("No client selected, preventing update")
        raise PreventUpdate
    
    # Determine selected alert from dropdown OR navigation state
    selected_fusion_id = dropdown_value
    
    # If dropdown is empty but navigation state has an alert ID, use that
    if not selected_fusion_id and nav_data and nav_data.get('alert_id'):
        selected_fusion_id = nav_data.get('alert_id')
        logger.info(f"Using alert ID from navigation state: {selected_fusion_id}")
    
    if not selected_fusion_id:
        logger.info("No alert selected, showing placeholder")
        return dbc.Alert([
            html.I(className="fas fa-arrow-up me-2"),
            "Por favor, seleccione una alerta para ver los detalles"
        ], color="info", className="text-center")
    
    logger.info(f"Loading detail view for alert: {selected_fusion_id}")
    
    # Load alerts data
    alerts_df = load_alerts_data(client)
    
    if alerts_df.empty:
        return dbc.Alert("No hay datos de alertas disponibles", color="warning")
    
    # Find selected alert
    alert_row = alerts_df[alerts_df['FusionID'] == selected_fusion_id]
    
    if alert_row.empty:
        return dbc.Alert(f"Alerta no encontrada: {selected_fusion_id}", color="danger")
    
    alert_row = alert_row.iloc[0]
    
    try:
        # Determine which evidence sections to show
        trigger_type = alert_row['Trigger_type']
        # Normalize trigger type comparison (case-insensitive)
        trigger_lower = str(trigger_type).lower()
        show_telemetry = 'telemetria' in trigger_lower or 'mixto' in trigger_lower
        show_oil = 'tribologia' in trigger_lower or 'oil' in trigger_lower or 'mixto' in trigger_lower
        show_maintenance = pd.notna(alert_row.get('Semana_Resumen_Mantencion'))
        
        logger.info(f"Trigger type: {trigger_type}, Evidence sections - Telemetry: {show_telemetry}, Oil: {show_oil}, Maintenance: {show_maintenance}")
        
        # Render the alert itself first. Evidence is appended only after the
        # identity and IA analysis are available, avoiding a graph-first state.
        sections = [_alert_case_header(alert_row)]

        if show_telemetry:
            sections.append(create_telemetry_evidence_section(alert_row, client))
        
        # 3. Oil Evidence (conditional)
        if show_oil:
            sections.append(create_oil_evidence_section(alert_row, client))
        
        # 4. Maintenance Evidence (always if available)
        if show_maintenance:
            sections.append(create_maintenance_evidence_section(alert_row, client))
        
        return html.Div(sections)
    
    except Exception as e:
        logger.error(f"Error creating detail view: {e}")
        return dbc.Alert(f"Error al cargar detalles: {str(e)}", color="danger")


clientside_callback(
    """
    function(children) {
        if (!children) {
            return window.dash_clientside.no_update;
        }
        // The detail content can include large Plotly figures.  Scroll only
        // after Dash has committed the new content so the alert header is
        // the first visible element, instead of the browser restoring a
        // middle-of-page position from the previous alert.
        window.requestAnimationFrame(function() {
            window.scrollTo({top: 0, left: 0, behavior: 'auto'});
            document.documentElement.scrollTop = 0;
            document.body.scrollTop = 0;
        });
        return Date.now();
    }
    """,
    Output('alerts-detail-scroll-trigger', 'data'),
    Input('alert-detail-content', 'children'),
    prevent_initial_call=True,
)


def create_telemetry_evidence_section(alert_row: pd.Series, client: str) -> html.Div:
    """
    Create telemetry evidence section with sensor trends, GPS, and KPIs.
    Uses pre-processed golden layer data for simplicity and performance.
    
    Args:
        alert_row: Selected alert data
        client: Client identifier
    
    Returns:
        HTML Div with telemetry evidence
    """
    logger.info("Creating telemetry evidence section using golden layer data")
    
    try:
        alert_ids = list(dict.fromkeys(
            identifier
            for identifier in (
                _normalise_alert_identifier(alert_row.get('TelemetryID')),
                _normalise_alert_identifier(alert_row.get('FusionID')),
            )
            if identifier
        ))
        unit_id = _normalise_alert_identifier(alert_row.get('UnitId'))

        if not alert_ids:
            return html.Div([
                dbc.Alert("Esta alerta no tiene un identificador asociado", color="info")
            ])
        if not unit_id:
            return html.Div([
                dbc.Alert("Esta alerta no tiene UnitId asociado", color="info")
            ])

        # Read only the selected alert/unit when Polars is available. The
        # pandas fallback preserves the previous cached behavior.
        telemetry_golden = load_telemetry_alert_detail_for_alert(
            client, alert_ids, unit_id
        )

        if telemetry_golden.empty:
            return html.Div([
                dbc.Alert("No hay datos de telemetría disponibles", color="warning")
            ])

        # Filter telemetry data by BOTH AlertID AND Unit (AlertID is unique
        # per unit, not globally). Keep the comparison textual: Capstone IDs
        # are deterministic strings such as CAP-....
        alert_data, _, _ = _select_telemetry_alert_data(telemetry_golden, alert_row)
        
        if alert_data.empty:
            return html.Div([
                dbc.Alert(
                    "No se encontraron datos de telemetría para los identificadores: "
                    f"{', '.join(alert_ids)}",
                    color="warning",
                )
            ])
        
        # Drop columns with all NaN values
        alert_data_clean = alert_data.dropna(axis=1, how='all')
        
        # Extract metadata
        unit_id = alert_data_clean['Unit'].iloc[0]
        # IMPORTANT: Use alert_time from alerts_data, NOT from telemetry TimeStart
        # TimeStart is just the beginning of the telemetry window, not the actual alert moment
        alert_time = pd.to_datetime(alert_row.get('Timestamp'))
        trigger = alert_data_clean['Trigger'].iloc[0]
        
        logger.info(f"Processing telemetry alert: Unit={unit_id}, Time={alert_time}, Trigger={trigger}")

        # Load feature names mapping for Spanish titles (use FEATURE_NAMES_ES from alerts_charts)
        from dashboard.components.alerts_charts import FEATURE_NAMES_ES, select_plottable_signals
        feature_name_map = FEATURE_NAMES_ES

        # Alert-context header shown above the telemetry charts: alert id,
        # unit and the (Spanish) trigger signal name.
        alert_id_display = (
            _normalise_alert_identifier(alert_row.get('FusionID'))
            or _normalise_alert_identifier(alert_row.get('TelemetryID'))
            or '-'
        )
        trigger_display = (
            feature_name_map.get(trigger, trigger) if pd.notna(trigger) else 'Sin señal'
        )

        # Identify features to plot (columns ending with _Value)
        value_cols = [col for col in alert_data_clean.columns if col.endswith('_Value')]
        feature_names = [col.replace('_Value', '') for col in value_cols]

        # W34-11: a panel is drawn only for signals that are both present in the
        # source (checked above) AND permitted (see select_plottable_signals).
        # Data stays available for KPIs regardless of this filter —
        # alert_data_clean itself is untouched.
        feature_names, uncatalogued = select_plottable_signals(feature_names)
        if uncatalogued:
            logger.warning(
                "Señales presentes en la fuente pero no catalogadas en SIGNAL_LABELS, "
                f"omitidas del gráfico de tendencias: {uncatalogued}"
            )

        if not feature_names:
            return html.Div([
                dbc.Alert("No se encontraron señales con valores para graficar", color="warning")
            ])

        logger.info(f"Found {len(feature_names)} features to plot: {feature_names}")
        
        # Create sensor trends chart (using new simplified approach)
        sensor_trends_fig = create_sensor_trends_chart_golden(
            alert_data=alert_data_clean,
            feature_names=feature_names,
            unit_id=unit_id,
            alert_time=alert_time,
            feature_name_map=feature_name_map,
            client=client
        )
        
        # Create GPS map (if GPS data available)
        gps_map_fig = create_gps_route_map_golden(
            alert_data=alert_data_clean,
            unit_id=unit_id,
            alert_time=alert_time,
            mapbox_token=MAPBOX_TOKEN
        )
        
        # Create context KPIs
        context_kpis = create_context_kpis_cards_golden(
            alert_data=alert_data_clean,
            alert_time=alert_time,
            trigger=trigger
        )
        
        # Build section with NEW LAYOUT: [Trends full] then [KPIs 4 | GPS 8]
        return html.Div([
            # Section header
            dbc.Row([
                dbc.Col([
                    html.H4([
                        html.I(className="fas fa-signal me-2"),
                        "Evidencia de Telemetría"
                    ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
                    html.P("Análisis de datos de sensores y ubicación GPS durante el evento", 
                           className="text-muted mb-3")
                ])
            ]),

            # Row 1: Sensor Trends (FULL WIDTH)
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-chart-line me-2"),
                                "Tendencias de Sensores"
                            ], className="mb-0"),
                            html.Div(
                                f"Alerta {alert_id_display} · {unit_id} · Gatillo: {trigger_display}",
                                className="small fw-bold text-primary mt-1"
                            ),
                            # Quality-review follow-up: a signal present in the
                            # source but not yet in SIGNAL_LABELS used to be
                            # invisible here (logger.warning only, nothing on
                            # screen) — this line is the only user-facing
                            # trace that some evidence exists but isn't
                            # charted, so it's never mistaken for "not
                            # recorded".
                            html.Div(
                                [
                                    html.I(className="fas fa-triangle-exclamation me-1"),
                                    f"{len(uncatalogued)} señal(es) adicional(es) no catalogada(s) "
                                    "omitida(s) de este gráfico.",
                                ],
                                className="small text-warning mt-1",
                            ) if uncatalogued else None,
                        ], className="bg-light"),
                        dbc.CardBody([
                            dcc.Loading(
                                id="loading-sensor-trends-callback",
                                type="circle",
                                children=[
                                    dcc.Graph(
                                        figure=sensor_trends_fig,
                                        config={'displayModeBar': True}
                                    )
                                ]
                            )
                        ])
                    ], className="shadow-sm mb-4")
                ], md=12)
            ]),
            
            # Row 2: KPIs (LEFT, 1 col x 4 rows, 4 cols) + GPS Map (RIGHT, 8 cols) - SAME HEIGHT
            dbc.Row([
                # Left: KPIs (vertical layout, 1 column x 4 rows)
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-tachometer-alt me-2"),
                                "Indicadores de Contexto"
                            ], className="mb-0")
                        ], className="bg-light"),
                        dbc.CardBody([
                            dcc.Loading(
                                id="loading-context-kpis-callback",
                                type="circle",
                                children=[context_kpis]
                            )
                        ], className="p-3")
                    ], className="shadow-sm mb-4 h-100")  # h-100 for full height
                ], md=4),
                
                # Right: GPS Map
                dbc.Col([
                    dbc.Card([
                        dbc.CardHeader([
                            html.H5([
                                html.I(className="fas fa-map-marked-alt me-2"),
                                "Ubicación y Ruta GPS"
                            ], className="mb-0")
                        ], className="bg-light"),
                        dbc.CardBody([
                            dcc.Loading(
                                id="loading-gps-map-callback",
                                type="circle",
                                children=[
                                    dcc.Graph(
                                        figure=gps_map_fig,
                                        config={'displayModeBar': True},
                                        style={'height': '500px'}
                                    )
                                ]
                            )
                        ], className="p-2")
                    ], className="shadow-sm mb-4 h-100")  # h-100 for full height
                ], md=8)
            ], className="gx-3")  # Horizontal spacing between columns
        ], className="mb-5")
    
    except Exception as e:
        logger.error(f"Error creating telemetry evidence: {e}")
        return html.Div([
            dbc.Alert(f"Error al cargar evidencia de telemetría: {str(e)}", color="danger")
        ])


def _build_oil_tendencia_view(history_full, comp_limits, oil_hour_range, start_date, end_date):
    """
    Build the Tendencia (oil report history) sub-view: a date-range filter on
    the oil REPORT date (sampleDate, inclusive boundaries) plus the shared
    9-chart time-series grid. Isolated by design - this filter only affects
    this chart, not the rest of Monitoring > Alertas.

    Args:
        history_full: Unfiltered sampleDate-sorted history for this equipment/component.
        comp_limits: Four-limit Stewart limits dict for this component.
        oil_hour_range: oilHourRange of the most recent sample, for limit lookup.
        start_date, end_date: ISO date strings (or None for no bound).

    Returns:
        List of Dash components (date-range picker row + the chart grid).
    """
    history = history_full
    if not history.empty:
        if start_date:
            history = history[history['sampleDate'] >= pd.to_datetime(start_date)]
        if end_date:
            history = history[history['sampleDate'] <= pd.to_datetime(end_date)]

    grid = build_oil_time_series_grid(history, comp_limits, oil_hour_range)

    return [
        dbc.Row([
            dbc.Col([
                html.Small("Rango de fechas (reporte de aceite): ", className="text-muted me-2"),
                dcc.DatePickerRange(
                    id='alert-oil-tendencia-date-range',
                    start_date=start_date,
                    end_date=end_date,
                    display_format='DD/MM/YYYY',
                    className="d-inline-block",
                ),
            ], width='auto'),
            dbc.Col([
                dbc.Button([html.I(className="fas fa-times me-1"), "Limpiar"],
                           id='alert-oil-tendencia-date-clear', color="outline-secondary", size="sm")
            ], width='auto'),
        ], className="mb-2 align-items-center g-2"),
        grid,
    ]


def create_oil_evidence_section(alert_row: pd.Series, client: str) -> html.Div:
    """
    Create oil evidence section with grouped radar charts and threshold tables.
    Matches the style from monitoring>oil section.
    
    Args:
        alert_row: Selected alert data
        client: Client identifier
    
    Returns:
        HTML Div with oil evidence
    """
    logger.info("Creating oil evidence section")
    
    try:
        from pathlib import Path

        # Load oil data
        oil_classified = load_oil_classified(client)
        
        # Check if oil data is available
        tribology_id = alert_row.get('TribologyID')
        if oil_classified.empty or tribology_id is None or (isinstance(tribology_id, float) and pd.isna(tribology_id)):
            return html.Div([
                dbc.Alert("No hay datos de tribología disponibles", color="warning")
            ])
        
        # Filter for this sample
        oil_report = oil_classified[
            oil_classified['sampleNumber'] == tribology_id
        ]
        
        if oil_report.empty:
            return html.Div([
                dbc.Alert(f"Reporte no encontrado para muestra: {tribology_id}", color="warning")
            ])
        
        oil_report = oil_report.iloc[0]
        
        # Load essays_elements mapping
        essays_file = _data_path("oil", "essays_elements.xlsx")
        if not essays_file.exists():
            return html.Div([
                dbc.Alert("Archivo essays_elements.xlsx no encontrado", color="warning")
            ])
        
        essays_df = load_essays_mapping(essays_file)

        # Load four-limit Stewart limits (LIC/LIM/LSM/LSC, data contract v2.8)
        from src.data.loaders import load_stewart_limits_four
        from config.settings import get_settings
        settings = get_settings()
        limits_file = settings.get_stewart_limits_four_path(client)
        limits = load_stewart_limits_four(limits_file) if limits_file.exists() else None

        if not limits:
            return html.Div([
                dbc.Alert("Límites Stewart no disponibles", color="warning")
            ])

        # Get limits for this component
        machine = oil_report.get('machineName', '')
        component_normalized = oil_report.get('componentNameNormalized', oil_report.get('componentName', ''))

        if client not in limits or machine not in limits[client] or component_normalized not in limits[client][machine]:
            return html.Div([
                dbc.Alert(f"Límites no disponibles para {machine}/{component_normalized}", color="warning")
            ])

        comp_limits = limits[client][machine][component_normalized]

        # Get sample's oil hour range for v2.3 stratified limits
        sample_oil_hour_range = oil_report.get('oilHourRange', 'UNKNOWN')
        logger.info(f"Sample oilHourRange: {sample_oil_hour_range}")

        # ── Tendencia: same equipment/component history, shared grid builder ──
        # Scoped to a date-range filter on the oil REPORT date (sampleDate),
        # defaulting to this equipment/component's own latest 12 months of
        # history. This filter is isolated to the Tendencia chart below - it
        # does not affect the alerts list/table/KPIs elsewhere in Monitoring >
        # Alertas.
        unit_id = oil_report.get('unitId')
        oil_component_name = oil_report.get('componentName')
        tendencia_history_full = oil_classified[
            (oil_classified['unitId'] == unit_id) & (oil_classified['componentName'] == oil_component_name)
        ].copy()
        if not tendencia_history_full.empty:
            tendencia_history_full['sampleDate'] = pd.to_datetime(tendencia_history_full['sampleDate'])
            tendencia_history_full = tendencia_history_full.sort_values('sampleDate')

        default_end = tendencia_history_full['sampleDate'].max() if not tendencia_history_full.empty else None
        default_start = (default_end - pd.DateOffset(months=12)) if default_end is not None else None
        default_start_str = default_start.strftime('%Y-%m-%d') if default_start is not None else None
        default_end_str = default_end.strftime('%Y-%m-%d') if default_end is not None else None

        tendencia_context = {
            'client': client,
            'unit_id': unit_id,
            'component_name': oil_component_name,
            'machine': machine,
            'component_normalized': component_normalized,
            'oil_hour_range': sample_oil_hour_range,
        }

        tendencia_view_children = _build_oil_tendencia_view(
            tendencia_history_full, comp_limits, sample_oil_hour_range,
            start_date=default_start_str, end_date=default_end_str,
        )

        # Radar charts + tables for the latest essay, shared with
        # Monitoring > Oil > Details (dashboard/components/oil_charts.py::build_oil_radar_view)
        charts_and_tables = build_oil_radar_view(oil_report, comp_limits, sample_oil_hour_range, essays_df)

        # Build final section
        report_status = oil_report.get('report_status', 'N/A')
        status_colors = {
            'Normal': 'success',
            'Marginal': 'warning',
            'Condenatorio': 'danger',
            'Critico': 'danger',
            'Anormal': 'danger'
        }
        status_color = status_colors.get(report_status, 'secondary')
        
        # Get oil meter and oil hour range for display
        oil_meter = oil_report.get('oilMeter', None)
        oil_meter_display = f"{oil_meter:.1f}h" if pd.notna(oil_meter) else "N/A"
        
        # Oil hour range badge color and text
        oil_hour_range_colors = {
            'LT_1000': 'success',  # Fresh oil - green
            'GE_1000': 'warning',  # Aged oil - orange
            'UNKNOWN': 'secondary'  # Unknown - gray
        }
        oil_hour_range_labels = {
            'LT_1000': 'Aceite Fresco (<1000h)',
            'GE_1000': 'Aceite Envejecido (≥1000h)',
            'UNKNOWN': 'Edad de Aceite Desconocida'
        }
        oil_hour_color = oil_hour_range_colors.get(sample_oil_hour_range, 'secondary')
        oil_hour_label = oil_hour_range_labels.get(sample_oil_hour_range, sample_oil_hour_range)
        
        return html.Div([
            dbc.Row([
                dbc.Col([
                    html.H4([
                        html.I(className="fas fa-flask me-2"),
                        "Análisis de Aceite"
                    ], className="text-warning mb-2"),
                    html.Div([
                        dbc.Badge(
                            f"Estado: {report_status}",
                            color=status_color,
                            className="me-2",
                            style={'fontSize': '1rem'}
                        ),
                        dbc.Badge(
                            f"ID Muestra: {tribology_id}",
                            color="info",
                            className="me-2",
                            style={'fontSize': '1rem'}
                        ),
                        dbc.Badge(
                            f"Horas Aceite: {oil_meter_display}",
                            color="dark",
                            className="me-2",
                            style={'fontSize': '1rem'}
                        ),
                        dbc.Badge(
                            oil_hour_label,
                            color=oil_hour_color,
                            className="mb-3",
                            style={'fontSize': '1rem'},
                            title="Límites estratificados v2.3 basados en edad del aceite"
                        )
                    ], className="mb-3")
                ])
            ]),
            dcc.Store(id='alert-oil-tendencia-context', data=tendencia_context),
            dcc.Tabs(
                id='alert-oil-view-selector',
                value='tendencia',
                children=[
                    dcc.Tab(label='  Tendencia', value='tendencia',
                            className='custom-tab', selected_className='custom-tab--selected'),
                    dcc.Tab(label='  Último Ensayo', value='ultimo_ensayo',
                            className='custom-tab', selected_className='custom-tab--selected'),
                ],
                className='mb-3'
            ),
            html.Div(id='alert-oil-tendencia-view', children=tendencia_view_children),
            html.Div(id='alert-oil-radar-view', children=[html.Div(charts_and_tables)],
                     style={'display': 'none'}),
        ], className="mb-5")
    
    except Exception as e:
        logger.error(f"Error creating oil evidence: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return html.Div([
            dbc.Alert(f"Error al cargar evidencia de tribología: {str(e)}", color="danger")
        ])


@callback(
    Output('alert-oil-tendencia-view', 'style'),
    Output('alert-oil-radar-view', 'style'),
    Input('alert-oil-view-selector', 'value'),
    prevent_initial_call=True,
)
def toggle_oil_evidence_view(view):
    """Switch between the Tendencia grid and the Último Ensayo radar without re-rendering either."""
    if view == 'ultimo_ensayo':
        return {'display': 'none'}, {'display': 'block'}
    return {'display': 'block'}, {'display': 'none'}


@callback(
    Output('alert-oil-tendencia-view', 'children'),
    Input('alert-oil-tendencia-date-range', 'start_date'),
    Input('alert-oil-tendencia-date-range', 'end_date'),
    State('alert-oil-tendencia-context', 'data'),
    prevent_initial_call=True,
)
def update_oil_tendencia_range(start_date, end_date, context):
    """
    Re-filter the Tendencia chart by oil report date (sampleDate). Isolated by
    design: only this chart's Output is touched, nothing else in Monitoring >
    Alertas reacts to this filter.
    """
    if not context:
        raise PreventUpdate

    from src.data.loaders import load_stewart_limits_four
    from config.settings import get_settings

    client = context['client']
    oil_classified = load_oil_classified(client)
    history_full = oil_classified[
        (oil_classified['unitId'] == context['unit_id'])
        & (oil_classified['componentName'] == context['component_name'])
    ].copy()
    if not history_full.empty:
        history_full['sampleDate'] = pd.to_datetime(history_full['sampleDate'])
        history_full = history_full.sort_values('sampleDate')

    settings = get_settings()
    limits_file = settings.get_stewart_limits_four_path(client)
    limits = load_stewart_limits_four(limits_file) if limits_file.exists() else {}
    comp_limits = limits.get(client, {}).get(context['machine'], {}).get(context['component_normalized'], {})

    return _build_oil_tendencia_view(
        history_full, comp_limits, context['oil_hour_range'],
        start_date=start_date, end_date=end_date,
    )


@callback(
    Output('alert-oil-tendencia-date-range', 'start_date'),
    Output('alert-oil-tendencia-date-range', 'end_date'),
    Input('alert-oil-tendencia-date-clear', 'n_clicks'),
    prevent_initial_call=True,
)
def clear_oil_tendencia_date_range(_):
    """Clear the Tendencia date filter, showing the full available history."""
    return None, None


def create_maintenance_evidence_section(alert_row: pd.Series, client: str) -> html.Div:
    """
    Create maintenance evidence section.
    
    Args:
        alert_row: Selected alert data
        client: Client identifier
    
    Returns:
        HTML Div with maintenance evidence
    """
    logger.info("Creating maintenance evidence section")
    
    try:
        # Get maintenance week
        maintenance_week = alert_row.get('Semana_Resumen_Mantencion')
        
        if pd.isna(maintenance_week):
            return html.Div([
                dbc.Alert("No hay referencia de semana de mantenimiento", color="info")
            ])
        
        # Load maintenance data
        maintenance_df = load_maintenance_week(client, maintenance_week)
        
        if maintenance_df.empty:
            return html.Div([
                dbc.Alert(f"No hay datos de mantenimiento para semana {maintenance_week}", color="warning")
            ])
        
        # Filter for this unit
        unit_maintenance = maintenance_df[
            maintenance_df['UnitId'] == alert_row['UnitId']
        ]
        
        if unit_maintenance.empty:
            return html.Div([
                dbc.Alert(f"No hay datos de mantenimiento para unidad {alert_row['UnitId']}", color="warning")
            ])
        
        unit_maintenance = unit_maintenance.iloc[0]
        
        # Create maintenance display
        maintenance_card = create_maintenance_display(
            maintenance_data=unit_maintenance,
            alert_system=alert_row['sistema']
        )
        
        # Build section
        return html.Div([
            dbc.Row([
                dbc.Col([
                    html.H4([
                        html.I(className="fas fa-tools me-2"),
                        "Evidencia de Mantenimiento"
                    ], className="text-secondary mb-3")
                ])
            ]),
            
            dbc.Row([
                dbc.Col([
                    maintenance_card
                ], md=12)
            ])
        ], className="mb-4")
    
    except Exception as e:
        logger.error(f"Error creating maintenance evidence: {e}")
        return html.Div([
            dbc.Alert(f"Error al cargar evidencia de mantenimiento: {str(e)}", color="danger")
        ])
