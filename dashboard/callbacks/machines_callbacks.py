"""
Machines Overview tab callbacks for Multi-Technical-Alerts dashboard.

Updated July 2026 v2:
- KPI cards reactive to filters (reflect filtered dataset)
- Selectable component columns (default: top 5 by sample count)
- Machine status visually prominent in table
- Component Distribution commented out
- Machine recommendation in detail panel only
"""

from dash import Input, Output, State, html, dcc, dash_table, ctx, no_update
from dash.exceptions import PreventUpdate
import pandas as pd
from config.settings import get_settings
from src.utils.file_utils import safe_read_parquet
from src.data.loaders import get_latest_component_hours
from src.utils.logger import get_logger
from dashboard.components.tables import create_machine_detail_table
import dash_bootstrap_components as dbc

logger = get_logger(__name__)

# Status colors
_STATUS_BG = {'Normal': '#d4edda', 'Alerta': '#fff3cd', 'Anormal': '#f8d7da'}
_STATUS_FG = {'Normal': '#155724', 'Alerta': '#856404', 'Anormal': '#721c24'}
# Machine status: stronger colors for prominence
_MACHINE_STATUS_BG = {'Normal': '#28a745', 'Alerta': '#ffc107', 'Anormal': '#dc3545'}
_MACHINE_STATUS_FG = {'Normal': '#ffffff', 'Alerta': '#000000', 'Anormal': '#ffffff'}

DEFAULT_VISIBLE_COMPONENTS = 5


def _get_filtered_data(client, machine_types, sites):
    """Load and filter classified reports. Returns (df, reports_file) or (None, None)."""
    if not client:
        return None, None
    settings = get_settings()
    reports_file = settings.get_classified_reports_path(client.lower())
    if not reports_file.exists():
        return None, None
    df = safe_read_parquet(reports_file)
    if machine_types:
        df = df[df['machineName'].isin(machine_types)]
    if sites:
        df = df[df['site'].isin(sites)]
    return df, reports_file


def _infer_machine_status(row):
    """Infer machine status from component statuses."""
    vals = row.dropna().values
    if 'Anormal' in vals:
        return 'Anormal'
    if 'Alerta' in vals:
        return 'Alerta'
    return 'Normal'


def register_machines_callbacks(app):
    """Register callbacks for Machines Overview tab."""

    # ========================================
    # SECTION 0: Fleet Filters
    # ========================================
    @app.callback(
        [Output('fleet-machine-type-filter', 'options'),
         Output('fleet-site-filter', 'options')],
        [Input('client-selector', 'value')]
    )
    def populate_fleet_filters(client):
        """Populate equipment type and site filter options."""
        if not client:
            return [], []
        settings = get_settings()
        reports_file = settings.get_classified_reports_path(client.lower())
        if not reports_file.exists():
            return [], []
        try:
            df = safe_read_parquet(reports_file)
            machine_types = sorted(df['machineName'].dropna().unique().tolist())
            type_options = [{'label': t.title(), 'value': t} for t in machine_types]
            sites = sorted(df['site'].dropna().unique().tolist())
            site_options = [{'label': s, 'value': s} for s in sites]
            return type_options, site_options
        except Exception as e:
            logger.error(f"Error populating fleet filters: {e}")
            return [], []

    # ========================================
    # SECTION 1: KPIs + Component Column Options (filter-reactive)
    # ========================================
    @app.callback(
        [Output('kpi-total-machines', 'children'),
         Output('kpi-normal-machines', 'children'),
         Output('kpi-alerta-machines', 'children'),
         Output('kpi-anormal-machines', 'children'),
         Output('machine-detail-selector', 'options'),
         Output('nav-equipment-selector', 'options'),
         Output('fleet-component-columns-selector', 'options'),
         Output('fleet-component-columns-selector', 'value')],
        [Input('client-selector', 'value'),
         Input('fleet-machine-type-filter', 'value'),
         Input('fleet-site-filter', 'value'),
         Input('fleet-status-filter', 'value')]
    )
    def update_kpis_and_component_options(client, machine_types, sites, statuses):
        """Update KPIs based on filters and provide component column options."""
        empty = ("0", "0", "0", "0", [], [], [], [])
        if not client:
            return empty

        df, _ = _get_filtered_data(client, machine_types, sites)
        if df is None or df.empty:
            return empty

        try:
            # Get latest sample per unit × component
            df['sampleDate'] = pd.to_datetime(df['sampleDate'])
            latest = df.loc[df.groupby(['unitId', 'componentNameNormalized'])['sampleDate'].idxmax()]

            # Machine status
            settings = get_settings()
            machine_file = settings.get_machine_status_path(client.lower())
            machine_status_map = {}
            if machine_file.exists():
                ms_df = safe_read_parquet(machine_file)
                machine_status_map = dict(zip(ms_df['unit_id'], ms_df['overall_status']))

            # Build pivot to determine machine statuses
            pivot = latest.pivot_table(
                index='unitId', columns='componentNameNormalized',
                values='report_status', aggfunc='first'
            )
            pivot['__ms__'] = pivot.index.map(
                lambda u: machine_status_map.get(u, _infer_machine_status(pivot.loc[u]))
            )

            # Apply status filter for KPIs
            if statuses:
                pivot = pivot[pivot['__ms__'].isin(statuses)]

            # KPIs
            total = len(pivot)
            status_counts = pivot['__ms__'].value_counts()
            normal = status_counts.get('Normal', 0)
            alerta = status_counts.get('Alerta', 0)
            anormal = status_counts.get('Anormal', 0)

            # Machine options
            machines = sorted(pivot.index.tolist())
            machine_options = [{'label': m, 'value': m} for m in machines]

            # Component columns: ranked by sample count in filtered data
            comp_sample_counts = latest['componentNameNormalized'].value_counts()
            all_components = comp_sample_counts.index.tolist()
            comp_options = [{'label': c.title(), 'value': c} for c in all_components]

            # Default: top 5
            default_components = all_components[:DEFAULT_VISIBLE_COMPONENTS]

            return (str(total), str(normal), str(alerta), str(anormal),
                    machine_options, machine_options, comp_options, default_components)

        except Exception as e:
            logger.error(f"Error updating KPIs: {e}")
            return empty

    # ========================================
    # SECTION 2: Unified Fleet Heatmap Table
    # ========================================
    @app.callback(
        [Output('fleet-heatmap-table-container', 'children'),
         Output('table-filter-badge', 'children')],
        [Input('client-selector', 'value'),
         Input('fleet-machine-type-filter', 'value'),
         Input('fleet-site-filter', 'value'),
         Input('fleet-status-filter', 'value'),
         Input('fleet-component-columns-selector', 'value')]
    )
    def update_fleet_heatmap_table(client, machine_types, sites, statuses, selected_components):
        """Build unified fleet table with selectable component columns."""
        if not client:
            return html.P("Seleccione un cliente", className="text-muted"), ""

        df, _ = _get_filtered_data(client, machine_types, sites)
        if df is None or df.empty:
            return html.P("Sin datos para los filtros seleccionados", className="text-muted"), ""

        try:
            settings = get_settings()
            machine_file = settings.get_machine_status_path(client.lower())

            df['sampleDate'] = pd.to_datetime(df['sampleDate'])
            latest = df.loc[df.groupby(['unitId', 'componentNameNormalized'])['sampleDate'].idxmax()]

            # Machine status
            machine_status_map = {}
            if machine_file.exists():
                ms_df = safe_read_parquet(machine_file)
                machine_status_map = dict(zip(ms_df['unit_id'], ms_df['overall_status']))

            # Pivot
            pivot = latest.pivot_table(
                index='unitId', columns='componentNameNormalized',
                values='report_status', aggfunc='first'
            )
            pivot['__machine_status__'] = pivot.index.map(
                lambda u: machine_status_map.get(u, _infer_machine_status(pivot.loc[u]))
            )

            # Status filter
            if statuses:
                pivot = pivot[pivot['__machine_status__'].isin(statuses)]
            if pivot.empty:
                return html.P("Sin datos para los filtros seleccionados", className="text-muted"), ""

            # Sort by criticality
            status_order = {'Anormal': 0, 'Alerta': 1, 'Normal': 2}
            pivot = pivot.assign(__sort=pivot['__machine_status__'].map(status_order).fillna(3))
            pivot = pivot.sort_values('__sort').drop('__sort', axis=1)

            # Select component columns
            component_cols = [c for c in pivot.columns if c != '__machine_status__']
            if selected_components:
                display_cols = [c for c in selected_components if c in component_cols]
            else:
                # Default top 5 by non-null count
                col_counts = {c: pivot[c].notna().sum() for c in component_cols}
                display_cols = sorted(col_counts, key=col_counts.get, reverse=True)[:DEFAULT_VISIBLE_COMPONENTS]

            # Build DataTable
            columns = [{'name': 'Unidad', 'id': 'unit_id'}]
            for col in display_cols:
                columns.append({'name': col.title(), 'id': col})
            columns.append({'name': 'ESTADO MÁQUINA', 'id': 'machine_status'})

            records = []
            for unit_id in pivot.index:
                row = {'unit_id': unit_id}
                for col in display_cols:
                    val = pivot.loc[unit_id, col]
                    row[col] = val if pd.notna(val) else ''
                row['machine_status'] = pivot.loc[unit_id, '__machine_status__']
                records.append(row)

            # Style conditions - component cells
            style_conditions = []
            for col in display_cols:
                for status, bg in _STATUS_BG.items():
                    style_conditions.append({
                        'if': {'filter_query': '{' + col + '} = "' + status + '"', 'column_id': col},
                        'backgroundColor': bg, 'color': _STATUS_FG[status],
                        'fontWeight': 'bold', 'textAlign': 'center'
                    })

            # Machine status: PROMINENT styling (full solid color, larger font)
            for status in ['Normal', 'Alerta', 'Anormal']:
                style_conditions.append({
                    'if': {'filter_query': '{machine_status} = "' + status + '"', 'column_id': 'machine_status'},
                    'backgroundColor': _MACHINE_STATUS_BG[status],
                    'color': _MACHINE_STATUS_FG[status],
                    'fontWeight': 'bold',
                    'textAlign': 'center',
                    'fontSize': '13px',
                    'borderLeft': '3px solid ' + _MACHINE_STATUS_BG[status],
                })

            table = dash_table.DataTable(
                id='fleet-heatmap-table',
                columns=columns,
                data=records,
                style_table={'overflowX': 'auto'},
                style_cell={
                    'textAlign': 'center', 'padding': '6px 10px',
                    'fontSize': '11px', 'minWidth': '75px', 'whiteSpace': 'nowrap'
                },
                style_header={
                    'backgroundColor': '#343a40', 'color': 'white',
                    'fontWeight': 'bold', 'textAlign': 'center', 'fontSize': '11px'
                },
                style_cell_conditional=[
                    {'if': {'column_id': 'unit_id'}, 'textAlign': 'left', 'fontWeight': '600', 'minWidth': '80px'},
                    {'if': {'column_id': 'machine_status'}, 'minWidth': '110px', 'fontWeight': 'bold'},
                ],
                style_data_conditional=style_conditions,
                row_selectable='single',
                selected_rows=[],
                sort_action='native',
                page_size=25
            )

            badge = dbc.Badge(f"{len(records)} máquinas", color="secondary", className="ms-2")
            return table, badge

        except Exception as e:
            logger.error(f"Error building fleet table: {e}")
            return html.P(f"Error: {str(e)}", className="text-danger"), ""

    # ========================================
    # SECTION 3: Machine Detail
    # ========================================
    @app.callback(
        [Output('machine-selection-indicator', 'children'),
         Output('machine-selection-indicator', 'color'),
         Output('machine-recommendation-container', 'children'),
         Output('machine-detail-table-container', 'children')],
        [Input('fleet-heatmap-table', 'selected_rows'),
         Input('machine-detail-selector', 'value'),
         Input('client-selector', 'value')],
        [State('fleet-heatmap-table', 'data')]
    )
    def update_machine_detail(selected_rows, manual_selection, client, table_data):
        """Update machine detail view."""
        if not client:
            return "Ninguna máquina seleccionada", "light", html.Div(), \
                   "Seleccione un cliente"

        unit_id = None
        if selected_rows and len(selected_rows) > 0 and table_data:
            unit_id = table_data[selected_rows[0]]['unit_id']
        elif manual_selection:
            unit_id = manual_selection

        if not unit_id:
            return "Ninguna máquina seleccionada", "light", html.Div(), \
                   "Seleccione una máquina de la tabla o del menú"

        settings = get_settings()
        reports_file = settings.get_classified_reports_path(client.lower())
        machine_file = settings.get_machine_status_path(client.lower())

        if not reports_file.exists():
            return "Sin datos", "light", html.Div(), "No hay datos disponibles"

        try:
            df = safe_read_parquet(reports_file)
            machine_df = df[df['unitId'] == unit_id].copy()
            if machine_df.empty:
                return f"Máquina {unit_id}", "warning", html.Div(), f"Sin datos para {unit_id}"

            machine_df['sampleDate'] = pd.to_datetime(machine_df['sampleDate'])
            latest_samples = machine_df.loc[machine_df.groupby('componentName')['sampleDate'].idxmax()]

            display_df = latest_samples[['componentName', 'report_status', 'severity_score',
                                          'essays_broken', 'sampleDate']].copy()
            for col in ['breached_essays', 'ai_recommendation', 'anomalyType']:
                if col in latest_samples.columns:
                    display_df[col] = latest_samples[col]

            # Component hours
            comp_hours_allowed = [c.upper() for c in settings.component_hours_allowed_clients]
            if client.upper() in comp_hours_allowed:
                comp_hours_file = settings.get_component_hours_path(client.lower())
                if comp_hours_file.exists():
                    try:
                        latest_hours = get_latest_component_hours(comp_hours_file)
                        if not latest_hours.empty:
                            unit_hours = latest_hours[latest_hours['unitId'] == unit_id][
                                ['componentName', 'componentHours_cleaned']].copy()
                            if not unit_hours.empty:
                                display_df = display_df.merge(unit_hours, on='componentName', how='left')
                    except Exception as e:
                        logger.warning(f"Could not load component hours: {e}")

            display_df['sampleDate'] = pd.to_datetime(display_df['sampleDate']).dt.strftime('%Y-%m-%d')

            machine_type = str(machine_df.iloc[0].get('machineName', 'N/A')).title()
            anormal_count = (display_df['report_status'] == 'Anormal').sum()
            alerta_count = (display_df['report_status'] == 'Alerta').sum()
            normal_count = (display_df['report_status'] == 'Normal').sum()

            indicator = html.Div([
                html.Strong(f"📍 {unit_id} ({machine_type})", className="me-3"),
                html.Span(f"🟢{normal_count} 🟡{alerta_count} 🔴{anormal_count}", className="small")
            ])

            # Machine recommendation
            recommendation_card = html.Div()
            if machine_file.exists():
                try:
                    ms_df = safe_read_parquet(machine_file)
                    machine_row = ms_df[ms_df['unit_id'] == unit_id]
                    if not machine_row.empty:
                        rec = machine_row.iloc[0].get('machine_ai_recommendation', None)
                        if rec and pd.notna(rec) and str(rec).strip():
                            recommendation_card = dbc.Card([
                                dbc.CardHeader("🤖 Recomendación IA", className="fw-bold bg-info text-white"),
                                dbc.CardBody(html.P(str(rec), style={
                                    'whiteSpace': 'pre-wrap', 'fontSize': '0.9rem', 'lineHeight': '1.5'
                                }))
                            ], className="mb-3")
                except Exception as e:
                    logger.warning(f"Could not load recommendation: {e}")

            table = create_machine_detail_table(display_df)
            return indicator, "info", recommendation_card, table

        except Exception as e:
            logger.error(f"Error in machine detail: {e}")
            return f"Error: {unit_id}", "danger", html.Div(), str(e)

    # ========================================
    # SECTION 3b: Sync table click to selectors
    # ========================================
    @app.callback(
        [Output('machine-detail-selector', 'value'),
         Output('nav-equipment-selector', 'value'),
         Output('heatmap-click-data', 'data')],
        [Input('fleet-heatmap-table', 'selected_rows')],
        [State('fleet-heatmap-table', 'data')],
        prevent_initial_call=True
    )
    def handle_table_row_click(selected_rows, table_data):
        """Sync table row selection to detail and nav selectors."""
        if not selected_rows or not table_data:
            raise PreventUpdate
        try:
            unit_id = table_data[selected_rows[0]]['unit_id']
            return unit_id, unit_id, {'unit_id': unit_id}
        except (KeyError, IndexError):
            raise PreventUpdate

    # ========================================
    # SECTION 4: Component Distribution (kept for compat)
    # ========================================
    @app.callback(
        Output('component-grouping-state', 'data'),
        [Input('toggle-component-grouping', 'n_clicks')],
        [State('component-grouping-state', 'data')],
        prevent_initial_call=True
    )
    def toggle_component_grouping(n_clicks, current_state):
        if n_clicks:
            return {'use_normalized': not current_state.get('use_normalized', False)}
        return current_state

    # ========================================
    # SECTION 5: Quick Navigation
    # ========================================
    @app.callback(
        [Output('nav-component-selector', 'options'),
         Output('nav-component-selector', 'disabled'),
         Output('nav-to-report-button', 'disabled')],
        [Input('nav-equipment-selector', 'value'),
         Input('client-selector', 'value')]
    )
    def update_nav_options(unit_id, client):
        if not unit_id or not client:
            return [], True, True
        settings = get_settings()
        reports_file = settings.get_classified_reports_path(client.lower())
        if not reports_file.exists():
            return [], True, True
        try:
            df = safe_read_parquet(reports_file)
            df = df[df['unitId'] == unit_id]
            components = sorted(df['componentName'].unique().tolist())
            return [{'label': c.title(), 'value': c} for c in components], False, False
        except:
            return [], True, True

    @app.callback(
        [Output('oil-internal-tabs', 'value'),
         Output('navigation-state', 'data', allow_duplicate=True)],
        [Input('nav-to-report-button', 'n_clicks')],
        [State('nav-equipment-selector', 'value'),
         State('nav-component-selector', 'value'),
         State('client-selector', 'value')],
        prevent_initial_call=True
    )
    def navigate_to_report_detail(n_clicks, equipo, component, client):
        if not n_clicks or not equipo or not component or not client:
            raise PreventUpdate
        settings = get_settings()
        reports_file = settings.get_classified_reports_path(client.lower())
        familia = None
        if reports_file.exists():
            try:
                df = safe_read_parquet(reports_file)
                machine_data = df[df['unitId'] == equipo]
                if not machine_data.empty:
                    familia = machine_data.iloc[0]['machineName']
            except Exception as e:
                logger.error(f"Error fetching familia: {e}")
        nav_state = {'equipo': equipo, 'component': component}
        if familia:
            nav_state['familia'] = familia
        return 'report-detail', nav_state
