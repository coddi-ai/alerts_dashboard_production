# Standard color mapping for sistema
SISTEMA_COLORS = {
    'Tren de Fuerza': '#4f8a8b',
    'Tren de fuerza': '#4f8a8b',
    'Motor': '#355c7d',
    'Frenos': '#d08c60',
    'Direccion': '#7c6a9a',
    'Dirección': '#7c6a9a',
}
"""
Chart components for Alerts Dashboard.

Functions to create Plotly figures for alerts analytics.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import List, Dict, Optional
from datetime import datetime, timedelta
import dash_bootstrap_components as dbc
from dash import html
import plotly.colors

from src.utils.logger import get_logger

logger = get_logger(__name__)

# Operational state color mapping
STATE_COLORS = {
    'Operacional': '#2ecc71',  # Green
    'Ralenti': '#f39c12',      # Orange
    'RalentÃ­': '#f39c12',
    'IDLE': '#f39c12',
    'PREPARACION': '#f39c12',
    'PREPARACIÃ“N': '#f39c12',
    'PreparaciÃ³n': '#f39c12',
    'RPM_BAJA': '#f39c12',
    'HABILITADO': '#2ecc71',
    'Habilitado': '#2ecc71',
    'ND': '#95a5a6'            # Gray
}

STATE_LABELS = {
    'HABILITADO': 'Operacional',
    'Habilitado': 'Operacional',
    'Operacional': 'Operacional',
    'PREPARACION': 'PreparaciÃ³n',
    'PREPARACIÃ“N': 'PreparaciÃ³n',
    'PreparaciÃ³n': 'PreparaciÃ³n',
    'Ralenti': 'RalentÃ­ / Idle',
    'RalentÃ­': 'RalentÃ­ / Idle',
    'IDLE': 'RalentÃ­ / Idle',
    'RPM_BAJA': 'RalentÃ­ / RPM baja',
}

# Capstone state labels may arrive with either UTF-8 or legacy decoded text.
# Normalize both forms for the legend without changing CDA's existing states.
STATE_COLORS.update({
    'Preparaci\u00f3n': '#f39c12',
    'PREPARACI\u00d3N': '#f39c12',
    'Transici\u00f3n': '#95a5a6',
    'Transicion': '#95a5a6',
})
STATE_LABELS.update({
    'Preparaci\u00f3n': 'Preparaci\u00f3n',
    'PREPARACI\u00d3N': 'Preparaci\u00f3n',
    'PreparaciÃ³n': 'Preparaci\u00f3n',
    'PREPARACION': 'Preparaci\u00f3n',
    'Transici\u00f3n': 'Transici\u00f3n',
    'Transicion': 'Transici\u00f3n',
})

# Spanish feature names mapping
FEATURE_NAMES_ES = {
    "EngCoolTemp": 'Temperatura del refrigerante del motor',
    "RAftrclrTemp": 'Temperatura del post-enfriador del motor',
    "EngOilPres": 'Presión del aceite del motor',
    "EngOilFltr": 'Estado del filtro de aceite del motor',
    "CnkcasePres": 'Presión del cárter del motor',
    "RtLtExhTemp": 'Diferencia de temperatura del escape derecho e izquierdo',
    "RtExhTemp": 'Temperatura del escape derecho del motor',
    "LtExhTemp": 'Temperatura del escape izquierdo del motor',
    "AirFltr": 'Estado del filtro de aire del motor',
    "LckupSlip": 'Deslizamiento del embrague de bloqueo',
    "TrnSlip": 'Deslizamiento de la transmisión',
    # Variables de tribología que pueden aparecer junto a una señal de
    # telemetría en una alerta mixta.
    "Hierro": 'Hierro',
    "Aluminio": 'Aluminio',
    "Zinc": 'Zinc',
    "Calcio": 'Calcio',
    "Fósforo": 'Fósforo',
    "Índice PQ": 'Índice PQ',
    "Oxidación": 'Oxidación',
    "Hollín": 'Hollín',
    "Silicio": 'Silicio',
    "Potasio": 'Potasio',
    "Níquel": 'Níquel',
    "Cobre": 'Cobre',
    "Cromo": 'Cromo',
    "Plomo": 'Plomo',
    "Estaño": 'Estaño',
    "DiffLubePres": 'Presión del lubricante del diferencial',
    "DiffTemp": 'Temperatura del diferencial',
    "TrnLubeTemp": 'Temperatura del lubricante de la transmisión',
    "TCOutTemp": 'Temperatura de salida del convertidor de par',
    "RtRBrkTemp": 'Temperatura del freno trasero derecho',
    "RtFBrkTemp": 'Temperatura del freno delantero derecho',
    "LtRBrkTemp": 'Temperatura del freno trasero izquierdo',
    "LtFBrkTemp": 'Temperatura del freno delantero izquierdo',
    "StrgOilTemp": 'Temperatura del aceite de dirección'
}

# Capstone canonical signal names. These keys are additive and do not change
# the established CDA labels or chart rendering.
FEATURE_NAMES_ES.update({
    'engine_speed_rpm': 'Velocidad del motor',
    'engine_load_pct': 'Carga del motor',
    'coolant_temp_c': 'Temperatura del refrigerante',
    'coolant_pressure_psi': 'Presi\u00f3n del refrigerante',
    'ecu_temp_c': 'Temperatura de la ECU',
    'crankcase_pressure_inh2o': 'Presi\u00f3n del c\u00e1rter',
    'compressor_intake_temp_c': 'Temperatura de admisi\u00f3n del compresor',
    'turbo_speed_rpm': 'Velocidad del turbo',
    'oil_filter_dp_psi': 'Presi\u00f3n diferencial del filtro de aceite',
    'oil_filter_dp_mcrs_psi': 'Presi\u00f3n diferencial del filtro de aceite (MCRS)',
    'oil_temp_c': 'Temperatura del aceite',
    'fuel_pump_intake_pressure_psi': 'Presi\u00f3n de admisi\u00f3n de la bomba de combustible',
    'oil_diff_pressure_psi': 'Presi\u00f3n diferencial del aceite',
    'pre_filter_oil_pressure_psi': 'Presi\u00f3n de aceite pre-filtro',
    'rifle_oil_pressure_psi': 'Presi\u00f3n de aceite del rifle',
    'post_engine_pressure_psi': 'Presi\u00f3n de aceite post-motor',
    'oil_level_pct': 'Nivel de aceite',
    'oil_priming_state': 'Estado de cebado del aceite',
    'fan_speed_rpm': 'Velocidad del ventilador',
    'power_hp': 'Potencia del motor',
    'imp_lb_psi': 'Presi\u00f3n de admisi\u00f3n banco izquierdo',
    'imp_rb_psi': 'Presi\u00f3n de admisi\u00f3n banco derecho',
    'imt_lbf_c': 'Temperatura de admisi\u00f3n banco izquierdo frontal',
    'imt_lbr_c': 'Temperatura de admisi\u00f3n banco izquierdo trasero',
    'imt_rbf_c': 'Temperatura de admisi\u00f3n banco derecho frontal',
    'imt_rbr_c': 'Temperatura de admisi\u00f3n banco derecho trasero',
    'egt_avg_c': 'Temperatura promedio de gases de escape',
    'egt_lb_c': 'Temperatura de escape banco izquierdo',
    'egt_rb_c': 'Temperatura de escape banco derecho',
    **{f'egt_{index:02d}_c': f'Temperatura de escape cilindro {index:02d}' for index in range(1, 17)},
})

# Features to omit from dashboard
OMITTED_FEATURES = ['GroundSpd', 'EngLoad']


def create_alerts_per_unit_chart(alerts_df: pd.DataFrame) -> go.Figure:
    """
    Create horizontal bar chart showing distribution of alerts per unit.
    
    Args:
        alerts_df: DataFrame with columns ['UnitId', 'sistema']
    
    Returns:
        Plotly Figure with horizontal bar chart
    """
    if alerts_df.empty:
        logger.warning("Cannot create alerts per unit chart: empty dataframe")
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Count alerts per unit and system
        alerts_per_unit = alerts_df.groupby(['UnitId', 'sistema']).size().reset_index(name='Count')
        
        # Sort systems in reverse alphabetical order for consistent ordering
        alerts_per_unit['sistema'] = pd.Categorical(
            alerts_per_unit['sistema'],
            categories=sorted(alerts_per_unit['sistema'].unique(), reverse=True),
            ordered=True
        )
        alerts_per_unit = alerts_per_unit.sort_values('sistema')
        
        # Create horizontal bar chart
        fig = px.bar(
            alerts_per_unit,
            y='UnitId',
            x='Count',
            color='sistema',
            orientation='h',
            title=None,
            labels={'Count': 'Número de Alertas', 'UnitId': 'Unidad'},
            template='plotly_white',
            height=500,
            color_discrete_map=SISTEMA_COLORS
        )
        # Horizontal, compact legend at top right
        fig.update_layout(
            yaxis={'categoryorder': 'total ascending'},
            showlegend=True,
            legend=dict(
                title='Sistema',
                orientation='h',
                x=1,
                y=1.08,
                xanchor='right',
                yanchor='bottom',
                font=dict(size=11),
                itemwidth=80
            ),
            hovermode='closest'
        )
        
        logger.info("Created alerts per unit chart successfully")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating alerts per unit chart: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_alerts_per_month_chart(alerts_df: pd.DataFrame) -> go.Figure:
    """
    Create vertical bar chart showing distribution of alerts per month.
    
    Args:
        alerts_df: DataFrame with columns ['Month', 'sistema']
    
    Returns:
        Plotly Figure with vertical bar chart
    """
    if alerts_df.empty:
        logger.warning("Cannot create alerts per month chart: empty dataframe")
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Count alerts per month and system
        alerts_per_month = alerts_df.groupby(['Month', 'sistema']).size().reset_index(name='Count')
        alerts_per_month['Month_str'] = alerts_per_month['Month'].astype(str)
        
        # Sort systems in reverse alphabetical order for consistent ordering
        alerts_per_month['sistema'] = pd.Categorical(
            alerts_per_month['sistema'],
            categories=sorted(alerts_per_month['sistema'].unique(), reverse=True),
            ordered=True
        )
        alerts_per_month = alerts_per_month.sort_values('sistema')
        
        # Create vertical bar chart
        fig = px.bar(
            alerts_per_month,
            x='Month_str',
            y='Count',
            color='sistema',
            title=None,
            labels={'Month_str': 'Mes', 'Count': 'Número de Alertas'},
            template='plotly_white',
            height=500,
            color_discrete_map=SISTEMA_COLORS
        )
        # Horizontal, compact legend at top right
        fig.update_layout(
            xaxis_tickangle=-45,
            showlegend=True,
            legend=dict(
                title='Sistema',
                orientation='h',
                x=1,
                y=1.08,
                xanchor='right',
                yanchor='bottom',
                font=dict(size=11),
                itemwidth=80
            ),
            hovermode='x unified'
        )
        
        logger.info("Created alerts per month chart successfully")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating alerts per month chart: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_alerts_per_week_chart(alerts_df: pd.DataFrame) -> go.Figure:
    """Create a weekly stacked alert evolution chart."""
    if alerts_df is None or alerts_df.empty:
        return go.Figure().add_annotation(text="No hay alertas para el período", x=0.5, y=0.5, showarrow=False)
    frame = alerts_df.copy()
    timestamp = pd.to_datetime(frame.get('Timestamp'), errors='coerce')
    frame = frame.loc[timestamp.notna()].copy()
    frame['_week_start'] = timestamp.loc[frame.index].dt.to_period('W-SUN').dt.start_time
    frame['_system_display'] = frame.get('sistema', '').map(lambda value: {
        'Direccion': 'Dirección', 'Dirección': 'Dirección', 'Tren de Fuerza': 'Tren de fuerza'
    }.get(value, value))
    grouped = frame.groupby(['_week_start', '_system_display']).size().reset_index(name='Count')
    weeks = pd.date_range(frame['_week_start'].min(), frame['_week_start'].max(), freq='7D')
    systems = sorted(frame['_system_display'].dropna().unique())
    full = pd.MultiIndex.from_product([weeks, systems], names=['_week_start', '_system_display']).to_frame(index=False)
    grouped = full.merge(grouped, how='left', on=['_week_start', '_system_display']).fillna({'Count': 0})
    grouped['Semana'] = grouped['_week_start'].dt.strftime('%d/%m')
    fig = px.bar(
        grouped,
        x='Semana',
        y='Count',
        color='_system_display',
        barmode='stack',
        labels={'Semana': 'Semana iniciada', 'Count': 'Alertas', '_system_display': 'Sistema'},
        color_discrete_map=SISTEMA_COLORS,
        template='plotly_white',
        height=360,
    )
    fig.update_traces(hovertemplate='<b>%{fullData.name}</b><br>Semana: %{x}<br>Alertas: %{y}<extra></extra>')
    fig.update_layout(
        margin=dict(l=45, r=15, t=18, b=55),
        legend=dict(orientation='h', y=1.08, x=1, xanchor='right', yanchor='bottom', font=dict(size=10)),
        hovermode='x unified',
    )
    return fig


def create_trigger_distribution_treemap(alerts_df: pd.DataFrame) -> go.Figure:
    """
    Create treemap showing distribution of alert triggers.
    
    Args:
        alerts_df: DataFrame with column ['Trigger_type']
    
    Returns:
        Plotly Figure with treemap
    """
    if alerts_df.empty:
        logger.warning("Cannot create trigger distribution treemap: empty dataframe")
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Count alerts by trigger type
        trigger_counts = alerts_df['Trigger_type'].value_counts().reset_index()
        trigger_counts.columns = ['Trigger_type', 'Frequency']
        
        # Create treemap (no frequency bar, just label)
        fig = px.treemap(
            trigger_counts,
            path=['Trigger_type'],
            values='Frequency',
            title=None,
            color_discrete_sequence=['#3498db'],
            height=500
        )
        fig.update_traces(
            textinfo='label+percent parent',
            textfont_size=14
        )
        fig.update_layout(showlegend=False)
        logger.info("Created trigger distribution treemap successfully")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating trigger distribution treemap: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_sensor_trends_chart(
    telemetry_values: pd.DataFrame,
    telemetry_states: pd.DataFrame,
    limits_config: pd.DataFrame,
    unit_id: str,
    sensor_columns: List[str],
    alert_time: datetime,
    window_start: datetime,
    window_end: datetime,
    feature_names: Dict[str, str]
) -> go.Figure:
    """
    **DEPRECATED**: Use create_sensor_trends_chart_golden() instead.
    
    Old implementation: Create multi-panel time series chart showing sensor trends with limits.
    This function loads from silver layer and performs complex merging operations.
    
    Args:
        telemetry_values: DataFrame with telemetry sensor values
        telemetry_states: DataFrame with operational states
        limits_config: DataFrame with sensor limits
        unit_id: Unit identifier
        sensor_columns: List of sensor column names to display
        alert_time: Alert timestamp
        window_start: Start of time window
        window_end: End of time window
        feature_names: Dictionary mapping feature codes to Spanish names
    
    Returns:
        Plotly Figure with subplots (one per sensor)
    """
    if telemetry_values.empty:
        logger.warning("Cannot create sensor trends chart: empty telemetry values")
        return go.Figure().add_annotation(
            text="No telemetry data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Filter data for unit and time window
        unit_data = telemetry_values[
            (telemetry_values['Unit'] == unit_id) &
            (telemetry_values['Fecha'] >= window_start) &
            (telemetry_values['Fecha'] <= window_end)
        ].copy()
        
        # Merge with states
        if not telemetry_states.empty:
            unit_data = unit_data.merge(
                telemetry_states[['Fecha', 'Unit', 'Estado', 'EstadoCarga']],
                on=['Fecha', 'Unit'],
                how='left'
            )
        
        if unit_data.empty:
            logger.warning("No telemetry data in time window")
            return go.Figure().add_annotation(
                text="No data in time window",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
        
        # Merge limits into unit_data
        if not limits_config.empty:
            unit_limits = limits_config[limits_config['Unit'] == unit_id].copy()
            
            for sensor in sensor_columns:
                feature_limits = unit_limits[unit_limits['Feature'] == sensor].copy()
                
                if not feature_limits.empty:
                    feature_limits = feature_limits.rename(columns={
                        'Limit_Lower': f'{sensor}_Lower',
                        'Limit_Upper': f'{sensor}_Upper'
                    })
                    
                    unit_data = unit_data.merge(
                        feature_limits[['Estado', 'EstadoCarga', f'{sensor}_Lower', f'{sensor}_Upper']],
                        on=['Estado', 'EstadoCarga'],
                        how='left'
                    )
        
        # Create subplots
        fig = make_subplots(
            rows=len(sensor_columns),
            cols=1,
            shared_xaxes=True,
            subplot_titles=[feature_names.get(sensor, sensor) for sensor in sensor_columns],
            vertical_spacing=0.08
        )
        
        # Plot each sensor
        for idx, sensor in enumerate(sensor_columns, 1):
            sensor_name = feature_names.get(sensor, sensor)
            
            # Plot data points colored by operational state
            for estado in unit_data['Estado'].dropna().unique():
                estado_data = unit_data[unit_data['Estado'] == estado]
                
                fig.add_trace(
                    go.Scatter(
                        x=estado_data['Fecha'],
                        y=estado_data[sensor],
                        mode='markers',
                        name=f'{estado}',
                        legendgroup=estado,
                        showlegend=(idx == 1),  # Only show legend for first subplot
                        marker=dict(
                            color=STATE_COLORS.get(estado, '#95a5a6'),
                            size=6
                        ),
                        hovertemplate=(
                            f'<b>{sensor_name}</b><br>' +
                            'Hora: %{x}<br>' +
                            'Valor: %{y:.2f}<br>' +
                            f'Estado: {estado}<br>' +
                            '<extra></extra>'
                        )
                    ),
                    row=idx,
                    col=1
                )
            
            # Plot continuous limit lines
            lower_col = f'{sensor}_Lower'
            upper_col = f'{sensor}_Upper'
            
            if lower_col in unit_data.columns and unit_data[lower_col].notna().any():
                fig.add_trace(
                    go.Scatter(
                        x=unit_data['Fecha'],
                        y=unit_data[lower_col],
                        mode='lines',
                        name='Límite Inferior',
                        legendgroup='limits',
                        showlegend=(idx == 1),
                        line=dict(color='red', width=2, dash='dash'),
                        hovertemplate='Límite Inferior: %{y:.2f}<extra></extra>'
                    ),
                    row=idx,
                    col=1
                )
            
            if upper_col in unit_data.columns and unit_data[upper_col].notna().any():
                fig.add_trace(
                    go.Scatter(
                        x=unit_data['Fecha'],
                        y=unit_data[upper_col],
                        mode='lines',
                        name='Límite Superior',
                        legendgroup='limits',
                        showlegend=(idx == 1),
                        line=dict(color='red', width=2, dash='dash'),
                        hovertemplate='Límite Superior: %{y:.2f}<extra></extra>'
                    ),
                    row=idx,
                    col=1
                )
            
            # Add alert time marker
            y_min = unit_data[sensor].min()
            y_max = unit_data[sensor].max()
            
            if lower_col in unit_data.columns and unit_data[lower_col].notna().any():
                y_min = min(y_min, unit_data[lower_col].min())
            if upper_col in unit_data.columns and unit_data[upper_col].notna().any():
                y_max = max(y_max, unit_data[upper_col].max())
            
            if pd.notna(y_min) and pd.notna(y_max):
                y_range = y_max - y_min if y_max != y_min else 1
                y_extended_min = y_min - (0.1 * y_range)
                y_extended_max = y_max + (0.1 * y_range)
                
                fig.add_trace(
                    go.Scatter(
                        x=[alert_time, alert_time],
                        y=[y_extended_min, y_extended_max],
                        mode='lines',
                        name='⚠️ Alerta',
                        legendgroup='alert',
                        showlegend=(idx == 1),
                        line=dict(color='orange', width=3),
                        hovertemplate=f"Momento de Alerta: {alert_time}<extra></extra>"
                    ),
                    row=idx,
                    col=1
                )
        
        # Update layout
        fig.update_layout(
            title={
                'text': f'Análisis de Tendencias - {unit_id}',
                'x': 0.5,
                'xanchor': 'center',
                'font': dict(size=16, color='#2c3e50')
            },
            height=300 * len(sensor_columns),
            template='plotly_white',
            hovermode='x unified',
            margin=dict(l=60, r=20, t=50, b=40)
        )
        
        # Update axes
        fig.update_xaxes(
            title_text='Hora',
            showgrid=True,
            gridwidth=1,
            gridcolor='#ecf0f1',
            row=len(sensor_columns),
            col=1
        )
        
        for i in range(1, len(sensor_columns) + 1):
            fig.update_yaxes(
                title_text='Valor',
                showgrid=True,
                gridwidth=1,
                gridcolor='#ecf0f1',
                row=i,
                col=1
            )
        
        logger.info(f"Created sensor trends chart with {len(sensor_columns)} sensors")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating sensor trends chart: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_gps_route_map(
    telemetry_values: pd.DataFrame,
    unit_id: str,
    alert_time: datetime,
    window_start: datetime,
    window_end: datetime,
    mapbox_token: str
) -> go.Figure:
    """
    **DEPRECATED**: Use create_gps_route_map_golden() instead.
    
    Old implementation: Create GPS route map with alert location.
    This function loads from silver layer and performs filtering operations.
    
    Args:
        telemetry_values: DataFrame with GPS columns (GPSLat, GPSLon, Fecha)
        unit_id: Unit identifier
        alert_time: Alert timestamp
        window_start: Start of time window
        window_end: End of time window
        mapbox_token: Mapbox access token
    
    Returns:
        Plotly Figure with GPS map
    """
    if telemetry_values.empty:
        logger.warning("Cannot create GPS map: empty telemetry values")
        return go.Figure().add_annotation(
            text="No GPS data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Filter data
        unit_data = telemetry_values[
            (telemetry_values['Unit'] == unit_id) &
            (telemetry_values['Fecha'] >= window_start) &
            (telemetry_values['Fecha'] <= window_end)
        ].copy()
        
        gps_data = unit_data.dropna(subset=['GPSLat', 'GPSLon']).copy()
        
        if gps_data.empty:
            logger.warning("No GPS data in time window")
            return go.Figure().add_annotation(
                text="No GPS data in time window",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
        
        # Normalize time for color gradient
        time_min = gps_data['Fecha'].min()
        time_max = gps_data['Fecha'].max()
        
        if time_max > time_min:
            gps_data['TimeNorm'] = (gps_data['Fecha'] - time_min) / (time_max - time_min)
        else:
            gps_data['TimeNorm'] = 0.5
        
        # Create map
        fig = go.Figure()
        
        # Add route line
        fig.add_trace(go.Scattermapbox(
            lat=gps_data['GPSLat'],
            lon=gps_data['GPSLon'],
            mode='lines',
            line=dict(width=2, color='rgba(100, 100, 100, 0.5)'),
            showlegend=False,
            hoverinfo='skip'
        ))
        
        # Add colored points
        fig.add_trace(go.Scattermapbox(
            lat=gps_data['GPSLat'],
            lon=gps_data['GPSLon'],
            mode='markers',
            marker=dict(
                size=10,
                color=gps_data['TimeNorm'],
                colorscale='Reds',
                showscale=False
            ),
            showlegend=False,
            text=gps_data['Fecha'].dt.strftime('%H:%M:%S'),
            hovertemplate='Hora: %{text}<extra></extra>'
        ))
        
        # Add alert marker
        alert_idx = (gps_data['Fecha'] - alert_time).abs().argmin()
        alert_point = gps_data.iloc[alert_idx]
        
        fig.add_trace(go.Scattermapbox(
            lat=[alert_point['GPSLat']],
            lon=[alert_point['GPSLon']],
            mode='markers',
            marker=dict(
                size=25,
                color='black',
                symbol='marker'
            ),
            showlegend=False,
            text=[f"⚠️ Alerta: {alert_time.strftime('%H:%M:%S')}"],
            hovertemplate='%{text}<extra></extra>'
        ))
        
        fig.update_layout(
            mapbox=dict(
                accesstoken=mapbox_token,
                style="satellite-streets",
                center=dict(
                    lat=gps_data['GPSLat'].mean(),
                    lon=gps_data['GPSLon'].mean()
                ),
                zoom=14
            ),
            title='Ruta GPS - Vista Satelital',
            height=600,
            margin=dict(l=0, r=0, t=40, b=0),
            showlegend=False
        )
        
        logger.info(f"Created GPS route map with {len(gps_data)} points")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating GPS route map: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_oil_radar_chart(oil_report: pd.Series, essay_cols: List[str]) -> go.Figure:
    """
    Create radar chart showing oil essay levels.
    
    Args:
        oil_report: Series with oil report data
        essay_cols: List of essay column names (ending with _ppm)
    
    Returns:
        Plotly Figure with radar chart
    """
    # Check if data is available (Series doesn't have .empty attribute)
    if oil_report is None or len(oil_report) == 0 or not essay_cols:
        logger.warning("Cannot create oil radar chart: empty data or no essay columns")
        return go.Figure().add_annotation(
            text="No oil data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        fig = go.Figure()
        
        # Get values for each essay column
        r_values = [float(oil_report.get(col, 0)) if pd.notna(oil_report.get(col, 0)) else 0 for col in essay_cols]
        theta_values = [col.replace('_ppm', '').replace('_', ' ').title() for col in essay_cols]
        
        # Calculate max value for scale (ensure at least 1 for visibility)
        max_value = max(r_values) if max(r_values) > 0 else 1
        
        # Add actual values
        fig.add_trace(go.Scatterpolar(
            r=r_values,
            theta=theta_values,
            fill='toself',
            name='Valores Actuales',
            line_color='#3498db',
            hovertemplate='<b>%{theta}</b><br>Valor: %{r:.2f} ppm<extra></extra>'
        ))
        
        fig.update_layout(
            polar=dict(
                radialaxis=dict(
                    visible=True,
                    range=[0, max_value * 1.2]
                )
            ),
            title='Análisis de Aceite - Niveles de Elementos',
            height=500,
            showlegend=True
        )
        
        logger.info(f"Created oil radar chart successfully with {len(essay_cols)} essays")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating oil radar chart: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_system_distribution_pie_chart(alerts_df: pd.DataFrame) -> go.Figure:
    """
    Create pie chart showing distribution of alerts per system.
    
    Args:
        alerts_df: DataFrame with column ['sistema']
    
    Returns:
        Plotly Figure with pie chart
    """
    if alerts_df.empty:
        logger.warning("Cannot create system distribution pie chart: empty dataframe")
        return go.Figure().add_annotation(
            text="No data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Count alerts by system
        system_counts = alerts_df['sistema'].value_counts().reset_index()
        system_counts.columns = ['sistema', 'Count']
        
        # Sort systems in reverse alphabetical order
        system_counts = system_counts.sort_values('sistema', ascending=False)
        
        # Create pie chart with standard color mapping
        fig = px.pie(
            system_counts,
            values='Count',
            names='sistema',
            title=None,  # Remove title
            hole=0.3,  # Makes it a donut chart
            color='sistema',
            color_discrete_map=SISTEMA_COLORS
        )
        fig.update_traces(
            textposition='inside',
            textinfo='percent+label',
            hovertemplate='<b>%{label}</b><br>Alertas: %{value}<br>Porcentaje: %{percent}<extra></extra>'
        )
        # Remove legend
        fig.update_layout(
            height=500,
            showlegend=False
        )
        logger.info("Created system distribution pie chart successfully")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating system distribution pie chart: {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )

# ================================
# NEW GOLDEN LAYER CHART FUNCTIONS
# ================================

def create_sensor_trends_chart_golden(
    alert_data: pd.DataFrame,
    feature_names: List[str],
    unit_id: str,
    alert_time: datetime,
    feature_name_map: Optional[Dict[str, str]] = None,
    client: Optional[str] = None
) -> go.Figure:
    """
    Create multi-panel time series chart using pre-processed golden layer data.
    
    Args:
        alert_data: DataFrame with alert data from golden layer
        feature_names: List of feature names to plot
        unit_id: Unit identifier
        alert_time: Alert timestamp
        feature_name_map: Dictionary mapping feature codes to Spanish names
    
    Returns:
        Plotly Figure with subplots (one per sensor)
    """
    if alert_data.empty or not feature_names:
        logger.warning("Cannot create sensor trends chart: empty data or no features")
        return go.Figure().add_annotation(
            text="No sensor data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    try:
        is_capstone = str(client or '').strip().upper() == 'CAPSTONE'
        # Filter data to M1 minutes before and M2 minutes after alert
        M1 = 90  # minutes before alert
        M2 = 10   # minutes after alert
        time_window_start = alert_time - timedelta(minutes=M1)
        time_window_end = alert_time + timedelta(minutes=M2)
        
        alert_data_filtered = alert_data[
            (alert_data['TimeStart'] >= time_window_start) &
            (alert_data['TimeStart'] <= time_window_end)
        ].copy()
        
        if alert_data_filtered.empty:
            logger.warning(f"No data in time window [{time_window_start}, {time_window_end}]")
            return go.Figure().add_annotation(
                text="No sensor data in time window",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
        
        # Use filtered data for plotting
        alert_data = alert_data_filtered
        
        # Use Spanish names if mapping provided
        subplot_titles = [feature_name_map.get(f, f) if feature_name_map else f for f in feature_names]
        
        # Plotly limits vertical_spacing to 1 / (rows - 1). Capstone can
        # expose many mapped signals, so reduce spacing for tall charts.
        panel_count = len(feature_names)
        vertical_spacing = (
            (0.12 if panel_count <= 1 else min(0.05, 0.9 / (panel_count - 1)))
            if is_capstone else 0.12
        )
        fig = make_subplots(
            rows=panel_count,
            cols=1,
            shared_xaxes=True,
            subplot_titles=subplot_titles,
            vertical_spacing=vertical_spacing
        )
        limit_legend_shown = False
        # Plot each feature
        for idx, feature in enumerate(feature_names, 1):
            value_col = f'{feature}_Value'
            upper_col = f'{feature}_Upper_Limit'
            lower_col = f'{feature}_Lower_Limit'
            display_name = feature_name_map.get(feature, feature) if feature_name_map else feature
            if is_capstone:
                # Capstone may expose the same context signal under the
                # legacy CDA aliases. Prefer the canonical ETL column, but
                # fall back to the alias when the canonical series is empty.
                alias = {'engine_speed_rpm': 'EngSpd', 'engine_load_pct': 'EngLoad'}.get(feature)
                if alias:
                    canonical_has_values = (
                        value_col in alert_data.columns
                        and pd.to_numeric(alert_data[value_col], errors='coerce').notna().any()
                    )
                    if not canonical_has_values and f'{alias}_Value' in alert_data.columns:
                        value_col = f'{alias}_Value'
                        upper_col = f'{alias}_Upper_Limit'
                        lower_col = f'{alias}_Lower_Limit'
            if is_capstone:
                if value_col not in alert_data.columns:
                    logger.warning("Skipping feature without value column: %s", feature)
                    continue
                # Keep one continuous trace per variable. State is retained
                # in hover metadata and represented by explicit swatches.
                value_columns = ['TimeStart', value_col]
                if 'State' in alert_data.columns:
                    value_columns.append('State')
                value_data = alert_data[value_columns].copy()
                value_data[value_col] = pd.to_numeric(value_data[value_col], errors='coerce')
                value_data = value_data.dropna(subset=['TimeStart', value_col]).sort_values('TimeStart')
                if value_data.empty:
                    continue
                if 'State' not in value_data.columns:
                    value_data['State'] = ''
                state_labels = value_data['State'].map(
                    lambda state: STATE_LABELS.get(str(state), str(state)) if str(state) else ''
                )
                state_colors = value_data['State'].map(
                    lambda state: STATE_COLORS.get(str(state), '#2ecc71') if str(state) else '#2ecc71'
                )
                fig.add_trace(
                    go.Scatter(
                        x=value_data['TimeStart'],
                        y=value_data[value_col],
                        mode='lines+markers',
                        connectgaps=True,
                        name=display_name,
                        showlegend=False,
                        customdata=state_labels.to_numpy(),
                        marker=dict(
                            size=6,
                            color=state_colors.to_numpy(),
                            line=dict(width=1, color='white')
                        ),
                        line=dict(color='#2ecc71', width=2),
                        hovertemplate=(
                            f'<b>{display_name}</b><br>' +
                            'Hora: %{x}<br>' +
                            'Valor: %{y:.2f}<br>' +
                            'Estado: %{customdata}<br>' +
                            '<extra></extra>'
                        )
                    ),
                    row=idx,
                    col=1
                )
            else:
                # Preserve CDA's established state-split marker rendering.
                if 'State' in alert_data.columns and alert_data['State'].notna().any():
                    for state in alert_data['State'].dropna().unique():
                        state_data = alert_data[alert_data['State'] == state]
                        fig.add_trace(
                            go.Scatter(
                                x=state_data['TimeStart'],
                                y=state_data[value_col],
                                mode='markers',
                                name=state,
                                legendgroup=state,
                                showlegend=(idx == 1),
                                marker=dict(
                                    color=STATE_COLORS.get(state, '#95a5a6'),
                                    size=8,
                                    line=dict(width=1, color='white')
                                ),
                                line=dict(
                                    color=STATE_COLORS.get(state, '#95a5a6'),
                                    width=2
                                ),
                                hovertemplate=(
                                    f'<b>{display_name}</b><br>' +
                                    'Hora: %{x}<br>' +
                                    'Valor: %{y:.2f}<br>' +
                                    f'Estado: {state}<br>' +
                                    '<extra></extra>'
                                )
                            ),
                            row=idx,
                            col=1
                        )
                else:
                    fig.add_trace(
                        go.Scatter(
                            x=alert_data['TimeStart'],
                            y=alert_data[value_col],
                            mode='markers',
                            name=display_name,
                            showlegend=(idx == 1),
                            marker=dict(
                                size=8,
                                color='#3498db',
                                line=dict(width=1, color='white')
                            ),
                            line=dict(color='#3498db', width=2),
                            hovertemplate=(
                                f'<b>{display_name}</b><br>' +
                                'Hora: %{x}<br>' +
                                'Valor: %{y:.2f}<br>' +
                                '<extra></extra>'
                            )
                        ),
                        row=idx,
                        col=1
                    )
            # Plot limits (SECONDARY PRIORITY - Visually lighter)
            # Lower limit - Use lighter color and thinner line
            if lower_col in alert_data.columns and alert_data[lower_col].notna().any():
                alert_low = alert_data[['TimeStart', lower_col]].copy()
                alert_low.sort_values(by='TimeStart', inplace=True)  # Ensure limits are plotted in order
                fig.add_trace(
                    go.Scatter(
                        x=alert_low['TimeStart'],
                        y=alert_low[lower_col],
                        mode='lines',
                        name='L\u00edmite',
                        legendgroup='limits',
                        showlegend=not limit_legend_shown,
                        line=dict(
                            color='rgba(231, 76, 60, 0.4)',  # Lighter red with transparency
                            width=1.5,  # Thinner than signal
                            dash='dash'  # Dashed style for lower limit
                        ),
                        hovertemplate='Límite Inferior: %{y:.2f}<extra></extra>'
                    ),
                    row=idx,
                    col=1
                )
                limit_legend_shown = True
            
            # Upper limit - Use different style to distinguish from lower
            if upper_col in alert_data.columns and alert_data[upper_col].notna().any():
                alert_high = alert_data[['TimeStart', upper_col]].copy()
                alert_high.sort_values(by='TimeStart', inplace=True)  # Ensure limits are plotted in order
                fig.add_trace(
                    go.Scatter(
                        x=alert_high['TimeStart'],
                        y=alert_high[upper_col],
                        mode='lines',
                        name='L\u00edmite',
                        legendgroup='limits',
                        showlegend=not limit_legend_shown,
                        line=dict(
                            color='rgba(231, 76, 60, 0.4)',  # Lighter red with transparency
                            width=1.5,  # Thinner than signal
                            dash='dash'  # Dashed style for upper limit (different from lower)
                        ),
                        hovertemplate='Límite Superior: %{y:.2f}<extra></extra>'
                    ),
                    row=idx,
                    col=1
                )
                limit_legend_shown = True
            
        
        if is_capstone:
            # Add state swatches after the real sensor traces so they cannot
            # interfere with the first subplot's data rendering.
            state_values = alert_data.get(
                'State', pd.Series(index=alert_data.index, dtype='object')
            ).fillna('').astype(str)
            seen_states = []
            for raw_state in state_values.tolist():
                if raw_state and raw_state not in seen_states:
                    seen_states.append(raw_state)
            for raw_state in reversed(seen_states):
                state_label = STATE_LABELS.get(raw_state, raw_state)
                fig.add_trace(
                    go.Scatter(
                        x=[None],
                        y=[None],
                        mode='markers',
                        name=state_label,
                        legendgroup=raw_state,
                        marker=dict(
                            size=8,
                            color=STATE_COLORS.get(raw_state, '#95a5a6'),
                            line=dict(width=1, color='white')
                        ),
                        hoverinfo='skip',
                        showlegend=True
                    ),
                    row=1,
                    col=1
                )

        # Update layout with proper spacing and horizontal legend at top
        fig.update_layout(
            height=280 + 200 * len(feature_names),  # Increased height per chart for better spacing
            template='plotly_white',
            showlegend=True,  # Show legend for state colors and limits
            legend=dict(
                orientation='h',  # Horizontal orientation
                traceorder='reversed' if is_capstone else 'normal',
                yanchor='bottom',
                y=1.02,  # Same legend position as CDA
                xanchor='center',
                x=0.5,
                entrywidth=90,
                entrywidthmode='pixels',
                font=dict(size=11),
                bgcolor='rgba(255, 255, 255, 0.9)',
                bordercolor='#e0e0e0',
                borderwidth=1
            ),
            margin=dict(l=60, r=40, t=80, b=50),
            hovermode='x unified',
            title=dict(
                text=f'<b>Análisis de Tendencias - {unit_id}</b>',
                x=0.5,
                xanchor='center',
                y=0.99,
                yanchor='top',
                font=dict(size=16, color='#2c3e50', family='Arial, sans-serif')
            )
        )

        if is_capstone:
            # The card heading and subplot titles identify the chart; avoid a
            # second global title covering the first panel or the legend.
            fig.layout.title = None
        
        # Add alert time vertical lines as shapes (full height in each subplot)
        for idx in range(1, len(feature_names) + 1):
            yref = 'y' if idx == 1 else f'y{idx}'
            fig.add_shape(
                type='line',
                x0=alert_time,
                x1=alert_time,
                y0=0,
                y1=1,
                yref=f'{yref} domain',
                line=dict(color='rgba(128, 128, 128, 0.5)', width=2.5, dash='dot'),
                row=idx,
                col=1
            )
        
        # Update subplot backgrounds for better separation
        for idx in range(1, len(feature_names) + 1):
            xref = 'x' if idx == 1 else f'x{idx}'
            yref = 'y' if idx == 1 else f'y{idx}'
            
            # Add subtle background rectangle for each subplot
            fig.add_shape(
                type='rect',
                xref=f'{xref} domain',
                yref=f'{yref} domain',
                x0=0, x1=1,
                y0=0, y1=1,
                fillcolor='rgba(248, 249, 250, 0.5)',
                layer='below',
                line_width=0,
                row=idx,
                col=1
            )
        
        # Update x and y axes for better readability
        fig.update_xaxes(
            showgrid=True,
            gridwidth=1,
            gridcolor='rgba(220, 220, 220, 0.5)',
            showline=True,
            linewidth=1,
            linecolor='#e0e0e0'
        )
        
        fig.update_yaxes(
            showgrid=True,
            gridwidth=1,
            gridcolor='rgba(220, 220, 220, 0.5)',
            showline=True,
            linewidth=1,
            linecolor='#e0e0e0',
            title_font=dict(size=11)
        )
        
        # Style subplot titles (annotations)
        for annotation in fig['layout']['annotations']:
            annotation['font'] = dict(size=13, color='#2c3e50', family='Arial, sans-serif')
            annotation['xanchor'] = 'center'
            annotation['yanchor'] = 'bottom'
        
        logger.info(f"Created sensor trends chart (golden layer) with {len(feature_names)} features")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating sensor trends chart (golden layer): {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def create_gps_route_map_golden(
    alert_data: pd.DataFrame,
    unit_id: str,
    alert_time: datetime,
    mapbox_token: str
) -> go.Figure:
    """
    Create GPS route map using pre-processed golden layer data.
    
    Args:
        alert_data: DataFrame with GPS data from golden layer
        unit_id: Unit identifier
        alert_time: Alert timestamp
        mapbox_token: Mapbox access token
    
    Returns:
        Plotly Figure with GPS map
    """
    if alert_data.empty:
        logger.warning("Cannot create GPS map: empty data")
        return go.Figure().add_annotation(
            text="No GPS data available",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )
    
    try:
        # Filter data to M1 minutes before alert (GPS shows route only up to alert time)
        M1 = 90  # minutes before alert
        time_window_start = alert_time - timedelta(minutes=M1)
        
        alert_data_filtered = alert_data[
            (alert_data['TimeStart'] >= time_window_start) &
            (alert_data['TimeStart'] <= alert_time)
        ].copy()
        alert_data_filtered.sort_values('TimeStart', inplace=True)
        
        # Filter GPS data
        gps_data = alert_data_filtered.dropna(subset=['GPSLat', 'GPSLon']).copy()
        
        if gps_data.empty:
            logger.warning("No GPS data with valid coordinates")
            return go.Figure().add_annotation(
                text="No GPS data with valid coordinates",
                xref="paper", yref="paper",
                x=0.5, y=0.5, showarrow=False
            )
        
        # Normalize time for color gradient
        time_min = gps_data['TimeStart'].min()
        time_max = gps_data['TimeStart'].max()
        
        if time_max > time_min:
            gps_data['TimeNorm'] = (gps_data['TimeStart'] - time_min) / (time_max - time_min)
        else:
            gps_data['TimeNorm'] = 0.5
        
        # Create map
        fig = go.Figure()
        
        # Add route line with subtle gray color for better contrast against satellite background
        fig.add_trace(go.Scattermapbox(
            lat=gps_data['GPSLat'],
            lon=gps_data['GPSLon'],
            mode='lines',
            line=dict(width=2, color='rgba(100, 100, 100, 0.5)'),
            showlegend=False,
            hoverinfo='skip'
        ))
        
        # Find alert point (closest to alert_time)
        alert_idx = (gps_data['TimeStart'] - alert_time).abs().argmin()
        alert_point = gps_data.iloc[alert_idx]
        
        # Add all non-alert points with single blue color (use boolean masking to avoid index issues)
        alert_point_index = gps_data.index[alert_idx]
        non_alert_gps = gps_data[gps_data.index != alert_point_index]
        if not non_alert_gps.empty:
            fig.add_trace(go.Scattermapbox(
                lat=non_alert_gps['GPSLat'],
                lon=non_alert_gps['GPSLon'],
                mode='markers',
                marker=dict(
                    size=10,
                    color="#ea6648",  # Light red color for non-alert points
                ),
                showlegend=False,
                text=non_alert_gps['TimeStart'].dt.strftime('%H:%M:%S'),
                hovertemplate='Hora: %{text}<extra></extra>'
            ))
        
        # Add white border circle first (bottom layer) for alert point
        fig.add_trace(go.Scattermapbox(
            lat=[alert_point['GPSLat']],
            lon=[alert_point['GPSLon']],
            mode='markers',
            marker=dict(
                size=35,
                color='white',
                opacity=0.9,
                symbol='circle',
                allowoverlap=True
            ),
            showlegend=False,
            hoverinfo='skip'
        ))
        
        # Add red circle on top for alert point
        fig.add_trace(go.Scattermapbox(
            lat=[alert_point['GPSLat']],
            lon=[alert_point['GPSLon']],
            mode='markers',
            marker=dict(
                size=25,
                color='red',
                symbol='circle',
                allowoverlap=True
            ),
            showlegend=False,
            text=[f"⚠️ Alerta: {alert_time.strftime('%H:%M:%S')}"],
            hovertemplate='%{text}<extra></extra>'
        ))
        
        fig.update_layout(
            mapbox=dict(
                accesstoken=mapbox_token,
                style="satellite-streets",
                center=dict(
                    lat=gps_data['GPSLat'].mean(),
                    lon=gps_data['GPSLon'].mean()
                ),
                zoom=14
            ),
            title=None,
            height=600,
            margin=dict(l=0, r=0, t=10, b=0),
            showlegend=False
        )
        
        logger.info(f"Created GPS route map (golden layer) with {len(gps_data)} points")
        return fig
    
    except Exception as e:
        logger.error(f"Error creating GPS route map (golden layer): {e}")
        return go.Figure().add_annotation(
            text=f"Error: {str(e)}",
            xref="paper", yref="paper",
            x=0.5, y=0.5, showarrow=False
        )


def _first_numeric_context_value(alert_point: pd.Series, column_names: List[str]) -> Optional[float]:
    """Return the first non-null numeric context value from candidate columns."""
    for column_name in column_names:
        if column_name not in alert_point.index:
            continue

        raw_value = alert_point[column_name]
        if pd.isna(raw_value):
            continue

        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            logger.warning(
                "Ignoring non-numeric context value in %s: %r",
                column_name,
                raw_value,
            )
            continue

        if pd.notna(value):
            logger.info("Found context value in column: %s with value: %s", column_name, value)
            return value

    return None


def create_context_kpis_cards_golden(
    alert_data: pd.DataFrame,
    alert_time: pd.Timestamp,
    trigger: str
) -> dbc.Row:
    """
    Create KPI cards using pre-processed golden layer data.
    Shows 4 KPIs: Elevación, Carga (Payload), Carga de Motor, Velocidad de Motor.
    
    Args:
        alert_data: DataFrame with golden layer data
        alert_time: Alert timestamp
        trigger: Trigger feature name
    
    Returns:
        Bootstrap Row with 4 KPI cards
    """
    if alert_data.empty:
        return dbc.Alert("No hay datos de contexto disponibles", color="info")
    
    try:
        # Sort by time
        alert_data = alert_data.sort_values('TimeStart').reset_index(drop=True)
        
        # Find point closest to alert time
        alert_data['time_diff'] = abs((alert_data['TimeStart'] - alert_time).dt.total_seconds())
        alert_idx = alert_data['time_diff'].idxmin()
        alert_point = alert_data.iloc[alert_idx]
        
        # KPI 1: Elevación
        elevation_status = "➡️ Plano"
        elevation_color = "secondary"
        
        if 'GPSElevation' in alert_data.columns:
            before_data = alert_data[alert_data['TimeStart'] < alert_time]
            after_data = alert_data[alert_data['TimeStart'] >= alert_time]
            
            if not before_data.empty and not after_data.empty:
                elevation_before = before_data['GPSElevation'].tail(5).mean()
                elevation_after = after_data['GPSElevation'].head(5).mean()
                
                if pd.notna(elevation_before) and pd.notna(elevation_after):
                    gradient = (elevation_after - elevation_before) / 5
                    
                    if gradient > 0.05:
                        elevation_status = "⬆️ Subiendo"
                        elevation_color = "info"
                    elif gradient < -0.05:
                        elevation_status = "⬇️ Bajando"
                        elevation_color = "warning"
        
        # KPI 2: Carga (Payload)
        payload_value = alert_point.get('Payload_Value', 'N/A')
        if pd.isna(payload_value):
            payload_value = 'N/A'
        else:
            # Round to 0 decimals if numeric
            try:
                payload_value = f"{float(payload_value):.0f} t"
            except:
                pass
        payload_status = f"📦 {payload_value}"
        payload_color = "primary"
        
        # KPI 3: Carga de Motor (EngLoad)
        engine_load = "N/A"
        load_color = "secondary"
        
        # Log available columns for debugging
        logger.info(f"Available columns for KPI: {list(alert_point.index)[:10]}...")  # First 10 columns
        
        # Capstone publishes canonical snake_case signals and may also carry
        # the legacy aliases. Prefer the canonical contract, while retaining
        # the aliases used by the CDA golden layer.
        engload_cols = [
            'engine_load_pct_Value',
            'EngLoad_Value',
            'engine_load_pct',
            'EngLoad',
            'Engine Load',
            'EngineLoad',
        ]
        engload_value = _first_numeric_context_value(alert_point, engload_cols)
        
        if engload_value is not None:
            engine_load = f"⚙️ {engload_value:.0f}%"
            
            # Color based on load level
            if engload_value < 50:
                load_color = "success"
            elif engload_value < 80:
                load_color = "warning"
            else:
                load_color = "danger"
        else:
            logger.warning("EngLoad_Value not found in data or is NaN")
        
        # KPI 4: Velocidad de Motor (EngSpd)
        engine_rpm = "N/A"
        rpm_color = "success"
        
        rpm_value = _first_numeric_context_value(
            alert_point,
            [
                'engine_speed_rpm_Value',
                'EngSpd_Value',
                'engine_speed_rpm',
                'EngSpd',
            ],
        )
        if rpm_value is not None:
            engine_rpm = f"🏎️ {rpm_value:.0f} RPM"
        
        # Create 4 KPI cards in vertical layout (1 column x 4 rows)
        return html.Div([
            # Row 1: Elevación
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H6("Elevación", className="text-muted mb-2 text-uppercase", 
                                   style={'fontSize': '0.85rem'}),
                            html.H5(elevation_status, className=f"text-{elevation_color} mb-0")
                        ])
                    ], color=elevation_color, outline=True, className="text-center")
                ], md=12)
            ], className="mb-3"),
            
            # Row 2: Carga
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H6("Carga", className="text-muted mb-2 text-uppercase",
                                   style={'fontSize': '0.85rem'}),
                            html.H5(payload_status, className=f"text-{payload_color} mb-0")
                        ])
                    ], color=payload_color, outline=True, className="text-center")
                ], md=12)
            ], className="mb-3"),
            
            # Row 3: Carga de Motor
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H6("Carga de Motor", className="text-muted mb-2 text-uppercase",
                                   style={'fontSize': '0.85rem'}),
                            html.H5(engine_load, className=f"text-{load_color} mb-0")
                        ])
                    ], color=load_color, outline=True, className="text-center")
                ], md=12)
            ], className="mb-3"),
            
            # Row 4: Velocidad Motor
            dbc.Row([
                dbc.Col([
                    dbc.Card([
                        dbc.CardBody([
                            html.H6("Velocidad Motor", className="text-muted mb-2 text-uppercase",
                                   style={'fontSize': '0.85rem'}),
                            html.H5(engine_rpm, className=f"text-{rpm_color} mb-0")
                        ])
                    ], color=rpm_color, outline=True, className="text-center")
                ], md=12)
            ])
        ])
    
    except Exception as e:
        logger.error(f"Error creating context KPIs (golden): {e}")
        return dbc.Alert(f"Error al crear KPIs de contexto: {str(e)}", color="danger")