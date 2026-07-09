"""
Machines Overview callbacks — July 2026 v3.

Filter chain: Site → Fleet → Status (dynamic dependencies).
Heatmap requires fleet selection when multiple fleets exist.
Default components: all with ≥1 sample for the selected fleet.
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

_STATUS_BG = {'Normal': '#d4edda', 'Alerta': '#fff3cd', 'Anormal': '#f8d7da'}
_STATUS_FG = {'Normal': '#155724', 'Alerta': '#856404', 'Anormal': '#721c24'}
_MACHINE_STATUS_BG = {'Normal': '#28a745', 'Alerta': '#ffc107', 'Anormal': '#dc3545'}
_MACHINE_STATUS_FG = {'Normal': '#ffffff', 'Alerta': '#000000', 'Anormal': '#ffffff'}


def _infer_machine_status(row):
    vals = row.dropna().values
    if 'Anormal' in vals:
        return 'Anormal'
    if 'Alerta' in vals:
        return 'Alerta'
    return 'Normal'


def register_machines_callbacks(app):
    """Register all Fleet Overview callbacks."""

    # ========================================
    # Filter Chain: Site options (from client)
    # ========================================
    @app.callback(
        Output('fleet-site-filter', 'options'),
        [Input('client-selector', 'value')]
    )
    def populate_site_filter(client):
        if not client:
            return []
        settings = get_settings()
        path = settings.get_classified_reports_path(client.lower())
        if not path.exists():
            return []
        try:
            df = safe_read_parquet(path)
            sites = sorted(df['site'].dropna().unique().tolist())
            return [{'label': s, 'value': s} for s in sites]
        except Exception as e:
            logger.error(f"Error loading sites: {e}")
            return []

    # ========================================
    # Filter Chain: Fleet options (depends on site)
    # ========================================
    @app.callback(
        [Output('fleet-machine-type-filter', 'options'),
         Output('fleet-machine-type-filter', 'value')],
        [Input('client-selector', 'value'),
         Input('fleet-site-filter', 'value')]
    )
    def populate_fleet_filter(client, site):
        """Populate fleet options based on selected site. Auto-select if only one."""
        if not client:
            return [], None
        settings = get_settings()
        path = settings.get_classified_reports_path(client.lower())
        if not path.exists():
            return [], None
        try:
            df = safe_read_parquet(path)
            if site:
                df = df[df['site'] == site]
            fleets = sorted(df['machineName'].dropna().unique().tolist())
            options = [{'label': f.title(), 'value': f} for f in fleets]
            # Auto-select if only one fleet
            value = fleets[0] if len(fleets) == 1 else None
            return options, value
        except Exception as e:
            logger.error(f"Error loading fleets: {e}")
            return [], None

    # ========================================
    # KPIs (reactive to all filters)
    # ========================================
    @app.callback(
        [Output('kpi-total-machines', 'children'),
         Output('kpi-normal-machines', 'children'),
         Output('kpi-alerta-machines', 'children'),
         Output('kpi-anormal-machines', 'children'),
         Output('machine-detail-selector', 'options'),
         Output('nav-equipment-selector', 'options')],
        [Input('client-selector', 'value'),
         Input('fleet-site-filter', 'value'),
         Input('fleet-machine-type-filter', 'value'),
         Input('fleet-status-filter', 'value')]
    )
    def update_kpis(client, site, fleet, statuses):
        empty = ("0", "0", "0", "0", [], [])
        if not client:
            return empty
        settings = get_settings()
        path = settings.get_classified_reports_path(client.lower())
        if not path.exists():
            return empty
        try:
            df = safe_read_parquet(path)
            if site:
                df = df[df['site'] == site]
            if fleet:
                df = df[df['machineName'] == fleet]
            if df.empty:
                return empty

            df['sampleDate'] = pd.to_datetime(df['sampleDate'])
            latest = df.loc[df.groupby(['unitId', 'componentNameNormalized'])['sampleDate'].idxmax()]

            # Machine statuses
            machine_file = settings.get_machine_status_path(client.lower())
            ms_map = {}
            if machine_file.exists():
                ms_df = safe_read_parquet(machine_file)
                ms_map = dict(zip(ms_df['unit_id'], ms_df['overall_status']))

            pivot = latest.pivot_table(index='unitId', columns='componentNameNormalized',
                                       values='report_status', aggfunc='first')
            pivot['__ms__'] = pivot.index.map(lambda u: ms_map.get(u, _infer_machine_status(pivot.loc[u])))

            if statuses:
                pivot = pivot[pivot['__ms__'].isin(statuses)]

            total = len(pivot)
            sc = pivot['__ms__'].value_counts()
            machines = sorted(pivot.index.tolist())
            opts = [{'label': m, 'value': m} for m in machines]
            return (str(total), str(sc.get('Normal', 0)), str(sc.get('Alerta', 0)),
                    str(sc.get('Anormal', 0)), opts, opts)
        except Exception as e:
            logger.error(f"KPI error: {e}")
            return empty

    # ========================================
    # Component column options (depends on fleet)
    # ========================================
    @app.callback(
        [Output('fleet-component-columns-selector', 'options'),
         Output('fleet-component-columns-selector', 'value')],
        [Input('client-selector', 'value'),
         Input('fleet-site-filter', 'value'),
         Input('fleet-machine-type-filter', 'value')]
    )
    def update_component_options(client, site, fleet):
        """Component options from selected fleet. Default = all with ≥1 sample."""
        if not client or not fleet:
            return [], []
        settings = get_settings()
        path = settings.get_classified_reports_path(client.lower())
        if not path.exists():
            return [], []
        try:
            df = safe_read_parquet(path)
            if site:
                df = df[df['site'] == site]
            df = df[df['machineName'] == fleet]
            if df.empty:
                return [], []

            df['sampleDate'] = pd.to_datetime(df['sampleDate'])
            latest = df.loc[df.groupby(['unitId', 'componentNameNormalized'])['sampleDate'].idxmax()]
            comps = latest['componentNameNormalized'].value_counts()
            # All components with at least 1 sample
            all_comps = comps[comps >= 1].index.tolist()
            options = [{'label': c.title(), 'value': c} for c in all_comps]
            return options, all_comps
        except Exception as e:
            logger.error(f"Component options error: {e}")
            return [], []

    # ========================================
    # Heatmap Table (requires fleet)
    # ========================================
    @app.callback(
        [Output('fleet-heatmap-table-container', 'children'),
         Output('table-filter-badge', 'children')],
        [Input('client-selector', 'value'),
         Input('fleet-site-filter', 'value'),
         Input('fleet-machine-type-filter', 'value'),
         Input('fleet-status-filter', 'value'),
         Input('fleet-component-columns-selector', 'value')]
    )
    def update_fleet_heatmap_table(client, site, fleet, statuses, selected_components):
        if not client:
            return html.P("Seleccione un cliente", className="text-muted"), ""
        if not fleet:
            return html.P(
                "Seleccione una flota para ver el mapa de estado por componente.",
                className="text-muted text-center py-4"
            ), ""

        settings = get_settings()
        path = settings.get_classified_reports_path(client.lower())
        if not path.exists():
            return html.P("Sin datos disponibles", className="text-muted"), ""

        try:
            df = safe_read_parquet(path)
            if site:
                df = df[df['site'] == site]
            df = df[df['machineName'] == fleet]
            if df.empty:
                return html.P("Sin datos para la flota seleccionada", className="text-muted"), ""

            df['sampleDate'] = pd.to_datetime(df['sampleDate'])
            latest = df.loc[df.groupby(['unitId', 'componentNameNormalized'])['sampleDate'].idxmax()]

            machine_file = settings.get_machine_status_path(client.lower())
            ms_map = {}
            if machine_file.exists():
                ms_df = safe_read_parquet(machine_file)
                ms_map = dict(zip(ms_df['unit_id'], ms_df['overall_status']))

            pivot = latest.pivot_table(index='unitId', columns='componentNameNormalized',
                                       values='report_status', aggfunc='first')
            pivot['__machine_status__'] = pivot.index.map(
                lambda u: ms_map.get(u, _infer_machine_status(pivot.loc[u])))

            if statuses:
                pivot = pivot[pivot['__machine_status__'].isin(statuses)]
            if pivot.empty:
                return html.P("Sin datos para los filtros seleccionados", className="text-muted"), ""

            # Sort by criticality
            order = {'Anormal': 0, 'Alerta': 1, 'Normal': 2}
            pivot = pivot.assign(__s=pivot['__machine_status__'].map(order).fillna(3))
            pivot = pivot.sort_values('__s').drop('__s', axis=1)

            comp_cols = [c for c in pivot.columns if c != '__machine_status__']
            display_cols = [c for c in (selected_components or []) if c in comp_cols] or comp_cols

            # Build table
            columns = [{'name': 'Unidad', 'id': 'unit_id'}]
            for col in display_cols:
                columns.append({'name': col.title(), 'id': col})
            columns.append({'name': 'ESTADO MÁQUINA', 'id': 'machine_status'})

            records = []
            for uid in pivot.index:
                row = {'unit_id': uid}
                for col in display_cols:
                    v = pivot.loc[uid, col]
                    row[col] = v if pd.notna(v) else ''
                row['machine_status'] = pivot.loc[uid, '__machine_status__']
                records.append(row)

            style_cond = []
            for col in display_cols:
                for st, bg in _STATUS_BG.items():
                    style_cond.append({
                        'if': {'filter_query': '{' + col + '} = "' + st + '"', 'column_id': col},
                        'backgroundColor': bg, 'color': _STATUS_FG[st],
                        'fontWeight': 'bold', 'textAlign': 'center'
                    })
            for st in ['Normal', 'Alerta', 'Anormal']:
                style_cond.append({
                    'if': {'filter_query': '{machine_status} = "' + st + '"', 'column_id': 'machine_status'},
                    'backgroundColor': _MACHINE_STATUS_BG[st], 'color': _MACHINE_STATUS_FG[st],
                    'fontWeight': 'bold', 'textAlign': 'center', 'fontSize': '13px',
                    'borderLeft': '3px solid ' + _MACHINE_STATUS_BG[st],
                })

            table = dash_table.DataTable(
                id='fleet-heatmap-table', columns=columns, data=records,
                style_table={'overflowX': 'auto'},
                style_cell={'textAlign': 'center', 'padding': '6px 10px', 'fontSize': '11px',
                            'minWidth': '75px', 'whiteSpace': 'nowrap'},
                style_header={'backgroundColor': '#343a40', 'color': 'white',
                              'fontWeight': 'bold', 'textAlign': 'center', 'fontSize': '11px'},
                style_cell_conditional=[
                    {'if': {'column_id': 'unit_id'}, 'textAlign': 'left', 'fontWeight': '600', 'minWidth': '80px'},
                    {'if': {'column_id': 'machine_status'}, 'minWidth': '110px'},
                ],
                style_data_conditional=style_cond,
                row_selectable='single', selected_rows=[], sort_action='native', page_size=25
            )
            badge = dbc.Badge(f"{len(records)} máquinas", color="secondary", className="ms-2")
            return table, badge

        except Exception as e:
            logger.error(f"Heatmap table error: {e}")
            return html.P(f"Error: {str(e)}", className="text-danger"), ""

    # ========================================
    # Machine Detail
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
        if not client:
            return "Ninguna máquina seleccionada", "light", html.Div(), "Seleccione un cliente"

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
            return "Sin datos", "light", html.Div(), "No hay datos"

        try:
            df = safe_read_parquet(reports_file)
            mdf = df[df['unitId'] == unit_id].copy()
            if mdf.empty:
                return f"Máquina {unit_id}", "warning", html.Div(), f"Sin datos para {unit_id}"

            mdf['sampleDate'] = pd.to_datetime(mdf['sampleDate'])
            latest = mdf.loc[mdf.groupby('componentName')['sampleDate'].idxmax()]
            display_df = latest[['componentName', 'report_status', 'severity_score',
                                  'essays_broken', 'sampleDate']].copy()
            for col in ['breached_essays', 'ai_recommendation', 'anomalyType']:
                if col in latest.columns:
                    display_df[col] = latest[col]

            comp_hours_allowed = [c.upper() for c in settings.component_hours_allowed_clients]
            if client.upper() in comp_hours_allowed:
                chf = settings.get_component_hours_path(client.lower())
                if chf.exists():
                    try:
                        lh = get_latest_component_hours(chf)
                        if not lh.empty:
                            uh = lh[lh['unitId'] == unit_id][['componentName', 'componentHours_cleaned']].copy()
                            if not uh.empty:
                                display_df = display_df.merge(uh, on='componentName', how='left')
                    except Exception as e:
                        logger.warning(f"Component hours: {e}")

            display_df['sampleDate'] = pd.to_datetime(display_df['sampleDate']).dt.strftime('%Y-%m-%d')
            mt = str(mdf.iloc[0].get('machineName', 'N/A')).title()
            an = (display_df['report_status'] == 'Anormal').sum()
            al = (display_df['report_status'] == 'Alerta').sum()
            no = (display_df['report_status'] == 'Normal').sum()

            indicator = html.Div([
                html.Strong(f"📍 {unit_id} ({mt})", className="me-3"),
                html.Span(f"🟢{no} 🟡{al} 🔴{an}", className="small")
            ])

            rec_card = html.Div()
            if machine_file.exists():
                try:
                    ms_df = safe_read_parquet(machine_file)
                    mr = ms_df[ms_df['unit_id'] == unit_id]
                    if not mr.empty:
                        rec = mr.iloc[0].get('machine_ai_recommendation', None)
                        if rec and pd.notna(rec) and str(rec).strip():
                            rec_card = dbc.Card([
                                dbc.CardHeader("🤖 Recomendación IA", className="fw-bold bg-info text-white"),
                                dbc.CardBody(html.P(str(rec), style={
                                    'whiteSpace': 'pre-wrap', 'fontSize': '0.9rem', 'lineHeight': '1.5'}))
                            ], className="mb-3")
                except Exception as e:
                    logger.warning(f"Recommendation: {e}")

            table = create_machine_detail_table(display_df)
            return indicator, "info", rec_card, table
        except Exception as e:
            logger.error(f"Machine detail error: {e}")
            return f"Error: {unit_id}", "danger", html.Div(), str(e)

    # ========================================
    # Sync table click → selectors
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
        if not selected_rows or not table_data:
            raise PreventUpdate
        try:
            uid = table_data[selected_rows[0]]['unit_id']
            return uid, uid, {'unit_id': uid}
        except (KeyError, IndexError):
            raise PreventUpdate

    # ========================================
    # Compat: component grouping toggle
    # ========================================
    @app.callback(
        Output('component-grouping-state', 'data'),
        [Input('toggle-component-grouping', 'n_clicks')],
        [State('component-grouping-state', 'data')],
        prevent_initial_call=True
    )
    def toggle_component_grouping(n_clicks, state):
        if n_clicks:
            return {'use_normalized': not state.get('use_normalized', False)}
        return state

    # ========================================
    # Quick Navigation
    # ========================================
    @app.callback(
        [Output('nav-component-selector', 'options'),
         Output('nav-component-selector', 'disabled'),
         Output('nav-to-report-button', 'disabled')],
        [Input('nav-equipment-selector', 'value'), Input('client-selector', 'value')]
    )
    def update_nav_options(unit_id, client):
        if not unit_id or not client:
            return [], True, True
        settings = get_settings()
        path = settings.get_classified_reports_path(client.lower())
        if not path.exists():
            return [], True, True
        try:
            df = safe_read_parquet(path)
            comps = sorted(df[df['unitId'] == unit_id]['componentName'].unique().tolist())
            return [{'label': c.title(), 'value': c} for c in comps], False, False
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
        path = settings.get_classified_reports_path(client.lower())
        familia = None
        if path.exists():
            try:
                df = safe_read_parquet(path)
                md = df[df['unitId'] == equipo]
                if not md.empty:
                    familia = md.iloc[0]['machineName']
            except:
                pass
        nav = {'equipo': equipo, 'component': component}
        if familia:
            nav['familia'] = familia
        return 'report-detail', nav
