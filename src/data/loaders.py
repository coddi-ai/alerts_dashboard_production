"""
Data loaders for Multi-Technical-Alerts.

Load data from different layers:
- Bronze layer: Raw data (data/oil/bronze/{client}/)
- Silver layer: Harmonized data (data/oil/silver/{CLIENT}.parquet)
- Golden layer: Analysis-ready outputs (data/oil/golden/{client}/)
"""

import pandas as pd
import json
import warnings
from pathlib import Path
from typing import Dict, List, Optional

from src.utils.logger import get_logger
from src.utils.file_utils import list_excel_files, safe_read_excel, safe_read_parquet

logger = get_logger(__name__)


def load_essays_mapping(file_path: str | Path = "essays_elements.xlsx") -> pd.DataFrame:
    """
    Load essays mapping table for harmonizing column names.
    
    Args:
        file_path: Path to essays mapping Excel file
    
    Returns:
        DataFrame with Element → ElementNameSpanish mapping
    """
    logger.info(f"Loading essays mapping from {file_path}")
    
    df = pd.read_excel(file_path, engine='openpyxl')
    # Drop rows with incomplete mappings
    df = df.dropna()
    
    logger.info(f"Loaded {len(df)} essay mappings")
    return df


def load_cda_data(raw_folder: str | Path) -> pd.DataFrame:
    """
    Load CDA data from Finning lab Excel files.
    
    Args:
        raw_folder: Path to raw/cda directory
    
    Returns:
        Concatenated DataFrame from all Excel files
    """
    import warnings
    warnings.filterwarnings("ignore", message="Workbook contains no default style")
    
    raw_folder = Path(raw_folder)
    logger.info(f"Loading CDA data from {raw_folder}")
    
    excel_files = list_excel_files(raw_folder)
    
    if not excel_files:
        logger.warning(f"No Excel files found in {raw_folder}")
        return pd.DataFrame()
    
    logger.info(f"Found {len(excel_files)} Excel files to process")
    
    dataframes = []
    for file in excel_files:
        logger.debug(f"Reading {file.name}")
        df = safe_read_excel(file, engine='openpyxl')
        if not df.empty:
            dataframes.append(df)
    
    if not dataframes:
        logger.warning("No valid dataframes loaded from CDA files")
        return pd.DataFrame()
    
    # Concatenate all dataframes
    df_combined = pd.concat(dataframes, ignore_index=True)
    
    # Drop completely empty rows
    df_combined = df_combined.dropna(how='all')
    
    logger.info(f"Loaded {len(df_combined)} rows from CDA data")
    return df_combined


def load_emin_data(file_path: str | Path) -> pd.DataFrame:
    """
    Load EMIN data from ALS lab Parquet file.
    
    Args:
        file_path: Path to EMIN parquet file (e.g., raw/emin/muestrasAlsHistoricos.parquet)
    
    Returns:
        DataFrame with EMIN data
    """
    file_path = Path(file_path)
    logger.info(f"Loading EMIN data from {file_path}")
    
    df = safe_read_parquet(file_path)
    
    if df.empty:
        logger.warning(f"No data loaded from {file_path}")
        return df
    
    logger.info(f"Loaded {len(df)} rows from EMIN data")
    return df


def load_stewart_limits(file_path: str | Path) -> Dict:
    """
    Load pre-computed Stewart Limits from Parquet file.
    Supports both v2.2 (non-stratified) and v2.3 (oil-hour stratified) formats.
    
    Args:
        file_path: Path to stewart_limits.parquet
    
    Returns:
        Dictionary with limits structure: 
        {client: {machine: {component: {essay: {oilHourRange: {threshold_normal, threshold_alert, threshold_critic}}}}}}
        
        For v2.2 compatibility, oilHourRange key is 'ALL' when column doesn't exist.
    """
    file_path = Path(file_path)
    logger.info(f"Loading Stewart Limits from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Stewart Limits file not found: {file_path}")
        return {}
    
    # Read Parquet file
    df = safe_read_parquet(file_path)
    
    if df.empty:
        logger.warning("Stewart Limits dataframe is empty")
        return {}
    
    # Check if oilHourRange column exists (v2.3) or not (v2.2)
    has_oil_hour_range = 'oilHourRange' in df.columns
    logger.info(f"Stewart Limits format: {'v2.3 (stratified)' if has_oil_hour_range else 'v2.2 (non-stratified)'}")
    
    # Convert dataframe to nested dictionary structure
    limits = {}
    for _, row in df.iterrows():
        client = row['client']
        machine = row['machine']
        component = row['component']
        essay = row['essay']
        oil_hour_range = row.get('oilHourRange', 'ALL') if has_oil_hour_range else 'ALL'
        
        if client not in limits:
            limits[client] = {}
        if machine not in limits[client]:
            limits[client][machine] = {}
        if component not in limits[client][machine]:
            limits[client][machine][component] = {}
        if essay not in limits[client][machine][component]:
            limits[client][machine][component][essay] = {}
        
        limits[client][machine][component][essay][oil_hour_range] = {
            'threshold_normal': row.get('threshold_normal', 0),
            'threshold_alert': row.get('threshold_alert', 0),
            'threshold_critic': row.get('threshold_critic', 0),
            'percentile_marginal': row.get('percentile_marginal', 90),
            'percentile_condenatorio': row.get('percentile_condenatorio', 95),
            'percentile_critico': row.get('percentile_critico', 98),
            'sample_count': row.get('sample_count', 0)
        }
    
    logger.info(f"Loaded Stewart Limits for {len(limits)} clients")
    return limits


def save_stewart_limits(limits: Dict, file_path: str | Path) -> None:
    """
    Save Stewart Limits to Parquet file.
    
    Args:
        limits: Dictionary with limits structure
        file_path: Path to save Parquet file
    """
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    logger.info(f"Saving Stewart Limits to {file_path}")
    
    # Convert nested dict to dataframe
    rows = []
    for client, machines in limits.items():
        for machine, components in machines.items():
            for component, essays in components.items():
                for essay, thresholds in essays.items():
                    rows.append({
                        'client': client,
                        'machine': machine,
                        'component': component,
                        'essay': essay,
                        'threshold_normal': thresholds.get('threshold_normal', 0),
                        'threshold_alert': thresholds.get('threshold_alert', 0),
                        'threshold_critic': thresholds.get('threshold_critic', 0),
                        'percentile_marginal': thresholds.get('percentile_marginal', 90),
                        'percentile_condenatorio': thresholds.get('percentile_condenatorio', 95),
                        'percentile_critico': thresholds.get('percentile_critico', 98),
                        'sample_count': thresholds.get('sample_count', 0)
                    })
    
    df = pd.DataFrame(rows)
    df.to_parquet(file_path, index=False, engine='pyarrow', compression='zstd')
    
    logger.info("Stewart Limits saved successfully")

# ========================================
# GOLDEN LAYER LOADERS
# ========================================

def load_classified_reports(file_path: str | Path) -> pd.DataFrame:
    """
    Load classified oil analysis reports from Golden layer.
    
    Args:
        file_path: Path to golden/{client}/classified.parquet
    
    Returns:
        DataFrame with classified reports including essay_status columns,
        report_status, ai_recommendation, etc.
    """
    file_path = Path(file_path)
    logger.info(f"Loading classified reports from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Classified reports file not found: {file_path}")
        return pd.DataFrame()
    
    df = safe_read_parquet(file_path)
    
    if df.empty:
        logger.warning("Classified reports dataframe is empty")
        return df
    
    logger.info(f"Loaded {len(df)} classified reports")
    return df


def load_machine_status(file_path: str | Path) -> pd.DataFrame:
    """
    Load machine status aggregations from Golden layer.
    
    Args:
        file_path: Path to golden/{client}/machine_status.parquet
    
    Returns:
        DataFrame with machine-level status aggregations
    """
    file_path = Path(file_path)
    logger.info(f"Loading machine status from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Machine status file not found: {file_path}")
        return pd.DataFrame()
    
    df = safe_read_parquet(file_path)
    
    if df.empty:
        logger.warning("Machine status dataframe is empty")
        return df
    
    logger.info(f"Loaded {len(df)} machine status records")
    return df


def load_stewart_limits_for_client(file_path: str | Path) -> pd.DataFrame:
    """
    Load Stewart Limits for a specific client from Golden layer.
    
    Args:
        file_path: Path to golden/{client}/stewart_limits.parquet
    
    Returns:
        DataFrame with Stewart Limits for the client
    """
    file_path = Path(file_path)
    logger.info(f"Loading Stewart Limits from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Stewart Limits file not found: {file_path}")
        return pd.DataFrame()
    
    df = safe_read_parquet(file_path)
    
    if df.empty:
        logger.warning("Stewart Limits dataframe is empty")
        return df
    
    logger.info(f"Loaded {len(df)} Stewart Limit records")
    return df


def load_silver_data(file_path: str | Path) -> pd.DataFrame:
    """
    Load harmonized silver layer data for a client.
    
    Args:
        file_path: Path to silver/{CLIENT}.parquet
    
    Returns:
        DataFrame with harmonized oil sample data
    """
    file_path = Path(file_path)
    logger.info(f"Loading silver data from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Silver data file not found: {file_path}")
        return pd.DataFrame()
    
    df = safe_read_parquet(file_path)
    
    if df.empty:
        logger.warning("Silver data dataframe is empty")
        return df
    
    logger.info(f"Loaded {len(df)} silver layer records")
    return df


# ========================================
# ALERTS DASHBOARD LOADERS (CDA ONLY)
# ========================================

def load_alerts_data(client: str) -> pd.DataFrame:
    """
    Load consolidated alerts data for a specific client.
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with alerts data including derived columns (has_telemetry, has_tribology, Month)
    
    Note:
        This feature is currently only available for CDA client.
    """
    # CDA-only check
    if client.lower() != 'cda':
        logger.warning(f"Alerts dashboard is only available for CDA client. Requested: {client}")
        return pd.DataFrame()
    
    file_path = Path(f"data/alerts/golden/{client.lower()}/consolidated_alerts.csv")
    logger.info(f"Loading alerts data from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Alerts file not found: {file_path}")
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(file_path)
        
        # Parse timestamp
        df['Timestamp'] = pd.to_datetime(df['Timestamp'])
        
        # Fill sistema, subsistema and componente missing values
        df['sistema'] = df['sistema'].fillna('Desconocido')
        df['subsistema'] = df['subsistema'].fillna('Desconocido')
        df['componente'] = df['componente'].fillna('Desconocido')
        
        # Derive additional columns
        df['has_telemetry'] = df['Trigger_type'].isin(['Telemetria', 'Mixto'])
        df['has_tribology'] = df['Trigger_type'].isin(['Tribologia', 'Mixto'])
        df['Month'] = df['Timestamp'].dt.to_period('M')
        
        logger.info(f"Loaded {len(df)} alerts for client {client}")
        return df
    
    except Exception as e:
        logger.error(f"Error loading alerts data: {e}")
        return pd.DataFrame()


def load_telemetry_values(client: str) -> pd.DataFrame:
    """
    Load telemetry values in wide format (one column per sensor).
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with telemetry values (Fecha, Unit, sensor columns)
    """
    if client.lower() != 'cda':
        logger.warning(f"Telemetry data is only available for CDA client. Requested: {client}")
        return pd.DataFrame()
    
    file_path = Path(f"data/telemetry/silver/{client.lower()}/telemetry_values_wide.parquet")
    logger.info(f"Loading telemetry values from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Telemetry values file not found: {file_path}")
        return pd.DataFrame()
    
    try:
        df = safe_read_parquet(file_path)
        df['Fecha'] = pd.to_datetime(df['Fecha'])
        logger.info(f"Loaded {len(df)} telemetry value records")
        return df
    
    except Exception as e:
        logger.error(f"Error loading telemetry values: {e}")
        return pd.DataFrame()


def load_telemetry_states(client: str) -> pd.DataFrame:
    """
    Load telemetry states (operational state, payload state).
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with telemetry states (Fecha, Unit, Estado, EstadoCarga)
    """
    if client.lower() != 'cda':
        logger.warning(f"Telemetry states is only available for CDA client. Requested: {client}")
        return pd.DataFrame()
    
    file_path = Path(f"data/telemetry/silver/{client.lower()}/telemetry_states.parquet")
    logger.info(f"Loading telemetry states from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Telemetry states file not found: {file_path}")
        return pd.DataFrame()
    
    try:
        df = safe_read_parquet(file_path)
        df['Fecha'] = pd.to_datetime(df['Fecha'])
        logger.info(f"Loaded {len(df)} telemetry state records")
        return df
    
    except Exception as e:
        logger.error(f"Error loading telemetry states: {e}")
        return pd.DataFrame()


def load_telemetry_limits(client: str) -> pd.DataFrame:
    """
    Load telemetry limits configuration.
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with limits (Unit, Feature, Estado, EstadoCarga, Limit_Lower, Limit_Upper)
    """
    if client.lower() != 'cda':
        logger.warning(f"Telemetry limits is only available for CDA client. Requested: {client}")
        return pd.DataFrame()
    
    file_path = Path(f"data/telemetry/silver/{client.upper()}/limits_config.parquet")
    logger.info(f"Loading telemetry limits from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Telemetry limits file not found: {file_path}")
        return pd.DataFrame()
    
    try:
        df = safe_read_parquet(file_path)
        logger.info(f"Loaded {len(df)} telemetry limit records")
        return df
    
    except Exception as e:
        logger.error(f"Error loading telemetry limits: {e}")
        return pd.DataFrame()


def load_telemetry_alerts_metadata(client: str) -> pd.DataFrame:
    """
    Load telemetry alerts metadata (includes Trigger field).
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with alerts metadata (AlertID, Trigger, etc.)
    """
    if client.lower() != 'cda':
        logger.warning(f"Telemetry alerts metadata is only available for CDA client. Requested: {client}")
        return pd.DataFrame()
    
    file_path = Path(f"data/telemetry/golden/{client.lower()}/alerts_data.csv")
    logger.info(f"Loading telemetry alerts metadata from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Telemetry alerts metadata file not found: {file_path}")
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(file_path)
        df['AlertID'] = df['AlertID'].astype(str)
        logger.info(f"Loaded {len(df)} telemetry alert metadata records")
        return df
    
    except Exception as e:
        logger.error(f"Error loading telemetry alerts metadata: {e}")
        return pd.DataFrame()


def load_component_mapping(client: str) -> pd.DataFrame:
    """
    Load component-to-feature mapping for telemetry sensors.
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with Component, PrimaryFeature, System, SubSystem, Meaning, RelatedFeatures
    """
    if client.lower() != 'cda':
        logger.warning(f"Component mapping is only available for CDA client. Requested: {client}")
        return pd.DataFrame()
    
    file_path = Path(f"data/telemetry/golden/{client.lower()}/component_mapping.parquet")
    logger.info(f"Loading component mapping from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Component mapping file not found: {file_path}")
        return pd.DataFrame()
    
    try:
        df = safe_read_parquet(file_path)
        logger.info(f"Loaded {len(df)} component mapping entries")
        return df
    
    except Exception as e:
        logger.error(f"Error loading component mapping: {e}")
        return pd.DataFrame()


def load_feature_names(client: str) -> Dict[str, str]:
    """
    Load feature names mapping (Variable code → Spanish name).
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        Dictionary mapping feature codes to Spanish names
    """
    if client.lower() != 'cda':
        logger.warning(f"Feature names is only available for CDA client. Requested: {client}")
        return {}
    
    file_path = Path("data/telemetry/features_mapping_name.json")
    logger.info(f"Loading feature names from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Feature names file not found: {file_path}")
        return {}
    
    try:
        import json
        with open(file_path, 'r', encoding='utf-8') as f:
            mapping = json.load(f)
        logger.info(f"Loaded {len(mapping)} feature names")
        return mapping
    
    except Exception as e:
        logger.error(f"Error loading feature names: {e}")
        return {}


def load_telemetry_alerts_detail_golden(client: str) -> pd.DataFrame:
    """
    Load pre-processed telemetry alert details from golden layer.
    This file contains all signals, limits, and GPS data for alerts in wide format.
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with columns:
        - AlertID, Unit, TimeStart, Trigger: Alert metadata
        - GPSLat, GPSLon, GPSElevation: GPS data
        - State: Operational state
        - {Feature}_Value: Sensor values
        - {Feature}_{Kind}_Limit: Limit values (Upper/Lower)
    """
    if client.lower() != 'cda':
        logger.warning(f"Telemetry alerts detail is only available for CDA client. Requested: {client}")
        return pd.DataFrame()
    
    file_path = Path(f"data/telemetry/golden/{client.lower()}/alerts_detail_wide_with_gps.csv")
    logger.info(f"Loading telemetry alerts detail from golden layer: {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Telemetry alerts detail file not found: {file_path}")
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(file_path)
        df['TimeStart'] = pd.to_datetime(df['TimeStart'])
        logger.info(f"Loaded {len(df)} telemetry alert detail records from golden layer")
        return df
    
    except Exception as e:
        logger.error(f"Error loading telemetry alerts detail: {e}")
        return pd.DataFrame()


def load_oil_classified(client: str) -> pd.DataFrame:
    """
    Load classified oil reports for alerts dashboard.
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with classified oil samples (sampleNumber, essay columns, report_status, etc.)
    """
    if client.lower() != 'cda':
        logger.warning(f"Oil classified data is only available for CDA client. Requested: {client}")
        return pd.DataFrame()
    
    file_path = Path(f"data/oil/golden/{client.lower()}/classified.parquet")
    logger.info(f"Loading oil classified data from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Oil classified file not found: {file_path}")
        return pd.DataFrame()
    
    try:
        df = safe_read_parquet(file_path)
        logger.info(f"Loaded {len(df)} classified oil reports")
        return df
    
    except Exception as e:
        logger.error(f"Error loading oil classified data: {e}")
        return pd.DataFrame()



# ========================================
# TELEMETRY HEALTH DASHBOARD LOADERS
# ========================================

def load_telemetry_unit_health(client: str) -> pd.DataFrame:
    """
    Load unit health assessments from golden layer.
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with unit-level health (overall_status, priority_score, executive_summary, etc.)
    """
    if client.lower() != 'cda':
        logger.warning(f"Telemetry unit health only available for CDA client. Requested: {client}")
        return pd.DataFrame()

    base = Path(f"data/telemetry/golden/{client.lower()}/unit_health")
    logger.info(f"Loading telemetry unit health from {base}")

    if not base.exists():
        logger.warning(f"Unit health path not found: {base}")
        return pd.DataFrame()

    try:
        df = safe_read_parquet(base)
        logger.info(f"Loaded {len(df)} unit health records")
        return df
    except Exception as e:
        logger.error(f"Error loading telemetry unit health: {e}")
        return pd.DataFrame()


def load_telemetry_system_health(client: str) -> pd.DataFrame:
    """
    Load system health assessments from golden layer.
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with system-level health (system_score, system_status, explanation, etc.)
    """
    if client.lower() != 'cda':
        logger.warning(f"Telemetry system health only available for CDA client. Requested: {client}")
        return pd.DataFrame()

    base = Path(f"data/telemetry/golden/{client.lower()}/system_health")
    logger.info(f"Loading telemetry system health from {base}")

    if not base.exists():
        logger.warning(f"System health path not found: {base}")
        return pd.DataFrame()

    try:
        df = safe_read_parquet(base)
        logger.info(f"Loaded {len(df)} system health records")
        return df
    except Exception as e:
        logger.error(f"Error loading telemetry system health: {e}")
        return pd.DataFrame()


def load_telemetry_deviation_results(client: str) -> pd.DataFrame:
    """
    Load deviation analysis results from golden layer.
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with per-signal deviation risk scores and abnormal percentages
    """
    if client.lower() != 'cda':
        return pd.DataFrame()

    base = Path(f"data/telemetry/golden/{client.lower()}/technique_results/deviation")
    if not base.exists():
        logger.warning(f"Deviation results path not found: {base}")
        return pd.DataFrame()

    try:
        df = safe_read_parquet(base)
        logger.info(f"Loaded {len(df)} deviation results")
        return df
    except Exception as e:
        logger.error(f"Error loading deviation results: {e}")
        return pd.DataFrame()


def load_telemetry_events(client: str) -> pd.DataFrame:
    """
    Load event analysis results from golden layer.
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with abnormal episodes (duration, severity, classification)
    """
    if client.lower() != 'cda':
        return pd.DataFrame()

    base = Path(f"data/telemetry/golden/{client.lower()}/technique_results/events")
    if not base.exists():
        logger.warning(f"Events path not found: {base}")
        return pd.DataFrame()

    try:
        df = safe_read_parquet(base)
        logger.info(f"Loaded {len(df)} event records")
        return df
    except Exception as e:
        logger.error(f"Error loading events: {e}")
        return pd.DataFrame()


def load_telemetry_trends(client: str) -> pd.DataFrame:
    """
    Load trend analysis results from golden layer.
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with trend significance, slopes, and interpretations
    """
    if client.lower() != 'cda':
        return pd.DataFrame()

    base = Path(f"data/telemetry/golden/{client.lower()}/technique_results/trend")
    if not base.exists():
        logger.warning(f"Trend results path not found: {base}")
        return pd.DataFrame()

    try:
        df = safe_read_parquet(base)
        logger.info(f"Loaded {len(df)} trend results")
        return df
    except Exception as e:
        logger.error(f"Error loading trend results: {e}")
        return pd.DataFrame()


def load_telemetry_baselines(client: str) -> pd.DataFrame:
    """
    Load telemetry baselines from silver layer.
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with percentile thresholds per model_specification/signal/state
    """
    if client.lower() != 'cda':
        return pd.DataFrame()

    baselines_dir = Path(f"data/telemetry/silver/{client.lower()}/baselines")
    if not baselines_dir.exists():
        logger.warning(f"Baselines directory not found: {baselines_dir}")
        return pd.DataFrame()

    try:
        baseline_files = sorted(baselines_dir.glob('baseline_*.parquet'))
        if not baseline_files:
            logger.warning("No baseline files found")
            return pd.DataFrame()
        file_path = baseline_files[-1]
        df = safe_read_parquet(file_path)
        logger.info(f"Loaded {len(df)} baseline records from {file_path.name}")
        return df
    except Exception as e:
        logger.error(f"Error loading telemetry baselines: {e}")
        return pd.DataFrame()


def load_silver_telemetry_week(client: str, week: int, year: int) -> pd.DataFrame:
    """
    Load silver layer telemetry data for a specific week.
    
    Args:
        client: Client identifier (e.g., 'cda')
        week: Week number (1-53)
        year: Year (e.g., 2026)
    
    Returns:
        DataFrame with raw sensor data (wide format with states)
    """
    if client.lower() != 'cda':
        return pd.DataFrame()

    file_path = Path(f"data/telemetry/silver/{client.lower()}/Telemetry_Wide_With_States/Week{week:02d}Year{year}.parquet")

    if not file_path.exists():
        return pd.DataFrame()

    try:
        df = safe_read_parquet(file_path)
        if 'Fecha' in df.columns:
            df['Fecha'] = pd.to_datetime(df['Fecha'])
        return df
    except Exception as e:
        logger.error(f"Error loading silver telemetry week: {e}")
        return pd.DataFrame()


def load_maintenance_week(client: str, week: str) -> pd.DataFrame:
    """
    Load maintenance data for a specific week.
    
    Args:
        client: Client identifier (e.g., 'cda')
        week: Week identifier (e.g., '01-2025')
    
    Returns:
        DataFrame with maintenance records for the week
    """
    if client.lower() != 'cda':
        logger.warning(f"Maintenance data is only available for CDA client. Requested: {client}")
        return pd.DataFrame()
    
    file_path = Path(f"data/mantentions/golden/{client.lower()}/{week}.csv")
    logger.info(f"Loading maintenance data from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Maintenance file not found for week {week}: {file_path}")
        return pd.DataFrame()
    
    try:
        df = pd.read_csv(file_path)
        logger.info(f"Loaded {len(df)} maintenance records for week {week}")
        return df
    
    except Exception as e:
        logger.error(f"Error loading maintenance data: {e}")
        return pd.DataFrame()


# =============================================================================
# MAINTENANCE / MANTENCIONES DATA LOADERS
# =============================================================================

def _get_mantentions_data_path(client: str = "cda") -> Optional[Path]:
    """
    Get the path to the mantentions data directory following production architecture.
    
    Args:
        client: Client name (default: "cda"). Can be overridden by CLIENT_NAME env var.
        
    Returns:
        Path to data/mantentions/golden/{client}/Maintance_Labeler_Views/ or None if not found
    """
    import os
    
    # Get client from environment variable if available
    client = os.getenv("CLIENT_NAME", client)
    
    # Get project root (3 levels up from this file)
    base_path = Path(__file__).parent.parent.parent
    
    # Try both lowercase and uppercase variants for compatibility
    # Production structure: data/mantentions/golden/{client}/Maintance_Labeler_Views/
    client_lower = client.lower()
    client_upper = client.upper()
    
    # Try lowercase first (preferred convention)
    data_path = base_path / "data" / "mantentions" / "golden" / client_lower / "Maintance_Labeler_Views"
    if data_path.exists():
        logger.info(f"Using mantentions data path: {data_path}")
        return data_path
    
    # Try uppercase if lowercase doesn't exist
    data_path = base_path / "data" / "mantentions" / "golden" / client_upper / "Maintance_Labeler_Views"
    if data_path.exists():
        logger.info(f"Using mantentions data path: {data_path}")
        return data_path
    
    # No fallback - if data doesn't exist for client, return None
    logger.warning(f"No mantentions data found for client '{client}'. Checked paths: {client_lower}, {client_upper}")
    return None


def load_maintenance_actions_all_equipment(client: str = "cda", base_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Load detailed maintenance actions for all equipment from query_3_actions_all_equipment.parquet.
    
    Args:
        client: Client name (default: "cda")
        base_path: Base path override. If None, uses production structure.
        
    Returns:
        DataFrame with maintenance actions (659 rows, 21 columns)
        Columns: action_id, job_id, record_id, machine_id, machine_code, event_ts, 
                 change_date, action_type_name, job_system_name, job_subsystem_name,
                 action_subsystem_name, action_system_name, component_names, component_count,
                 target_level, action_detail_raw, action_detail_clean, action_detail_source,
                 action_detail_version, source_system, record_original_text
    """
    if base_path is None:
        base_path = _get_mantentions_data_path(client)
        if base_path is None:
            logger.warning(f"No maintenance data available for client: {client}")
            return pd.DataFrame()
    
    file_path = base_path / "query_3_actions_all_equipment.parquet"
    
    try:
        logger.info(f"Loading maintenance actions from {file_path}")
        df = pd.read_parquet(file_path)
        
        # Convert date strings to datetime (UTC to handle mixed timezones)
        df['event_ts'] = pd.to_datetime(df['event_ts'], utc=True)
        df['change_date'] = pd.to_datetime(df['change_date'], utc=True)
        
        logger.info(f"Loaded {len(df)} maintenance actions for {df['machine_code'].nunique()} machines")
        return df
    except FileNotFoundError:
        logger.error(f"Maintenance actions file not found: {file_path}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Error loading maintenance actions: {e}")
        return pd.DataFrame()


def load_business_kpis(client: str = "cda", base_path: Optional[Path] = None) -> pd.DataFrame:
    """
    Load pre-calculated business KPIs from query_4_business_kpis.parquet.
    
    Args:
        client: Client name (default: "cda")
        base_path: Base path override. If None, uses production structure.
        
    Returns:
        DataFrame with business KPIs (11 rows - one per machine, 18 columns)
        Columns: machine_code, machine_id, equipment_status, has_ongoing_maintenance,
                 last_ongoing_date, days_since_last_maintenance, last_action_date,
                 total_actions_70d, ongoing_actions_70d, downtime_hours_70d,
                 maintenance_frequency_per_day, action_types_70d, top_3_components,
                 inspections_70d, replacements_70d, repairs_70d, maintenances_70d,
                 reference_date
    """
    if base_path is None:
        base_path = _get_mantentions_data_path(client)
        if base_path is None:
            logger.warning(f"No business KPIs data available for client: {client}")
            return pd.DataFrame()
    
    file_path = base_path / "query_4_business_kpis.parquet"
    
    try:
        logger.info(f"Loading business KPIs from {file_path}")
        df = pd.read_parquet(file_path)
        
        # Convert date columns to datetime
        if 'last_action_date' in df.columns:
            df['last_action_date'] = pd.to_datetime(df['last_action_date'])
        if 'reference_date' in df.columns:
            df['reference_date'] = pd.to_datetime(df['reference_date'])
        if 'last_ongoing_date' in df.columns:
            df['last_ongoing_date'] = pd.to_datetime(df['last_ongoing_date'])
        
        logger.info(f"Loaded KPIs for {len(df)} machines")
        return df
    except FileNotFoundError:
        logger.error(f"Business KPIs file not found: {file_path}")
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Error loading business KPIs: {e}")
        return pd.DataFrame()