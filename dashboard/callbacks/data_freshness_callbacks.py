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
import os
import pytz

from src.utils.logger import get_logger
from dashboard.components.labels import NO_DATA_ICON, NO_DATA_BG, NO_DATA_TEXT

logger = get_logger(__name__)


def load_data_freshness(client: str = "cda") -> pd.DataFrame:
    """
    Load data freshness information from Data_Date_Last_Update.csv

    Args:
        client: Client identifier (e.g., 'cda')

    Returns:
        DataFrame with data freshness information
    """
    try:
        # W34: honor DASHBOARD_DATA_ROOT like every other loader
        # (src/data/loaders.py::_data_path) — this was the one hardcoded
        # "data/..." path in the codebase, which made this function
        # untestable with a tmp_path fixture the way every other loader is.
        data_root = Path(os.getenv("DASHBOARD_DATA_ROOT", "data")).expanduser()
        file_path = data_root / "auxiliar" / client.lower() / "Data_Date_Last_Update.csv"

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

    Quality-review follow-up: this predates and duplicates
    src/utils/date_utils.py::to_local_naive, which W34-06 introduced as the
    single place for UTC->Chile conversion. Deliberately NOT switched to call
    it here: to_local_naive returns a tz-NAIVE Timestamp, but every caller of
    this function (calculate_freshness_status, both in this file and in
    overview_general_callbacks.py) subtracts its result from a tz-AWARE
    `current_time_chile` (`datetime.now(chile_tz)`) — swapping the return
    type would raise `TypeError: can't subtract offset-naive and
    offset-aware datetimes` at every call site. Changing that arithmetic to
    naive-throughout is a real, separate fix (touching both freshness call
    sites together), not a drop-in rename — left as a known, intentional
    duplication rather than risking a silent behavior change here.

    Second critical-review pass: a lower-risk fix path exists without
    touching the naive-vs-aware arithmetic at all — add a tz-AWARE sibling
    (e.g. `to_local_aware`) to date_utils.py, mirroring `to_local_naive`
    exactly except it skips the final `.tz_localize(None)` strip, and have
    this function delegate to it. Not applied in this pass: the "already
    tz-aware input" branch below (`if utc_datetime.tzinfo is None`) implies a
    caller once passed an aware value, and there is no full audit here
    confirming every current caller only ever passes naive — a delegating
    rewrite should preserve that defensive branch exactly, verified against
    real call sites, not assumed.
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


# ========================================
# W34-02 — single style source for freshness status
# ========================================
# The legend (tab_data_freshness.py::_build_legend) and this table's
# style_data_conditional each used to hand-pick their own icon/color values
# for the same three statuses — a third, independent palette from the one
# below. All three now read from here. `bg`/`text` reuse the app-wide
# :root design tokens (predictive_styles.css, loaded globally via assets/
# on every page) instead of a fourth set of hardcoded hex values, so this
# tab's palette is visually consistent with the rest of the dashboard
# rather than its own island — `accent` stays a literal hex because it also
# feeds FRESHNESS_CRITERIA's threshold tuples below, unchanged in value.
FRESHNESS_STATUS_STYLE: dict[str, dict[str, str]] = {
    'Ok':          {'icon': '🟢', 'accent': '#28a745', 'bg': 'var(--green-light)', 'text': 'var(--green-text)'},
    'Atención':    {'icon': '🟡', 'accent': '#ffc107', 'bg': 'var(--amber-light)', 'text': 'var(--amber-text)'},
    'Preocupante': {'icon': '🔴', 'accent': '#dc3545', 'bg': 'var(--red-light)',   'text': 'var(--red-text)'},
    # W34-13 terminology: a unit with no record for this data type, distinct
    # from a resolved Ok/Atención/Preocupante status. icon/bg/text come from
    # labels.py's NO_DATA_* constants — the same "no data" identity Estado x
    # Unidad and Predictivo use, not a third independently hand-picked one
    # kept in sync only by a comment (quality-review follow-up).
    'Sin Datos':   {'icon': NO_DATA_ICON, 'accent': '#808080', 'bg': NO_DATA_BG, 'text': NO_DATA_TEXT},
}


# ========================================
# FRESHNESS CRITERIA CONFIGURATION
# ========================================
# Modular criteria for data freshness status.
# Each data type defines thresholds and labels.
# Format: list of (max_timedelta, label, color) in order of priority (best to worst).
# The last entry is the fallback (worst status). Thresholds themselves are
# W34's "don't touch the freshness calculation" boundary — only the `color`
# values were consolidated (W34-02) to trace to FRESHNESS_STATUS_STYLE.
FRESHNESS_CRITERIA = {
    'Telemetria': [
        (timedelta(hours=2),  'Ok',          FRESHNESS_STATUS_STYLE['Ok']['accent']),
        (timedelta(hours=24), 'Atención',    FRESHNESS_STATUS_STYLE['Atención']['accent']),
        (timedelta(hours=24), 'Preocupante', FRESHNESS_STATUS_STYLE['Preocupante']['accent']),
    ],
    'Tribologia': [
        (timedelta(days=20),  'Ok',          FRESHNESS_STATUS_STYLE['Ok']['accent']),
        (timedelta(days=40),  'Atención',    FRESHNESS_STATUS_STYLE['Atención']['accent']),
        (timedelta(days=40),  'Preocupante', FRESHNESS_STATUS_STYLE['Preocupante']['accent']),
    ],
}


def calculate_freshness_status(last_update, data_type, current_time_chile):
    """
    Calculate freshness status based on time elapsed since last update.
    Uses modular criteria defined in FRESHNESS_CRITERIA.
    
    Args:
        last_update: datetime of last update (in Chile timezone)
        data_type: 'Telemetria' or 'Tribologia'
        current_time_chile: current datetime in Chile timezone
        
    Returns:
        tuple: (status, color, time_diff_str)
    """
    if pd.isna(last_update):
        return 'Sin Datos', FRESHNESS_STATUS_STYLE['Sin Datos']['accent'], 'N/A'
    
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
    
    # Look up criteria for this data type
    criteria = FRESHNESS_CRITERIA.get(data_type)
    if not criteria:
        return 'Desconocido', '#808080', time_diff_str
    
    # Evaluate thresholds in order
    for threshold, label, color in criteria:
        if time_diff < threshold:
            return label, color, time_diff_str
    
    # Exceeded all thresholds → return worst status
    _, worst_label, worst_color = criteria[-1]
    return worst_label, worst_color, time_diff_str


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
    Input('data-freshness-table', 'id'),
    Input('client-selector', 'value')
)
def update_data_freshness(_, selected_client):
    """
    Update data freshness table.
    
    Args:
        _: Dummy input to trigger callback
        selected_client: Currently selected client from dropdown
        
    Returns:
        DataTable with freshness information
    """
    try:
        # Get client from selector
        client = (selected_client or 'cda').lower()
        
        # Load and process data
        df_raw = load_data_freshness(client)
        
        if df_raw.empty:
            return html.Div([
                html.I(className="fas fa-info-circle fa-3x text-muted mb-3"),
                html.H4("Datos no disponibles", className="text-muted"),
                html.P(
                    f"No se encontraron datos de estado de actualización para el cliente '{client.upper()}'.",
                    className="text-muted"
                ),
                html.P(
                    "Esta funcionalidad estará disponible próximamente.",
                    className="text-muted small"
                )
            ], className="text-center p-5")
        
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
            # W34-02: generated from FRESHNESS_STATUS_STYLE instead of 8
            # hand-written rules repeating the same 4 colors twice (once per
            # column) — the single source of truth also used by the legend.
            style_data_conditional=[
                *[
                    {
                        'if': {
                            'filter_query': f'{{{column}_Status}} = "{status_label}"',
                            'column_id': column,
                        },
                        'backgroundColor': style['bg'],
                        'color': style['text'],
                        'fontWeight': 'bold' if status_label != 'Sin Datos' else 'normal',
                    }
                    for column in ('Telemetría', 'Tribología')
                    for status_label, style in FRESHNESS_STATUS_STYLE.items()
                ],
                # Alternate row colors
                {
                    'if': {'row_index': 'odd'},
                    'backgroundColor': '#f9f9f9'
                }
            ],
            page_size=20,
            sort_action='native',
            filter_action='native',
        )
        
        return table
        
    except Exception as e:
        logger.error(f"Error in update_data_freshness: {e}", exc_info=True)
        return html.Div(f"Error: {str(e)}", className="text-center text-danger p-4")
