"""
Table components for Alerts Dashboard.

Functions to create Dash DataTables for alerts listings.
"""

import pandas as pd
import re
import ast
import json
from dash import dash_table, html
import dash_bootstrap_components as dbc
from typing import List, Optional, Dict

from src.utils.logger import get_logger
from dashboard.components.alerts_charts import FEATURE_NAMES_ES

logger = get_logger(__name__)


def _translate_signal_text(value: object) -> str:
    """Translate canonical Capstone signal keys in client-facing text."""
    text = "" if value is None else str(value)
    for key in sorted(FEATURE_NAMES_ES, key=len, reverse=True):
        label = FEATURE_NAMES_ES[key]
        text = re.sub(
            rf"(?<![A-Za-z0-9_]){re.escape(key)}(?![A-Za-z0-9_])",
            label,
            text,
        )
    return text


def _translate_system(value: object) -> str:
    mapping = {"motor": "Motor", "Motor": "Motor"}
    key = str(value or "").strip()
    return mapping.get(key, key or "Sin sistema")


def _translate_component(value: object) -> str:
    mapping = {
        "engine": "Motor",
        "post_engine": "Posterior al motor",
        "rifle": "Conducto principal de aceite",
        "crankcase": "Cárter",
        "lubrication": "Lubricación",
    }
    key = str(value or "").strip()
    return mapping.get(key, key or "Sin componente")


def parse_ia_message_sections(mensaje_ia: str) -> Dict[str, str]:
    """
    Separa el mensaje de IA en las secciones útiles para el cliente usando regex.
    
    Args:
        mensaje_ia: Texto completo generado por la IA
        
    Returns:
        dict con diagnóstico, causa probable y acciones.
        El nivel de riesgo no se calcula ni se expone en Alertas.
    """
    sections = {
        'diagnostico': '',
        'causa_probable': '',
        'acciones': ''
    }
    
    if not mensaje_ia or pd.isna(mensaje_ia):
        return sections

    # Capstone stores the structured IA contract as JSON. Decode it before
    # applying the legacy CDA section regex so the cards show readable
    # diagnosis and recommendation instead of raw JSON fragments.
    try:
        parsed = json.loads(str(mensaje_ia))
        if isinstance(parsed, dict) and any(
            key in parsed for key in ("diagnostic", "recommended_actions", "evidence")
        ):
            sections['diagnostico'] = _translate_signal_text(
                str(parsed.get('diagnostic') or '').strip()
            )
            actions = parsed.get('recommended_actions') or parsed.get('actions') or []
            if isinstance(actions, (list, tuple)):
                sections['acciones'] = _translate_signal_text(
                    '\n'.join(str(item).strip() for item in actions if str(item).strip())
                )
            else:
                sections['acciones'] = _translate_signal_text(str(actions).strip())
            sections['causa_probable'] = (
                'No se infiere una causa probable con la evidencia disponible.'
            )
            return sections
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    
    # Patrones para identificar secciones (case insensitive)
    patterns = {
        'diagnostico': r'(?:DIAGNÓSTICO|DIAGNOSTICO)[:\s](.+?)(?=(?:CAUSA|RIESGO|ACCIONES|$))',
        'causa_probable': r'(?:CAUSA PROBABLE|CAUSA)[:\s](.+?)(?=(?:RIESGO|ACCIONES|$))',
        'acciones': r'(?:ACCIONES CLARAS|ACCIONES RECOMENDADAS|ACCIONES)[:\s](.+?)$'
    }
    
    try:
        for key, pattern in patterns.items():
            match = re.search(pattern, mensaje_ia, re.IGNORECASE | re.DOTALL)
            if match:
                text = match.group(1).strip()
                text = re.sub(r'^[:\-\s]+', '', text)
                # Remove "DIRECTO" from diagnostico if present (case sensitive)
                if key == 'diagnostico':
                    text = text.replace('DIRECTO:', '').strip()
                    # Clean up any extra spaces
                    text = re.sub(r'\s+', ' ', text)
                sections[key] = _translate_signal_text(text)
        
        # Fallback: dividir por párrafos si no se encontraron secciones
        if not any([sections['diagnostico'], sections['causa_probable'], sections['acciones']]):
            paragraphs = [p.strip() for p in mensaje_ia.split('\n\n') if p.strip()]
            if len(paragraphs) >= 1:
                sections['diagnostico'] = _translate_signal_text(paragraphs[0])
            if len(paragraphs) >= 2:
                sections['causa_probable'] = _translate_signal_text(paragraphs[1])
            if len(paragraphs) >= 3:
                sections['acciones'] = _translate_signal_text('\n'.join(paragraphs[2:]))
    
    except Exception as e:
        logger.warning(f"Error parseando mensaje IA: {e}")
        sections['diagnostico'] = _translate_signal_text(mensaje_ia)
    
    return sections


def create_alerts_datatable(alerts_df: pd.DataFrame) -> dash_table.DataTable:
    """
    Create interactive DataTable for alerts listing.
    
    Args:
        alerts_df: DataFrame with alerts data
    
    Returns:
        Dash DataTable component
    """
    if alerts_df.empty:
        logger.warning("Cannot create alerts table: empty dataframe")
        return html.Div([
            dbc.Alert("No hay alertas disponibles", color="info")
        ])
    
    try:
        # Prepare table data
        table_df = alerts_df[[
            'FusionID', 'Timestamp', 'UnitId', 'sistema', 'componente', 'Trigger_type',
            'mensaje_ia', 'has_telemetry', 'has_tribology'
        ]].copy()
        
        # Sort by timestamp (newest first)
        table_df = table_df.sort_values('Timestamp', ascending=False)
        
        # Truncate AI message for display
        table_df['mensaje_ia_short'] = table_df['mensaje_ia'].map(
            lambda value: (parse_ia_message_sections(value).get('diagnostico') or _translate_signal_text(value))[:80] + '...'
        )
        table_df['sistema'] = table_df['sistema'].map(_translate_system)
        table_df['componente'] = table_df['componente'].map(_translate_component)
        table_df['Trigger_type'] = table_df['Trigger_type'].map(
            {"Telemetria": "Telemetría", "Tribologia": "Tribología"}
        ).fillna(table_df['Trigger_type'])
        
        # Convert booleans to symbols
        table_df['Telemetría'] = table_df['has_telemetry'].map({True: '✓', False: '✗'})
        table_df['Tribología'] = table_df['has_tribology'].map({True: '✓', False: '✗'})
        
        # Format timestamp
        table_df['Timestamp_display'] = table_df['Timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # Select display columns
        display_df = table_df[[
            'FusionID', 'Timestamp_display', 'UnitId', 'sistema', 'componente', 
            'Trigger_type', 'mensaje_ia_short', 'Telemetría', 'Tribología'
        ]].copy()
        
        display_df.columns = [
            'ID', 'Fecha', 'Unidad', 'Sistema', 'Componente',
            'Fuente', 'Diagnóstico IA', 'Telemetría', 'Tribología'
        ]
        
        # Create DataTable (no subtitle)
        table = dash_table.DataTable(
            id='alerts-datatable',
            columns=[
                {"name": col, "id": col, "selectable": True} 
                for col in display_df.columns
            ],
            data=display_df.to_dict('records'),
            style_table={
                'overflowX': 'auto',
                'overflowY': 'auto',
                'maxHeight': '500px'
            },
            style_cell={
                'textAlign': 'left',
                'padding': '10px',
                'fontFamily': 'Arial, sans-serif',
                'fontSize': '14px',
                'minWidth': '100px',
                'maxWidth': '400px',
                'whiteSpace': 'normal',
                'height': 'auto'
            },
            style_header={
                'backgroundColor': '#2c3e50',
                'color': 'white',
                'fontWeight': 'bold',
                'textAlign': 'center'
            },
            style_data_conditional=[
                {
                    'if': {'row_index': 'odd'},
                    'backgroundColor': '#f8f9fa'
                },
                {
                    'if': {'state': 'active'},
                    'backgroundColor': '#3498db',
                    'color': 'white',
                    'border': '2px solid #2980b9',
                    'cursor': 'pointer'
                }
            ],
            cell_selectable=True,
            filter_action='native',
            sort_action='native',
            sort_mode='multi',
            page_action='native',
            page_current=0,
            page_size=20
        )
        logger.info(f"Created alerts DataTable with {len(display_df)} rows")
        return table
    
    except Exception as e:
        logger.error(f"Error creating alerts DataTable: {e}")
        return html.Div([
            dbc.Alert(f"Error al crear tabla: {str(e)}", color="danger")
        ])


def create_alerts_report_table(alerts_df: pd.DataFrame) -> dash_table.DataTable:
    """Create the executive alerts table with client-facing fields only."""
    if alerts_df is None or alerts_df.empty:
        return html.Div([dbc.Alert("No hay alertas para los filtros seleccionados.", color="info")])
    try:
        rows = []
        for _, row in alerts_df.sort_values("Timestamp", ascending=False).iterrows():
            sections = parse_ia_message_sections(row.get("mensaje_ia", ""))
            trigger_vars = row.get("Trigger_Var", "Sin señal registrada")
            # Mixed alerts store Trigger_Var as a serialized list. Preserve
            # that representation so each telemetry/oil variable is translated.
            raw_signal_values = trigger_vars
            if isinstance(raw_signal_values, str):
                try:
                    raw_signal_values = ast.literal_eval(raw_signal_values)
                except (ValueError, SyntaxError):
                    raw_signal_values = [raw_signal_values]
            if not isinstance(raw_signal_values, (list, tuple, set)):
                raw_signal_values = [raw_signal_values]
            signal_labels = []
            for signal in raw_signal_values:
                signal_key = str(signal).strip()
                if signal_key and signal_key not in signal_labels:
                    signal_labels.append(FEATURE_NAMES_ES.get(signal_key, signal_key))
            signal_label = ", ".join(signal_labels) or "Sin señal registrada"
            source = {"Telemetria": "Telemetría", "Tribologia": "Tribología"}.get(
                str(row.get("Trigger_type", "")), str(row.get("Trigger_type", "Sin fuente"))
            )
            if bool(row.get("has_telemetry")) and bool(row.get("has_tribology")):
                evidence = "Telemetría + Tribología"
            elif bool(row.get("has_telemetry")):
                evidence = "Telemetría"
            elif bool(row.get("has_tribology")):
                evidence = "Tribología"
            else:
                evidence = "Sin evidencia"
            rows.append({
                "ID": row.get("FusionID", "-"),
                "Fecha": pd.to_datetime(row.get("Timestamp"), errors="coerce").strftime("%d/%m/%Y %H:%M") if pd.notna(row.get("Timestamp")) else "-",
                "Unidad": row.get("UnitId", "-"),
                "Sistema": _translate_system(row.get("sistema", "-")),
                "Componente": _translate_component(row.get("componente", "-")),
                "Señal / variable": signal_label,
                "Fuente": source,
                "Diagnóstico": sections.get("diagnostico", "Sin diagnóstico IA disponible"),
                "diagnostico_completo": sections.get("diagnostico", "Sin diagnóstico IA disponible"),
                "causa_completa": sections.get("causa_probable", "Sin causa probable registrada"),
                "accion_completa": sections.get("acciones", "Sin acción recomendada registrada"),
                "Evidencia": evidence,
                "Acción": sections.get("acciones", "Sin acción recomendada registrada"),
            })
        table = dash_table.DataTable(
            id="alerts-datatable",
            columns=[
                {"name": name, "id": name}
                for name in ["ID", "Fecha", "Unidad", "Sistema", "Componente", "Señal / variable", "Fuente", "Diagnóstico", "Evidencia", "Acción"]
            ],
            data=rows,
            active_cell=None,
            cell_selectable=True,
            filter_action="native",
            sort_action="native",
            sort_mode="multi",
            page_action="native",
            page_size=15,
            tooltip_data=[
                {"Diagnóstico": {"value": row["Diagnóstico"], "type": "text"}, "Acción": {"value": row["Acción"], "type": "text"}}
                for row in rows
            ],
            tooltip_duration=None,
            style_table={"overflowX": "auto", "overflowY": "auto", "maxHeight": "560px"},
            style_cell={"textAlign": "left", "padding": "9px", "fontSize": "12px", "whiteSpace": "normal", "height": "auto", "minWidth": "90px"},
            style_header={"backgroundColor": "#23384d", "color": "white", "fontWeight": "bold", "textAlign": "center", "whiteSpace": "normal"},
            style_cell_conditional=[
                {"if": {"column_id": "ID"}, "fontWeight": "600", "minWidth": "150px"},
                {"if": {"column_id": "Diagnóstico"}, "minWidth": "260px", "maxWidth": "420px"},
                {"if": {"column_id": "Acción"}, "display": "none"},
                {"if": {"column_id": "Señal / variable"}, "minWidth": "150px"},
            ],
            style_data_conditional=[
                {"if": {"filter_query": '{Fuente} = "Mixto"'}, "borderLeft": "4px solid #6f42c1"},
                {"if": {"state": "active"}, "backgroundColor": "#dbeafe", "color": "#12344d", "border": "1px solid #4f8fc0"},
            ],
        )
        return table
    except Exception as exc:
        logger.error(f"Error creando tabla ejecutiva de alertas: {exc}")
        return dbc.Alert(f"Error al crear tabla: {exc}", color="danger")


def create_alert_detail_card(alert_row: pd.Series) -> dbc.Card:
    """
    Create card displaying detailed alert specification with structured AI diagnosis.
    
    Args:
        alert_row: Series with alert data
    
    Returns:
        Bootstrap Card with alert details
    """
    if alert_row.empty:
        return dbc.Alert("No se ha seleccionado ninguna alerta", color="warning")
    
    try:
        # Parse AI diagnosis into structured sections
        ai_message = alert_row['mensaje_ia']
        diagnosis_sections = parse_ia_message_sections(ai_message)
        
        card_content = dbc.Card([
            dbc.CardHeader([
                html.H4([
                    html.I(className="fas fa-exclamation-circle me-2"),
                    f"Alerta: {alert_row.get('FusionID', 'N/A')}"
                ], className="mb-0 text-white")
            ], className="bg-danger"),
            
            dbc.CardBody([
                # Alert Metadata Section
                html.Div([
                    html.H5([
                        html.I(className="fas fa-info-circle me-2"),
                        "Información de la Alerta"
                    ], className="text-primary mb-3 pb-2 border-bottom"),
                    
                    dbc.Row([
                        dbc.Col([
                            html.Div([
                                html.Span([
                                    html.I(className="fas fa-calendar-alt me-2 text-muted"),
                                    html.Strong("Fecha: ")
                                ]),
                                html.Span(alert_row['Timestamp'].strftime('%d/%m/%Y %H:%M:%S'))
                            ], className="mb-3"),
                            
                            html.Div([
                                html.Span([
                                    html.I(className="fas fa-truck me-2 text-muted"),
                                    html.Strong("Unidad: ")
                                ]),
                                html.Span(alert_row['UnitId'], className="badge bg-primary")
                            ], className="mb-3"),
                            
                            html.Div([
                                html.Span([
                                    html.I(className="fas fa-broadcast-tower me-2 text-muted"),
                                    html.Strong("Fuente: ")
                                ]),
                                html.Span(alert_row['Trigger_type'], 
                                         className="badge bg-info")
                            ], className="mb-3")
                        ], md=6),
                        
                        dbc.Col([
                            html.Div([
                                html.Span([
                                    html.I(className="fas fa-cogs me-2 text-muted"),
                                    html.Strong("Sistema: ")
                                ]),
                                html.Span(alert_row['sistema'], className="text-dark")
                            ], className="mb-3"),
                            
                            html.Div([
                                html.Span([
                                    html.I(className="fas fa-layer-group me-2 text-muted"),
                                    html.Strong("SubSistema: ")
                                ]),
                                html.Span(alert_row['subsistema'] if pd.notna(alert_row['subsistema']) else 'N/A')
                            ], className="mb-3"),
                            
                            html.Div([
                                html.Span([
                                    html.I(className="fas fa-wrench me-2 text-muted"),
                                    html.Strong("Componente: ")
                                ]),
                                html.Span(alert_row['componente'] if pd.notna(alert_row['componente']) else 'N/A')
                            ], className="mb-3")
                        ], md=6)
                    ])
                ], className="mb-4"),
                
                # AI Diagnosis Section - Only Diagnóstico and Recomendaciones
                html.Div([
                    html.H5([
                        html.I(className="fas fa-brain me-2"),
                        "Análisis Inteligente"
                    ], className="text-primary mb-3 pb-2 border-bottom"),
                    
                    # Diagnóstico subsection
                    html.Div([
                        html.H6([
                            html.Span("🔬", className="me-2"),
                            "Diagnóstico"
                        ], className="text-dark mb-2"),
                        html.P(
                            diagnosis_sections['diagnostico'] or "No disponible",
                            className="text-muted ps-4",
                            style={'whiteSpace': 'pre-wrap', 'lineHeight': '1.6'}
                        )
                    ], className="mb-3 p-3 bg-light rounded"),
                    
                    # Recomendaciones subsection
                    html.Div([
                        html.H6([
                            html.Span("✅", className="me-2"),
                            "Recomendaciones"
                        ], className="text-dark mb-2"),
                        html.P(
                            diagnosis_sections['acciones'] or "No disponible",
                            className="text-muted ps-4",
                            style={'whiteSpace': 'pre-wrap', 'lineHeight': '1.6'}
                        )
                    ], className="mb-3 p-3 bg-light rounded")
                ])
            ])
        ], className="shadow-sm mb-4 border-0")
        
        logger.info(f"Created alert detail card for FusionID: {alert_row.get('FusionID', 'N/A')}")
        return card_content
    
    except Exception as e:
        logger.error(f"Error creating alert detail card: {e}")
        return dbc.Alert(f"Error al mostrar detalles: {str(e)}", color="danger")


def create_context_kpis_cards(
    alert_row: pd.Series,
    telemetry_data: pd.DataFrame,
    alert_time: pd.Timestamp
) -> dbc.Row:
    """
    **DEPRECATED**: Use create_context_kpis_cards_golden() instead.
    
    Old implementation: Create KPI cards showing alert context information.
    This function loads from silver layer and performs filtering operations.
    
    Args:
        alert_row: Series with alert data
        telemetry_data: DataFrame with telemetry data around alert time
        alert_time: Alert timestamp
    
    Returns:
        Bootstrap Row with KPI cards
    """
    if telemetry_data.empty:
        return dbc.Alert("No hay datos de contexto disponibles", color="info")
    
    try:
        # Get data at alert time (closest point)
        alert_idx = (telemetry_data['Fecha'] - alert_time).abs().idxmin()
        alert_point = telemetry_data.loc[alert_idx]
        
        # KPI 1: Elevation Status
        if 'GPSElevation' in telemetry_data.columns:
            elevation_before = telemetry_data[telemetry_data['Fecha'] < alert_time]['GPSElevation'].tail(5).mean()
            elevation_after = telemetry_data[telemetry_data['Fecha'] >= alert_time]['GPSElevation'].head(5).mean()
            gradient = (elevation_after - elevation_before) / 5 if pd.notna(elevation_before) and pd.notna(elevation_after) else 0
            
            if gradient > 0.05:
                elevation_status = "⬆️ Subiendo"
                elevation_color = "info"
            elif gradient < -0.05:
                elevation_status = "⬇️ Bajando"
                elevation_color = "warning"
            else:
                elevation_status = "➡️ Plano"
                elevation_color = "secondary"
        else:
            elevation_status = "❓ Desconocido"
            elevation_color = "light"
        
        # KPI 2: Payload Status
        payload_status = alert_point.get('EstadoCarga', 'Desconocido')
        if payload_status == 'Cargado':
            payload_display = "✅ Cargado"
            payload_color = "success"
        elif payload_status == 'Vacío':
            payload_display = "❌ Vacío"
            payload_color = "danger"
        else:
            payload_display = "❓ Desconocido"
            payload_color = "light"
        
        # KPI 3: Engine RPM
        rpm_cols = [col for col in telemetry_data.columns if 'rpm' in col.lower() or 'engspd' in col.lower()]
        if rpm_cols:
            rpm_value = round(alert_point.get(rpm_cols[0], None), -2)
            rpm_display = f"{rpm_value:.0f} RPM" if pd.notna(rpm_value) else "❓ Desconocido"
            rpm_color = "primary"
        else:
            rpm_display = "❓ Desconocido"
            rpm_color = "light"
        
        # Create KPI cards
        kpi_row = dbc.Row([
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6("🏔️ Elevación", className="text-muted mb-2"),
                        html.H4(elevation_status, className="mb-0")
                    ])
                ], color=elevation_color, outline=True)
            ], md=4),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6("📦 Estado de Carga", className="text-muted mb-2"),
                        html.H4(payload_display, className="mb-0")
                    ])
                ], color=payload_color, outline=True)
            ], md=4),
            
            dbc.Col([
                dbc.Card([
                    dbc.CardBody([
                        html.H6("⚙️ RPM del Motor", className="text-muted mb-2"),
                        html.H4(rpm_display, className="mb-0")
                    ])
                ], color=rpm_color, outline=True)
            ], md=4)
        ], className="mb-4")
        
        logger.info("Created context KPI cards successfully")
        return kpi_row
    
    except Exception as e:
        logger.error(f"Error creating context KPI cards: {e}")
        return dbc.Alert(f"Error al mostrar KPIs: {str(e)}", color="danger")


def create_maintenance_display(maintenance_data: pd.Series, alert_system: str) -> dbc.Card:
    """
    Create card displaying maintenance information.
    
    Args:
        maintenance_data: Series with maintenance record
        alert_system: System name from alert (for filtering tasks)
    
    Returns:
        Bootstrap Card with maintenance information
    """
    if maintenance_data.empty:
        return dbc.Alert("No hay datos de mantenimiento disponibles", color="info")
    
    try:
        import json
        
        card_content = dbc.Card([
            dbc.CardHeader([
                html.H5([
                    html.I(className="fas fa-wrench me-2"),
                    f"Mantenimiento - Semana {maintenance_data.get('Semana', 'N/A')}"
                ], className="mb-0")
            ]),
            
            dbc.CardBody([
                html.P([
                    html.Strong("🚜 Unidad: "),
                    maintenance_data.get('UnitId', 'N/A')
                ], className="mb-3"),
                
                # Summary
                html.Div([
                    html.H6("📝 Resumen de Actividades:", className="text-primary mb-2"),
                    html.P(
                        maintenance_data.get('Summary', 'No disponible'),
                        className="text-muted",
                        style={'whiteSpace': 'pre-wrap'}
                    )
                ], className="mb-3") if pd.notna(maintenance_data.get('Summary')) else html.Div(),
                
                html.Hr(),
                
                # Tasks filtered by system
                html.Div([
                    html.H6(f"📋 Actividades Relacionadas con {alert_system}:", className="text-primary mb-2"),
                    html.Div(id='maintenance-tasks-list')
                ]) if pd.notna(maintenance_data.get('Tasks_List')) else html.Div([
                    dbc.Alert("No hay lista de tareas disponible", color="info")
                ])
            ])
        ], className="shadow")
        
        # Parse tasks if available
        if pd.notna(maintenance_data.get('Tasks_List')):
            try:
                tasks_dict = json.loads(maintenance_data['Tasks_List'])
                tasks_elements = []
                
                found_tasks = False
                for date, systems in tasks_dict.items():
                    # Compare systems case-insensitively (maintenance CSV uses uppercase)
                    if alert_system.upper() in [s.upper() for s in systems.keys()]:
                        # Find the original key in systems dict (case-insensitive match)
                        matching_key = next(k for k in systems.keys() if k.upper() == alert_system.upper())
                        found_tasks = True
                        tasks_elements.append(html.H6(f"📆 {date}:", className="mt-2"))
                        
                        for task in systems[matching_key]:
                            tasks_elements.append(html.Li(task, className="mb-1"))
                
                if not found_tasks:
                    tasks_elements = [dbc.Alert(
                        f"No se encontraron actividades específicas para {alert_system}",
                        color="warning"
                    )]
                
                card_content = dbc.Card([
                    dbc.CardHeader([
                        html.H5([
                            html.I(className="fas fa-wrench me-2"),
                            f"Mantenimiento - Semana {maintenance_data.get('Semana', 'N/A')}"
                        ], className="mb-0")
                    ]),
                    
                    dbc.CardBody([
                        html.P([
                            html.Strong("🚜 Unidad: "),
                            maintenance_data.get('UnitId', 'N/A')
                        ], className="mb-3"),
                        
                        html.P([
                            html.Strong("🔧 Sistema de Interés: "),
                            alert_system
                        ], className="mb-3"),
                        
                        # Summary
                        html.Div([
                            html.H6("📝 Resumen de Actividades:", className="text-primary mb-2"),
                            html.P(
                                maintenance_data.get('Summary', 'No disponible'),
                                className="text-muted",
                                style={'whiteSpace': 'pre-wrap'}
                            )
                        ], className="mb-3") if pd.notna(maintenance_data.get('Summary')) else html.Div(),
                        
                        html.Hr(),
                        
                        html.Div([
                            html.H6(f"📋 Actividades Relacionadas con {alert_system}:", className="text-primary mb-2"),
                            html.Ul(tasks_elements, className="mb-0")
                        ])
                    ])
                ], className="shadow")
                
            except json.JSONDecodeError:
                logger.warning("Failed to decode maintenance tasks JSON")
        
        logger.info("Created maintenance display card successfully")
        return card_content
    
    except Exception as e:
        logger.error(f"Error creating maintenance display: {e}")
        return dbc.Alert(f"Error al mostrar mantenimiento: {str(e)}", color="danger")
