"""
Table/data helpers for Telemetry Health Dashboard.

Build display DataFrames from golden layer outputs.
"""

import pandas as pd
import json
from typing import Optional


def build_fleet_priority_table(unit_health_df: pd.DataFrame) -> list:
    """
    Build priority table data sorted by priority_score descending.

    Returns list of dicts ready for DataTable.
    """
    if unit_health_df.empty:
        return []

    df = unit_health_df.copy()

    # Parse top_risk_systems JSON if needed
    if 'top_risk_systems' in df.columns:
        df['top_risk_systems'] = df['top_risk_systems'].apply(_parse_json_list)

    # Round numeric columns
    if 'priority_score' in df.columns:
        df['priority_score'] = df['priority_score'].round(1)
    if 'unit_score' in df.columns:
        df['unit_score'] = df['unit_score'].round(1)

    df = df.sort_values('priority_score', ascending=False)

    cols = ['unit', 'overall_status', 'priority_score', 'unit_score',
            'n_anormal_systems', 'n_alerta_systems', 'top_risk_systems']
    available = [c for c in cols if c in df.columns]

    return df[available].to_dict('records')


def build_system_risk_table(system_health_df: pd.DataFrame, unit: str) -> list:
    """
    Build system risk table for a specific unit, sorted by system_score descending.
    """
    if system_health_df.empty:
        return []

    df = system_health_df[system_health_df['unit'] == unit].copy()
    if df.empty:
        return []

    if 'system_score' in df.columns:
        df['system_score'] = df['system_score'].round(1)
    df = df.sort_values('system_score', ascending=False)

    cols = ['system', 'system_score', 'system_status', 'n_techniques_triggered',
            'top_signal', 'top_technique']
    available = [c for c in cols if c in df.columns]

    return df[available].to_dict('records')


def build_signal_overview_table(
    deviation_df: pd.DataFrame,
    events_df: pd.DataFrame,
    unit: str,
    system: Optional[str] = None
) -> list:
    """
    Build signal overview table combining deviation risk and event stats.

    Args:
        deviation_df: Deviation analysis results
        events_df: Event analysis results
        unit: Selected unit
        system: Optional system filter
    """
    if deviation_df.empty:
        return []

    dev = deviation_df[deviation_df['unit'] == unit].copy()
    if system:
        dev = dev[dev['system'] == system]
    if dev.empty:
        return []

    # Get latest evaluation per signal
    if 'evaluation_date' in dev.columns:
        dev = dev.sort_values('evaluation_date', ascending=False).drop_duplicates(subset=['signal'])

    # Summarize events per signal
    event_stats = {}
    if not events_df.empty:
        evt = events_df[events_df['unit'] == unit]
        if system:
            evt = evt[evt['system'] == system]
        if not evt.empty:
            event_stats = evt.groupby('signal').agg(
                total_events=('event_id', 'count'),
                max_episode=('duration_minutes', 'max')
            ).to_dict('index')

    rows = []
    for _, row in dev.iterrows():
        sig = row['signal']
        evt_info = event_stats.get(sig, {})
        rows.append({
            'signal': sig,
            'risk_score': round(row.get('risk_score', 0), 1),
            'status': row.get('status', 'Normal'),
            'abnormal_pct': round(row.get('abnormal_pct', 0), 2),
            'total_events': evt_info.get('total_events', 0),
            'max_episode': evt_info.get('max_episode', 0),
        })

    # Sort by risk_score descending
    rows.sort(key=lambda x: x['risk_score'], reverse=True)
    return rows


def build_signal_kpi(
    signal_name: str,
    deviation_df: pd.DataFrame,
    events_df: pd.DataFrame,
    trends_df: pd.DataFrame,
    unit: str
) -> dict:
    """
    Build KPI dictionary for a single signal.

    Returns dict with keys: total_events, warnings, longest_episode,
    trend_detected, trend_direction, trend_formula
    """
    kpi = {
        'total_events': 0,
        'warnings': 0,
        'longest_episode': 0,
        'trend_detected': 'No',
        'trend_direction': '-',
        'trend_formula': '-'
    }

    # Event stats
    if not events_df.empty:
        evt = events_df[(events_df['unit'] == unit) & (events_df['signal'] == signal_name)]
        if not evt.empty:
            kpi['total_events'] = len(evt)
            kpi['warnings'] = int((evt['event_type_weighted'] == 'warning').sum())
            kpi['longest_episode'] = int(evt['duration_minutes'].max())

    # Trend stats
    if not trends_df.empty:
        trnd = trends_df[
            (trends_df['unit'] == unit) &
            (trends_df['signal'] == signal_name) &
            (trends_df['is_significant'] == True) &
            (trends_df['is_good_fit'] == True)
        ]
        if not trnd.empty:
            best = trnd.sort_values('r2', ascending=False).iloc[0]
            kpi['trend_detected'] = 'Sí'
            kpi['trend_direction'] = best.get('trend_interpretation', '-')
            slope = best.get('slope_per_day', 0)
            r2 = best.get('r2', 0)
            kpi['trend_formula'] = f"{slope:+.2f}/día (R²={r2:.2f})"

    return kpi


def _parse_json_list(val) -> str:
    """Parse a JSON array field to comma-separated string."""
    if pd.isna(val) if isinstance(val, float) else val is None:
        return ''
    if isinstance(val, str):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return ', '.join(str(x) for x in parsed)
        except (json.JSONDecodeError, TypeError):
            return val
    if isinstance(val, list):
        return ', '.join(str(x) for x in val)
    return str(val)
