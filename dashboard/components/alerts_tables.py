"""
Table components for Alerts Dashboard.

Functions to create Dash DataTables for alerts listings.
"""

import pandas as pd
from dash import dash_table, html
import dash_bootstrap_components as dbc
from typing import List, Optional

from src.utils.logger import get_logger

logger = get_logger(__name__)


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
        table_df['mensaje_ia_short'] = table_df['mensaje_ia'].str[:80] + '...'
        
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
        # Parse AI diagnosis into structured sections (if formatted)
        # Expected format: sections separated by newlines or keywords
        ai_message = alert_row['mensaje_ia']
        
        # Try to parse structured diagnosis (basic implementation)
        # This assumes the AI message might contain keywords or is a single paragraph
        diagnosis_sections = {
            'diagnosis': ai_message,  # Default: full message as diagnosis
            'cause': None,
            'risk': None,
            'actions': None
        }
        
        # TODO: Enhance this parsing logic if AI messages have consistent structure
        # For now, display as unified diagnosis with improved formatting
        
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
                
                # AI Diagnosis Section - Structured
                html.Div([
                    html.H5([
                        html.I(className="fas fa-brain me-2"),
                        "Análisis Inteligente"
                    ], className="text-primary mb-3 pb-2 border-bottom"),
                    
                    # Diagnosis subsection
                    html.Div([
                        html.H6([
                            html.I(className="fas fa-stethoscope me-2 text-danger"),
                            "Diagnóstico"
                        ], className="text-dark mb-2"),
                        html.P(
                            diagnosis_sections['diagnosis'],
                            className="text-muted ps-4",
                            style={'whiteSpace': 'pre-wrap', 'lineHeight': '1.6'}
                        )
                    ], className="mb-3 p-3 bg-light rounded"),
                    
                    # Note: If AI messages are structured in the future, uncomment these sections
                    # and implement proper parsing logic above
                    
                    # # Probable Cause subsection
                    # html.Div([
                    #     html.H6([
                    #         html.I(className="fas fa-search me-2 text-warning"),
                    #         "Causa Probable"
                    #     ], className="text-dark mb-2"),
                    #     html.P(
                    #         diagnosis_sections['cause'] or "Análisis en progreso...",
                    #         className="text-muted ps-4"
                    #     )
                    # ], className="mb-3 p-3 bg-light rounded"),
                    
                    # # Operational Risk subsection
                    # html.Div([
                    #     html.H6([
                    #         html.I(className="fas fa-exclamation-triangle me-2 text-danger"),
                    #         "Riesgo Operacional"
                    #     ], className="text-dark mb-2"),
                    #     html.P(
                    #         diagnosis_sections['risk'] or "Evaluación pendiente...",
                    #         className="text-muted ps-4"
                    #     )
                    # ], className="mb-3 p-3 bg-light rounded"),
                    
                    # # Recommended Actions subsection
                    # html.Div([
                    #     html.H6([
                    #         html.I(className="fas fa-tasks me-2 text-success"),
                    #         "Acciones Recomendadas"
                    #     ], className="text-dark mb-2"),
                    #     html.P(
                    #         diagnosis_sections['actions'] or "Recomendaciones en desarrollo...",
                    #         className="text-muted ps-4"
                    #     )
                    # ], className="mb-3 p-3 bg-light rounded")
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
