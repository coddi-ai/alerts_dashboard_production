"""
Callbacks for Hot Sheet Tab.

Handles the traffic light status view combining alerts and tribology data.
"""

import pandas as pd
import numpy as np
from dash import callback, Input, Output, html
from dash.exceptions import PreventUpdate
import dash_bootstrap_components as dbc
from datetime import datetime, timedelta

from src.data.loaders import load_alerts_data, load_oil_classified, load_telemetry_alerts_metadata
from src.utils.logger import get_logger

logger = get_logger(__name__)


# Alert level classification based on Trigger field
ALERT_LEVEL_1_TRIGGERS = [
    'Engine Coolant Temperature',
    'Engine Oil Pressure',
    'eng cool temp',
    'eng oil pres'
]

ALERT_LEVEL_2_TRIGGERS = [
    'Transmission Oil Temperature',
    'Differential Oil Temperature',
    'Brake Oil Temperature',
    'trans oil temp',
    'diff oil temp',
    'brake oil temp',
    'Left Front Brake Oil Temperature',
    'Left Rear Brake Oil Temperature',
    'Right Front Brake Oil Temperature',
    'Right Rear Brake Oil Temperature'
]


def classify_alert_level(trigger: str) -> int:
    """
    Classify alert into levels 1, 2, or 3 based on trigger.
    
    Args:
        trigger: Alert trigger/sensor name
    
    Returns:
        1, 2, or 3 (alert level)
    """
    if pd.isna(trigger):
        return 3
    
    trigger_lower = str(trigger).lower()
    
    # Check level 1 (most critical)
    for l1_trigger in ALERT_LEVEL_1_TRIGGERS:
        if l1_trigger.lower() in trigger_lower:
            return 1
    
    # Check level 2 (important)
    for l2_trigger in ALERT_LEVEL_2_TRIGGERS:
        if l2_trigger.lower() in trigger_lower:
            return 2
    
    # Level 3 (general)
    return 3


def calculate_alert_status(df_alerts: pd.DataFrame, unit_id: str) -> str:
    """
    Calculate alert status for a unit based on alert levels and timeframes.
    
    Criteria:
    - Anormal (red): 1+ level 1 alerts in last 7 days OR 3+ level 2 alerts in last 14 days
    - Alerta (yellow): 1-2 level 2 alerts in last 14 days OR 3+ level 3 alerts in last 14 days
    - Normal (green): Otherwise
    
    Args:
        df_alerts: Alerts dataframe with Timestamp and Trigger columns
        unit_id: Unit identifier
    
    Returns:
        'anormal', 'alerta', or 'normal'
    """
    if df_alerts.empty:
        return 'normal'
    
    # Filter alerts for this unit
    equipment_col = 'UnitId' if 'UnitId' in df_alerts.columns else 'Unidad'
    unit_alerts = df_alerts[df_alerts[equipment_col] == unit_id].copy()
    
    if unit_alerts.empty:
        return 'normal'
    
    # Classify each alert by level
    # Try to use Trigger field first, fallback to Componente
    if 'Trigger' in unit_alerts.columns:
        trigger_col = 'Trigger'
    elif 'componente' in unit_alerts.columns:
        trigger_col = 'componente'
    elif 'Componente' in unit_alerts.columns:
        trigger_col = 'Componente'
    else:
        # No trigger info, use conservative approach
        logger.warning(f"No Trigger or Componente column found for unit {unit_id}")
        return 'normal'
    
    unit_alerts['alert_level'] = unit_alerts[trigger_col].apply(classify_alert_level)
    
    # Calculate timeframes
    now = datetime.now()
    last_7_days = now - timedelta(days=7)
    last_14_days = now - timedelta(days=14)
    
    # Ensure Timestamp is datetime
    if 'Timestamp' in unit_alerts.columns:
        unit_alerts['Timestamp'] = pd.to_datetime(unit_alerts['Timestamp'], errors='coerce')
    else:
        # No timestamp, cannot calculate time-based criteria
        return 'normal'
    
    # Count alerts by level and timeframe
    alerts_7d_level1 = len(unit_alerts[
        (unit_alerts['Timestamp'] >= last_7_days) & 
        (unit_alerts['alert_level'] == 1)
    ])
    
    alerts_14d_level2 = len(unit_alerts[
        (unit_alerts['Timestamp'] >= last_14_days) & 
        (unit_alerts['alert_level'] == 2)
    ])
    
    alerts_14d_level3 = len(unit_alerts[
        (unit_alerts['Timestamp'] >= last_14_days) & 
        (unit_alerts['alert_level'] == 3)
    ])
    
    # Apply criteria
    # Anormal (red): 1+ level 1 in last 7 days OR 3+ level 2 in last 14 days
    if alerts_7d_level1 >= 1 or alerts_14d_level2 >= 3:
        return 'anormal'
    
    # Alerta (yellow): 1-2 level 2 in last 14 days OR 3+ level 3 in last 14 days
    if (1 <= alerts_14d_level2 <= 2) or alerts_14d_level3 >= 3:
        return 'alerta'
    
    # Normal (green)
    return 'normal'


def calculate_tribology_status(df_oil: pd.DataFrame, unit_id: str) -> str:
    """
    Calculate tribology status for a unit based on most recent oil analysis.
    
    Args:
        df_oil: Oil classified dataframe
        unit_id: Unit identifier
    
    Returns:
        'anormal', 'alerta', 'normal', or 'sin_datos'
    """
    if df_oil.empty:
        return 'sin_datos'
    
    # Filter oil samples for this unit
    if 'unitId' not in df_oil.columns:
        return 'sin_datos'
    
    unit_oil = df_oil[df_oil['unitId'] == unit_id].copy()
    
    if unit_oil.empty:
        return 'sin_datos'
    
    # Get most recent sample
    if 'sampleDate' in unit_oil.columns:
        unit_oil['sampleDate'] = pd.to_datetime(unit_oil['sampleDate'], errors='coerce')
        unit_oil = unit_oil.sort_values('sampleDate', ascending=False)
    
    latest_sample = unit_oil.iloc[0]
    
    # Check report_status
    if 'report_status' not in latest_sample or pd.isna(latest_sample['report_status']):
        return 'sin_datos'
    
    status = str(latest_sample['report_status']).lower()
    
    # Map status to colors
    if 'anormal' in status or 'critic' in status or 'critico' in status:
        return 'anormal'
    elif 'precaucion' in status or 'advertencia' in status or 'alerta' in status or 'warning' in status:
        return 'alerta'
    elif 'normal' in status:
        return 'normal'
    else:
        return 'sin_datos'


def get_hot_sheet_data(df_alerts: pd.DataFrame, df_oil: pd.DataFrame) -> pd.DataFrame:
    """
    Generate hot sheet data with status for all units.
    
    Args:
        df_alerts: Alerts dataframe
        df_oil: Oil classified dataframe
    
    Returns:
        DataFrame with columns: Unidad, Estado_Telemetria, Estado_Tribologia
    """
    # Get unique units from both sources
    units = set()
    
    if not df_alerts.empty:
        equipment_col = 'UnitId' if 'UnitId' in df_alerts.columns else 'Unidad'
        units.update(df_alerts[equipment_col].unique())
    
    if not df_oil.empty and 'unitId' in df_oil.columns:
        units.update(df_oil['unitId'].unique())
    
    if not units:
        return pd.DataFrame(columns=['Unidad', 'Estado_Telemetria', 'Estado_Tribologia'])
    
    # Calculate status for each unit
    results = []
    for unit in sorted(units):
        alert_status = calculate_alert_status(df_alerts, unit)
        trib_status = calculate_tribology_status(df_oil, unit)
        
        results.append({
            'Unidad': unit,
            'Estado_Telemetria': alert_status,
            'Estado_Tribologia': trib_status
        })
    
    df_result = pd.DataFrame(results)
    
    # Sort by worst status first (anormal > alerta > normal > sin_datos)
    status_priority = {'anormal': 0, 'alerta': 1, 'normal': 2, 'sin_datos': 3}
    
    df_result['telemetry_priority'] = df_result['Estado_Telemetria'].map(status_priority)
    df_result['trib_priority'] = df_result['Estado_Tribologia'].map(status_priority)
    df_result['combined_priority'] = df_result['telemetry_priority'] + df_result['trib_priority']
    
    df_result = df_result.sort_values('combined_priority')
    df_result = df_result.drop(columns=['telemetry_priority', 'trib_priority', 'combined_priority'])
    
    return df_result


@callback(
    Output('hot-sheet-table', 'children'),
    [Input('client-selector', 'value')]
)
def update_hot_sheet_table(client):
    """Update hot sheet table with unit statuses."""
    if not client:
        raise PreventUpdate
    
    try:
        df_alerts = load_alerts_data(client)
        df_oil = load_oil_classified(client)
        
        # Get hot sheet data
        df_hot = get_hot_sheet_data(df_alerts, df_oil)
        
        if df_hot.empty:
            return dbc.Alert("No hay datos de unidades disponibles", color="warning")
        
        # Define color mappings
        status_colors = {
            'anormal': '#ffcccc',  # Light red
            'alerta': '#fff3cd',   # Light yellow
            'normal': '#d4edda',   # Light green
            'sin_datos': '#e2e3e5' # Light gray
        }
        
        status_icons = {
            'anormal': '🔴',
            'alerta': '🟡',
            'normal': '🟢',
            'sin_datos': '⚪'
        }
        
        status_text = {
            'anormal': 'Anormal',
            'alerta': 'Alerta',
            'normal': 'Normal',
            'sin_datos': 'Sin Datos'
        }
        
        # Create table
        table_header = [html.Thead(html.Tr([
            html.Th("Unidad", style={'width': '33%'}),
            html.Th("Telemetría", style={'width': '33%', 'textAlign': 'center'}),
            html.Th("Tribología", style={'width': '33%', 'textAlign': 'center'})
        ]))]
        
        rows = []
        for idx, row in df_hot.iterrows():
            telemetry_status = row['Estado_Telemetria']
            trib_status = row['Estado_Tribologia']
            
            cells = [
                html.Td(row['Unidad'], style={'fontWeight': 'bold', 'verticalAlign': 'middle'}),
                html.Td(
                    html.Div([
                        html.Span(status_icons[telemetry_status], className="me-2"),
                        status_text[telemetry_status]
                    ], style={'textAlign': 'center'}),
                    style={
                        'backgroundColor': status_colors[telemetry_status],
                        'textAlign': 'center',
                        'verticalAlign': 'middle',
                        'fontWeight': 'bold' if telemetry_status == 'anormal' else 'normal'
                    }
                ),
                html.Td(
                    html.Div([
                        html.Span(status_icons[trib_status], className="me-2"),
                        status_text[trib_status]
                    ], style={'textAlign': 'center'}),
                    style={
                        'backgroundColor': status_colors[trib_status],
                        'textAlign': 'center',
                        'verticalAlign': 'middle',
                        'fontWeight': 'bold' if trib_status == 'anormal' else 'normal'
                    }
                )
            ]
            
            rows.append(html.Tr(cells))
        
        table_body = [html.Tbody(rows)]
        
        table = dbc.Table(
            table_header + table_body,
            bordered=True,
            hover=True,
            responsive=True,
            size='sm',
            className='hot-sheet-table'
        )
        
        return table
        
    except Exception as e:
        logger.error(f"Error updating hot sheet table: {e}")
        return dbc.Alert(f"Error al cargar tabla: {str(e)}", color="danger")


# Summary statistics callback disabled - cards removed from layout
# @callback(
#     Output('hot-sheet-summary', 'children'),
#     [Input('client-selector', 'value')]
# )
# def update_hot_sheet_summary(client):
#     """Update summary statistics for hot sheet."""
#     if not client:
#         raise PreventUpdate
#     
#     try:
#         df_alerts = load_alerts_data(client)
#         df_oil = load_oil_classified(client)
#         
#         # Get hot sheet data
#         df_hot = get_hot_sheet_data(df_alerts, df_oil)
#         
#         if df_hot.empty:
#             return html.Div()
#         
#         # Count units by status
#         alert_counts = df_hot['Estado_Alertas'].value_counts()
#         trib_counts = df_hot['Estado_Tribologia'].value_counts()
#         
#         total_units = len(df_hot)
#         
#         # Create summary cards (5 cards without "Alertas Normales")
#         cards = dbc.Row([
#             # Total units
#             dbc.Col([
#                 dbc.Card([
#                     dbc.CardBody([
#                         html.H4(f"{total_units}", className="text-primary mb-0"),
#                         html.P("Unidades Totales", className="text-muted mb-0 small")
#                     ])
#                 ], className="text-center shadow-sm")
#             ], md=2, sm=6),
#             
#             # Alerts - Anormal
#             dbc.Col([
#                 dbc.Card([
#                     dbc.CardBody([
#                         html.H4(f"{alert_counts.get('anormal', 0)}", className="text-danger mb-0"),
#                         html.P("Alertas Anormales", className="text-muted mb-0 small")
#                     ])
#                 ], className="text-center shadow-sm")
#             ], md=2, sm=6),
#             
#             # Alerts - Alerta
#             dbc.Col([
#                 dbc.Card([
#                     dbc.CardBody([
#                         html.H4(f"{alert_counts.get('alerta', 0)}", className="text-warning mb-0"),
#                         html.P("Alertas en Alerta", className="text-muted mb-0 small")
#                     ])
#                 ], className="text-center shadow-sm")
#             ], md=2, sm=6),
#             
#             # Tribology - Anormal
#             dbc.Col([
#                 dbc.Card([
#                     dbc.CardBody([
#                         html.H4(f"{trib_counts.get('anormal', 0)}", className="text-danger mb-0"),
#                         html.P("Tribología Anormal", className="text-muted mb-0 small")
#                     ])
#                 ], className="text-center shadow-sm")
#             ], md=3, sm=6),
#             
#             # Tribology - Normal
#             dbc.Col([
#                 dbc.Card([
#                     dbc.CardBody([
#                         html.H4(f"{trib_counts.get('normal', 0)}", className="text-success mb-0"),
#                         html.P("Tribología Normal", className="text-muted mb-0 small")
#                     ])
#                 ], className="text-center shadow-sm")
#             ], md=3, sm=6)
#         ])
#         
#         return cards
#         
#     except Exception as e:
#         logger.error(f"Error updating hot sheet summary: {e}")
#         return html.Div()

