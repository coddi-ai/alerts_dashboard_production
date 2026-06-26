"""
Machines Overview tab callbacks for Multi-Technical-Alerts dashboard.

Redesigned following OIL-M-01 through OIL-M-06 requirements with improved UX.
"""

from dash import Input, Output, State, html, dcc, dash_table, ctx
from dash.exceptions import PreventUpdate
import pandas as pd
import plotly.graph_objects as go
from pathlib import Path
from config.settings import get_settings
from src.utils.file_utils import safe_read_parquet
from src.data.loaders import get_latest_component_hours
from src.utils.logger import get_logger
from dashboard.components.charts import (
    create_machine_status_donut, 
    create_component_stacked_bar_chart, 
    STATUS_COLORS
)
from dashboard.components.tables import create_priority_table, create_machine_detail_table
import dash_bootstrap_components as dbc

logger = get_logger(__name__)


def register_machines_callbacks(app):
    """
    Register callbacks for Machines Overview tab.
    
    Implements:
    - OIL-M-01: Interactive donut chart filtering priority table
    - OIL-M-02: User-facing diagnostic table columns
    - OIL-M-03: Persistent master-detail flow
    - OIL-M-04: Component evidence focused on condition
    - OIL-M-05: Quick navigation to report detail
    - OIL-M-06: Component stacked bar chart with grouping toggle
    
    Args:
        app: Dash application instance
    """
    
    # ========================================
    # SECTION 1: Fleet Status KPIs (Redesigned June 2026)
    # ========================================
    
    @app.callback(
        [Output('kpi-total-machines', 'children'),
         Output('kpi-normal-machines', 'children'),
         Output('kpi-alerta-machines', 'children'),
         Output('kpi-anormal-machines', 'children'),
         Output('machine-detail-selector', 'options'),
         Output('nav-equipment-selector', 'options')],
        [Input('client-selector', 'value')]
    )
    def update_fleet_kpis(client):
        """
        Update fleet status KPI cards and machine options.
        
        Redesigned June 2026: Replaced donut chart with KPIs for better data density.
        """
        logger.info(f"Fleet KPIs callback triggered: client={client}")
        
        if not client:
            logger.warning("No client selected")
            return "0", "0", "0", "0", [], []
        
        settings = get_settings()
        machine_file = settings.get_machine_status_path(client.lower())
        logger.info(f"Looking for machine file at: {machine_file}")
        
        if not machine_file.exists():
            logger.error(f"Machine file not found: {machine_file}")
            return "0", "0", "0", "0", [], []
        
        try:
            df = safe_read_parquet(machine_file)
            
            # Calculate status counts
            status_counts = df['overall_status'].value_counts()
            total = len(df)
            normal = status_counts.get('Normal', 0)
            alerta = status_counts.get('Alerta', 0)
            anormal = status_counts.get('Anormal', 0)
            
            # Machine options for selectors
            machines = sorted(df['unit_id'].unique().tolist())
            machine_options = [{'label': m, 'value': m} for m in machines]
            
            return str(total), str(normal), str(alerta), str(anormal), machine_options, machine_options
            
        except Exception as e:
            logger.error(f"Error loading fleet KPIs: {str(e)}")
            return "0", "0", "0", "0", [], []
    
    
    @app.callback(
        [Output('priority-table-container', 'children'),
         Output('table-filter-badge', 'children')],
        [Input('kpi-normal-card', 'n_clicks'),
         Input('kpi-alerta-card', 'n_clicks'),
         Input('kpi-anormal-card', 'n_clicks'),
         Input('client-selector', 'value')],
        prevent_initial_call=False
    )
    def update_priority_table(normal_clicks, alerta_clicks, anormal_clicks, client):
        """
        Update priority table with optional filter from KPI card clicks.
        
        Redesigned June 2026: Click on KPI cards to filter table by status.
        """
        if not client:
            return "Por favor seleccione un cliente", ""
        
        settings = get_settings()
        machine_file = settings.get_machine_status_path(client.lower())
        
        if not machine_file.exists():
            return "No hay datos de máquinas disponibles", ""
        
        try:
            df = safe_read_parquet(machine_file)
            
            # Determine status filter from clicked KPI
            status_filter = None
            filter_badge = ""
            
            triggered = ctx.triggered_id if ctx.triggered else None
            
            if triggered == 'kpi-normal-card' and normal_clicks:
                status_filter = 'Normal'
                filter_badge = dbc.Badge("Filtrado: Normal", color="success", className="ms-2")
            elif triggered == 'kpi-alerta-card' and alerta_clicks:
                status_filter = 'Alerta'
                filter_badge = dbc.Badge("Filtrado: Alerta", color="warning", className="ms-2")
            elif triggered == 'kpi-anormal-card' and anormal_clicks:
                status_filter = 'Anormal'
                filter_badge = dbc.Badge("Filtrado: Anormal", color="danger", className="ms-2")
            
            # Create priority table with filter
            priority_table = create_priority_table(df, status_filter)
            
            return priority_table, filter_badge
            
        except Exception as e:
            logger.error(f"Error updating priority table: {str(e)}")
            return f"Error: {str(e)}", ""
    
    
    # ========================================
    # SECTION 2: Machine Detail (Master-Detail)
    # ========================================
    
    @app.callback(
        [Output('machine-selection-indicator', 'children'),
         Output('machine-selection-indicator', 'color'),
         Output('machine-detail-table-container', 'children')],
        [Input('priority-table', 'selected_rows'),
         Input('machine-detail-selector', 'value'),
         Input('client-selector', 'value')],
        [State('priority-table', 'data')]
    )
    def update_machine_detail(selected_rows, manual_selection, client, table_data):
        """
        Update machine detail view with persistent selection indicator.
        
        Implements OIL-M-03 (persistent master-detail), OIL-M-04 (condition-focused).
        """
        if not client:
            return "Ninguna máquina seleccionada", "light", "Seleccione un cliente para ver los detalles de la máquina"
        
        # Determine which machine to show
        unit_id = None
        selection_source = "manual"
        
        # Priority: Table selection > Manual dropdown
        if selected_rows and len(selected_rows) > 0 and table_data:
            # Don't convert to lowercase - use the unit_id as-is from the table
            # The parquet files store unit_id as 'T_10', 'T_11', etc.
            unit_id = table_data[selected_rows[0]]['unit_id']
            selection_source = "table"
        elif manual_selection:
            unit_id = manual_selection
            selection_source = "dropdown"
        
        if not unit_id:
            return "Ninguna máquina seleccionada", "light", "Seleccione una máquina de la tabla de prioridad o del menú desplegable"
        
        # Load data
        settings = get_settings()
        reports_file = settings.get_classified_reports_path(client.lower())
        
        logger.info(f"Looking for unit_id: {unit_id} in classified reports")
        
        if not reports_file.exists():
            return "Ninguna máquina seleccionada", "light", "No hay datos de reportes disponibles"
        
        try:
            df = safe_read_parquet(reports_file)
            machine_df = df[df['unitId'] == unit_id].copy()
            
            if machine_df.empty:
                logger.warning(f"No data found for unit_id: {unit_id}")
                return f"Máquina {unit_id} seleccionada", "warning", f"No se encontraron datos para la máquina {unit_id}"
            
            # Get latest sample for each component
            latest_samples = machine_df.loc[machine_df.groupby('componentName')['sampleDate'].idxmax()]
            
            # Add breached_essays and ai_recommendation columns if needed
            display_df = latest_samples[['componentName', 'report_status', 'severity_score', 
                                          'essays_broken', 'sampleDate']].copy()
            
            # Add additional columns if available
            if 'breached_essays' in latest_samples.columns:
                display_df['breached_essays'] = latest_samples['breached_essays']
            if 'ai_recommendation' in latest_samples.columns:
                display_df['ai_recommendation'] = latest_samples['ai_recommendation']
            
            # Merge component hours (horómetro) if available for this client
            comp_hours_allowed = [c.upper() for c in settings.component_hours_allowed_clients]
            if client.upper() in comp_hours_allowed:
                comp_hours_file = settings.get_component_hours_path(client.lower())
                if comp_hours_file.exists():
                    try:
                        latest_hours = get_latest_component_hours(comp_hours_file)
                        if not latest_hours.empty:
                            unit_hours = latest_hours[latest_hours['unitId'] == unit_id][['componentName', 'componentHours_cleaned']].copy()
                            if not unit_hours.empty:
                                display_df = display_df.merge(
                                    unit_hours, on='componentName', how='left'
                                )
                                logger.info(f"Merged {len(unit_hours)} component hours for {unit_id}")
                    except Exception as e:
                        logger.warning(f"Could not load component hours: {e}")
            
            # Format date
            display_df['sampleDate'] = pd.to_datetime(display_df['sampleDate']).dt.strftime('%Y-%m-%d')
            
            # Create persistent selection indicator (OIL-M-03)
            machine_info = machine_df.iloc[0]
            machine_type = str(machine_info.get('machineName', 'N/A')).title()
            
            # Count critical components
            anormal_count = (display_df['report_status'] == 'Anormal').sum()
            alerta_count = (display_df['report_status'] == 'Alerta').sum()
            normal_count = (display_df['report_status'] == 'Normal').sum()
            
            indicator = html.Div([
                html.H5([
                    html.Span("📍 ", style={'fontSize': '1.2em'}),
                    f"Seleccionada: {unit_id}",
                    html.Span(f" ({machine_type})", className="text-muted ms-2")
                ], className="mb-2"),
                html.Div([
                    html.Span([
                        html.Strong("Componentes: "),
                        f"{len(display_df)} total"
                    ], className="me-3"),
                    html.Span([
                        html.Span(f"🟢 {normal_count} Normal", className="me-2"),
                        html.Span(f"🟡 {alerta_count} Alerta", className="me-2"),
                        html.Span(f"🔴 {anormal_count} Anormal", className="me-2")
                    ])
                ], className="small")
            ])
            
            # Create component detail table (OIL-M-04)
            table = create_machine_detail_table(display_df)
            
            return indicator, "info", table
            
        except Exception as e:
            logger.error(f"Error updating machine detail for {unit_id}: {str(e)}")
            return f"Error al cargar máquina {unit_id}", "danger", f"Error: {str(e)}"
    
    
    # ========================================
    # SECTION 4: Component Distribution Chart
    # ========================================
    
    @app.callback(
        Output('component-grouping-state', 'data'),
        [Input('toggle-component-grouping', 'n_clicks')],
        [State('component-grouping-state', 'data')],
        prevent_initial_call=True
    )
    def toggle_component_grouping(n_clicks, current_state):
        """
        Toggle between original and normalized component grouping (OIL-M-06).
        """
        if n_clicks:
            return {'use_normalized': not current_state.get('use_normalized', False)}
        return current_state
    
    
    @app.callback(
        [Output('component-stacked-bar-chart', 'figure'),
         Output('component-grouping-indicator', 'children')],
        [Input('component-grouping-state', 'data'),
         Input('client-selector', 'value')]
    )
    def update_component_distribution(grouping_state, client):
        """
        Update component status stacked bar chart (OIL-M-06).
        
        Replaces donut with scalable horizontal stacked bar chart.
        Toggle between original component names and normalized (grouped) names.
        """
        if not client:
            from plotly.graph_objects import Figure
            return Figure(), ""
        
        settings = get_settings()
        reports_file = settings.get_classified_reports_path(client.lower())
        
        if not reports_file.exists():
            from plotly.graph_objects import Figure
            return Figure(), ""
        
        try:
            df = safe_read_parquet(reports_file)
            
            use_normalized = grouping_state.get('use_normalized', False)
            
            # Create stacked bar chart (OIL-M-06)
            chart = create_component_stacked_bar_chart(df, use_normalized)
            
            # Indicator text
            if use_normalized:
                indicator_text = "📊 Showing grouped components (using componentNameNormalized)"
            else:
                indicator_text = "📊 Showing original component granularity"
            
            return chart, indicator_text
            
        except Exception as e:
            logger.error(f"Error updating component distribution: {str(e)}")
            from plotly.graph_objects import Figure
            return Figure(), f"Error: {str(e)}"
    
    
    # ========================================
    # SECTION 3: Quick Navigation
    # ========================================
    
    @app.callback(
        [Output('nav-component-selector', 'options'),
         Output('nav-component-selector', 'disabled'),
         Output('nav-to-report-button', 'disabled')],
        [Input('nav-equipment-selector', 'value'),
         Input('client-selector', 'value')]
    )
    def update_nav_options(unit_id, client):
        """
        Update navigation dropdowns (OIL-M-05).
        """
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
            component_options = [{'label': c.title(), 'value': c} for c in components]
            
            return component_options, False, False
            
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
        """
        Navigate to Report Detail tab (OIL-M-05).
        
        Switches to the report-detail tab and pre-populates equipment and component selectors.
        """
        if not n_clicks or not equipo or not component or not client:
            raise PreventUpdate
        
        logger.info(f"Navigation requested: equipment={equipo}, component={component}, client={client}")
        
        # Fetch familia (machine type) from data
        settings = get_settings()
        reports_file = settings.get_classified_reports_path(client.lower())
        
        familia = None
        if reports_file.exists():
            try:
                df = safe_read_parquet(reports_file)
                machine_data = df[df['unitId'] == equipo]
                if not machine_data.empty:
                    familia = machine_data.iloc[0]['machineName']
                    logger.info(f"Found familia: {familia} for equipment: {equipo}")
            except Exception as e:
                logger.error(f"Error fetching familia: {str(e)}")
        
        # Create navigation state with familia, equipo, and component
        nav_state = {
            'equipo': equipo,
            'component': component
        }
        
        # Add familia if found
        if familia:
            nav_state['familia'] = familia
        
        logger.info(f"Switching to report-detail tab with navigation state: {nav_state}")
        
        # Switch to report-detail tab and set navigation state
        return 'report-detail', nav_state
