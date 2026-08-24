"""
Data loaders for Multi-Technical-Alerts.

Load data from different layers:
- Bronze layer: Raw data (data/oil/bronze/{client}/)
- Silver layer: Harmonized data (data/oil/silver/{CLIENT}.parquet)
- Golden layer: Analysis-ready outputs (data/oil/golden/{client}/)
"""

import pandas as pd
import json
import os
import warnings
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from src.utils.logger import get_logger
from src.utils.file_utils import list_excel_files, safe_read_excel, safe_read_parquet
from src.utils.date_utils import to_utc_naive
from src.data.fast_io import (
    read_csv as fast_read_csv,
    read_csv_filtered as fast_read_csv_filtered,
    read_parquet as fast_read_parquet,
)

logger = get_logger(__name__)


def _data_path(*parts: str) -> Path:
    """Resolve dashboard data below the mounted/configured data root."""
    return Path(os.getenv("DASHBOARD_DATA_ROOT", "data")).expanduser().joinpath(*parts)


# These files are read by several Dash callbacks during a single interaction
# (filters, tables, charts and detail cards).  Keep one process-local parsed
# copy and return defensive copies from the public loaders.  The cache is
# cleared when the dashboard process restarts, which is also the normal data
# refresh boundary for the mounted data directory.


@lru_cache(maxsize=16)
def _load_essays_mapping_cached(path: str, mtime_ns: int, size: int) -> pd.DataFrame:
    """Read one mapping-file generation; callers receive defensive copies."""
    logger.info(f"Loading essays mapping from {path}")
    df = pd.read_excel(path, engine='openpyxl').dropna()
    logger.info(f"Loaded {len(df)} essay mappings")
    return df


def load_essays_mapping(file_path: str | Path = "essays_elements.xlsx") -> pd.DataFrame:
    """
    Load essays mapping table for harmonizing column names.
    
    Args:
        file_path: Path to essays mapping Excel file
    
    Returns:
        DataFrame with Element → ElementNameSpanish mapping
    """
    path = Path(file_path)
    stat = path.stat()
    return _load_essays_mapping_cached(
        str(path), stat.st_mtime_ns, stat.st_size
    ).copy(deep=True)


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


def load_component_hours(file_path: str | Path) -> pd.DataFrame:
    """
    Load cleaned component hours (horómetro) from Parquet file.
    
    The file contains component-level usage hours per sample, with cleaned values
    that interpolate missing readings.
    
    Args:
        file_path: Path to cleaned_component_hours.parquet
    
    Returns:
        DataFrame with columns: client, unitId, componentName, sampleDate,
        componentHours, componentHours_cleaned
    """
    file_path = Path(file_path)
    logger.info(f"Loading component hours from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Component hours file not found: {file_path}")
        return pd.DataFrame()
    
    df = safe_read_parquet(file_path)
    
    if df.empty:
        logger.warning("Component hours dataframe is empty")
        return pd.DataFrame()
    
    # Ensure sampleDate is datetime
    if 'sampleDate' in df.columns:
        df['sampleDate'] = pd.to_datetime(df['sampleDate'])
    
    logger.info(f"Loaded {len(df)} component hours records ({df['unitId'].nunique()} units, {df['componentName'].nunique()} components)")
    return df


def get_latest_component_hours(file_path: str | Path) -> pd.DataFrame:
    """
    Get the most recent component hours for each unit+component combination.
    
    Args:
        file_path: Path to cleaned_component_hours.parquet
    
    Returns:
        DataFrame with the latest horómetro reading per unit+component
    """
    df = load_component_hours(file_path)
    
    if df.empty:
        return pd.DataFrame()
    
    # Get latest sample per unit+component
    idx = df.groupby(['unitId', 'componentName'])['sampleDate'].idxmax()
    latest = df.loc[idx].copy()
    
    logger.info(f"Got latest component hours: {len(latest)} records")
    return latest


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


def _load_stewart_limits_four_uncached(file_path: str | Path) -> Dict:
    """
    Load pre-computed four-limit Stewart Limits (LIC/LIM/LSM/LSC) from Parquet file (v2.8).

    Args:
        file_path: Path to stewart_limits_four.parquet

    Returns:
        Dictionary with limits structure:
        {client: {machine: {component: {essay: {oilHourRange: {LIC, LIM, LSM, LSC, min_value,
        GroupElement, sample_count, calculation_date}}}}}}

        LIC/LIM are None (not 0) whenever the source column is null - a missing lower limit
        must never be treated as a lower limit of zero.
    """
    file_path = Path(file_path)
    logger.info(f"Loading four-limit Stewart Limits from {file_path}")

    if not file_path.exists():
        logger.warning(f"Four-limit Stewart Limits file not found: {file_path}")
        return {}

    df = safe_read_parquet(file_path)

    if df.empty:
        logger.warning("Four-limit Stewart Limits dataframe is empty")
        return {}

    def _nullable_float(value) -> Optional[float]:
        return None if pd.isna(value) else float(value)

    limits: Dict = {}
    for _, row in df.iterrows():
        client = row['client']
        machine = row['machine']
        component = row['component']
        essay = row['essay']
        oil_hour_range = row.get('oilHourRange', 'ALL')

        limits.setdefault(client, {}).setdefault(machine, {}).setdefault(component, {}).setdefault(essay, {})

        limits[client][machine][component][essay][oil_hour_range] = {
            'LIC': _nullable_float(row.get('LIC')),
            'LIM': _nullable_float(row.get('LIM')),
            'LSM': _nullable_float(row.get('LSM')),
            'LSC': _nullable_float(row.get('LSC')),
            'min_value': _nullable_float(row.get('min_value')),
            'GroupElement': row.get('GroupElement'),
            'sample_count': row.get('sample_count', 0),
            'calculation_date': row.get('calculation_date'),
        }

    logger.info(f"Loaded four-limit Stewart Limits for {len(limits)} clients")
    return limits


@lru_cache(maxsize=16)
def _load_stewart_limits_four_cached(path: str, mtime_ns: int, size: int) -> Dict:
    """Cache the derived four-limit dictionary by source generation."""
    return _load_stewart_limits_four_uncached(path)


def load_stewart_limits_four(file_path: str | Path) -> Dict:
    """Return four-limit Stewart data without reparsing unchanged Parquet."""
    path = Path(file_path)
    if not path.exists():
        return {}
    stat = path.stat()
    return _load_stewart_limits_four_cached(
        str(path), stat.st_mtime_ns, stat.st_size
    )


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

@lru_cache(maxsize=8)
def _load_alerts_data_cached(client: str, path: str, mtime_ns: int, size: int) -> pd.DataFrame:
    """
    Load consolidated alerts data for a specific client.
    
    Args:
        client: Client identifier (e.g., 'cda', 'emin')
    
    Returns:
        DataFrame with alerts data including derived columns (has_telemetry, has_tribology, Month)
    """
    file_path = Path(path)
    logger.info(f"Loading alerts data from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Alerts file not found: {file_path}")
        return pd.DataFrame()
    
    try:
        df = fast_read_csv(file_path)
        
        # Normalize event timestamps to timezone-naive UTC (W34-06: the single
        # normalization point — every comparison, window and filter downstream
        # stays in this UTC-naive form; conversion to local time happens only
        # at display time, via to_local_naive()/format_local()). Capstone
        # emits ISO timestamps with offsets while the Dash date picker emits
        # naive calendar dates; one representation avoids aware/naive
        # comparisons.
        df['Timestamp'] = to_utc_naive(df['Timestamp'])
        
        # Fill sistema, subsistema and componente missing values
        df['sistema'] = df['sistema'].fillna('Desconocido')
        df['subsistema'] = df['subsistema'].fillna('Desconocido')
        df['componente'] = df['componente'].fillna('Desconocido')
        if 'TribologyID' in df.columns:
            df['TribologyID'] = (
                df['TribologyID']
                .fillna('')
                .astype(str)
                .str.replace(r'\.0$', '', regex=True)
            )
        
        # Derive additional columns
        df['has_telemetry'] = df['Trigger_type'].isin(['Telemetria', 'Mixto'])
        df['has_tribology'] = df['Trigger_type'].isin(['Tribologia', 'Mixto'])
        df['Month'] = df['Timestamp'].dt.to_period('M')
        
        logger.info(f"Loaded {len(df)} alerts for client {client}")
        return df
    
    except Exception as e:
        logger.error(f"Error loading alerts data: {e}")
        return pd.DataFrame()


def load_alerts_data(client: str) -> pd.DataFrame:
    """Return alerts data cached by the current source generation."""
    file_path = _data_path("alerts", "golden", (client or '').lower(), "consolidated_alerts.csv")
    if not file_path.exists():
        return pd.DataFrame()
    stat = file_path.stat()
    return _load_alerts_data_cached(
        (client or '').lower(), str(file_path), stat.st_mtime_ns, stat.st_size
    ).copy(deep=True)


def load_telemetry_values(client: str) -> pd.DataFrame:
    """
    Load telemetry values in wide format (one column per sensor).
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with telemetry values (Fecha, Unit, sensor columns)
    """
    file_path = _data_path("telemetry", "silver", client.lower(), "telemetry_values_wide.parquet")
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
    file_path = _data_path("telemetry", "silver", client.lower(), "telemetry_states.parquet")
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
    file_path = _data_path("telemetry", "silver", client.upper(), "limits_config.parquet")
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
    file_path = _data_path("telemetry", "golden", client.lower(), "alerts_data.csv")
    logger.info(f"Loading telemetry alerts metadata from {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Telemetry alerts metadata file not found: {file_path}")
        return pd.DataFrame()
    
    try:
        df = fast_read_csv(file_path)
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
    file_path = _data_path("telemetry", "golden", client.lower(), "component_mapping.parquet")
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
    file_path = _data_path("telemetry", "features_mapping_name.json")
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


@lru_cache(maxsize=8)
def _load_telemetry_alerts_detail_golden_cached(
    client: str, path: str, mtime_ns: int, size: int
) -> pd.DataFrame:
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
    file_path = Path(path)
    logger.info(f"Loading telemetry alerts detail from golden layer: {file_path}")
    
    if not file_path.exists():
        logger.warning(f"Telemetry alerts detail file not found: {file_path}")
        return pd.DataFrame()
    
    try:
        df = fast_read_csv(file_path)
        # W34-06: same UTC-naive normalization point as consolidated_alerts's
        # Timestamp column, so the alert instant and its telemetry evidence
        # window compare against the same clock.
        df['TimeStart'] = to_utc_naive(df['TimeStart'])
        logger.info(f"Loaded {len(df)} telemetry alert detail records from golden layer")
        return df
    
    except Exception as e:
        logger.error(f"Error loading telemetry alerts detail: {e}")
        return pd.DataFrame()


def load_telemetry_alerts_detail_golden(client: str, *, copy: bool = True) -> pd.DataFrame:
    """Return cached golden alert evidence with optional zero-copy access.

    The detail callback only filters and reads the frame.  It can opt out of a
    75MB defensive copy while callers that may mutate data retain the safe
    default.
    """
    file_path = _data_path(
        "telemetry", "golden", (client or '').lower(), "alerts_detail_wide_with_gps.csv"
    )
    if not file_path.exists():
        return pd.DataFrame()
    stat = file_path.stat()
    frame = _load_telemetry_alerts_detail_golden_cached(
        (client or '').lower(), str(file_path), stat.st_mtime_ns, stat.st_size
    )
    return frame.copy(deep=True) if copy else frame


@lru_cache(maxsize=128)
def _load_telemetry_alert_detail_for_alert_cached(
    client: str,
    path: str,
    mtime_ns: int,
    size: int,
    identifiers: tuple[str, ...],
    unit_id: str,
) -> pd.DataFrame:
    """Cache one filtered alert generation for fast back/forward navigation."""
    file_path = Path(path)
    try:
        frame = fast_read_csv_filtered(
            file_path,
            {"AlertID": identifiers, "Unit": (unit_id,)},
        )
        if "TimeStart" in frame.columns:
            frame["TimeStart"] = to_utc_naive(frame["TimeStart"])
        return frame
    except Exception as exc:
        logger.warning("Filtered telemetry detail read failed; using cached source: %s", exc)
        frame = load_telemetry_alerts_detail_golden(client, copy=False)
        if frame.empty:
            return frame
        alert_keys = frame["AlertID"].astype(str).str.strip()
        unit_keys = frame["Unit"].astype(str).str.strip()
        return frame.loc[alert_keys.isin(identifiers) & unit_keys.eq(unit_id)]


def load_telemetry_alert_detail_for_alert(
    client: str,
    alert_ids: list[str] | tuple[str, ...],
    unit_id: str,
) -> pd.DataFrame:
    """Read only one alert/unit from the wide telemetry evidence CSV.

    Polars can push these predicates into the CSV scan.  With pandas the
    function falls back to the cached full reader and applies the same filter,
    preserving behavior on installations that have not installed Polars yet.
    """

    identifiers = tuple(str(value).strip() for value in alert_ids if str(value).strip())
    unit_id = str(unit_id or "").strip()
    if not identifiers or not unit_id:
        return pd.DataFrame()
    file_path = _data_path(
        "telemetry", "golden", (client or '').lower(), "alerts_detail_wide_with_gps.csv"
    )
    if not file_path.exists():
        return pd.DataFrame()
    stat = file_path.stat()
    return _load_telemetry_alert_detail_for_alert_cached(
        (client or '').lower(), str(file_path), stat.st_mtime_ns, stat.st_size,
        identifiers, unit_id,
    )


@lru_cache(maxsize=8)
def _load_oil_classified_cached(client: str) -> pd.DataFrame:
    """
    Load classified oil reports for alerts dashboard.
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with classified oil samples (sampleNumber, essay columns, report_status, etc.)
    """
    file_path = _data_path("oil", "golden", client.lower(), "classified.parquet")
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


def load_oil_classified(client: str) -> pd.DataFrame:
    """Return cached classified oil data as a defensive copy."""
    return _load_oil_classified_cached((client or '').lower()).copy(deep=True)


@lru_cache(maxsize=8)
def _load_analisis_inteligente_cached(client: str) -> pd.DataFrame:
    """
    Load AI-generated risk analysis/recommendation for Predictivo -> Evidencia
    (one row per Unit per Fecha). Callers filter to a single Unit and take the
    most recent Fecha.

    Args:
        client: Client identifier (e.g., 'cda')

    Returns:
        DataFrame with columns including Unit, Fecha, diagnostico,
        causa_probable, acciones. Empty DataFrame if the file is missing.
    """
    file_path = _data_path("predictive", "golden", client.lower(), "analisis_inteligente.parquet")
    logger.info(f"Loading analisis inteligente data from {file_path}")

    if not file_path.exists():
        logger.warning(f"Analisis inteligente file not found: {file_path}")
        return pd.DataFrame()

    try:
        df = safe_read_parquet(file_path)
        if "Fecha" in df.columns:
            df["Fecha"] = pd.to_datetime(df["Fecha"])
        logger.info(f"Loaded {len(df)} analisis inteligente rows")
        return df

    except Exception as e:
        logger.error(f"Error loading analisis inteligente data: {e}")
        return pd.DataFrame()


def load_analisis_inteligente(client: str) -> pd.DataFrame:
    """Return cached AI analysis data as a defensive copy."""
    return _load_analisis_inteligente_cached((client or '').lower()).copy(deep=True)


def _filter_analisis_inteligente_component(df: pd.DataFrame, component: str = None) -> pd.DataFrame:
    """Narrow analisis_inteligente rows to `component` when the column supports it.

    Falls back to the unfiltered frame if `componente` is absent or the filter
    would drop every row, so callers on clients/files without this column
    keep working exactly as before.
    """
    if not component or "componente" not in df.columns:
        return df
    filtered = df[df["componente"].astype(str).str.lower() == str(component).lower()]
    return filtered if not filtered.empty else df


def get_latest_analisis_inteligente(client: str, component: str = None) -> pd.DataFrame:
    """One row per Unit: the most recent analisis_inteligente.parquet row.

    Used by Predictivo -> Estado de Flota (REQ-PR-04) to read `estado` per
    unit instead of computing status from ranking thresholds, mirroring how
    Evidencia (REQ-PR-03) already reads this file.
    """
    df = load_analisis_inteligente(client)
    if df.empty or "Unit" not in df.columns:
        return df
    df = _filter_analisis_inteligente_component(df, component)
    if "Fecha" in df.columns:
        df = df.sort_values("Fecha")
    return df.groupby("Unit", as_index=False).last()


def get_model_run_date(client: str, component: str = None):
    """Latest `Fecha` in analisis_inteligente.parquet — the model's last run date.

    Shared by Estado de Flota and Evidencia (REQ-PR-08) so both tabs always
    show the same date. Returns None if unavailable.
    """
    df = load_analisis_inteligente(client)
    if df.empty or "Fecha" not in df.columns:
        return None
    df = _filter_analisis_inteligente_component(df, component)
    if df.empty:
        return None
    return df["Fecha"].max()


@lru_cache(maxsize=8)
def _load_machine_status_cached(client: str) -> pd.DataFrame:
    """
    Load machine-level status aggregations for the oil dashboards (fleet
    overview KPIs, heatmap table, machine detail card).

    Args:
        client: Client identifier (e.g., 'cda')

    Returns:
        DataFrame with columns: unit_id, overall_status, machine_ai_recommendation, etc.
    """
    file_path = _data_path("oil", "golden", client.lower(), "machine_status.parquet")
    logger.info(f"Loading machine status from {file_path}")

    if not file_path.exists():
        logger.warning(f"Machine status file not found: {file_path}")
        return pd.DataFrame()

    try:
        df = safe_read_parquet(file_path)
        logger.info(f"Loaded {len(df)} machine status records")
        return df

    except Exception as e:
        logger.error(f"Error loading machine status data: {e}")
        return pd.DataFrame()


def load_machine_status_for_client(client: str) -> pd.DataFrame:
    """Return cached machine status data as a defensive copy."""
    return _load_machine_status_cached((client or '').lower()).copy(deep=True)


# ========================================
# TELEMETRY HEALTH DASHBOARD LOADERS
# ========================================

def _filter_latest_week(df: pd.DataFrame) -> pd.DataFrame:
    """Filter DataFrame to only the latest year/week partition."""
    if df.empty:
        return df
    if 'year' in df.columns and 'week' in df.columns:
        # Convert categorical to numeric if needed (from Hive partitioning)
        year_col = df['year'].astype(int)
        week_col = df['week'].astype(int)
        latest_year = year_col.max()
        latest_week = week_col[year_col == latest_year].max()
        df = df[(year_col == latest_year) & (week_col == latest_week)]
    return df


def _latest_telemetry_partition(base: Path) -> Path:
    """Select one materialized year/week partition before reading parquet.

    The S3 export can contain an older flat parquet tree alongside the newer
    Spark-style ``year=YYYY/week=WW`` output.  Reading both trees at once can
    fail when schemas evolved (for example, a list column becoming a string),
    so the dashboard must select the latest partition first.
    """
    if not base.is_dir():
        return base
    partitions = []
    for year_dir in base.glob("year=*"):
        if not year_dir.is_dir():
            continue
        try:
            year = int(year_dir.name.split("=", 1)[1])
        except (IndexError, ValueError):
            continue
        for week_dir in year_dir.glob("week=*"):
            if not week_dir.is_dir():
                continue
            try:
                week = int(week_dir.name.split("=", 1)[1])
            except (IndexError, ValueError):
                continue
            partitions.append((year, week, week_dir))
    if not partitions:
        return base
    return max(partitions, key=lambda item: (item[0], item[1]))[2]


def _keep_latest_execution(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Keep one row per entity when a partition contains repeated runs."""
    if df.empty or not keys:
        return df
    timestamp_col = next(
        (column for column in ("execution_timestamp", "evaluation_timestamp") if column in df.columns),
        None,
    )
    available_keys = [key for key in keys if key in df.columns]
    if not timestamp_col or not available_keys:
        return df
    result = df.copy()
    result["__telemetry_execution_ts"] = pd.to_datetime(result[timestamp_col], errors="coerce")
    if result["__telemetry_execution_ts"].notna().any():
        result = result.sort_values("__telemetry_execution_ts")
        result = result.drop_duplicates(subset=available_keys, keep="last")
    return result.drop(columns=["__telemetry_execution_ts"], errors="ignore")


def _load_latest_telemetry_output(
    paths: list[Path],
    label: str,
    dedupe_keys: list[str] | None = None,
    columns: list[str] | None = None,
) -> pd.DataFrame:
    """Read the newest partition from the first available output location."""
    base = next((path for path in paths if path.exists()), None)
    if base is None:
        logger.warning("%s path not found: %s", label, paths[0])
        return pd.DataFrame()
    target = _latest_telemetry_partition(base)
    try:
        # Event output can contain millions of rows.  Read only the fields
        # consumed by the report and chart layer when a projection is given.
        read_columns = columns
        if columns:
            try:
                import pyarrow.parquet as pq
                schema_path = target
                if schema_path.is_dir():
                    schema_path = next(schema_path.rglob("*.parquet"), schema_path)
                available = set(pq.ParquetFile(schema_path).schema.names)
                read_columns = [column for column in columns if column in available]
            except Exception:
                # Let pandas perform the read if schema inspection is not
                # available (legacy parquet engines may not expose it).
                read_columns = columns
        df = safe_read_parquet(target, columns=read_columns) if read_columns else safe_read_parquet(target)
        df = _filter_latest_week(df)
        df = _keep_latest_execution(df, dedupe_keys or [])
        logger.info("Loaded %s %s records from %s", len(df), label, target)
        return df
    except Exception as e:
        logger.error("Error loading %s: %s", label, e)
        return pd.DataFrame()


@lru_cache(maxsize=8)
def _load_telemetry_unit_health_cached(client: str) -> pd.DataFrame:
    """
    Load unit health assessments from golden layer.

    Args:
        client: Client identifier (e.g., 'cda')

    Returns:
        DataFrame with unit-level health (overall_status, priority_score, executive_summary, etc.)
    """
    base = _data_path("telemetry", "golden", client.lower(), "unit_health")
    logger.info(f"Loading telemetry unit health from {base}")

    if not base.exists():
        logger.warning(f"Unit health path not found: {base}")
        return pd.DataFrame()

    try:
        df = safe_read_parquet(_latest_telemetry_partition(base))
        df = _filter_latest_week(df)
        df = _keep_latest_execution(df, ["unit"])
        logger.info(f"Loaded {len(df)} unit health records")
        return df
    except Exception as e:
        logger.error(f"Error loading telemetry unit health: {e}")
        return pd.DataFrame()


def load_telemetry_unit_health(client: str) -> pd.DataFrame:
    """Return cached telemetry unit health data as a defensive copy.

    Cached because this is on the post-login critical path (Resumen ->
    General's overview aggregator calls it on every page mount / client
    switch) and involves a directory-partition scan plus a parquet read -
    not something to repeat on every login. A caller mutating the returned
    frame in place (e.g. reassigning a column) only affects its own copy.
    """
    return _load_telemetry_unit_health_cached((client or '').lower()).copy(deep=True)


def load_telemetry_system_health(client: str) -> pd.DataFrame:
    """
    Load system health assessments from golden layer.
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with system-level health (system_score, system_status, explanation, etc.)
    """
    base = _data_path("telemetry", "golden", client.lower(), "system_health")
    logger.info(f"Loading telemetry system health from {base}")

    if not base.exists():
        logger.warning(f"System health path not found: {base}")
        return pd.DataFrame()

    try:
        df = safe_read_parquet(_latest_telemetry_partition(base))
        df = _filter_latest_week(df)
        df = _keep_latest_execution(df, ["unit", "system"])
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
    root = _data_path("telemetry", "golden", client.lower())
    return _load_latest_telemetry_output(
        [root / "deviation_summary", root / "technique_results" / "deviation"],
        "deviation results",
        ["unit", "system", "signal"],
    )


def load_telemetry_events(client: str) -> pd.DataFrame:
    """
    Load event analysis results from golden layer.
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with abnormal episodes (duration, severity, classification)
    """
    root = _data_path("telemetry", "golden", client.lower())
    return _load_latest_telemetry_output(
        [root / "event_results", root / "technique_results" / "events"],
        "event records",
        columns=[
            "unit", "feature", "signal", "event_id", "event_group",
            "start_time", "end_time", "duration_minutes",
            "event_type_binary", "event_type_weighted", "execution_timestamp",
        ],
    )


def load_telemetry_trends(client: str) -> pd.DataFrame:
    """
    Load trend analysis results from golden layer.
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with trend significance, slopes, and interpretations
    """
    root = _data_path("telemetry", "golden", client.lower())
    return _load_latest_telemetry_output(
        [root / "trend_results", root / "technique_results" / "trend"],
        "trend results",
        ["unit", "system", "signal", "window_weeks"],
    )


def load_telemetry_baselines(client: str) -> pd.DataFrame:
    """
    Load telemetry baselines from silver layer.
    
    Args:
        client: Client identifier (e.g., 'cda')
    
    Returns:
        DataFrame with percentile thresholds per model_specification/signal/state
    """
    baselines_dir = _data_path("telemetry", "silver", client.lower(), "baselines")
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


def load_telemetry_manifest(client: str) -> dict:
    """
    Load pipeline manifest (latest.json) indicating the most recent evaluation.

    Returns dict with keys: evaluation_week, evaluation_year, execution_timestamp,
    silver_weeks_available, baseline_version. Returns empty dict if not found.
    """
    manifest_path = _data_path("telemetry", "golden", client.lower(), "latest.json")
    if not manifest_path.exists():
        logger.warning(f"Telemetry manifest not found: {manifest_path}")
        return {}

    try:
        import json
        with open(manifest_path, 'r', encoding='utf-8') as f:
            manifest = json.load(f)
        logger.info(f"Loaded manifest: week {manifest.get('evaluation_week')}/{manifest.get('evaluation_year')}")
        return manifest
    except Exception as e:
        logger.error(f"Error loading telemetry manifest: {e}")
        return {}


def load_telemetry_limits(client: str) -> pd.DataFrame:
    """
    Load computed limits from silver layer, falling back to baselines.

    Limits location: data/telemetry/silver/{client}/limits/limits_{YYYYMMDD}.parquet
    Fallback: data/telemetry/silver/{client}/baselines/baseline_{YYYYMMDD}.parquet

    Returns:
        DataFrame with percentile thresholds (P2, P5, P95, P98 at minimum)
    """
    # Try limits directory first (new schema)
    limits_dir = _data_path("telemetry", "silver", client.lower(), "limits")
    if limits_dir.exists():
        try:
            limit_files = sorted(limits_dir.glob('limits_*.parquet'))
            if limit_files:
                df = safe_read_parquet(limit_files[-1])
                logger.info(f"Loaded {len(df)} limit records from {limit_files[-1].name}")
                return df
        except Exception as e:
            logger.warning(f"Error loading limits, falling back to baselines: {e}")

    # Fallback to baselines
    return load_telemetry_baselines(client)


def load_silver_telemetry_week(
    client: str,
    week: int,
    year: int,
    columns: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Load silver layer telemetry data for a specific week.
    
    Args:
        client: Client identifier (e.g., 'cda')
        week: Week number (1-53)
        year: Year (e.g., 2026)
    
    Returns:
        DataFrame with raw sensor data (wide format with states)
    """
    file_path = _data_path(
        "telemetry", "silver", client.lower(), "Telemetry_Wide_With_States",
        f"Week{week:02d}Year{year}.parquet",
    )

    if not file_path.exists():
        return pd.DataFrame()

    try:
        read_columns = columns
        if columns:
            # Avoid loading the complete wide table for a single signal.  The
            # schema check also handles weeks where a legacy signal is absent.
            try:
                import pyarrow.parquet as pq
                available = set(pq.ParquetFile(file_path).schema.names)
                read_columns = [column for column in columns if column in available]
                if not {"Unit", "Fecha"}.issubset(read_columns):
                    return pd.DataFrame()
            except Exception:
                read_columns = columns
        df = fast_read_parquet(file_path, columns=read_columns) if read_columns else fast_read_parquet(file_path)
        if 'Fecha' in df.columns:
            df['Fecha'] = pd.to_datetime(df['Fecha'])
        return df
    except Exception as e:
        logger.error(f"Error loading silver telemetry week: {e}")
        return pd.DataFrame()


def load_telemetry_ai_comments(client: str, level: str) -> pd.DataFrame:
    """
    Load AI diagnostic comments from golden layer.

    Args:
        client: Client identifier (e.g., 'cda')
        level: One of 'signal', 'system', 'unit'

    Returns:
        DataFrame with AI comments for the specified level.
        Returns empty DataFrame if data not available.
    """
    root = _data_path("telemetry", "golden", client.lower())
    if level not in {"unit", "system", "signal"}:
        logger.warning("Unknown telemetry AI comment level: %s", level)
        return pd.DataFrame()

    # The current pipeline writes one directory per level.  The legacy
    # ``ai_comments/{level}_comments.parquet`` tree is kept only as fallback;
    # otherwise a stale week-26 comment can be joined to a week-30 health row.
    candidate_bases = [
        root / f"ai_{level}_comments",
        root / "ai_comments",
    ]
    dedupe_keys = {
        "unit": ["unit"],
        "system": ["unit", "system"],
        "signal": ["unit", "system", "signal"],
    }[level]

    try:
        for base in candidate_bases:
            if not base.exists():
                continue
            target = _latest_telemetry_partition(base)
            if target.is_file():
                parquet_target = target
            else:
                parquet_files = sorted(target.rglob("*.parquet"))
                parquet_target = target if parquet_files else None
            if parquet_target is None:
                continue

            df = safe_read_parquet(parquet_target)
            if df.empty:
                continue
            df = _filter_latest_week(df)
            df = _keep_latest_execution(df, dedupe_keys)
            logger.info(
                "Loaded %s %s AI comments from %s",
                len(df), level, target,
            )
            return df
        return pd.DataFrame()
    except Exception as e:
        logger.error(f"Error loading {level} AI comments: {e}")
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
    file_path = _data_path("mantentions", "golden", client.lower(), f"{week}.csv")
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
