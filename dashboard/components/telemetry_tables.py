"""
Table/data helpers for Telemetry Health Dashboard.

Build display DataFrames from golden layer outputs.
"""

import pandas as pd
import json
from typing import Optional

from dashboard.components.telemetry_charts import translate_system


def build_fleet_priority_table(unit_health_df: pd.DataFrame) -> list:
    """
    Build priority table: Unidad | Estado | Sistemas en Alerta.

    Returns list of dicts ready for DataTable.
    """
    if unit_health_df.empty:
        return []

    df = unit_health_df.copy()
    df = df.sort_values('priority_score', ascending=False)

    # Build "sistemas en alerta" column combining anormal + alerta counts
    n_anormal = df.get('n_anormal_systems', pd.Series(0, index=df.index))
    n_alerta = df.get('n_alerta_systems', pd.Series(0, index=df.index))
    df['sistemas_en_alerta'] = (n_anormal.fillna(0) + n_alerta.fillna(0)).astype(int)

    cols = ['unit', 'overall_status', 'sistemas_en_alerta']
    available = [c for c in cols if c in df.columns]

    return df[available].to_dict('records')


def build_system_risk_table(system_health_df: pd.DataFrame, unit: str, deviation_df: pd.DataFrame = None) -> list:
    """
    Build system risk table: Sistema | Estado | Señales en Alerta.

    Translates system names to Spanish.
    """
    if system_health_df.empty:
        return []

    df = system_health_df[system_health_df['unit'] == unit].copy()
    if df.empty:
        return []

    df['system_score'] = df['system_score'].round(1) if 'system_score' in df.columns else 0
    df = df.sort_values('system_score', ascending=False)

    # Translate system names
    df['system'] = df['system'].map(translate_system)

    # Count signals in alert per system from deviation data
    if deviation_df is not None and not deviation_df.empty:
        dev_unit = deviation_df[deviation_df['unit'] == unit]
        alert_counts = dev_unit[dev_unit['status'].isin(['Alerta', 'Anormal'])].groupby('system').size()
        # Translate keys
        alert_counts.index = alert_counts.index.map(translate_system)
        df['signals_in_alert'] = df['system'].map(alert_counts).fillna(0).astype(int)
    else:
        df['signals_in_alert'] = 0

    cols = ['system', 'system_status', 'signals_in_alert']
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
        events_df: Event analysis results (uses 'feature' column for signal name)
        unit: Selected unit
        system: Optional system filter (in Spanish — will be reverse-translated)
    """
    if deviation_df.empty:
        return []

    dev = deviation_df[deviation_df['unit'] == unit].copy()

    # Reverse-translate system name for filtering (Spanish → English)
    if system:
        reverse_map = {v: k for k, v in {
            'Engine': 'Motor', 'Transmission': 'Transmisión',
            'Brakes': 'Frenos', 'Steering': 'Dirección'
        }.items()}
        system_en = reverse_map.get(system, system)
        dev = dev[dev['system'] == system_en]

    if dev.empty:
        return []

    # Get latest evaluation per signal (use year/week instead of evaluation_date)
    if 'year' in dev.columns and 'week' in dev.columns:
        dev = dev.sort_values(['year', 'week'], ascending=False).drop_duplicates(subset=['signal'])

    # Summarize events per signal — events use 'feature' column, not 'signal'
    event_stats = {}
    if not events_df.empty:
        evt = events_df[events_df['unit'] == unit]
        # Events don't have 'system' column, match by feature name against signal names
        signal_list = dev['signal'].tolist()
        feature_col = 'feature' if 'feature' in evt.columns else 'signal'
        evt = evt[evt[feature_col].isin(signal_list)]
        if not evt.empty:
            group_col = 'event_group' if 'event_group' in evt.columns else 'event_id'
            event_stats = evt.groupby(feature_col).agg(
                total_events=(group_col, 'count'),
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

    # Event stats — events use 'feature' column
    if not events_df.empty:
        feature_col = 'feature' if 'feature' in events_df.columns else 'signal'
        evt = events_df[(events_df['unit'] == unit) & (events_df[feature_col] == signal_name)]
        if not evt.empty:
            group_col = 'event_group' if 'event_group' in evt.columns else 'event_id'
            kpi['total_events'] = len(evt[group_col].unique()) if group_col in evt.columns else len(evt)
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
