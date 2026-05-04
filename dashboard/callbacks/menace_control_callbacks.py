"""
Callbacks for Menace Control Tab.

Handles data processing and visualization for equipment criticality monitoring.
"""

import pandas as pd
import numpy as np
from dash import callback, Input, Output, html
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from datetime import datetime, timedelta

from src.data.loaders import load_alerts_data, load_oil_classified
from src.utils.logger import get_logger

logger = get_logger(__name__)


def get_equipment_status_data(df_alerts: pd.DataFrame, df_oil: pd.DataFrame, days: int = 90) -> pd.DataFrame:
    """
    Calculate equipment status based on alerts per system.
    
    Args:
        df_alerts: DataFrame with alert data
        df_oil: DataFrame with oil/tribology data
        days: Number of days to analyze
    
    Returns:
        DataFrame with columns: Equipo, Sistema1, Sistema2, ..., SistemaN, Eventos_Totales
    """
    if df_alerts.empty:
        return pd.DataFrame()
    
    # Filter by date range
    cutoff_date = datetime.now() - timedelta(days=days)
    df_recent = df_alerts[df_alerts['Timestamp'] >= cutoff_date].copy()
    
    if df_recent.empty:
        return pd.DataFrame()
    
    # Group by equipment and system
    # Use 'UnitId' or 'Unidad' for equipment, and 'sistema' for system
    equipment_col = 'UnitId' if 'UnitId' in df_recent.columns else 'Unidad'
    system_col = 'sistema' if 'sistema' in df_recent.columns else 'Sistema'
    
    # Count alerts per equipment-system combination
    alerts_by_eq_sys = df_recent.groupby([equipment_col, system_col]).size().reset_index(name='count')
    
    # Pivot to create matrix: Equipment as rows, Systems as columns
    pivot_table = alerts_by_eq_sys.pivot_table(
        index=equipment_col, 
        columns=system_col, 
        values='count', 
        fill_value=0,
        aggfunc='sum'
    )
    
    # Calculate total events per equipment
    pivot_table['Eventos_Totales'] = pivot_table.sum(axis=1)
    
    # Sort by total events (descending)
    pivot_table = pivot_table.sort_values('Eventos_Totales', ascending=False)
    
    # Reset index to make equipment a column
    pivot_table = pivot_table.reset_index()
    pivot_table.rename(columns={equipment_col: 'Equipo'}, inplace=True)
    
    return pivot_table


def get_critical_systems_data(df_alerts: pd.DataFrame, df_oil: pd.DataFrame, days: int = 90) -> pd.DataFrame:
    """
    Calculate critical systems ranking based on alert count.
    
    Args:
        df_alerts: DataFrame with alert data
        df_oil: DataFrame with oil/tribology data
        days: Number of days to analyze
    
    Returns:
        DataFrame with columns: Equipo, Sistema, Criticidad, Estado_Tribologia, Ultima_Muestra
    """
    if df_alerts.empty:
        return pd.DataFrame()
    
    # Filter by date range
    cutoff_date = datetime.now() - timedelta(days=days)
    df_recent = df_alerts[df_alerts['Timestamp'] >= cutoff_date].copy()
    
    if df_recent.empty:
        return pd.DataFrame()
    
    # Use correct column names
    equipment_col = 'UnitId' if 'UnitId' in df_recent.columns else 'Unidad'
    system_col = 'sistema' if 'sistema' in df_recent.columns else 'Sistema'
    component_col = 'componente' if 'componente' in df_recent.columns else 'Componente'
    
    # Count alerts per equipment-system
    criticality = df_recent.groupby([equipment_col, system_col]).size().reset_index(name='Criticidad')
    
    # Add component information (most common component for that system)
    component_info = df_recent.groupby([equipment_col, system_col])[component_col].agg(
        lambda x: x.value_counts().index[0] if len(x) > 0 else 'N/A'
    ).reset_index()
    component_info.rename(columns={component_col: 'Componente_Principal'}, inplace=True)
    
    # Merge criticality with component info
    criticality = criticality.merge(component_info, on=[equipment_col, system_col], how='left')
    
    # Add tribology status if available
    if not df_oil.empty:
        # Map equipment to most recent oil sample status
        oil_status_map = {}
        
        if 'unitId' in df_oil.columns and 'report_status' in df_oil.columns:
            # Get most recent oil sample per equipment
            df_oil_recent = df_oil.copy()
            if 'sampleDate' in df_oil.columns:
                df_oil_recent['sampleDate'] = pd.to_datetime(df_oil_recent['sampleDate'], errors='coerce')
                df_oil_recent = df_oil_recent.sort_values('sampleDate', ascending=False)
            
            for unit in df_oil_recent['unitId'].unique():
                unit_samples = df_oil_recent[df_oil_recent['unitId'] == unit]
                if not unit_samples.empty:
                    latest = unit_samples.iloc[0]
                    oil_status_map[unit] = {
                        'status': latest.get('report_status', 'N/A'),
                        'date': latest.get('sampleDate', 'N/A')
                    }
        
        # Add tribology info to criticality table
        criticality['Estado_Tribologia'] = criticality[equipment_col].map(
            lambda x: oil_status_map.get(x, {}).get('status', 'Sin datos')
        )
        criticality['Ultima_Muestra'] = criticality[equipment_col].map(
            lambda x: oil_status_map.get(x, {}).get('date', 'N/A')
        )
        
        # Format date
        if 'Ultima_Muestra' in criticality.columns:
            criticality['Ultima_Muestra'] = pd.to_datetime(criticality['Ultima_Muestra'], errors='coerce')
            criticality['Ultima_Muestra'] = criticality['Ultima_Muestra'].dt.strftime('%Y-%m-%d')
            criticality['Ultima_Muestra'] = criticality['Ultima_Muestra'].fillna('N/A')
    else:
        criticality['Estado_Tribologia'] = 'Sin datos'
        criticality['Ultima_Muestra'] = 'N/A'
    
    # Sort by criticality (descending)
    criticality = criticality.sort_values('Criticidad', ascending=False)
    
    # Rename columns
    criticality.rename(columns={
        equipment_col: 'Equipo',
        system_col: 'Sistema'
    }, inplace=True)
    
    return criticality


@callback(
    Output('menace-summary-cards', 'children'),
    [
        Input('menace-days-selector', 'value'),
        Input('client-selector', 'value')
    ]
)
def update_summary_cards(days, client):
    """Update summary statistics cards."""
    if not client:
        raise PreventUpdate
        
    try:
        df_alerts = load_alerts_data(client)
        df_oil = load_oil_classified(client)
        
        if df_alerts.empty:
            return dbc.Alert("No hay datos de alertas disponibles", color="warning")
        
        # Filter by date range
        cutoff_date = datetime.now() - timedelta(days=days)
        df_recent = df_alerts[df_alerts['Timestamp'] >= cutoff_date]
        
        # Calculate metrics
        total_alerts = len(df_recent)
        equipment_col = 'UnitId' if 'UnitId' in df_recent.columns else 'Unidad'
        system_col = 'sistema' if 'sistema' in df_recent.columns else 'Sistema'
        
        total_equipment = df_recent[equipment_col].nunique() if not df_recent.empty else 0
        total_systems = df_recent[system_col].nunique() if not df_recent.empty else 0
        
        # Critical equipment (top 10% by alerts)
        if not df_recent.empty:
            eq_counts = df_recent[equipment_col].value_counts()
            critical_threshold = int(len(eq_counts) * 0.1) if len(eq_counts) > 0 else 0
            critical_equipment = max(1, critical_threshold) if critical_threshold > 0 else 0
        else:
            critical_equipment = 0
        
        # Create cards
        cards = dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H3(f"{total_alerts:,}", className="text-danger mb-0"),
                        html.P("Total Alertas", className="text-muted mb-0 small")
                    ])
                ], className="text-center shadow-sm")
            ], md=3),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H3(f"{total_equipment}", className="text-warning mb-0"),
                        html.P("Equipos Monitoreados", className="text-muted mb-0 small")
                    ])
                ], className="text-center shadow-sm")
            ], md=3),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H3(f"{total_systems}", className="text-info mb-0"),
                        html.P("Sistemas Afectados", className="text-muted mb-0 small")
                    ])
                ], className="text-center shadow-sm")
            ], md=3),
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H3(f"{critical_equipment}", className="text-danger mb-0"),
                        html.P("Equipos Críticos (Top 10%)", className="text-muted mb-0 small")
                    ])
                ], className="text-center shadow-sm")
            ], md=3)
        ])
        
        return cards
        
    except Exception as e:
        logger.error(f"Error updating summary cards: {e}")
        return dbc.Alert(f"Error al cargar estadísticas: {str(e)}", color="danger")


@callback(
    Output('menace-equipment-status-table', 'children'),
    [
        Input('menace-days-selector', 'value'),
        Input('client-selector', 'value')
    ]
)
def update_equipment_status_table(days, client):
    """Update equipment status table showing alerts per system."""
    if not client:
        raise PreventUpdate
        
    try:
        df_alerts = load_alerts_data(client)
        df_oil = load_oil_classified(client)
        
        if df_alerts.empty:
            return dbc.Alert("No hay datos de alertas disponibles", color="warning")
        
        # Get equipment status data
        df_status = get_equipment_status_data(df_alerts, df_oil, days)
        
        if df_status.empty:
            return dbc.Alert(f"No hay datos de alertas en los últimos {days} días", color="info")
        
        # Create table
        # Format numbers with commas
        df_display = df_status.copy()
        
        # Apply color coding to total events
        def format_total_events(val):
            """Apply color coding based on severity."""
            if pd.isna(val) or val == 0:
                return ''
            elif val >= 50:
                return f'background-color: #ffcccc; font-weight: bold;'  # Red
            elif val >= 20:
                return f'background-color: #ffe6cc; font-weight: bold;'  # Orange
            elif val >= 10:
                return f'background-color: #ffffcc;'  # Yellow
            else:
                return ''
        
        # Create HTML table with bootstrap styling
        table_header = [html.Thead(html.Tr([html.Th(col) for col in df_display.columns]))]
        
        rows = []
        for idx, row in df_display.iterrows():
            cells = []
            for i, col in enumerate(df_display.columns):
                val = row[col]
                if col == 'Eventos_Totales':
                    # Apply color coding
                    if val >= 50:
                        style = {'backgroundColor': '#ffcccc', 'fontWeight': 'bold'}
                    elif val >= 20:
                        style = {'backgroundColor': '#ffe6cc', 'fontWeight': 'bold'}
                    elif val >= 10:
                        style = {'backgroundColor': '#ffffcc'}
                    else:
                        style = {}
                    cells.append(html.Td(f"{int(val):,}" if pd.notna(val) else '', style=style))
                elif col == 'Equipo':
                    cells.append(html.Td(val, style={'fontWeight': 'bold'}))
                else:
                    # System columns - show 0 as empty
                    display_val = '' if val == 0 else f"{int(val):,}"
                    cells.append(html.Td(display_val))
            rows.append(html.Tr(cells))
        
        table_body = [html.Tbody(rows)]
        
        table = dbc.Table(
            table_header + table_body,
            bordered=True,
            hover=True,
            responsive=True,
            striped=True,
            size='sm',
            className='table-sm'
        )
        
        return html.Div([
            table,
            html.P(
                f"Mostrando {len(df_status)} equipos con alertas en los últimos {days} días",
                className="text-muted small mt-2"
            )
        ])
        
    except Exception as e:
        logger.error(f"Error updating equipment status table: {e}")
        return dbc.Alert(f"Error al cargar tabla: {str(e)}", color="danger")


@callback(
    Output('menace-critical-systems-table', 'children'),
    [
        Input('menace-days-selector', 'value'),
        Input('client-selector', 'value')
    ]
)
def update_critical_systems_table(days, client):
    """Update critical systems ranking table."""
    if not client:
        raise PreventUpdate
        
    try:
        df_alerts = load_alerts_data(client)
        df_oil = load_oil_classified(client)
        
        if df_alerts.empty:
            return dbc.Alert("No hay datos de alertas disponibles", color="warning")
        
        # Get critical systems data
        df_critical = get_critical_systems_data(df_alerts, df_oil, days)
        
        if df_critical.empty:
            return dbc.Alert(f"No hay datos de alertas en los últimos {days} días", color="info")
        
        # Limit to top 50 most critical systems
        df_display = df_critical.head(50).copy()
        
        # Add ranking column
        df_display.insert(0, 'Rank', range(1, len(df_display) + 1))
        
        # Create HTML table
        table_header = [html.Thead(html.Tr([html.Th(col) for col in df_display.columns]))]
        
        rows = []
        for idx, row in df_display.iterrows():
            cells = []
            for col in df_display.columns:
                val = row[col]
                
                if col == 'Rank':
                    # Add medal icons for top 3
                    if val == 1:
                        cells.append(html.Td([html.I(className="fas fa-trophy me-1", style={'color': 'gold'}), str(val)]))
                    elif val == 2:
                        cells.append(html.Td([html.I(className="fas fa-trophy me-1", style={'color': 'silver'}), str(val)]))
                    elif val == 3:
                        cells.append(html.Td([html.I(className="fas fa-trophy me-1", style={'color': '#cd7f32'}), str(val)]))
                    else:
                        cells.append(html.Td(val))
                elif col == 'Criticidad':
                    # Color code criticality
                    if val >= 50:
                        style = {'backgroundColor': '#ffcccc', 'fontWeight': 'bold', 'color': '#cc0000'}
                    elif val >= 20:
                        style = {'backgroundColor': '#ffe6cc', 'fontWeight': 'bold', 'color': '#ff6600'}
                    elif val >= 10:
                        style = {'backgroundColor': '#ffffcc', 'color': '#cc9900'}
                    else:
                        style = {}
                    cells.append(html.Td(f"{int(val):,}", style=style))
                elif col == 'Estado_Tribologia':
                    # Color code tribology status
                    if pd.isna(val) or val == 'Sin datos':
                        badge = dbc.Badge('Sin datos', color='secondary', className='me-1')
                    elif 'normal' in str(val).lower():
                        badge = dbc.Badge(val, color='success', className='me-1')
                    elif 'anormal' in str(val).lower() or 'critico' in str(val).lower():
                        badge = dbc.Badge(val, color='danger', className='me-1')
                    elif 'precaucion' in str(val).lower() or 'advertencia' in str(val).lower():
                        badge = dbc.Badge(val, color='warning', className='me-1')
                    else:
                        badge = dbc.Badge(val, color='info', className='me-1')
                    cells.append(html.Td(badge))
                else:
                    cells.append(html.Td(str(val) if pd.notna(val) else ''))
            
            rows.append(html.Tr(cells))
        
        table_body = [html.Tbody(rows)]
        
        table = dbc.Table(
            table_header + table_body,
            bordered=True,
            hover=True,
            responsive=True,
            striped=True,
            size='sm'
        )
        
        return html.Div([
            table,
            html.P(
                f"Mostrando los {len(df_display)} sistemas más críticos de {len(df_critical)} total "
                f"en los últimos {days} días",
                className="text-muted small mt-2"
            )
        ])
        
    except Exception as e:
        logger.error(f"Error updating critical systems table: {e}")
        return dbc.Alert(f"Error al cargar tabla: {str(e)}", color="danger")
