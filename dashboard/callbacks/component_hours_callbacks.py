"""
Component Hours (Horómetro) callbacks for Multi-Technical-Alerts dashboard.

Handles data loading and visualization for the component hours tab.
Available for CDA and ENEX clients.
"""

from dash import Input, Output, State, html, dash_table
from dash.exceptions import PreventUpdate
import pandas as pd
import plotly.graph_objects as go
from plotly.graph_objects import Figure
from config.settings import get_settings
from src.data.loaders import load_component_hours, get_latest_component_hours
from src.utils.logger import get_logger
import dash_bootstrap_components as dbc

logger = get_logger(__name__)


def register_component_hours_callbacks(app):
    """
    Register callbacks for Component Hours (Horómetro) tab.
    
    Implements:
    - Unit selector population
    - Summary table with latest component hours
    - Component selector population
    - Time series chart of component hours evolution
    
    Args:
        app: Dash application instance
    """
    
    # ========================================
    # SECTION 1: Populate unit selector
    # ========================================
    
    @app.callback(
        Output('comp-hours-unit-selector', 'options'),
        [Input('client-selector', 'value'),
         Input('oil-internal-tabs', 'value')]
    )
    def update_comp_hours_units(client, active_tab):
        """Populate unit selector when component-hours tab is active."""
        if active_tab != 'component-hours' or not client:
            return []
        
        settings = get_settings()
        allowed = [c.upper() for c in settings.component_hours_allowed_clients]
        if client.upper() not in allowed:
            return []
        
        comp_hours_file = settings.get_component_hours_path(client.lower())
        
        if not comp_hours_file.exists():
            logger.warning(f"Component hours file not found: {comp_hours_file}")
            return []
        
        try:
            df = load_component_hours(comp_hours_file)
            if df.empty:
                return []
            
            units = sorted(df['unitId'].unique().tolist())
            return [{'label': u, 'value': u} for u in units]
            
        except Exception as e:
            logger.error(f"Error loading units for component hours: {e}")
            return []
    
    # ========================================
    # SECTION 2: Summary table + component options
    # ========================================
    
    @app.callback(
        [Output('comp-hours-summary-table', 'children'),
         Output('comp-hours-component-selector', 'options'),
         Output('comp-hours-component-selector', 'value')],
        [Input('comp-hours-unit-selector', 'value'),
         Input('client-selector', 'value')]
    )
    def update_comp_hours_summary(unit_id, client):
        """
        Update summary table and component selector when a unit is selected.
        """
        if not unit_id or not client:
            return (
                html.P("Seleccione un equipo para ver el horómetro", className="text-muted"),
                [],
                []
            )
        
        settings = get_settings()
        comp_hours_file = settings.get_component_hours_path(client.lower())
        
        if not comp_hours_file.exists():
            return (
                html.P("No hay datos de horómetro disponibles", className="text-muted"),
                [],
                []
            )
        
        try:
            df = load_component_hours(comp_hours_file)
            if df.empty:
                return (
                    html.P("Datos de horómetro vacíos", className="text-muted"),
                    [],
                    []
                )
            
            # Filter by unit
            unit_df = df[df['unitId'] == unit_id].copy()
            
            if unit_df.empty:
                return (
                    html.P(f"No hay datos de horómetro para {unit_id}", className="text-muted"),
                    [],
                    []
                )
            
            # Get latest reading per component
            idx = unit_df.groupby('componentName')['sampleDate'].idxmax()
            latest = unit_df.loc[idx].copy()
            latest = latest.sort_values('componentHours_cleaned', ascending=False)
            
            # Format for display
            latest['fecha'] = latest['sampleDate'].dt.strftime('%Y-%m-%d')
            latest['horas_original'] = latest['componentHours'].apply(
                lambda x: f"{x:,.0f}" if pd.notna(x) else '—'
            )
            latest['horas_limpio'] = latest['componentHours_cleaned'].apply(
                lambda x: f"{x:,.0f}" if pd.notna(x) else '—'
            )
            latest['componente'] = latest['componentName'].str.title()
            
            # Count total samples per component
            sample_counts = unit_df.groupby('componentName').size().reset_index(name='muestras')
            latest = latest.merge(sample_counts, on='componentName', how='left')
            
            # Create table
            table = dash_table.DataTable(
                columns=[
                    {'name': 'Componente', 'id': 'componente'},
                    {'name': 'Horómetro (hrs)', 'id': 'horas_limpio'},
                    {'name': 'Horas Original', 'id': 'horas_original'},
                    {'name': 'Última Muestra', 'id': 'fecha'},
                    {'name': 'Total Muestras', 'id': 'muestras'},
                ],
                data=latest[['componente', 'horas_limpio', 'horas_original', 'fecha', 'muestras']].to_dict('records'),
                style_table={'overflowX': 'auto'},
                style_cell={
                    'textAlign': 'left',
                    'padding': '10px',
                    'fontSize': '13px'
                },
                style_header={
                    'backgroundColor': '#17a2b8',
                    'color': 'white',
                    'fontWeight': 'bold',
                    'textAlign': 'center'
                },
                style_cell_conditional=[
                    {'if': {'column_id': 'componente'}, 'width': '25%', 'fontWeight': '500'},
                    {'if': {'column_id': 'horas_limpio'}, 'width': '20%', 'fontWeight': 'bold', 'color': '#17a2b8'},
                    {'if': {'column_id': 'horas_original'}, 'width': '20%'},
                    {'if': {'column_id': 'fecha'}, 'width': '20%'},
                    {'if': {'column_id': 'muestras'}, 'width': '15%', 'textAlign': 'center'},
                ],
                sort_action='native',
                page_size=15
            )
            
            # Component options for chart
            components = sorted(unit_df['componentName'].unique().tolist())
            comp_options = [{'label': c.title(), 'value': c} for c in components]
            
            # Pre-select all components (up to 5)
            default_selection = components[:5]
            
            return table, comp_options, default_selection
            
        except Exception as e:
            logger.exception(f"Error in component hours summary: {e}")
            return (
                html.P(f"Error: {str(e)}", className="text-danger"),
                [],
                []
            )
    
    # ========================================
    # SECTION 3: Time series chart
    # ========================================
    
    @app.callback(
        Output('comp-hours-time-series', 'figure'),
        [Input('comp-hours-component-selector', 'value'),
         Input('comp-hours-unit-selector', 'value'),
         Input('client-selector', 'value')]
    )
    def update_comp_hours_chart(components, unit_id, client):
        """
        Update time series chart of component hours evolution.
        """
        if not components or not unit_id or not client:
            return Figure()
        
        settings = get_settings()
        comp_hours_file = settings.get_component_hours_path(client.lower())
        
        if not comp_hours_file.exists():
            return Figure()
        
        try:
            df = load_component_hours(comp_hours_file)
            if df.empty:
                return Figure()
            
            # Filter by unit and selected components
            plot_df = df[(df['unitId'] == unit_id) & (df['componentName'].isin(components))].copy()
            plot_df = plot_df.sort_values('sampleDate')
            
            if plot_df.empty:
                return Figure()
            
            # Create figure
            fig = go.Figure()
            
            # Color palette
            colors = [
                '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf'
            ]
            
            for i, component in enumerate(components):
                comp_data = plot_df[plot_df['componentName'] == component]
                if comp_data.empty:
                    continue
                
                color = colors[i % len(colors)]
                
                # Cleaned hours line (solid)
                fig.add_trace(go.Scatter(
                    x=comp_data['sampleDate'],
                    y=comp_data['componentHours_cleaned'],
                    mode='lines+markers',
                    name=component.title(),
                    line=dict(color=color, width=2),
                    marker=dict(size=5),
                    hovertemplate=(
                        f'<b>{component.title()}</b><br>'
                        'Fecha: %{x|%Y-%m-%d}<br>'
                        'Horómetro: %{y:,.0f} hrs<br>'
                        '<extra></extra>'
                    )
                ))
                
                # Show original values where they differ (NaN was interpolated)
                has_original = comp_data[comp_data['componentHours'].isna()]
                if not has_original.empty:
                    fig.add_trace(go.Scatter(
                        x=has_original['sampleDate'],
                        y=has_original['componentHours_cleaned'],
                        mode='markers',
                        name=f'{component.title()} (interpolado)',
                        marker=dict(
                            color=color,
                            size=10,
                            symbol='diamond-open',
                            line=dict(width=2)
                        ),
                        hovertemplate=(
                            f'<b>{component.title()} (interpolado)</b><br>'
                            'Fecha: %{x|%Y-%m-%d}<br>'
                            'Horómetro estimado: %{y:,.0f} hrs<br>'
                            '<extra></extra>'
                        ),
                        showlegend=True
                    ))
            
            # Update layout
            fig.update_layout(
                title=f"Evolución del Horómetro — {unit_id}",
                xaxis_title="Fecha de Muestra",
                yaxis_title="Horas de Componente",
                hovermode='x unified',
                showlegend=True,
                legend=dict(
                    orientation='h',
                    yanchor='bottom',
                    y=-0.3,
                    xanchor='center',
                    x=0.5
                ),
                height=500,
                margin=dict(l=60, r=40, t=60, b=80)
            )
            
            return fig
            
        except Exception as e:
            logger.exception(f"Error creating component hours chart: {e}")
            return Figure()
