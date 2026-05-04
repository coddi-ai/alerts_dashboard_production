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
    # SECTION 1: Fleet Status Overview
    # ========================================
    
    @app.callback(
        [Output('status-donut-chart', 'figure'),
         Output('machine-detail-selector', 'options'),
         Output('nav-equipment-selector', 'options')],
        [Input('client-selector', 'value')]
    )
    def update_fleet_status(client):
        """
        Update fleet status donut chart and machine options.
        
        Implements OIL-M-01, GR-02 (donut chart with total in center).
        """
        logger.info(f"Fleet status callback triggered: client={client}")
        
        if not client:
            from plotly.graph_objects import Figure
            logger.warning("No client selected")
            return Figure(), [], []
        
        settings = get_settings()
        machine_file = settings.get_machine_status_path(client.lower())
        logger.info(f"Looking for machine file at: {machine_file}")
        
        if not machine_file.exists():
            from plotly.graph_objects import Figure
            logger.error(f"Machine file not found: {machine_file}")
            return Figure(), [], []
        
        try:
            df = safe_read_parquet(machine_file)
            
            # Create donut chart (OIL-M-01, GR-02)
            donut_chart = create_machine_status_donut(df)
            
            # Machine options for selectors
            # Keep unit_id in original format (T_10, T_11, etc.) for proper matching
            machines = sorted(df['unit_id'].unique().tolist())
            machine_options = [{'label': m, 'value': m} for m in machines]
            
            return donut_chart, machine_options, machine_options
            
        except Exception as e:
            from plotly.graph_objects import Figure
            logger.error(f"Error loading fleet status: {str(e)}")
            return Figure(), [], []
    
    
    @app.callback(
        [Output('priority-table-container', 'children'),
         Output('status-filter-indicator', 'children')],
        [Input('status-donut-chart', 'clickData'),
         Input('client-selector', 'value')]
    )
    def update_priority_table(click_data, client):
        """
        Update priority table with optional filter from donut click.
        
        Implements OIL-M-01 (clickable donut segments), OIL-M-02 (diagnostic columns).
        """
        if not client:
            return "Please select a client", ""
        
        settings = get_settings()
        machine_file = settings.get_machine_status_path(client.lower())
        
        if not machine_file.exists():
            return "No hay datos de máquinas disponibles", ""
        
        try:
            df = safe_read_parquet(machine_file)
            
            # Determine status filter from donut click
            status_filter = None
            filter_indicator = ""
            
            if click_data and 'points' in click_data and len(click_data['points']) > 0:
                clicked_label = click_data['points'][0]['label']
                status_filter = clicked_label
                
                # Show removable filter indicator (OIL-M-01)
                filter_indicator = dbc.Alert([
                    html.Span(f"Filtered by: {clicked_label} ", className="fw-bold"),
                    html.Span("(Click chart again to clear)", className="text-muted small")
                ], color="info", dismissable=False, className="mb-0 py-2")
            
            # Create priority table with filter (OIL-M-02)
            priority_table = create_priority_table(df, status_filter)
            
            return priority_table, filter_indicator
            
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
            return "Ninguna máquina seleccionada", "light", "Seleccione un cliente para ver detalles de la máquina"
        
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
                return f"Machine {unit_id} selected", "warning", f"No data found for machine {unit_id}"
            
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
                    f"Selected: {unit_id}",
                    html.Span(f" ({machine_type})", className="text-muted ms-2")
                ], className="mb-2"),
                html.Div([
                    html.Span([
                        html.Strong("Components: "),
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
