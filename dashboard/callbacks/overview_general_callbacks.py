"""
Callbacks for Overview General tab.
Handles data loading and visualization for consolidated executive summary.
"""

from dash import callback, Output, Input, State, html, dash_table
from dash.exceptions import PreventUpdate
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
from pathlib import Path
import logging

from src.data.loaders import load_telemetry_unit_health, load_alerts_data, load_machine_status_for_client
from src.data.maintenance_repository import get_repository
from dashboard.callbacks.data_freshness_callbacks import load_data_freshness
from dashboard.components.source_status import render_service_source_status
from src.data.catalog import availability_as_dict
from dashboard.components.labels import translate_component_label, NO_DATA_ICON, NO_DATA_BG, NO_DATA_TEXT
from config.client_services import is_service_enabled

logger = logging.getLogger(__name__)


def build_component_filter_options(data: dict) -> list:
    """Component options for `overview-component-filter`, deduplicated across
    alerts and oil sources and labeled with the same function Alertas uses.

    Pulled out as a module-level, pure function (W34-01) so the label rule is
    unit-testable without registering the whole Dash app — the callback that
    used to inline this logic (`populate_component_filter`, defined inside
    `register_overview_general_callbacks`) is a nested closure and cannot be
    called directly in a test.

    `value` stays the raw, uppercased-for-dedup component (the join key used
    by `create_critical_equipment_summary_table`'s `component_filter`
    comparisons); only `label` goes through `translate_component_label`.
    """
    if not data:
        return []

    components = set()

    # From alerts (uppercase)
    alerts = data.get("alerts", [])
    for row in alerts:
        comp = row.get("componente", "")
        if comp and comp != "Desconocido":
            components.add(comp.upper())

    # From oil component_details (lowercase → uppercase)
    oil = data.get("oil", [])
    for row in oil:
        details = row.get("component_details", [])
        if isinstance(details, list):
            for d in details:
                if isinstance(d, dict):
                    comp = d.get("component", "")
                    if comp:
                        components.add(comp.upper())

    if not components:
        return []

    # W34-01: same label function as Alertas and the table header, instead of
    # a bare .title() on the raw (uppercased-for-dedup) value — "POST_ENGINE"
    # must read "Posterior al motor" here exactly like it does in the alerts
    # table, not "Post_Engine".
    return [{"label": translate_component_label(c), "value": c} for c in sorted(components)]


def clean_numpy_types(data):
    """
    Recursively clean numpy types from nested data structures to make them JSON serializable.
    Converts numpy arrays to lists and numpy types to Python native types.
    Also handles pandas Timestamp and Period types.
    
    Args:
        data: The data structure to clean (dict, list, numpy types, etc.)
        
    Returns:
        Cleaned data structure with Python native types only
    """
    if isinstance(data, dict):
        return {key: clean_numpy_types(value) for key, value in data.items()}
    elif isinstance(data, list):
        return [clean_numpy_types(item) for item in data]
    elif isinstance(data, np.ndarray):
        return [clean_numpy_types(item) for item in data.tolist()]
    elif isinstance(data, (np.integer, np.floating)):
        return data.item()
    elif isinstance(data, np.bool_):
        return bool(data)
    elif isinstance(data, (pd.Timestamp, pd.Period)):
        return str(data)
    elif pd.isna(data):
        return None
    else:
        return data


def calculate_alert_criticality_score(df_alerts: pd.DataFrame, days: int = 30) -> pd.DataFrame:
    """
    Calculate equipment criticality score based on recent alerts.
    
    Formula: More alerts for same equipment/component = higher criticality
    
    Args:
        df_alerts: DataFrame with alert data (using real columns: Timestamp, Unidad, Componente)
        days: Number of days to consider recent alerts
        
    Returns:
        DataFrame with equipment, alert_count, component_count, score, and status
    """
    if df_alerts.empty:
        return pd.DataFrame(columns=['equipo', 'alert_count', 'component_count', 'criticality_score', 'status'])
    
    # Use correct column names from load_alerts_data
    if 'Timestamp' not in df_alerts.columns:
        logger.warning(f"Column 'Timestamp' not found. Available: {df_alerts.columns.tolist()}")
        return pd.DataFrame(columns=['equipo', 'alert_count', 'component_count', 'criticality_score', 'status'])
    
    cutoff_date = datetime.now() - timedelta(days=days)
    
    # Ensure Timestamp is datetime (it might be string after clean_numpy_types)
    if 'Timestamp' in df_alerts.columns:
        df_alerts['Timestamp'] = pd.to_datetime(df_alerts['Timestamp'])
    
    # Filter recent alerts
    recent = df_alerts[df_alerts['Timestamp'] >= cutoff_date].copy()
    
    if recent.empty:
        return pd.DataFrame(columns=['equipo', 'alert_count', 'component_count', 'criticality_score', 'status'])
    
    # Use correct column names: UnitId (equipment) and componente (component)
    if 'UnitId' not in recent.columns or 'componente' not in recent.columns:
        logger.warning(f"Required columns not found. Available: {recent.columns.tolist()}")
        return pd.DataFrame(columns=['equipo', 'alert_count', 'component_count', 'criticality_score', 'status'])
    
    # Group by equipment and component
    grouped = recent.groupby(['UnitId', 'componente']).size().reset_index(name='alerts_per_component')
    
    # Calculate metrics per equipment
    equipment_stats = grouped.groupby('UnitId').agg({
        'alerts_per_component': 'sum',  # Total alerts
        'componente': 'nunique'  # Number of affected components
    }).reset_index()
    
    equipment_stats.columns = ['equipo', 'alert_count', 'component_count']
    
    # Criticality score: alerts * component diversity factor
    equipment_stats['criticality_score'] = (
        equipment_stats['alert_count'] * 
        (1 + equipment_stats['component_count'] * 0.5)
    ).round(1)
    
    # Categorize status
    def categorize_status(score):
        if score == 0:
            return 'Normal'
        elif score <= 15:
            return 'Alerta'
        else:
            return 'Crítico'
    
    equipment_stats['status'] = equipment_stats['criticality_score'].apply(categorize_status)
    
    return equipment_stats.sort_values('criticality_score', ascending=False)


def create_telemetry_pie_chart(df_telemetry: pd.DataFrame) -> go.Figure:
    """
    Create compact pie chart showing fleet status distribution from telemetry.
    
    Args:
        df_telemetry: DataFrame with telemetry machine status (using real columns: overall_status)
        
    Returns:
        Plotly figure
    """
    if df_telemetry.empty:
        return create_empty_figure("No hay datos")
    
    # Use correct column name from load_telemetry_unit_health
    if 'overall_status' not in df_telemetry.columns:
        logger.warning(f"Column 'overall_status' not found. Available: {df_telemetry.columns.tolist()}")
        return create_empty_figure("Datos incompletos")
    
    # Count by status
    status_counts = df_telemetry['overall_status'].value_counts()
    
    # Color mapping (matching telemetry status values)
    color_map = {
        'Normal': '#28a745',
        'Alerta': '#ffc107',
        'Anormal': '#dc3545',
        'Sin Datos': '#6c757d'
    }
    
    colors = [color_map.get(status, '#3498db') for status in status_counts.index]
    
    fig = go.Figure(data=[go.Pie(
        labels=status_counts.index,
        values=status_counts.values,
        marker_colors=colors,
        hole=0.5,
        textposition='inside',
        textinfo='value',
        textfont=dict(size=14, color='white'),
        hovertemplate='<b>%{label}</b><br>%{value} equipos (%{percent})<extra></extra>'
    )])
    
    fig.update_layout(
        title=None,
        height=220,
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.05,
            font=dict(size=10)
        ),
        font=dict(size=11)
    )
    
    return fig


def create_maintenance_pie_chart(df_status: pd.DataFrame, df_downtime: pd.DataFrame) -> go.Figure:
    """
    Create compact pie chart showing operational vs stopped equipment.
    
    Args:
        df_status: DataFrame with status counts
        df_downtime: DataFrame with downtime MTD data
        
    Returns:
        Plotly figure
    """
    if df_status.empty:
        return create_empty_figure("No hay datos")
    
    # Get counts
    sanos = int(df_status[df_status['machine_status'] == 'SANO']['n_machines'].sum()) if not df_status.empty else 0
    detenidos = int(df_status[df_status['machine_status'] == 'DETENIDO']['n_machines'].sum()) if not df_status.empty else 0
    
    # Get MTD
    mtd_hours = df_downtime['total_downtime_hours_mtd'].iloc[0] if not df_downtime.empty else 0
    
    labels = ['Operativos', f'Detenidos ({mtd_hours:.0f}h MTD)']
    values = [sanos, detenidos]
    colors = ['#28a745', '#dc3545']
    
    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        marker_colors=colors,
        hole=0.5,
        textposition='inside',
        textinfo='value',
        textfont=dict(size=14, color='white'),
        hovertemplate='<b>%{label}</b><br>%{value} equipos (%{percent})<extra></extra>'
    )])
    
    fig.update_layout(
        title=None,
        height=220,
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.05,
            font=dict(size=10)
        ),
        font=dict(size=11)
    )
    
    return fig


def create_oil_pie_chart(df_oil: pd.DataFrame) -> go.Figure:
    """
    Create compact donut chart showing oil analysis status distribution.
    
    Args:
        df_oil: DataFrame with oil analysis data
        
    Returns:
        Plotly figure
    """
    if df_oil.empty or 'estado' not in df_oil.columns:
        return create_empty_figure("No hay datos")
    
    # Count by status and get unique machines
    df_unique = df_oil.drop_duplicates(subset=['equipo']) if 'equipo' in df_oil.columns else df_oil
    status_counts = df_unique['estado'].value_counts()
    
    # Color mapping (using original values from machine_status.parquet)
    colors = {
        'Normal': '#28a745',
        'Anormal': '#dc3545',
        'Alerta': '#ffc107'
    }
    
    color_list = [colors.get(status, '#6c757d') for status in status_counts.index]
    
    fig = go.Figure(data=[go.Pie(
        labels=status_counts.index,
        values=status_counts.values,
        marker_colors=color_list,
        hole=0.5,
        textposition='inside',
        textinfo='value',
        textfont=dict(size=14, color='white'),
        hovertemplate='<b>%{label}</b><br>%{value} equipos (%{percent})<extra></extra>'
    )])
    
    fig.update_layout(
        title=None,
        height=220,
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.05,
            font=dict(size=10)
        ),
        font=dict(size=11)
    )
    
    return fig


def create_critical_equipment_summary_table(df_telemetry: pd.DataFrame, df_oil: pd.DataFrame,
                                            df_alerts: pd.DataFrame, df_maintenance: pd.DataFrame,
                                            df_freshness: pd.DataFrame = None,
                                            component_filter: str = None,
                                            client: str = None) -> html.Div:
    """
    Create summary table showing ALL equipment status across technical areas.
    Includes tooltip on hover with reason for each status.
    
    When component_filter is set:
      - Telemetría: only counts alerts for that specific component
      - Tribología: uses component_details to get status for that component
    When component_filter is None:
      - Telemetría: overall alert score across all components
      - Tribología: overall_status from machine_status.parquet

    W34-13: `client` gates each column against `config/client_services.json`
    via `is_service_enabled` — a client without the underlying service
    (Telemetría reads from monitoring-alerts/overview-data-freshness;
    Tribología from monitoring-oil) shows "Sin Fuente", never a default
    "Normal"/healthy badge. Within an enabled service, a unit that simply has
    no record yet shows "Sin Datos" — a third, distinct state from a
    resolved Normal/Alerta/Anormal, so a missing signal is never confused
    with a checked-and-healthy one at either level (client or unit).

    Returns:
        html.Div with a table using colored badges with tooltips
    """
    if df_telemetry.empty and df_oil.empty and df_alerts.empty and df_maintenance.empty:
        return html.Div(html.P("No hay datos disponibles", className="text-muted text-center p-2 mb-0", style={'fontSize': '12px'}))
    
    try:
        # ── Collect unique equipment across all sources ──
        equipos = set()
        if not df_telemetry.empty and 'unit_id' in df_telemetry.columns:
            equipos.update(df_telemetry['unit_id'].unique())
        if not df_oil.empty and 'equipo' in df_oil.columns:
            equipos.update(df_oil['equipo'].unique())
        if not df_alerts.empty and 'UnitId' in df_alerts.columns:
            equipos.update(df_alerts['UnitId'].unique())
        if not df_maintenance.empty and 'machine_code' in df_maintenance.columns:
            equipos.update(df_maintenance['machine_code'].unique())
        
        if not equipos:
            return html.Div(html.P("No hay equipos disponibles", className="text-muted text-center p-2 mb-0", style={'fontSize': '12px'}))

        # ── W34-13: source availability, once per render (client-wide, not
        # per-unit) — a client without the underlying service must show "Sin
        # Fuente" for every unit in that column, never a default "Normal".
        # Telemetría reads from load_alerts_data (monitoring-alerts) and
        # load_data_freshness (overview-data-freshness); Tribología from
        # load_machine_status_for_client (monitoring-oil). Either telemetry
        # source being enabled is enough — this column blends alerts and
        # freshness, so it degrades gracefully if only one is on.
        telemetry_source_available = (
            is_service_enabled(client, "monitoring-alerts")
            or is_service_enabled(client, "overview-data-freshness")
        )
        oil_source_available = is_service_enabled(client, "monitoring-oil")

        # ── Pre-compute alert scores ──
        # When filtering by component, only count alerts for that component
        df_alerts_filtered = df_alerts
        if component_filter and not df_alerts.empty and 'componente' in df_alerts.columns:
            df_alerts_filtered = df_alerts[df_alerts['componente'].str.upper() == component_filter.upper()].copy()
        alert_scores = calculate_alert_criticality_score(df_alerts_filtered, 30) if not df_alerts_filtered.empty else pd.DataFrame()
        
        # ── Pre-compute data freshness per unit (telemetry) ──
        freshness_by_unit = {}
        if df_freshness is not None and not df_freshness.empty:
            from dashboard.callbacks.data_freshness_callbacks import calculate_freshness_status, convert_utc_to_chile, FRESHNESS_CRITERIA
            import pytz
            chile_tz = pytz.timezone('America/Santiago')
            current_time_chile = datetime.now(chile_tz)
            
            telem_freshness = df_freshness[df_freshness['Data'] == 'Telemetria']
            for _, row in telem_freshness.iterrows():
                unit_id = row.get('Unit_Id', '')
                last_update = row.get('Ultima Fecha de Actualizacion')
                if pd.notna(last_update):
                    # Ensure datetime (may be string after JSON serialization from store)
                    last_update = pd.to_datetime(last_update)
                    last_update_chile = convert_utc_to_chile(last_update)
                    status, color, time_str = calculate_freshness_status(last_update_chile, 'Telemetria', current_time_chile)
                    freshness_by_unit[unit_id] = {'status': status, 'time_str': time_str}
        
        # ── Color and icon maps ──
        STATUS_STYLE = {
            'Normal':  {'icon': '🟢', 'bg': '#d4edda', 'color': '#155724'},
            'Alerta':  {'icon': '🟡', 'bg': '#fff3cd', 'color': '#856404'},
            'Anormal': {'icon': '🔴', 'bg': '#f8d7da', 'color': '#721c24'},
            'Atención':{'icon': '🟡', 'bg': '#fff3cd', 'color': '#856404'},
            'Crítico': {'icon': '🔴', 'bg': '#f8d7da', 'color': '#721c24'},
            # W34-13: two distinct "no signal" reasons instead of one 'N/A'
            # bucket. "Sin Datos": the service is enabled but this unit has
            # no record yet (was 'N/A'). "Sin Fuente": the client doesn't
            # have this service enabled at all — visually distinct (dashed
            # border) so it never reads as "checked, nothing to report".
            # Frontend-consistency pass: bg/text/icon come from labels.py's
            # NO_DATA_* constants — the same "no data" identity Estado de
            # Datos and Predictivo use (quality-review follow-up: previously
            # three independent dict literals kept in sync only by a
            # comment, now one real shared source). "Sin Fuente" keeps its
            # own filled-circle icon (not NO_DATA_ICON's hollow one) plus a
            # dashed border, so it still reads as "off" next to "sin
            # datos"'s hollow/empty circle, without breaking the 🟢🟡🔴⚪ dot
            # pattern.
            # 'muted': True (critical-review follow-up) is the same optional-
            # key idiom as 'border' below — one flag per status entry, not a
            # second, separately-maintained list of "which statuses are
            # de-emphasized" in make_badge. This is exactly the split that
            # let this table's own de-emphasis rule go missing once already
            # (Fase 8) until it was patched to match Estado de Datos.
            'Sin Datos':  {'icon': NO_DATA_ICON, 'bg': NO_DATA_BG, 'color': NO_DATA_TEXT, 'muted': True},
            'Sin Fuente': {'icon': '⚫', 'bg': NO_DATA_BG, 'color': NO_DATA_TEXT, 'border': '1px dashed var(--border-strong)', 'muted': True},
        }
        
        STATUS_PRIORITY = {
            'Anormal': 3, 'Crítico': 3,
            'Alerta': 2, 'Atención': 2,
            'Normal': 1,
            # W34-13: neither "no signal" reason outranks a real status —
            # max(real_priority, 0) always surfaces the real one when only
            # one of the two columns is unavailable/no-data.
            'Sin Datos': 0,
            'Sin Fuente': 0,
        }

        def make_badge(status, tooltip_text):
            """Create a colored badge with tooltip."""
            style_info = STATUS_STYLE.get(status, STATUS_STYLE['Sin Datos'])
            return html.Div(
                html.Span(
                    f"{style_info['icon']} {status}",
                    title=tooltip_text,
                    style={
                        'backgroundColor': style_info['bg'],
                        'color': style_info['color'],
                        'border': style_info.get('border', 'none'),
                        'padding': '2px 8px',
                        'borderRadius': '4px',
                        # Same de-emphasis rule as the Estado de Datos table
                        # (FRESHNESS_STATUS_STYLE / update_data_freshness):
                        # a "no signal" badge stays normal weight so it never
                        # competes visually with a real, resolved status.
                        'fontWeight': 'normal' if style_info.get('muted') else 'bold',
                        'fontSize': '11px',
                        'cursor': 'help',
                        'display': 'inline-block',
                        'whiteSpace': 'nowrap'
                    }
                ),
                style={'textAlign': 'center'}
            )
        
        # ── Build rows (simplified: Unidad | Telemetría | Tribología) ──
        table_rows = []
        for equipo in sorted(equipos):
            # --- Telemetría (alerts + data freshness only, no telemetry machine status) ---
            equipo_has_alert_record = not alert_scores.empty and (alert_scores['equipo'] == equipo).any()
            freshness_info = freshness_by_unit.get(equipo)

            if not telemetry_source_available:
                # W34-13: the client has neither alerts nor data-freshness
                # enabled — there is no telemetry-adjacent signal to read at
                # all, for any unit. Must not default to 'Normal'.
                telem_status = 'Sin Fuente'
                telem_reason = 'Alertas y frescura de datos no disponibles para este cliente'
            elif not equipo_has_alert_record and not freshness_info:
                # W34-13: the service is enabled, but THIS unit has never
                # produced an alert or a freshness record — that is an
                # absence of evidence, not evidence of health.
                telem_status = 'Sin Datos'
                telem_reason = 'Sin alertas ni registro de frescura de datos para esta unidad'
            else:
                telem_status = 'Normal'
                telem_reason = 'Sin alertas recientes'

                # 1) Alerts as base status
                if equipo_has_alert_record:
                    equipo_alerts = alert_scores[alert_scores['equipo'] == equipo]
                    telem_status = equipo_alerts['status'].iloc[0]
                    n_alerts = equipo_alerts['alert_count'].iloc[0]
                    n_comps = equipo_alerts['component_count'].iloc[0]
                    score = equipo_alerts['criticality_score'].iloc[0]
                    telem_reason = f"Alertas: {n_alerts} en {n_comps} comp. (score: {score:.1f})"

                # 2) Data freshness — can escalate further
                if freshness_info:
                    fr_status = freshness_info['status']
                    fr_time = freshness_info['time_str']
                    telem_reason += f" | Datos: {fr_status} (hace {fr_time})"
                    if fr_status == 'Preocupante':
                        telem_status = 'Anormal'
                        telem_reason += ' [Sin comunicación]'
                    elif fr_status == 'Atención' and STATUS_PRIORITY.get(telem_status, 0) < 2:
                        telem_status = 'Alerta'
                        telem_reason += ' [Datos con retraso]'

            # --- Tribología (from machine_status.parquet) ---
            if not oil_source_available:
                # W34-13: the client has monitoring-oil disabled entirely.
                oil_status = 'Sin Fuente'
                oil_reason = 'Servicio de tribología no disponible para este cliente'
            else:
                oil_status = 'Sin Datos'
                oil_reason = 'Sin datos de tribología'
            if oil_source_available and not df_oil.empty and 'equipo' in df_oil.columns:
                equipo_oil = df_oil[df_oil['equipo'] == equipo]
                if not equipo_oil.empty:
                    row = equipo_oil.iloc[0]

                    if component_filter:
                        # ── Component-level: search inside component_details ──
                        comp_details = row.get('component_details', [])
                        if isinstance(comp_details, (list, np.ndarray)):
                            match = None
                            for d in comp_details:
                                if isinstance(d, dict) and d.get('component', '').upper() == component_filter.upper():
                                    match = d
                                    break
                            if match:
                                oil_status = match.get('status', 'Sin Datos')
                                sev = match.get('severity_score', 0)
                                # W34-01: same label everywhere a component
                                # name is shown to the user.
                                oil_reason = f"Componente: {translate_component_label(component_filter)} | Estado: {oil_status} (severidad: {sev})"
                                sdate = match.get('sample_date')
                                if sdate:
                                    try:
                                        oil_reason += f" | Muestra: {pd.Timestamp(sdate).strftime('%Y-%m-%d')}"
                                    except Exception:
                                        pass
                                rec = match.get('ai_recommendation')
                                if rec and str(rec).strip() and str(rec) != 'None':
                                    oil_reason += f" | Rec: {str(rec)[:100]}"
                            else:
                                oil_status = 'Sin Datos'
                                oil_reason = f"Sin datos de tribología para {translate_component_label(component_filter)}"
                    else:
                        # ── Overall machine-level status ──
                        oil_status = equipo_oil['estado'].iloc[0]
                        n_normal = row.get('components_normal', 0) if 'components_normal' in equipo_oil.columns else 0
                        n_alerta = row.get('components_alerta', 0) if 'components_alerta' in equipo_oil.columns else 0
                        n_anormal = row.get('components_anormal', 0) if 'components_anormal' in equipo_oil.columns else 0
                        oil_reason = f"Estado: {oil_status} | Comp: {n_normal} normal, {n_alerta} alerta, {n_anormal} anormal"
                        if 'latest_sample_date' in equipo_oil.columns:
                            sample_date = row.get('latest_sample_date')
                            if pd.notna(sample_date):
                                oil_reason += f" | Última muestra: {pd.Timestamp(sample_date).strftime('%Y-%m-%d')}"
                        if 'machine_ai_recommendation' in equipo_oil.columns:
                            rec = row.get('machine_ai_recommendation')
                            if pd.notna(rec) and str(rec).strip():
                                oil_reason += f" | Rec: {str(rec)[:100]}"
            
            # ── Build human-readable description explaining status colors ──
            desc_parts = []

            # Telemetry description
            if telem_status in ('Anormal', 'Crítico'):
                if freshness_info and freshness_info.get('status') == 'Preocupante':
                    desc_parts.append(f"no llega data de telemetría hace {freshness_info['time_str']}")
                if not alert_scores.empty:
                    eq_a = alert_scores[alert_scores['equipo'] == equipo]
                    if not eq_a.empty:
                        _na = int(eq_a['alert_count'].iloc[0])
                        _nc = int(eq_a['component_count'].iloc[0])
                        desc_parts.append(f"presenta {_na} alerta(s) en {_nc} componente(s)")
                if not desc_parts:
                    desc_parts.append("telemetría en estado crítico")
            elif telem_status in ('Alerta', 'Atención'):
                sub = []
                if not alert_scores.empty:
                    eq_a = alert_scores[alert_scores['equipo'] == equipo]
                    if not eq_a.empty:
                        _na = int(eq_a['alert_count'].iloc[0])
                        sub.append(f"{_na} alerta(s) activa(s)")
                if freshness_info and freshness_info.get('status') == 'Atención':
                    sub.append(f"datos con retraso ({freshness_info['time_str']})")
                if sub:
                    desc_parts.extend(sub)

            # Tribology description
            if oil_status in ('Anormal', 'Crítico'):
                if component_filter:
                    # W34-01: translated label, lower-cased to fit mid-sentence
                    # (was the raw crude value, e.g. "post_engine").
                    desc_parts.append(f"muestra de {translate_component_label(component_filter).lower()} anormal")
                elif not df_oil.empty and 'equipo' in df_oil.columns:
                    eq_o = df_oil[df_oil['equipo'] == equipo]
                    if not eq_o.empty:
                        _r = eq_o.iloc[0]
                        _n_an = int(_r.get('components_anormal', 0)) if 'components_anormal' in eq_o.columns else 0
                        _n_al = int(_r.get('components_alerta', 0)) if 'components_alerta' in eq_o.columns else 0
                        if _n_an > 0:
                            desc_parts.append(f"{_n_an} componente(s) con aceite anormal")
                        elif _n_al > 0:
                            desc_parts.append(f"{_n_al} componente(s) con aceite en alerta")
                        else:
                            desc_parts.append("muestras de aceite fuera de rango")
            elif oil_status in ('Alerta', 'Atención'):
                if component_filter:
                    desc_parts.append(f"muestra de {translate_component_label(component_filter).lower()} en alerta")
                elif not df_oil.empty and 'equipo' in df_oil.columns:
                    eq_o = df_oil[df_oil['equipo'] == equipo]
                    if not eq_o.empty:
                        _n_al = int(eq_o.iloc[0].get('components_alerta', 0)) if 'components_alerta' in eq_o.columns else 0
                        if _n_al > 0:
                            desc_parts.append(f"{_n_al} componente(s) con aceite en alerta")
            elif oil_status == 'Sin Datos':
                desc_parts.append("sin datos de tribología")
            elif oil_status == 'Sin Fuente':
                desc_parts.append("tribología no disponible para este cliente")

            # W34-13: telemetry-side "no signal" reasons in the description too.
            if telem_status == 'Sin Fuente':
                desc_parts.append("telemetría no disponible para este cliente")
            elif telem_status == 'Sin Datos':
                desc_parts.append("sin datos de telemetría para esta unidad")

            if desc_parts:
                description = "; ".join(desc_parts)
                description = description[0].upper() + description[1:]
            else:
                description = "Operación normal; sin hallazgos destacables"

            table_rows.append({
                'equipo': equipo,
                'priority': max(STATUS_PRIORITY.get(telem_status, 0), STATUS_PRIORITY.get(oil_status, 0)),
                'row': html.Tr([
                    html.Td(equipo, style={'fontWeight': 'bold', 'fontSize': '13px', 'padding': '6px 12px'}),
                    html.Td(make_badge(telem_status, telem_reason)),
                    html.Td(make_badge(oil_status, oil_reason)),
                    html.Td(description, style={
                        'fontSize': '11px', 'padding': '6px 12px',
                        'color': '#495057', 'lineHeight': '1.4',
                        'maxWidth': '400px',
                    }),
                ])
            })
        
        # ── Sort rows: most critical first, then alphabetical ──
        table_rows.sort(key=lambda r: (-r['priority'], r['equipo']))
        sorted_rows = [r['row'] for r in table_rows]
        
        # ── Build HTML table ──
        # W34-01: same label function as the filter dropdown and Alertas —
        # a component_filter of "POST_ENGINE" reads "Posterior al motor" in
        # the header too, matching the dropdown option the user picked.
        component_header_label = translate_component_label(component_filter) if component_filter else None
        col_telemetria = f"Telemetría ({component_header_label})" if component_header_label else "Telemetría"
        col_tribologia = f"Tribología ({component_header_label})" if component_header_label else "Tribología"
        
        table = html.Table([
            html.Thead(html.Tr([
                html.Th(col, style={
                    'backgroundColor': '#f8f9fa', 'fontWeight': 'bold',
                    'textAlign': 'center', 'fontSize': '12px', 'padding': '8px',
                    'borderBottom': '2px solid #dee2e6', 'position': 'sticky', 'top': '0', 'zIndex': '1'
                })
                for col in ['Unidad', col_telemetria, col_tribologia, 'Descripción']
            ])),
            html.Tbody(sorted_rows)
        ], style={
            'width': '100%', 'borderCollapse': 'collapse',
            'fontSize': '13px'
        })
        
        return html.Div(table, style={
            'overflowX': 'auto'
        })
    except Exception as e:
        logger.error(f"Error creating critical equipment summary table: {e}", exc_info=True)
        return html.Div(html.P("Error al generar tabla", className="text-danger text-center p-2 mb-0", style={'fontSize': '12px'}))


def create_alerts_pie_chart(df_alerts: pd.DataFrame, days: int = 30) -> go.Figure:
    """
    Create compact pie chart showing components affected by alerts.
    
    Args:
        df_alerts: DataFrame with alerts data
        days: Number of days to consider
        
    Returns:
        Plotly figure
    """
    if df_alerts.empty:
        return create_empty_figure("No hay datos")
    
    # Filter by date range
    if 'Timestamp' in df_alerts.columns:
        cutoff_date = datetime.now() - timedelta(days=days)
        df_alerts['Timestamp'] = pd.to_datetime(df_alerts['Timestamp'])
        df_recent = df_alerts[df_alerts['Timestamp'] >= cutoff_date].copy()
    else:
        df_recent = df_alerts.copy()
    
    if df_recent.empty:
        return create_empty_figure(f"Sin alertas")
    
    # Count alerts by component
    if 'componente' not in df_recent.columns:
        return create_empty_figure("Datos incompletos")
    
    # Count alerts per component
    component_counts = df_recent['componente'].value_counts().head(10)  # Top 10 components
    
    if component_counts.empty:
        return create_empty_figure("Sin componentes")
    
    # Generate distinct colors for components
    import plotly.colors as pc
    colors_palette = pc.qualitative.Set3[:len(component_counts)]
    
    fig = go.Figure(data=[go.Pie(
        labels=component_counts.index,
        values=component_counts.values,
        marker_colors=colors_palette,
        hole=0.5,
        textposition='inside',
        textinfo='value',
        textfont=dict(size=12, color='white'),
        hovertemplate='<b>%{label}</b><br>%{value} alertas (%{percent})<extra></extra>'
    )])
    
    fig.update_layout(
        title=None,
        height=220,
        margin=dict(l=10, r=10, t=10, b=10),
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.05,
            font=dict(size=9)
        ),
        font=dict(size=11)
    )
    
    return fig


def create_summary_table(df_telemetry: pd.DataFrame, df_maintenance: pd.DataFrame, 
                         df_oil: pd.DataFrame, df_alerts: pd.DataFrame) -> html.Div:
    """
    Create comprehensive summary table combining all technical areas.
    
    Args:
        df_telemetry: Telemetry data (with correct columns: unit_id, overall_status)
        df_maintenance: Maintenance data
        df_oil: Oil analysis data
        df_alerts: Alerts data (with correct columns: Unidad, Componente, Timestamp)
        
    Returns:
        Dash DataTable component
    """
    try:
        # Build summary by equipment
        summary_data = []
        
        # Get unique equipment from all sources (using correct column names)
        equipos = set()
        if not df_telemetry.empty and 'unit_id' in df_telemetry.columns:
            equipos.update(df_telemetry['unit_id'].unique())
        if not df_alerts.empty and 'Unidad' in df_alerts.columns:
            equipos.update(df_alerts['Unidad'].unique())
        
        alert_scores = calculate_alert_criticality_score(df_alerts, 30) if not df_alerts.empty else pd.DataFrame()
        
        for equipo in sorted(equipos):
            # Telemetry status (use correct column: unit_id and overall_status)
            telem_status = 'N/A'
            if not df_telemetry.empty and 'unit_id' in df_telemetry.columns:
                equipo_telem = df_telemetry[df_telemetry['unit_id'] == equipo]
                if not equipo_telem.empty and 'overall_status' in equipo_telem.columns:
                    telem_status = equipo_telem['overall_status'].iloc[0]
            
            # Oil status
            oil_status = 'N/A'
            if not df_oil.empty and 'equipo' in df_oil.columns:
                equipo_oil = df_oil[df_oil['equipo'] == equipo]
                if not equipo_oil.empty:
                    oil_status = equipo_oil['estado'].iloc[0]
            
            # Alert score
            alert_score = 0
            alert_status = 'Normal'
            if not alert_scores.empty:
                equipo_alerts = alert_scores[alert_scores['equipo'] == equipo]
                if not equipo_alerts.empty:
                    alert_score = equipo_alerts['criticality_score'].iloc[0]
                    alert_status = equipo_alerts['status'].iloc[0]
            
            summary_data.append({
                'Equipo': equipo,
                'Telemetría': telem_status,
                'Aceite': oil_status,
                'Score Alertas': f"{alert_score:.1f}",
                'Estado Alertas': alert_status
            })
        
        df_summary = pd.DataFrame(summary_data)
        
        if df_summary.empty:
            return html.P("No hay datos disponibles", className="text-muted text-center p-3")
        
        return dash_table.DataTable(
            data=df_summary.to_dict('records'),
            columns=[{'name': col, 'id': col} for col in df_summary.columns],
            sort_action='native',
            filter_action='native',
            page_size=20,
            style_table={'overflowX': 'auto'},
            style_header={
                'backgroundColor': '#f8f9fa',
                'fontWeight': 'bold',
                'textAlign': 'center'
            },
            style_cell={
                'textAlign': 'center',
                'padding': '8px',
                'fontSize': '13px'
            },
            style_data_conditional=[
                # Telemetry status colors
                {
                    'if': {
                        'filter_query': '{Telemetría} = "Anormal"',
                        'column_id': 'Telemetría'
                    },
                    'backgroundColor': 'rgba(220, 53, 69, 0.1)',
                    'color': '#dc3545',
                    'fontWeight': 'bold'
                },
                {
                    'if': {
                        'filter_query': '{Telemetría} = "Alerta"',
                        'column_id': 'Telemetría'
                    },
                    'backgroundColor': 'rgba(255, 193, 7, 0.1)',
                    'color': '#856404',
                    'fontWeight': 'bold'
                },
                # Oil status colors
                {
                    'if': {
                        'filter_query': '{Aceite} = "Anormal"',
                        'column_id': 'Aceite'
                    },
                    'backgroundColor': 'rgba(220, 53, 69, 0.1)',
                    'color': '#dc3545',
                    'fontWeight': 'bold'
                },
                {
                    'if': {
                        'filter_query': '{Aceite} = "Alerta"',
                        'column_id': 'Aceite'
                    },
                    'backgroundColor': 'rgba(255, 193, 7, 0.1)',
                    'color': '#856404',
                    'fontWeight': 'bold'
                },
                # Alert status colors
                {
                    'if': {
                        'filter_query': '{Estado Alertas} = "Crítico"',
                        'column_id': 'Estado Alertas'
                    },
                    'backgroundColor': 'rgba(220, 53, 69, 0.1)',
                    'color': '#dc3545',
                    'fontWeight': 'bold'
                },
                {
                    'if': {
                        'filter_query': '{Estado Alertas} = "Alerta"',
                        'column_id': 'Estado Alertas'
                    },
                    'backgroundColor': 'rgba(255, 193, 7, 0.1)',
                    'color': '#856404',
                    'fontWeight': 'bold'
                }
            ]
        )
    except Exception as e:
        logger.error(f"Error creating summary table: {e}", exc_info=True)
        return html.P("Error al generar tabla resumen", className="text-danger text-center p-3")


def create_empty_figure(message: str) -> go.Figure:
    """
    Create empty figure with message.
    
    Args:
        message: Message to display
        
    Returns:
        Empty Plotly figure
    """
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=14, color="gray")
    )
    fig.update_layout(
        xaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        yaxis=dict(showgrid=False, showticklabels=False, zeroline=False),
        plot_bgcolor='white',
        height=300
    )
    return fig


def register_overview_general_callbacks(app):
    """
    Register all callbacks for Overview General tab.
    
    Args:
        app: Dash application instance
    """
    
    @callback(
        Output("overview-source-status", "children"),
        [Input("client-selector", "value")],
    )
    def update_overview_source_status(client):
        if not client:
            return html.Div()
        return render_service_source_status(client, "overview-general")

    @callback(
        [
            Output("store-overview-data", "data"),
            Output("store-overview-timestamp", "data"),
        ],
        [
            Input("btn-refresh-overview", "n_clicks"),
            Input("client-selector", "value"),
        ],
        prevent_initial_call=False
    )
    def load_overview_data(n_clicks, client):
        """
        Load all data for the overview general tab.
        Uses the most recent available data for each technical area.
        """
        if not client:
            raise PreventUpdate
        
        try:
            logger.info(f"Loading overview data for client: {client}")
            
            # Initialize metadata variables
            telemetry_latest = "N/A"
            oil_latest = "N/A"
            alerts_period = "N/A"
            
            # Load Telemetry data using proper loader (most recent week/year available)
            df_telemetry = load_telemetry_unit_health(client)
            if not df_telemetry.empty:
                # Get most recent evaluation timestamp
                if 'evaluation_timestamp' in df_telemetry.columns:
                    df_telemetry['evaluation_timestamp'] = pd.to_datetime(df_telemetry['evaluation_timestamp'])
                    latest_ts = df_telemetry['evaluation_timestamp'].max()
                    telemetry_latest = latest_ts.strftime("Semana %W, Año %Y")
                    logger.info(f"Telemetry: Using most recent data - {telemetry_latest}")
            
            # Load Maintenance data (already filtered by MTD) - MUST pass client parameter
            repo = get_repository(mode="parquet", client=client)
            df_status = repo.get_status_counts()
            df_downtime = repo.get_downtime_mtd()
            logger.info(f"Maintenance: Loaded {len(df_status)} status records for client: {client}")
            
            # Load Oil analysis data - use machine_status.parquet for overview charts
            df_oil = load_machine_status_for_client(client)
            if df_oil is None or df_oil.empty:
                df_oil = pd.DataFrame()
            else:
                if 'overall_status' in df_oil.columns:
                    df_oil['estado'] = df_oil['overall_status']
                if 'unit_id' in df_oil.columns and 'equipo' not in df_oil.columns:
                    df_oil['equipo'] = df_oil['unit_id']
                if 'latest_sample_date' in df_oil.columns:
                    df_oil['latest_sample_date'] = pd.to_datetime(df_oil['latest_sample_date'], errors='coerce')
                    latest_date = df_oil['latest_sample_date'].max()
                    if pd.notna(latest_date):
                        oil_latest = latest_date.strftime("%Y-%m-%d")
                logger.info(f"Oil Analysis: Loaded {len(df_oil)} machines from machine_status.parquet")
            
            # Load Alerts data using proper loader (load all recent alerts, filtering happens in visualizations)
            df_alerts = load_alerts_data(client)
            alerts_period = "Últimos 90 días (por defecto)"  # Default period shown
            if not df_alerts.empty:
                logger.info(f"Alerts: Loaded {len(df_alerts)} alerts (will be filtered by visualization)")
            
            # Load data freshness (lightweight CSV, ~22 rows)
            df_freshness = load_data_freshness(client)
            
            # Serialize to JSON with metadata about data freshness
            # Clean numpy types before serialization
            data = {
                # W34-13: travels with the snapshot so update_critical_equipment_table
                # can gate columns against config/client_services.json without a
                # second Input('client-selector', 'value') dependency.
                "client": client,
                # Derived provenance only; source files and schemas remain untouched.
                "availability": availability_as_dict(client),
                "telemetry": clean_numpy_types(df_telemetry.to_dict("records")) if not df_telemetry.empty else [],
                "maintenance_status": clean_numpy_types(df_status.to_dict("records")) if not df_status.empty else [],
                "maintenance_downtime": clean_numpy_types(df_downtime.to_dict("records")) if not df_downtime.empty else [],
                "oil": clean_numpy_types(df_oil.to_dict("records")) if not df_oil.empty else [],
                "alerts": clean_numpy_types(df_alerts.to_dict("records")) if not df_alerts.empty else [],
                "freshness": clean_numpy_types(df_freshness.to_dict("records")) if not df_freshness.empty else [],
                "metadata": {
                    "telemetry_latest": telemetry_latest,
                    "oil_latest": oil_latest,
                    "alerts_period": "Configurable (ver filtro)",  # Dynamic based on filter
                    "maintenance": "MTD (Month to Date)"
                }
            }
            
            timestamp = datetime.now().isoformat()
            logger.info("Overview data loaded successfully with latest available data")
            
            return data, timestamp
            
        except Exception as e:
            logger.error(f"Error loading overview data: {e}", exc_info=True)
            return {}, None
    
    @callback(
        [
            Output("overview-kpi-total", "children"),
            Output("overview-kpi-operational", "children"),
            Output("overview-kpi-warning", "children"),
            Output("overview-kpi-critical", "children"),
        ],
        [Input("store-overview-data", "data")]
    )
    def update_global_kpis(data):
        """Update global KPI cards using correct column names."""
        if not data:
            return "0", "0", "0", "0"
        
        try:
            # Parse data
            df_telemetry = pd.DataFrame(data.get("telemetry", []))
            df_status = pd.DataFrame(data.get("maintenance_status", []))
            df_oil = pd.DataFrame(data.get("oil", []))
            df_alerts = pd.DataFrame(data.get("alerts", []))
            
            logger.info(f"KPI Update - Telemetry rows: {len(df_telemetry)}, Maintenance rows: {len(df_status)}, Oil rows: {len(df_oil)}, Alerts rows: {len(df_alerts)}")
            
            # Total equipment (priority: telemetry > maintenance > oil)
            if not df_telemetry.empty:
                total = len(df_telemetry)
                logger.info(f"Total from telemetry: {total}")
            elif not df_status.empty:
                total = int(df_status['n_machines'].sum())
                # If maintenance shows 0 machines but we have oil data, use oil instead
                if total == 0 and not df_oil.empty:
                    if 'equipo' in df_oil.columns:
                        total = df_oil['equipo'].nunique()
                        logger.info(f"Total from oil (fallback from empty maintenance): {total}")
                    else:
                        total = len(df_oil)
                        logger.info(f"Total from oil length (fallback): {total}")
                else:
                    logger.info(f"Total from maintenance: {total}")
            elif not df_oil.empty:
                # Count unique equipment from oil analysis
                if 'equipo' in df_oil.columns:
                    total = df_oil['equipo'].nunique()
                    logger.info(f"Total from oil (equipo column): {total}, unique values: {df_oil['equipo'].unique()[:5]}")
                else:
                    total = len(df_oil)
                    logger.info(f"Total from oil (length): {total}")
            else:
                total = 0
                logger.info("Total: No data available")
            
            # Operational equipment (use correct column: overall_status)
            operational = 0
            if not df_telemetry.empty and 'overall_status' in df_telemetry.columns:
                operational = (df_telemetry['overall_status'] == 'Normal').sum()
            elif not df_status.empty:
                operational = int(df_status[df_status['machine_status'] == 'SANO']['n_machines'].sum())
                # If maintenance shows 0 operational but we have oil data, use oil instead
                if operational == 0 and not df_oil.empty and 'estado' in df_oil.columns:
                    operational = (df_oil['estado'] == 'Normal').sum()
                    logger.info(f"Operational from oil (fallback from empty maintenance): {operational}")
            elif not df_oil.empty and 'estado' in df_oil.columns:
                # Count equipment with Normal status in oil analysis
                operational = (df_oil['estado'] == 'Normal').sum()
                logger.info(f"Operational from oil: {operational}, estados: {df_oil['estado'].value_counts().to_dict()}")
            
            # Warning equipment (Alerta status in telemetry or oil)
            warning = 0
            if not df_telemetry.empty and 'overall_status' in df_telemetry.columns:
                warning = (df_telemetry['overall_status'] == 'Alerta').sum()
            elif not df_oil.empty and 'estado' in df_oil.columns:
                warning = (df_oil['estado'] == 'Alerta').sum()
            
            # Critical equipment (Anormal in telemetry, oil, or high alert score)
            critical = 0
            if not df_telemetry.empty and 'overall_status' in df_telemetry.columns:
                critical = (df_telemetry['overall_status'] == 'Anormal').sum()
            elif not df_oil.empty and 'estado' in df_oil.columns:
                critical = (df_oil['estado'] == 'Anormal').sum()
            
            # Add critical from alerts
            if not df_alerts.empty:
                alert_scores = calculate_alert_criticality_score(df_alerts, 30)
                if not alert_scores.empty:
                    critical += (alert_scores['status'] == 'Crítico').sum()
            
            logger.info(f"Final KPIs - Total: {total}, Operational: {operational}, Warning: {warning}, Critical: {critical}")
            return str(total), str(operational), str(warning), str(critical)
            
        except Exception as e:
            logger.error(f"Error updating global KPIs: {e}", exc_info=True)
            return "Error", "Error", "Error", "Error"
    
    @callback(
        Output("overview-telemetry-chart", "figure"),
        [Input("store-overview-data", "data")]
    )
    def update_telemetry_chart(data):
        """Telemetry chart is hidden — return empty figure immediately."""
        return create_empty_figure("")
    
    @callback(
        Output("overview-maintenance-chart", "figure"),
        [Input("store-overview-data", "data")]
    )
    def update_maintenance_chart(data):
        """Maintenance chart is hidden — return empty figure immediately."""
        return create_empty_figure("")
    
    @callback(
        Output("overview-oil-chart", "figure"),
        [Input("store-overview-data", "data")]
    )
    def update_oil_chart(data):
        """Oil chart is hidden — return empty figure immediately."""
        return create_empty_figure("")
    
    @callback(
        Output("overview-component-filter", "options"),
        [Input("store-overview-data", "data")]
    )
    def populate_component_filter(data):
        """Populate component filter dropdown from alerts + tribology data."""
        return build_component_filter_options(data)
    
    @callback(
        Output("overview-oil-ranking-table", "children"),
        [Input("store-overview-data", "data"),
         Input("overview-component-filter", "value")]
    )
    def update_critical_equipment_table(data, selected_component):
        """Update critical equipment summary table with data freshness from store."""
        if not data:
            return html.P("No hay datos disponibles", className="text-muted text-center p-3")
        
        try:
            df_telemetry = pd.DataFrame(data.get("telemetry", []))
            df_oil = pd.DataFrame(data.get("oil", []))
            df_alerts = pd.DataFrame(data.get("alerts", []))
            df_maintenance = pd.DataFrame(data.get("maintenance_status", []))
            df_freshness = pd.DataFrame(data.get("freshness", []))

            return create_critical_equipment_summary_table(
                df_telemetry, df_oil, df_alerts, df_maintenance, df_freshness,
                component_filter=selected_component,
                client=data.get("client"),
            )
        except Exception as e:
            logger.error(f"Error updating critical equipment table: {e}")
            return html.P("Error al cargar tabla", className="text-danger text-center p-3")
    
    @callback(
        Output("overview-alerts-chart", "figure"),
        [
            Input("store-overview-data", "data"),
            Input("overview-alerts-days-filter", "value")
        ]
    )
    def update_alerts_chart(data, days):
        """Alerts chart is hidden — return empty figure immediately."""
        return create_empty_figure("")
    
    @callback(
        Output("overview-summary-table", "children"),
        [Input("store-overview-data", "data")]
    )
    def update_summary_table(data):
        """Update comprehensive summary table."""
        if not data:
            return html.P("No hay datos disponibles", className="text-muted text-center p-3")
        
        try:
            df_telemetry = pd.DataFrame(data.get("telemetry", []))
            df_status = pd.DataFrame(data.get("maintenance_status", []))
            df_oil = pd.DataFrame(data.get("oil", []))
            df_alerts = pd.DataFrame(data.get("alerts", []))
            
            return create_summary_table(df_telemetry, df_status, df_oil, df_alerts)
        except Exception as e:
            logger.error(f"Error updating summary table: {e}")
            return html.P("Error al cargar tabla", className="text-danger text-center p-3")
    
    @callback(
        Output("overview-last-update", "children"),
        [Input("store-overview-timestamp", "data")]
    )
    def update_timestamp(timestamp):
        """Update last update timestamp."""
        if not timestamp:
            return "N/A"
        
        try:
            dt = datetime.fromisoformat(timestamp)
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            logger.error(f"Error formatting timestamp: {e}")
            return "Error"
    
    @callback(
        [
            Output("overview-telemetry-timestamp", "children"),
            Output("overview-maintenance-timestamp", "children"),
            Output("overview-oil-timestamp", "children"),
            Output("overview-alerts-timestamp", "children"),
        ],
        [Input("store-overview-data", "data")]
    )
    def update_section_timestamps(data):
        """Update individual section timestamps with data freshness info."""
        if not data or 'metadata' not in data:
            return "", "", "", ""
        
        try:
            metadata = data['metadata']
            
            telemetry_ts = f"📅 {metadata.get('telemetry_latest', 'N/A')}" if metadata.get('telemetry_latest') != 'N/A' else ""
            maintenance_ts = f"📅 {metadata.get('maintenance', 'MTD')}"
            oil_ts = f"📅 {metadata.get('oil_latest', 'N/A')}" if metadata.get('oil_latest') != 'N/A' else ""
            alerts_ts = f"📅 {metadata.get('alerts_period', 'N/A')}" if metadata.get('alerts_period') != 'N/A' else ""
            
            return telemetry_ts, maintenance_ts, oil_ts, alerts_ts
        except Exception as e:
            logger.error(f"Error updating section timestamps: {e}")
            return "", "", "", ""
