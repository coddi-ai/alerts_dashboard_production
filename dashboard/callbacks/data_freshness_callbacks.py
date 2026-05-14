"""
Callbacks for Data Freshness monitoring tab.
Handles data loading and visualization for data update status monitoring.
"""

from dash import callback, Output, Input, html, dash_table
from dash.exceptions import PreventUpdate
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
import logging
import pytz

from src.utils.logger import get_logger

logger = get_logger(__name__)


def load_data_freshness() -> pd.DataFrame:
    """
    Load data freshness information from Data_Date_Last_Update.csv
    
    Returns:
        DataFrame with data freshness information
    """
    try:
        file_path = Path("data/auxiliar/cda/Data_Date_Last_Update.csv")
        
        if not file_path.exists():
            logger.error(f"Data freshness file not found: {file_path}")
            return pd.DataFrame()
        
        df = pd.read_csv(file_path)
        
        # Validate required columns
        required_cols = ['Cliente', 'Unit_Id', 'Data', 'Ultima Fecha de Actualizacion']
        if not all(col in df.columns for col in required_cols):
            logger.error(f"Missing required columns. Found: {df.columns.tolist()}")
            return pd.DataFrame()
        
        # Convert timestamp to datetime (UTC+0)
        df['Ultima Fecha de Actualizacion'] = pd.to_datetime(df['Ultima Fecha de Actualizacion'])
        
        logger.info(f"Loaded {len(df)} data freshness records")
        return df
        
    except Exception as e:
        logger.error(f"Error loading data freshness: {e}")
        return pd.DataFrame()


def convert_utc_to_chile(utc_datetime):
    """
    Convert UTC datetime to Chile timezone (UTC-3 or UTC-4 depending on DST)
    
    Args:
        utc_datetime: datetime in UTC
        
    Returns:
        datetime in Chile timezone
    """
    if pd.isna(utc_datetime):
        return None
    
    # Define UTC and Chile timezones
    utc_tz = pytz.UTC
    chile_tz = pytz.timezone('America/Santiago')
    
    # Localize to UTC if naive
    if utc_datetime.tzinfo is None:
        utc_datetime = utc_tz.localize(utc_datetime)
    
    # Convert to Chile timezone
    chile_datetime = utc_datetime.astimezone(chile_tz)
    
    return chile_datetime


def calculate_freshness_status(last_update, data_type, current_time_chile):
    """
    Calculate freshness status based on time elapsed since last update.
    
    Args:
        last_update: datetime of last update (in Chile timezone)
        data_type: 'Telemetria' or 'Tribologia'
        current_time_chile: current datetime in Chile timezone
        
    Returns:
        tuple: (status, color, time_diff_str)
        status: 'Actualizado', 'Atención Requerida', 'Crítico'
        color: color code for styling
    """
    if pd.isna(last_update):
        return 'Sin Datos', '#808080', 'N/A'
    
    # Calculate time difference
    time_diff = current_time_chile - last_update
    
    # Format time difference string
    if time_diff.days > 0:
        if time_diff.days == 1:
            time_diff_str = "1 día"
        else:
            time_diff_str = f"{time_diff.days} días"
    else:
        hours = time_diff.seconds // 3600
        minutes = (time_diff.seconds % 3600) // 60
        if hours > 0:
            time_diff_str = f"{hours}h {minutes}m"
        else:
            time_diff_str = f"{minutes}m"
    
    # Determine status based on data type
    if data_type == 'Telemetria':
        # Green: < 1 hour
        if time_diff < timedelta(hours=1):
            return 'Actualizado', '#28a745', time_diff_str
        # Yellow: < 4 hours
        elif time_diff < timedelta(hours=4):
            return 'Atención Requerida', '#ffc107', time_diff_str
        # Red: >= 4 hours
        else:
            return 'Crítico', '#dc3545', time_diff_str
    
    elif data_type == 'Tribologia':
        # Green: < 1 week
        if time_diff < timedelta(weeks=1):
            return 'Actualizado', '#28a745', time_diff_str
        # Yellow: < 2 weeks
        elif time_diff < timedelta(weeks=2):
            return 'Atención Requerida', '#ffc107', time_diff_str
        # Red: >= 2 weeks
        else:
            return 'Crítico', '#dc3545', time_diff_str
    
    return 'Desconocido', '#808080', time_diff_str


def process_freshness_data(df: pd.DataFrame) -> pd.DataFrame:
    """
    Process data freshness and calculate status for each unit.
    
    Args:
        df: Raw data freshness DataFrame
        
    Returns:
        Processed DataFrame with status and colors
    """
    if df.empty:
        return pd.DataFrame()
    
    # Get current time in Chile timezone
    utc_now = datetime.now(pytz.UTC)
    chile_tz = pytz.timezone('America/Santiago')
    current_time_chile = utc_now.astimezone(chile_tz)
    
    # Convert UTC timestamps to Chile timezone
    df['Ultima_Fecha_Chile'] = df['Ultima Fecha de Actualizacion'].apply(convert_utc_to_chile)
    
    # Calculate status for each row
    df[['Status', 'Color', 'Tiempo_Transcurrido']] = df.apply(
        lambda row: pd.Series(calculate_freshness_status(
            row['Ultima_Fecha_Chile'],
            row['Data'],
            current_time_chile
        )),
        axis=1
    )
    
    # Pivot to have Telemetria and Tribologia as columns
    pivot_data = []
    
    for unit_id in df['Unit_Id'].unique():
        unit_data = df[df['Unit_Id'] == unit_id]
        
        telem_data = unit_data[unit_data['Data'] == 'Telemetria']
        tribo_data = unit_data[unit_data['Data'] == 'Tribologia']
        
        row = {
            'Unidad': unit_id,
        }
        
        # Telemetry data - Combined format "Estado - Hace"
        if not telem_data.empty:
            telem_row = telem_data.iloc[0]
            row['Telemetría'] = f"{telem_row['Status']} - {telem_row['Tiempo_Transcurrido']}"
            row['Telemetría_Status'] = telem_row['Status']
            row['Telemetría_Color'] = telem_row['Color']
        else:
            row['Telemetría'] = 'Sin Datos - N/A'
            row['Telemetría_Status'] = 'Sin Datos'
            row['Telemetría_Color'] = '#808080'
        
        # Tribology data - Combined format "Estado - Hace"
        if not tribo_data.empty:
            tribo_row = tribo_data.iloc[0]
            row['Tribología'] = f"{tribo_row['Status']} - {tribo_row['Tiempo_Transcurrido']}"
            row['Tribología_Status'] = tribo_row['Status']
            row['Tribología_Color'] = tribo_row['Color']
        else:
            row['Tribología'] = 'Sin Datos - N/A'
            row['Tribología_Status'] = 'Sin Datos'
            row['Tribología_Color'] = '#808080'
        
        pivot_data.append(row)
    
    result_df = pd.DataFrame(pivot_data)
    
    # Sort by Unit ID
    result_df = result_df.sort_values('Unidad')
    
    return result_df


@callback(
    Output('data-freshness-table', 'children'),
    Input('data-freshness-table', 'id')  # Trigger when component is mounted
)
def update_data_freshness(_):
    """
    Update data freshness table.
    
    Args:
        _: Dummy input to trigger callback
        
    Returns:
        DataTable with freshness information
    """
    try:
        # Load and process data
        df_raw = load_data_freshness()
        
        if df_raw.empty:
            return html.Div("No hay datos disponibles", className="text-center text-muted p-4")
        
        df_processed = process_freshness_data(df_raw)
        
        if df_processed.empty:
            return html.Div("Error procesando datos", className="text-center text-muted p-4")
        
        # Create DataTable with conditional styling
        table = dash_table.DataTable(
            data=df_processed.to_dict('records'),
            columns=[
                {'name': 'Unidad', 'id': 'Unidad'},
                {'name': 'Telemetría', 'id': 'Telemetría'},
                {'name': 'Tribología', 'id': 'Tribología'},
            ],
            style_table={'overflowX': 'auto'},
            style_cell={
                'textAlign': 'left',
                'padding': '12px',
                'fontFamily': 'Arial, sans-serif',
                'fontSize': '14px',
                'minWidth': '150px'
            },
            style_header={
                'backgroundColor': '#f8f9fa',
                'fontWeight': 'bold',
                'border': '1px solid #dee2e6',
                'fontSize': '14px',
                'textAlign': 'center'
            },
            style_data_conditional=[
                # Telemetría styling - based on Status
                {
                    'if': {
                        'filter_query': '{Telemetría_Status} = "Actualizado"',
                        'column_id': 'Telemetría'
                    },
                    'backgroundColor': '#d4edda',
                    'color': '#155724',
                    'fontWeight': 'bold'
                },
                {
                    'if': {
                        'filter_query': '{Telemetría_Status} = "Atención Requerida"',
                        'column_id': 'Telemetría'
                    },
                    'backgroundColor': '#fff3cd',
                    'color': '#856404',
                    'fontWeight': 'bold'
                },
                {
                    'if': {
                        'filter_query': '{Telemetría_Status} = "Crítico"',
                        'column_id': 'Telemetría'
                    },
                    'backgroundColor': '#f8d7da',
                    'color': '#721c24',
                    'fontWeight': 'bold'
                },
                {
                    'if': {
                        'filter_query': '{Telemetría_Status} = "Sin Datos"',
                        'column_id': 'Telemetría'
                    },
                    'backgroundColor': '#e2e3e5',
                    'color': '#6c757d'
                },
                
                # Tribología styling - based on Status
                {
                    'if': {
                        'filter_query': '{Tribología_Status} = "Actualizado"',
                        'column_id': 'Tribología'
                    },
                    'backgroundColor': '#d4edda',
                    'color': '#155724',
                    'fontWeight': 'bold'
                },
                {
                    'if': {
                        'filter_query': '{Tribología_Status} = "Atención Requerida"',
                        'column_id': 'Tribología'
                    },
                    'backgroundColor': '#fff3cd',
                    'color': '#856404',
                    'fontWeight': 'bold'
                },
                {
                    'if': {
                        'filter_query': '{Tribología_Status} = "Crítico"',
                        'column_id': 'Tribología'
                    },
                    'backgroundColor': '#f8d7da',
                    'color': '#721c24',
                    'fontWeight': 'bold'
                },
                {
                    'if': {
                        'filter_query': '{Tribología_Status} = "Sin Datos"',
                        'column_id': 'Tribología'
                    },
                    'backgroundColor': '#e2e3e5',
                    'color': '#6c757d'
                },
                
                # Alternate row colors
                {
                    'if': {'row_index': 'odd'},
                    'backgroundColor': '#f9f9f9'
                }
            ],
            page_size=20,
            sort_action='native',
            filter_action='native',
            export_format='xlsx',
            export_headers='display'
        )
        
        return table
        
    except Exception as e:
        logger.error(f"Error in update_data_freshness: {e}", exc_info=True)
        return html.Div(f"Error: {str(e)}", className="text-center text-danger p-4")
