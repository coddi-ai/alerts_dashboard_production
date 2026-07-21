"""Callbacks for the reportable telemetry fleet and unit views."""

from datetime import date, datetime, timedelta
from functools import lru_cache

import pandas as pd
from dash import callback, Input, Output, State, ctx, html, dcc, dash_table
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc

from src.data.loaders import load_silver_telemetry_week
from dashboard.components.telemetry_charts import (
    STATUS_COLORS,
    build_fleet_heatmap,
    build_heatmap_insights,
    build_signal_timeseries_card,
)
from dashboard.components.telemetry_report import (
    build_fleet_priority_rows,
    build_signal_rows,
    build_system_rows,
    client_facing_manifest,
    client_facing_text,
    filter_fleet_snapshot,
    format_urgency,
    load_telemetry_snapshot,
)
from dashboard.tabs.tab_telemetry_fleet import create_telemetry_fleet_layout
from dashboard.tabs.tab_telemetry_unit_detail import create_telemetry_unit_detail_layout
from src.utils.logger import get_logger

logger = get_logger(__name__)


@callback(Output('telemetry-availability-notice', 'children'), Input('client-selector', 'value'))
def update_telemetry_availability(client):
    if not client:
        return html.Div()
    snapshot = load_telemetry_snapshot(client)
    if snapshot.unit_health.empty and snapshot.system_health.empty:
        return dbc.Alert([
            html.I(className="fas fa-info-circle me-2"),
            f"No hay datos de Telemetría disponibles para el cliente {str(client).upper()}."
        ], color="info")
    return html.Div()


@callback(
    Output('telemetry-reference-date', 'children'),
    [Input('telemetry-health-tabs', 'value'), Input('client-selector', 'value')],
)
def update_reference_date(active_tab, client):
    """Show the materialized evaluation identity and refresh when client changes."""
    if not client:
        raise PreventUpdate
    manifest = client_facing_manifest(load_telemetry_snapshot(client).manifest)
    if not manifest:
        return html.Small("Sin datos de referencia", className="text-muted")
    week = manifest.get('evaluation_week', '?')
    year = manifest.get('evaluation_year', '?')
    timestamp = str(manifest.get('execution_timestamp', ''))
    date_str = timestamp[:10] if timestamp else ''
    return html.Div([
        html.Small([html.I(className="fas fa-calendar-alt me-1"), f"Semana {week}/{year}"], className="d-block text-muted"),
        html.Small([html.I(className="fas fa-sync-alt me-1"), f"Actualizado: {date_str}"], className="d-block text-muted") if date_str else html.Span(),
    ])


@callback(Output('telemetry-health-tab-content', 'children'), Input('telemetry-health-tabs', 'value'))
def render_telemetry_health_tab(active_tab):
    if active_tab == 'fleet-overview':
        return create_telemetry_fleet_layout()
    if active_tab == 'unit-detail':
        return create_telemetry_unit_detail_layout()
    return html.Div("Selección inválida")


@callback(
    [Output('telemetry-fleet-model-filter', 'options'), Output('telemetry-fleet-system-filter', 'options')],
    [Input('telemetry-health-tabs', 'value'), Input('client-selector', 'value')],
)
def populate_fleet_filters(active_tab, client):
    if active_tab != 'fleet-overview' or not client:
        raise PreventUpdate
    snapshot = load_telemetry_snapshot(client)
    models = sorted(set(snapshot.equipment_models.values()))
    systems = sorted({str(v) for v in snapshot.system_health.get('system', pd.Series(dtype=str)).map(lambda x: {
        'Engine': 'Motor', 'Transmission': 'Transmisión', 'Brakes': 'Frenos', 'Steering': 'Dirección'
    }.get(x, x)).dropna()})
    return ([{'label': model, 'value': model} for model in models],
            [{'label': system, 'value': system} for system in systems])


def _kpi_card(label: str, value, icon: str, color: str, bg_color: str) -> dbc.Col:
    return dbc.Col([
        dbc.Card([
            dbc.CardBody([
                html.Div([
                    html.I(className=f"{icon} fa-2x text-{color} mb-2"),
                    html.H6(label, className="text-muted text-uppercase mb-2", style={'fontSize': '0.78rem', 'letterSpacing': '0.4px'}),
                    html.H2(str(value), className=f"text-{color} mb-0 fw-bold")
                ], className="text-center")
            ])
        ], className="shadow-sm border-0", style={'backgroundColor': bg_color})
    ], xs=6, md=2, lg=2)


def _priority_table(rows: list[dict]):
    if not rows:
        return dbc.Alert("No hay unidades para los filtros seleccionados.", color="info")
    columns = [
        {'name': 'Unidad', 'id': 'unit'},
        {'name': 'Modelo', 'id': 'model'},
        {'name': 'Estado', 'id': 'overall_status'},
        {'name': 'Sistemas afectados', 'id': 'systems_in_alert', 'type': 'numeric'},
        {'name': 'Sistema principal', 'id': 'top_system'},
        {'name': 'Señal principal', 'id': 'top_signal_display'},
        {'name': 'Urgencia', 'id': 'urgency_display'},
        {'name': 'Acción recomendada', 'id': 'recommended_action'},
        {'name': 'top_system_raw', 'id': 'top_system_raw'},
        {'name': 'top_signal', 'id': 'top_signal'},
    ]
    data = []
    for row in rows:
        item = dict(row)
        item['urgency_display'] = format_urgency(item.get('urgency'))
        item['recommended_action'] = item.get('recommended_action') or '-'
        data.append(item)
    return dash_table.DataTable(
        id='telemetry-fleet-priority-table',
        columns=columns,
        data=data,
        row_selectable='single',
        selected_rows=[],
        sort_action='native',
        filter_action='native',
        page_size=12,
        tooltip_data=[
            {'recommended_action': {'value': row.get('recommended_action') or '', 'type': 'markdown'}}
            for row in data
        ],
        tooltip_duration=None,
        style_table={'overflowX': 'auto'},
        style_header={'backgroundColor': '#2c3e50', 'color': 'white', 'fontWeight': 'bold', 'textAlign': 'center'},
        style_cell={'padding': '8px', 'fontSize': '12px', 'whiteSpace': 'normal', 'height': 'auto', 'textAlign': 'center'},
        style_cell_conditional=[
            {'if': {'column_id': 'unit'}, 'textAlign': 'left', 'fontWeight': '600'},
            {'if': {'column_id': 'top_system'}, 'textAlign': 'left'},
            {'if': {'column_id': 'top_signal_display'}, 'textAlign': 'left'},
            {'if': {'column_id': 'recommended_action'}, 'textAlign': 'left', 'minWidth': '260px', 'maxWidth': '420px'},
            {'if': {'column_id': 'top_system_raw'}, 'display': 'none'},
            {'if': {'column_id': 'top_signal'}, 'display': 'none'},
        ],
        style_data_conditional=[
            {'if': {'filter_query': '{overall_status} = "Anormal"'}, 'backgroundColor': 'rgba(231, 76, 60, .12)', 'color': '#b02a37', 'fontWeight': 'bold'},
            {'if': {'filter_query': '{overall_status} = "Alerta"'}, 'backgroundColor': 'rgba(243, 156, 18, .12)', 'color': '#856404', 'fontWeight': 'bold'},
            {'if': {'filter_query': '{overall_status} = "InsufficientData"'}, 'backgroundColor': 'rgba(149, 165, 166, .15)', 'color': '#657174'},
            {'if': {'filter_query': '{overall_status} = "Normal"', 'column_id': 'overall_status'}, 'color': '#198754'},
        ],
    )


@callback(
    [
        Output('telemetry-fleet-kpi-row', 'children'),
        Output('telemetry-fleet-heatmap', 'figure'),
        Output('telemetry-fleet-heatmap-insights', 'children'),
        Output('telemetry-fleet-ai-table', 'children'),
    ],
    [
        Input('telemetry-health-tabs', 'value'),
        Input('client-selector', 'value'),
        Input('telemetry-fleet-model-filter', 'value'),
        Input('telemetry-fleet-status-filter', 'value'),
        Input('telemetry-fleet-system-filter', 'value'),
    ],
)
def update_fleet_overview(active_tab, client, model, statuses, systems):
    if active_tab != 'fleet-overview' or not client:
        raise PreventUpdate
    try:
        snapshot = load_telemetry_snapshot(client)
        if model and model not in set(snapshot.equipment_models.values()):
            model = None
        valid_systems = set(snapshot.system_health.get('system', pd.Series(dtype=str)).map(lambda x: {
            'Engine': 'Motor', 'Transmission': 'Transmisión', 'Brakes': 'Frenos', 'Steering': 'Dirección'
        }.get(x, x)).dropna())
        systems = [system for system in (systems or []) if system in valid_systems]
        unit_health, system_health = filter_fleet_snapshot(snapshot, model, statuses, systems)
        if unit_health.empty:
            empty = dbc.Alert("No hay unidades para los filtros seleccionados.", color="info")
            return empty, {}, html.Div(), empty

        counts = unit_health.get('overall_status', pd.Series(dtype=str)).value_counts()
        kpi = dbc.Row([
            _kpi_card("Total", len(unit_health), "fas fa-truck", "info", "#f0f8ff"),
            _kpi_card("Normal", int(counts.get('Normal', 0)), "fas fa-check-circle", "success", "#f0fff4"),
            _kpi_card("Alerta", int(counts.get('Alerta', 0)), "fas fa-exclamation-circle", "warning", "#fffcf0"),
            _kpi_card("Anormal", int(counts.get('Anormal', 0)), "fas fa-times-circle", "danger", "#fff5f5"),
            _kpi_card("Sin evidencia", int(counts.get('InsufficientData', 0)), "fas fa-question-circle", "secondary", "#f3f4f5"),
        ], className="g-3 mb-4 justify-content-center")

        heatmap = build_fleet_heatmap(system_health, unit_health)
        insights = build_heatmap_insights(system_health, unit_health)
        insight_row = dbc.Row([
            dbc.Col([html.Small("Unidad más riesgosa", className="text-muted d-block"), html.Strong(insights['most_risky_unit'])], className="text-center", md=4),
            dbc.Col([html.Small("Sistema con mayor riesgo", className="text-muted d-block"), html.Strong(insights['most_critical_system'])], className="text-center", md=4),
            dbc.Col([html.Small("Estado más crítico", className="text-muted d-block"), html.Strong(insights.get('most_critical_status', '-'), className="text-danger")], className="text-center", md=4),
        ], className="g-2 py-2 border rounded bg-light")
        rows = build_fleet_priority_rows(snapshot, unit_health, system_health)
        return kpi, heatmap, insight_row, _priority_table(rows)
    except Exception as exc:
        logger.exception("Error en Vista de Flota: %s", exc)
        error = dbc.Alert(f"Error cargando datos de telemetría: {exc}", color="danger")
        return error, {}, html.Div(), error


@callback(
    Output('telemetry-fleet-selected-unit', 'children'),
    [
        Input('telemetry-fleet-priority-table', 'selected_rows'),
        Input('client-selector', 'value'),
        Input('telemetry-fleet-model-filter', 'value'),
        Input('telemetry-fleet-status-filter', 'value'),
        Input('telemetry-fleet-system-filter', 'value'),
    ],
    [State('telemetry-fleet-priority-table', 'data'), State('telemetry-fleet-priority-table', 'derived_viewport_data')],
    prevent_initial_call=True,
)
def update_selected_fleet_unit(selected_rows, client, model, statuses, systems, table_data, visible_data):
    table_data = visible_data or table_data
    if not selected_rows or not table_data or not client:
        return html.Div()
    row = table_data[selected_rows[0]]
    return dbc.Card([
        dbc.CardHeader([html.I(className="fas fa-robot me-2"), f"Resumen de {row.get('unit', '-')}"]),
        dbc.CardBody([
            html.P(row.get('description') or "Sin descripción IA disponible.", className="mb-1"),
            html.P(row.get('explaining') or "", className="text-muted mb-1", style={'whiteSpace': 'pre-wrap'}),
            html.Div([
                html.I(className="fas fa-wrench me-1"),
                html.Strong("Acción: "), row.get('recommended_action') or "Sin acción recomendada disponible."
            ], className="text-primary")
        ])
    ], className="shadow-sm mb-4", style={'borderLeft': '4px solid #3498db'})


@callback(
    [
        Output('telemetry-health-tabs', 'value', allow_duplicate=True),
        Output('telemetry-navigation-state', 'data', allow_duplicate=True),
    ],
    [Input('telemetry-fleet-heatmap', 'clickData'), Input('telemetry-fleet-priority-table', 'active_cell')],
    [State('telemetry-fleet-priority-table', 'data'), State('telemetry-fleet-priority-table', 'derived_viewport_data'), State('telemetry-fleet-heatmap', 'figure')],
    prevent_initial_call=True,
)
def navigate_from_fleet(click_data, active_cell, table_data, visible_data, heatmap_figure):
    table_data = visible_data or table_data
    triggered = ctx.triggered_id
    unit = system = signal = None
    source = None
    if triggered == 'telemetry-fleet-priority-table' and active_cell and table_data:
        row = table_data[active_cell.get('row', 0)]
        unit, system, signal, source = row.get('unit'), row.get('top_system'), row.get('top_signal'), 'priority_table'
    elif triggered == 'telemetry-fleet-heatmap' and click_data and click_data.get('points'):
        point = click_data['points'][0]
        unit = point.get('y')
        system = point.get('x')
        if system == 'Estado':
            system = None
        source = 'fleet_heatmap'
    if not unit:
        raise PreventUpdate
    return 'unit-detail', {'unit': unit, 'system': system, 'signal': signal, 'source': source}


@callback(
    [Output('telemetry-detail-unit-selector', 'options'), Output('telemetry-detail-unit-selector', 'value')],
    [Input('telemetry-health-tabs', 'value'), Input('client-selector', 'value'), Input('telemetry-navigation-state', 'data')],
    State('telemetry-detail-unit-selector', 'value'),
)
def populate_unit_selector(active_tab, client, navigation_state, current_value):
    if active_tab != 'unit-detail' or not client:
        raise PreventUpdate
    snapshot = load_telemetry_snapshot(client)
    unit_health = snapshot.unit_health
    if unit_health.empty or 'unit' not in unit_health.columns:
        return [], None
    ordered = unit_health.sort_values('priority_score', ascending=False, na_position='last')
    options = [{'label': row['unit'], 'value': row['unit']} for _, row in ordered.iterrows()]
    requested = (navigation_state or {}).get('unit')
    if requested in [item['value'] for item in options]:
        return options, requested
    if current_value in [item['value'] for item in options]:
        return options, current_value
    return options, options[0]['value']


def _identity_display(snapshot, unit: str) -> html.Div:
    manifest = client_facing_manifest(snapshot.manifest)
    if not unit:
        return html.Div()
    return html.Div([
        html.Span(f"Unidad: {unit}", className="me-3"),
        html.Span(f"Modelo: {snapshot.equipment_models.get(unit, 'N/D')}", className="me-3"),
        html.Span(f"Evaluación: semana {manifest.get('evaluation_week', '?')}/{manifest.get('evaluation_year', '?')}", className="me-3"),
        html.Span(f"Ejecución: {str(manifest.get('execution_timestamp', ''))[:10]}")
    ])


def _decision_summary(snapshot, unit: str, system_rows: list[dict]) -> html.Div:
    unit_row = snapshot.unit_health[snapshot.unit_health.get('unit', pd.Series(dtype=str)) == unit]
    if unit_row.empty:
        return dbc.Alert("No hay datos para la unidad seleccionada.", color="info")
    row = unit_row.iloc[0]
    top = system_rows[0] if system_rows else {}
    unit_comment = snapshot.unit_comments[snapshot.unit_comments.get('unit', pd.Series(dtype=str)) == unit] if not snapshot.unit_comments.empty else pd.DataFrame()
    comment = unit_comment.iloc[0] if not unit_comment.empty else None
    description = client_facing_text(_text_value(comment, 'description', 'comment') or _text_value(row, 'executive_summary'), snapshot.signal_registry) or 'Operando dentro de parámetros normales.'
    explaining = client_facing_text(_text_value(comment, 'explaining'), snapshot.signal_registry)
    action = client_facing_text(_text_value(comment, 'recommended_action'), snapshot.signal_registry)
    urgency = format_urgency(_text_value(comment, 'urgency'))
    status = row.get('overall_status', 'InsufficientData')
    color = {'Normal': 'success', 'Alerta': 'warning', 'Anormal': 'danger', 'InsufficientData': 'secondary'}.get(status, 'secondary')
    title = "Por qué está en alerta" if status in {'Alerta', 'Anormal'} else "Resumen de la unidad"
    return dbc.Card([
        dbc.CardHeader([html.I(className="fas fa-bullseye me-2"), title]),
        dbc.CardBody([
            dbc.Row([
                dbc.Col([html.Small("Estado", className="text-muted d-block"), dbc.Badge(status, color=color, pill=True)], md=2),
                dbc.Col([html.Small("Sistemas afectados", className="text-muted d-block"), html.Strong(str(int(row.get('n_anormal_systems', 0) or 0) + int(row.get('n_alerta_systems', 0) or 0)))], md=2),
                dbc.Col([html.Small("Sistema principal", className="text-muted d-block"), html.Strong(top.get('system', '-'))], md=3),
                dbc.Col([html.Small("Señal principal", className="text-muted d-block"), html.Strong(top.get('top_signal_display', '-'))], md=3),
                dbc.Col([html.Small("Urgencia", className="text-muted d-block"), html.Strong(urgency)], md=2),
            ], className="mb-3"),
            html.Strong(description, className="d-block"),
            html.P(explaining or top.get('explaining') or top.get('description') or "", className="text-muted mb-1", style={'whiteSpace': 'pre-wrap'}),
            html.Div([html.I(className="fas fa-wrench me-1"), html.Strong("Acción: "), action or top.get('recommended_action') or "Sin acción recomendada disponible."], className="text-primary")
        ])
    ], className="shadow-sm mb-4", style={'borderLeft': f"4px solid {STATUS_COLORS.get(status, '#95a5a6')}"})


def _system_analysis_card(system_row: dict | None) -> html.Div:
    """Render the materialized system-level IA explanation before signals."""
    if not system_row:
        return dbc.Alert("No hay un sistema seleccionado para mostrar su evaluación.", color="info")
    status = system_row.get('system_status', 'InsufficientData')
    color = {'Normal': 'success', 'Alerta': 'warning', 'Anormal': 'danger', 'InsufficientData': 'secondary'}.get(status, 'secondary')
    description = system_row.get('description') or "Sin evaluación IA disponible para este sistema."
    explaining = system_row.get('explaining') or ""
    action = system_row.get('recommended_action') or "Sin acción recomendada disponible."
    return dbc.Card([
        dbc.CardBody([
            dbc.Row([
                dbc.Col([html.Small("Sistema", className="text-muted d-block"), html.Strong(system_row.get('system', '-'))], md=3),
                dbc.Col([html.Small("Estado", className="text-muted d-block"), dbc.Badge(status, color=color, pill=True)], md=2),
                dbc.Col([html.Small("Señales con hallazgo", className="text-muted d-block"), html.Strong(str(system_row.get('signals_in_alert', 0)))], md=2),
                dbc.Col([html.Small("Señal principal", className="text-muted d-block"), html.Strong(system_row.get('top_signal_display', '-'))], md=5),
            ], className="mb-3"),
            html.Strong(description, className="d-block"),
            html.P(explaining, className="text-muted mb-2", style={'whiteSpace': 'pre-wrap'}) if explaining else html.Span(),
            html.Div([html.I(className="fas fa-wrench me-1"), html.Strong("Acción: "), action], className="text-primary"),
        ])
    ], className="shadow-sm mb-4", style={'borderLeft': f"4px solid {STATUS_COLORS.get(status, '#95a5a6')}"})


def _text_value(row, *fields):
    if row is None:
        return None
    for field in fields:
        try:
            value = row.get(field, '')
        except AttributeError:
            value = ''
        if value is not None and not pd.isna(value) and str(value).strip():
            return str(value)
    return None


@callback(
    [
        Output('telemetry-detail-ai-comment', 'children'),
        Output('telemetry-detail-identity-display', 'children'),
        Output('telemetry-detail-system-table', 'data'),
        Output('telemetry-detail-system-selector', 'options'),
        Output('telemetry-detail-system-selector', 'value'),
        Output('telemetry-detail-system-analysis', 'children'),
    ],
    [Input('telemetry-detail-unit-selector', 'value'), Input('client-selector', 'value')],
    State('telemetry-navigation-state', 'data'),
)
def update_unit_detail_header(unit, client, navigation_state):
    if not unit or not client:
        raise PreventUpdate
    try:
        snapshot = load_telemetry_snapshot(client)
        system_rows = build_system_rows(snapshot, unit)
        options = [{'label': row['system'], 'value': row['system']} for row in system_rows]
        requested_system = (navigation_state or {}).get('system') if (navigation_state or {}).get('unit') == unit else None
        selected_system = requested_system if requested_system in [item['value'] for item in options] else (options[0]['value'] if options else None)
        selected_row = next((item for item in system_rows if item.get('system') == selected_system), None)
        return _decision_summary(snapshot, unit, system_rows), _identity_display(snapshot, unit), system_rows, options, selected_system, _system_analysis_card(selected_row)
    except Exception as exc:
        logger.exception("Error actualizando detalle de unidad: %s", exc)
        return dbc.Alert(f"Error cargando la unidad: {exc}", color="danger"), html.Div(), [], [], None, html.Div()


@callback(
    [
        Output('telemetry-detail-ai-comment', 'children', allow_duplicate=True),
        Output('telemetry-detail-system-analysis', 'children', allow_duplicate=True),
    ],
    [Input('telemetry-detail-system-selector', 'value'), Input('telemetry-detail-unit-selector', 'value'), Input('client-selector', 'value')],
    prevent_initial_call=True,
)
def update_selected_system_summary(system, unit, client):
    """Refresh the decision block when the user changes the selected system."""
    if not unit or not system or not client:
        raise PreventUpdate
    snapshot = load_telemetry_snapshot(client)
    rows = build_system_rows(snapshot, unit)
    selected = [row for row in rows if row.get('system') == system]
    remainder = [row for row in rows if row.get('system') != system]
    selected_row = selected[0] if selected else None
    return _decision_summary(snapshot, unit, selected + remainder), _system_analysis_card(selected_row)


@callback(
    Output('telemetry-detail-system-selector', 'value', allow_duplicate=True),
    Input('telemetry-detail-system-table', 'selected_rows'),
    State('telemetry-detail-system-table', 'data'),
    prevent_initial_call=True,
)
def sync_system_table_selection(selected_rows, table_data):
    if not selected_rows or not table_data:
        raise PreventUpdate
    return table_data[selected_rows[0]].get('system')


@callback(
    [
        Output('telemetry-detail-signal-table', 'data'),
        Output('telemetry-detail-signal-table', 'selected_rows'),
        Output('telemetry-detail-signal-selector', 'options'),
        Output('telemetry-detail-signal-selector', 'value'),
    ],
    [Input('telemetry-detail-system-selector', 'value'), Input('telemetry-detail-unit-selector', 'value'), Input('client-selector', 'value')],
    State('telemetry-navigation-state', 'data'),
)
def update_signal_section(system, unit, client, navigation_state):
    if not unit or not system or not client:
        raise PreventUpdate
    try:
        snapshot = load_telemetry_snapshot(client)
        rows = build_signal_rows(snapshot, unit, system)
        options = [{'label': f"{row['signal']} ({row['status']})", 'value': row['signal_raw']} for row in rows]
        requested = (navigation_state or {}).get('signal') if (navigation_state or {}).get('unit') == unit else None
        selected = requested if requested in [item['value'] for item in options] else (options[0]['value'] if options else None)
        selected_rows = [next((idx for idx, row in enumerate(rows) if row['signal_raw'] == selected), 0)] if rows else []
        return rows, selected_rows, options, selected
    except Exception as exc:
        logger.exception("Error actualizando señales: %s", exc)
        return [], [], [], None


@callback(
    Output('telemetry-detail-signal-selector', 'value', allow_duplicate=True),
    Input('telemetry-detail-signal-table', 'selected_rows'),
    State('telemetry-detail-signal-table', 'data'),
    prevent_initial_call=True,
)
def sync_signal_table_selection(selected_rows, table_data):
    if not selected_rows or not table_data:
        raise PreventUpdate
    return table_data[selected_rows[0]].get('signal_raw')


@lru_cache(maxsize=64)
def _load_recent_telemetry_cached(client: str, unit: str, cache_key: str, weeks: int = 8) -> pd.DataFrame:
    snapshot = load_telemetry_snapshot(client)
    manifest = snapshot.manifest
    anchor_year = int(manifest.get('evaluation_year', datetime.now().isocalendar()[0]))
    anchor_week = int(manifest.get('evaluation_week', datetime.now().isocalendar()[1]))
    available_weeks = manifest.get('silver_weeks_available', [])
    frames = []
    if available_weeks:
        candidates = sorted({int(w) for w in available_weeks}, reverse=True)[:weeks]
    else:
        anchor_date = date.fromisocalendar(anchor_year, anchor_week, 1)
        candidates = [(anchor_date - timedelta(weeks=i)).isocalendar()[1] for i in range(weeks + 4)]
    for week in candidates:
        frame = load_silver_telemetry_week(client, int(week), anchor_year)
        if not frame.empty and 'Unit' in frame.columns:
            frame = frame[frame['Unit'] == unit]
            if not frame.empty:
                frames.append(frame)
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    return combined.sort_values('Fecha') if 'Fecha' in combined.columns else combined


def _signal_kpi_table(row: dict) -> html.Table:
    values = [
        ("Total eventos", row.get('total_events', 0)),
        ("Warnings", row.get('warnings', 0)),
        ("Episodio máximo", f"{row.get('longest_episode', 0)} min"),
        ("Tendencia", row.get('trend_detected', 'No')),
        ("Dirección de tendencia", row.get('trend_direction', '-')),
        ("Fórmula", row.get('trend_formula', '-')),
        ("Fuera de rango", f"{row.get('abnormal_pct', 0):.2f}%"),
    ]
    return html.Table([
        html.Tbody([html.Tr([html.Td(label, className="fw-bold"), html.Td(str(value), className="text-end")]) for label, value in values])
    ], className="table table-sm table-borderless")


@callback(
    Output('telemetry-detail-signal-cards', 'children'),
    [Input('telemetry-detail-signal-selector', 'value'), Input('telemetry-detail-system-selector', 'value'), Input('telemetry-detail-unit-selector', 'value'), Input('client-selector', 'value')],
)
def update_signal_cards(signal, system, unit, client):
    if not signal or not system or not unit or not client:
        return dbc.Alert("Seleccione una unidad, sistema y señal para ver evidencia.", color="info")
    try:
        snapshot = load_telemetry_snapshot(client)
        rows = build_signal_rows(snapshot, unit, system)
        row = next((item for item in rows if item['signal_raw'] == signal), None)
        if row is None:
            return dbc.Alert("No hay evidencia para la señal seleccionada.", color="info")
        raw = _load_recent_telemetry_cached(client.lower(), unit, snapshot.cache_key)
        trend_df = snapshot.trends[(snapshot.trends.get('unit', pd.Series(dtype=str)) == unit) & (snapshot.trends.get('signal', pd.Series(dtype=str)) == signal)] if not snapshot.trends.empty else pd.DataFrame()
        event_signal_col = 'signal' if 'signal' in snapshot.events.columns else 'feature'
        event_df = snapshot.events[
            (snapshot.events.get('unit', pd.Series(dtype=str)) == unit)
            & (snapshot.events.get(event_signal_col, pd.Series(dtype=str)) == signal)
        ] if not snapshot.events.empty else pd.DataFrame()
        figure = build_signal_timeseries_card(signal, raw, snapshot.limits, trend_df, unit, event_df)
        metadata = snapshot.signal_metadata.get(signal, {})
        status_color = {'Normal': 'success', 'Alerta': 'warning', 'Anormal': 'danger', 'InsufficientData': 'secondary'}.get(row['status'], 'secondary')
        card = dbc.Card([
            dbc.CardHeader([
                    html.Strong(row['signal']),
                    dbc.Badge(row['status'], color=status_color, pill=True, className="ms-2")
                ], className="bg-light"),
                dbc.CardBody([
                    dbc.Row([
                        dbc.Col([
                        html.Div([html.Small("Nombre técnico", className="text-muted d-block"), html.Strong(row.get('signal_raw', '-') or '-')], className="mb-2"),
                        html.Div([html.Small("Unidad de medida", className="text-muted d-block"), html.Strong(metadata.get('unit', '-') or '-')], className="mb-2"),
                        html.Div([html.Small("Diagnóstico IA", className="text-muted d-block"), html.Strong(row.get('description', ''))], className="mb-1"),
                        html.P(row.get('explaining') or "", className="text-muted", style={'whiteSpace': 'pre-wrap'}),
                        _signal_kpi_table(row),
                    ], lg=4),
                    dbc.Col([dcc.Graph(figure=figure, config={'displayModeBar': False})], lg=8)
                ])
            ])
        ], className="shadow-sm mb-3", style={'borderLeft': f"4px solid {STATUS_COLORS.get(row['status'], '#95a5a6')}"})
        return card
    except Exception as exc:
        logger.exception("Error construyendo evidencia de señal: %s", exc)
        return dbc.Alert(f"Error cargando evidencia: {exc}", color="danger")
