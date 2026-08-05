"""
Stewart Limits tab callbacks for Multi-Technical-Alerts dashboard.
"""

from dash import Input, Output, State, html
from dash.exceptions import PreventUpdate
import pandas as pd
from pathlib import Path
from config.settings import get_settings
from src.utils.file_utils import safe_read_parquet
from dashboard.components.tables import create_limits_table


def register_limits_callbacks(app):
    """
    Register callbacks for Stewart Limits tab.
    
    Args:
        app: Dash application instance
    """
    
    @app.callback(
        [Output('machine-selector', 'options'),
         Output('machine-selector', 'value')],
        Input('client-selector', 'value')
    )
    def update_machine_options(client):
        """Update machine dropdown based on selected client."""
        if not client:
            return [], None
        
        settings = get_settings()
        # Load four-limit Stewart limits (LIC/LIM/LSM/LSC) for specific client from golden layer
        limits_file = settings.get_stewart_limits_four_path(client)
        
        if not limits_file.exists():
            return [], None
        
        try:
            df = safe_read_parquet(limits_file)
            
            machines = sorted(df['machine'].unique().tolist())
            options = [{'label': m, 'value': m} for m in machines]
            
            # Return options and None for value (no default selection)
            return options, None
        except Exception as e:
            print(f"Error loading machine options: {e}")
            return [], None
    
    
    @app.callback(
        [Output('component-selector', 'options'),
         Output('component-selector', 'value')],
        [Input('client-selector', 'value'),
         Input('machine-selector', 'value')]
    )
    def update_component_options(client, machine):
        """Update component dropdown based on selected client and machine."""
        if not client:
            return [], None
        
        settings = get_settings()
        # Load four-limit Stewart limits (LIC/LIM/LSM/LSC) for specific client from golden layer
        limits_file = settings.get_stewart_limits_four_path(client)
        
        if not limits_file.exists():
            return [], None
        
        try:
            df = safe_read_parquet(limits_file)
            
            if machine:
                df = df[df['machine'] == machine]
            
            components = sorted(df['component'].unique().tolist())
            options = [{'label': c, 'value': c} for c in components]
            
            # Return options and None for value (no default selection)
            return options, None
        except Exception as e:
            print(f"Error loading component options: {e}")
            return [], None
    
    
    @app.callback(
        Output('limits-table-container', 'children'),
        [Input('client-selector', 'value'),
         Input('machine-selector', 'value'),
         Input('component-selector', 'value'),
         Input('limits-search', 'value')]
    )
    def update_limits_table(client, machine, component, search_text):
        """Update limits table based on filters."""
        if not client:
            return html.Div("Please select a client to view limits", className="text-muted p-3")
        
        settings = get_settings()
        
        # Load four-limit Stewart Limits (LIC/LIM/LSM/LSC) for specific client from golden layer
        limits_file = settings.get_stewart_limits_four_path(client)
        
        if not limits_file.exists():
            return html.Div("No limits data available", className="text-warning p-3")
        
        try:
            df = safe_read_parquet(limits_file)
            
            # Filter by machine if selected
            if machine:
                df = df[df['machine'] == machine]
            
            # Filter by component if selected
            if component:
                df = df[df['component'] == component]
            
            # Search filter
            if search_text:
                df = df[df['essay'].str.contains(search_text, case=False, na=False)]
            
            if df.empty:
                return html.Div("No limits found matching the current filters", className="text-muted p-3")
            
            return create_limits_table(df)
            
        except Exception as e:
            return html.Div(f"Error loading limits: {str(e)}", className="text-danger p-3")
