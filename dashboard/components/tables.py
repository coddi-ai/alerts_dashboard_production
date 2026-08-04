"""
Reusable table components for Multi-Technical-Alerts dashboard.
"""

from dash import dash_table, html
import dash_bootstrap_components as dbc
import pandas as pd
import numpy as np
import json
from typing import List, Dict, Optional


def create_limits_table(df: pd.DataFrame) -> dash_table.DataTable:
    """
    Create Stewart Limits table with color coding.
    
    Args:
        df: DataFrame with limits (machine, component, essay, thresholds)
    
    Returns:
        Dash DataTable
    """
    if df.empty:
        return html.Div("No limits data available", className="text-muted p-3")
    
    # Apply title() to machine and component names
    df = df.copy()
    if 'machine' in df.columns:
        df['machine'] = df['machine'].str.title()
    if 'component' in df.columns:
        df['component'] = df['component'].str.title()
    
    return dash_table.DataTable(
        id='limits-table',
        columns=[
            {'name': 'Machine', 'id': 'machine'},
            {'name': 'Component', 'id': 'component'},
            {'name': 'Essay', 'id': 'essay'},
            {'name': 'Marginal (90%)', 'id': 'threshold_normal', 'type': 'numeric', 'format': {'specifier': '.2f'}},
            {'name': 'Condenatorio (95%)', 'id': 'threshold_alert', 'type': 'numeric', 'format': {'specifier': '.2f'}},
            {'name': 'Crítico (98%)', 'id': 'threshold_critic', 'type': 'numeric', 'format': {'specifier': '.2f'}}
        ],
        data=df.to_dict('records'),
        style_table={'overflowX': 'auto'},
        style_cell={
            'textAlign': 'left',
            'padding': '10px',
            'fontSize': '14px'
        },
        style_header={
            'backgroundColor': '#17a2b8',
            'color': 'white',
            'fontWeight': 'bold',
            'textAlign': 'center'
        },
        style_data_conditional=[
            {
                'if': {'column_id': 'threshold_normal'},
                'backgroundColor': '#d4edda'
            },
            {
                'if': {'column_id': 'threshold_alert'},
                'backgroundColor': '#fff3cd'
            },
            {
                'if': {'column_id': 'threshold_critic'},
                'backgroundColor': '#f8d7da'
            }
        ],
        filter_action='native',
        sort_action='native',
        page_action='native',
        page_size=20
    )


def create_priority_table(df: pd.DataFrame, status_filter: Optional[str] = None) -> dash_table.DataTable:
    """
    Create priority table for machines requiring attention.
    
    Simplified to show only 3 columns:
    - Unit: Equipment identifier
    - Status: Overall health status
    - AI Recommendation: AI-generated maintenance advice
    
    Args:
        df: DataFrame with machine statuses
        status_filter: Optional filter by status (from donut click)
    
    Returns:
        Dash DataTable
    """
    if df.empty:
        return html.Div("No machine data available", className="text-muted p-3")
    
    # Apply status filter if provided (OIL-M-01: clickable donut)
    if status_filter and status_filter != 'All':
        df = df[df['overall_status'] == status_filter].copy()
    
    # Sort by priority score descending (highest urgency first)
    df = df.sort_values('priority_score', ascending=False)
    
    # Select only the 3 required columns
    display_df = df[['unit_id', 'overall_status']].copy()
    
    # Add AI recommendation if available
    if 'machine_ai_recommendation' in df.columns:
        display_df['ai_recommendation'] = df['machine_ai_recommendation'].apply(
            lambda x: str(x) if pd.notna(x) else 'No recommendation available'
        )
    else:
        display_df['ai_recommendation'] = 'No recommendation available'
    
    # Keep unit_id in original format (don't convert case) for proper matching
    # The data uses format like 'T_10', 'T_11', etc.
    
    if display_df.empty:
        return html.Div("Ninguna máquina coincide con el filtro seleccionado", className="text-info p-3")
    
    return dash_table.DataTable(
        id='priority-table',
        columns=[
            {'name': 'Unidad', 'id': 'unit_id'},
            {'name': 'Estado', 'id': 'overall_status'},
            {'name': 'Recomendación IA', 'id': 'ai_recommendation'}
        ],
        data=display_df.to_dict('records'),
        style_table={'overflowX': 'auto'},
        style_cell={
            'textAlign': 'left',
            'padding': '12px',
            'fontSize': '13px',
            'whiteSpace': 'normal',
            'height': 'auto'
        },
        style_header={
            'backgroundColor': '#343a40',
            'color': 'white',
            'fontWeight': 'bold',
            'textAlign': 'center',
            'fontSize': '14px'
        },
        style_data_conditional=[
            # Status column styling (GR-05: Single status design language)
            {
                'if': {
                    'filter_query': '{overall_status} = "Anormal"',
                    'column_id': 'overall_status'
                },
                'backgroundColor': '#dc3545',
                'color': 'white',
                'fontWeight': 'bold'
            },
            {
                'if': {
                    'filter_query': '{overall_status} = "Alerta"',
                    'column_id': 'overall_status'
                },
                'backgroundColor': '#ffc107',
                'color': 'black',
                'fontWeight': 'bold'
            },
            {
                'if': {
                    'filter_query': '{overall_status} = "Normal"',
                    'column_id': 'overall_status'
                },
                'backgroundColor': '#28a745',
                'color': 'white',
                'fontWeight': 'bold'
            }
        ],
        style_cell_conditional=[
            {'if': {'column_id': 'unit_id'}, 'width': '15%', 'fontWeight': '500'},
            {'if': {'column_id': 'overall_status'}, 'width': '15%'},
            {'if': {'column_id': 'ai_recommendation'}, 'width': '70%', 'minWidth': '300px'}
        ],
        sort_action='native',
        page_size=15,
        row_selectable='single',  # Enable row selection for master-detail (OIL-M-03)
        selected_rows=[]
    )


def create_machine_detail_table(df: pd.DataFrame) -> dash_table.DataTable:
    """
    Create detailed machine component table (OIL-M-04).
    
    Displays:
    - Component name
    - Status
    - Sample date
    - Essays broken (extracted essay names from breached_essays)
    - AI recommendation
    
    Sorted worst-first (Anormal > Alerta > Normal, then by severity).
    
    Args:
        df: DataFrame with component statuses for a machine
    
    Returns:
        Dash DataTable
    """
    if df.empty:
        return html.Div("Seleccione una máquina para ver los detalles", className="text-muted p-3")
    
    df = df.copy()
    
    # Sort worst-first: Anormal first, then by severity descending
    status_order = {'Anormal': 0, 'Alerta': 1, 'Normal': 2}
    df['_status_rank'] = df['report_status'].map(status_order).fillna(99)
    df = df.sort_values(['_status_rank', 'severity_score'], ascending=[True, False])
    df = df.drop('_status_rank', axis=1)
    
    # Format component name
    if 'componentName' in df.columns:
        df['componentName'] = df['componentName'].str.title()
    
    # Format component hours (horómetro) if available
    if 'componentHours_cleaned' in df.columns:
        df['horometro_display'] = df['componentHours_cleaned'].apply(
            lambda x: f"{x:,.0f} hrs" if pd.notna(x) else 'N/A'
        )
    else:
        df['horometro_display'] = 'N/A'
    
    # Parse breached_essays to extract essay names from list of dictionaries
    if 'breached_essays' in df.columns:
        def extract_essay_names(x):
            try:
                # Handle None first
                if x is None:
                    return 'N/A'
                
                # Handle numpy array or list of dictionaries
                if isinstance(x, (list, np.ndarray)):
                    if len(x) == 0:
                        return 'N/A'
                    essay_names = [item.get('essay', '') for item in x if isinstance(item, dict)]
                    return ', '.join(essay_names) if essay_names else 'N/A'
                
                # Handle JSON string (fallback)
                if isinstance(x, str):
                    if x.startswith('['):
                        parsed = json.loads(x)
                        essay_names = [item.get('essay', '') for item in parsed if isinstance(item, dict)]
                        return ', '.join(essay_names) if essay_names else 'N/A'
                    return x
                
                # Fallback for any other type
                return 'N/A'
            except Exception as e:
                return 'N/A'
        
        df['essays_broken_names'] = df['breached_essays'].apply(extract_essay_names)
    else:
        df['essays_broken_names'] = 'N/A'
    
    # Format AI recommendations (full text, no truncation)
    if 'ai_recommendation' in df.columns:
        def format_ai_recommendation(x):
            try:
                if pd.isna(x) or x is None:
                    return 'N/A'
                return str(x)
            except:
                return 'N/A'
        
        df['ai_text'] = df['ai_recommendation'].apply(format_ai_recommendation)
    else:
        df['ai_text'] = 'N/A'

    # Format anomaly type (July 2026)
    if 'anomalyType' in df.columns:
        df['anomaly_display'] = df['anomalyType'].apply(
            lambda x: str(x) if pd.notna(x) and x != 'Normal' else '—'
        )
    else:
        df['anomaly_display'] = '—'
    
    # Define columns: Component, Status, Anomaly, Horómetro, Sample Date, Essays Broken, AI Recommendation
    has_horometro = 'componentHours_cleaned' in df.columns
    
    columns = [
        {'name': 'Componente', 'id': 'componentName'},
        {'name': 'Estado', 'id': 'report_status'},
        {'name': 'Anomalía', 'id': 'anomaly_display'},
    ]
    
    if has_horometro:
        columns.append({'name': 'Horómetro', 'id': 'horometro_display'})
    
    columns.extend([
        {'name': 'Fecha Muestra', 'id': 'sampleDate'},
        {'name': 'Ensayos Anormales', 'id': 'essays_broken_names'},
        {'name': 'Recomendación IA', 'id': 'ai_text'}
    ])
    
    return dash_table.DataTable(
        id='machine-detail-table',
        columns=columns,
        data=df.to_dict('records'),
        style_table={'overflowX': 'auto'},
        style_cell={
            'textAlign': 'left',
            'padding': '10px',
            'fontSize': '13px',
            'whiteSpace': 'normal',
            'height': 'auto'
        },
        style_header={
            'backgroundColor': '#6c757d',
            'color': 'white',
            'fontWeight': 'bold',
            'textAlign': 'center'
        },
        style_data_conditional=[
            # Status column styling (GR-05: Single status design language)
            {
                'if': {
                    'filter_query': '{report_status} = "Anormal"',
                    'column_id': 'report_status'
                },
                'backgroundColor': '#f8d7da',
                'color': '#721c24',
                'fontWeight': 'bold'
            },
            {
                'if': {
                    'filter_query': '{report_status} = "Alerta"',
                    'column_id': 'report_status'
                },
                'backgroundColor': '#fff3cd',
                'color': '#856404',
                'fontWeight': 'bold'
            },
            {
                'if': {
                    'filter_query': '{report_status} = "Normal"',
                    'column_id': 'report_status'
                },
                'backgroundColor': '#d4edda',
                'color': '#155724'
            },
            # Highlight high essays_broken
            {
                'if': {
                    'filter_query': '{essays_broken} > 3',
                    'column_id': 'essays_broken'
                },
                'backgroundColor': '#f8d7da',
                'fontWeight': 'bold'
            }
        ],
        style_cell_conditional=[
            {'if': {'column_id': 'ai_text'}, 'width': '25%', 'minWidth': '180px'},
            {'if': {'column_id': 'essays_broken_names'}, 'width': '18%', 'minWidth': '130px'},
            {'if': {'column_id': 'componentName'}, 'width': '14%'},
            {'if': {'column_id': 'anomaly_display'}, 'width': '15%', 'minWidth': '120px'}
        ],
        sort_action='native',
        page_size=20
    )


def create_ai_recommendations_card(recommendations: List[Dict]) -> dbc.Card:
    """
    Create card displaying AI recommendations.
    
    Args:
        recommendations: List of recommendation dictionaries
    
    Returns:
        Bootstrap card with recommendations
    """
    if not recommendations:
        return dbc.Card(
            dbc.CardBody("No AI recommendations available"),
            className="mb-3"
        )
    
    cards = []
    for rec in recommendations[:5]:  # Show top 5
        cards.append(
            dbc.Card([
                dbc.CardHeader(f"Sample: {rec.get('sampleNumber', 'N/A')}", className="fw-bold"),
                dbc.CardBody([
                    html.P(f"Status: {rec.get('status', 'N/A')}", className="mb-2"),
                    html.P(rec.get('recommendation', 'N/A'), className="text-muted")
                ])
            ], className="mb-2")
        )
    
    return dbc.Card(
        dbc.CardBody(cards),
        className="mb-3"
    )
