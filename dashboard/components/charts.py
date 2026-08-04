"""
Reusable chart components for Multi-Technical-Alerts dashboard.
"""

import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from typing import List, Dict, Optional

# Color scheme (GR-05: Single status design language).
# Defined once in src/charts/theme.py so the dashboard tabs and Campbell AI agree
# on what each status looks like; re-exported here for existing importers.
from src.charts.theme import STATUS_COLORS  # noqa: F401


def create_status_pie_chart(df: pd.DataFrame) -> go.Figure:
    """
    DEPRECATED: Use create_machine_status_donut instead.
    
    Kept for backward compatibility.
    """
    return create_machine_status_donut(df)


def create_machine_status_donut(df: pd.DataFrame, title: str = "Machine Status Distribution") -> go.Figure:
    """
    Create donut chart showing machine status distribution (GR-02, OIL-M-01).
    
    - Donut format (not pie)
    - Total count in center
    - Clickable segments for filtering
    - Legend shows count and percentage
    
    Args:
        df: DataFrame with machine statuses (Golden layer - Machine Status schema)
        title: Chart title
    
    Returns:
        Plotly figure with clickData support
    """
    if df.empty:
        return go.Figure()
    
    # Use 'overall_status' column
    status_counts = df['overall_status'].value_counts()
    total_machines = status_counts.sum()
    
    # Calculate percentages
    percentages = (status_counts / total_machines * 100).round(1)
    
    # Create labels with count and percentage for legend
    labels_with_counts = [
        f"{status}: {count} ({percentages[status]}%)" 
        for status, count in status_counts.items()
    ]
    
    fig = go.Figure(data=[go.Pie(
        labels=status_counts.index,
        values=status_counts.values,
        marker=dict(colors=[STATUS_COLORS.get(s, '#999999') for s in status_counts.index]),
        hole=0.5,  # Donut hole
        textinfo='label+percent',
        textfont=dict(size=13),
        hovertemplate='<b>%{label}</b><br>Count: %{value}<br>Percentage: %{percent}<extra></extra>',
        text=labels_with_counts,  # For legend
        textposition='inside'
    )])
    
    # Add total count annotation in center
    fig.add_annotation(
        text=f"<b>{total_machines}</b><br>Total",
        x=0.5, y=0.5,
        font=dict(size=20, color='#333'),
        showarrow=False,
        xref="paper",
        yref="paper"
    )
    
    fig.update_layout(
        title=dict(
            text=title,
            font=dict(size=18)
        ),
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.05
        ),
        height=400,
        margin=dict(l=20, r=150, t=60, b=20)
    )
    
    return fig


def create_component_stacked_bar_chart(
    df: pd.DataFrame, 
    use_normalized: bool = False,
    title: str = "Component Status Distribution"
) -> go.Figure:
    """
    Create stacked horizontal bar chart for component status distribution (OIL-M-06).
    
    Enhanced June 2026: Hover shows which units belong to each component-status combination.
    
    Replaces donut chart with scalable categorical comparison.
    - Each bar = component
    - Stacks = Normal, Alerta, Anormal
    - Sorted by highest abnormal burden first
    - Toggle between original and normalized component names
    - Hover shows unit IDs for traceability
    
    Args:
        df: DataFrame with classified reports (component-level data)
        use_normalized: Use componentNameNormalized (grouped) vs componentName (original)
        title: Chart title
    
    Returns:
        Plotly figure with interactive hover showing unit details
    """
    if df.empty:
        return go.Figure()
    
    # Choose component column
    component_col = 'componentNameNormalized' if use_normalized else 'componentName'
    
    # Get latest sample for each unit-component
    latest_components = df.loc[df.groupby(['unitId', component_col])['sampleDate'].idxmax()]
    
    # Count status by component AND collect unit IDs
    status_by_component = {}
    unit_lists = {}  # Store which units are in each component-status combination
    
    for component in latest_components[component_col].unique():
        component_df = latest_components[latest_components[component_col] == component]
        status_counts = component_df['report_status'].value_counts()
        status_by_component[component] = status_counts.to_dict()
        
        # Collect unit IDs for each status
        unit_lists[component] = {}
        for status in ['Normal', 'Alerta', 'Anormal']:
            units = component_df[component_df['report_status'] == status]['unitId'].tolist()
            unit_lists[component][status] = units
    
    # Convert to DataFrame for easier manipulation
    status_df = pd.DataFrame(status_by_component).T.fillna(0)
    
    # Ensure all status columns exist
    for status in ['Normal', 'Alerta', 'Anormal']:
        if status not in status_df.columns:
            status_df[status] = 0
    
    # Calculate abnormal burden for sorting (Anormal > Alerta > Normal)
    status_df['burden'] = (
        status_df.get('Anormal', 0) * 100 + 
        status_df.get('Alerta', 0) * 10
    )
    
    # Sort by burden descending
    status_df = status_df.sort_values('burden', ascending=True)  # True for horizontal bars (bottom to top)
    status_df = status_df.drop('burden', axis=1)
    
    # Title-case component names for display
    component_names = [str(c).title() for c in status_df.index]
    
    # Create stacked horizontal bar chart
    fig = go.Figure()
    
    for status in ['Normal', 'Alerta', 'Anormal']:
        if status in status_df.columns:
            # Build custom hover text with unit lists
            hover_texts = []
            for component in status_df.index:
                units = unit_lists.get(component, {}).get(status, [])
                count = len(units)
                if count > 0:
                    # Show first 10 units, indicate if there are more
                    units_display = ', '.join(units[:10])
                    if count > 10:
                        units_display += f'... (+{count-10} more)'
                    hover_text = f"<b>{status}</b><br>Count: {count}<br>Units: {units_display}"
                else:
                    hover_text = f"<b>{status}</b><br>Count: 0"
                hover_texts.append(hover_text)
            
            fig.add_trace(go.Bar(
                name=status,
                y=component_names,
                x=status_df[status],
                orientation='h',
                marker=dict(color=STATUS_COLORS[status]),
                text=status_df[status].astype(int),
                textposition='inside',
                hovertemplate='%{hovertext}<extra></extra>',
                hovertext=hover_texts,
                customdata=[[unit_lists.get(comp, {}).get(status, [])] for comp in status_df.index]
            ))
    
    fig.update_layout(
        title=dict(
            text=title,
            font=dict(size=16)
        ),
        xaxis=dict(
            title="Number of Components",
            tickangle=-90
        ),
        yaxis_title="Component",
        barmode='stack',
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        ),
        height=max(400, len(status_df) * 25),  # Scale height with number of components
        margin=dict(l=150, r=20, t=80, b=60),
        hoverlabel=dict(
            bgcolor="white",
            font_size=12,
            font_family="Arial"
        )
    )
    
    return fig


def create_radar_chart(
    sample: pd.Series,
    limits: Dict,
    group_element: str,
    essays_in_group: List[str]
) -> go.Figure:
    """
    Create radar chart for essays in a GroupElement.
    
    Args:
        sample: Sample data row
        limits: Stewart Limits dictionary
        group_element: GroupElement name
        essays_in_group: List of essay names in this group
    
    Returns:
        Plotly figure
    """
    client = sample.get('client', '')
    machine = sample.get('machineName', '')
    component = sample.get('componentName', '')
    
    # Get limits for this machine/component
    sel_limits = limits.get(client, {}).get(machine, {}).get(component, {})
    
    # Prepare data
    categories = []
    values = []
    marginal = []
    condenatorio = []
    critico = []
    
    for essay in essays_in_group:
        if essay in sample.index and not pd.isna(sample[essay]):
            categories.append(essay)
            values.append(sample[essay])
            
            # Get limits
            essay_limits = sel_limits.get(essay, {})
            marginal.append(essay_limits.get('threshold_normal', 0))
            condenatorio.append(essay_limits.get('threshold_alert', 0))
            critico.append(essay_limits.get('threshold_critic', 0))
    
    if not categories:
        return go.Figure()
    
    # Create radar chart
    fig = go.Figure()
    
    # Add threshold lines
    fig.add_trace(go.Scatterpolar(
        r=marginal + [marginal[0]],
        theta=categories + [categories[0]],
        name='Marginal',
        line=dict(color='#28a745', width=2, dash='dash')
    ))
    
    fig.add_trace(go.Scatterpolar(
        r=condenatorio + [condenatorio[0]],
        theta=categories + [categories[0]],
        name='Condenatorio',
        line=dict(color='#ffc107', width=2, dash='dash')
    ))
    
    fig.add_trace(go.Scatterpolar(
        r=critico + [critico[0]],
        theta=categories + [categories[0]],
        name='Crítico',
        line=dict(color='#dc3545', width=2, dash='dash')
    ))
    
    # Add actual values
    fig.add_trace(go.Scatterpolar(
        r=values + [values[0]],
        theta=categories + [categories[0]],
        name='Actual',
        fill='toself',
        fillcolor='rgba(23, 162, 184, 0.3)',
        line=dict(color='#17a2b8', width=3)
    ))
    
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, max(max(values), max(critico)) * 1.2])
        ),
        title=f"Radar Chart - {group_element}",
        title_font_size=16,
        showlegend=True,
        height=500
    )
    
    return fig


def create_time_series_chart(
    df: pd.DataFrame,
    unit_id: str,
    component: str,
    essays: List[str],
    limits: Dict = None
) -> go.Figure:
    """
    Create time series chart for essays in a component.
    
    Args:
        df: DataFrame with samples
        unit_id: Machine unit ID
        component: Component name
        essays: List of essay names to plot
        limits: Stewart Limits dictionary (optional)
    
    Returns:
        Plotly figure
    """
    # Filter data
    filtered_df = df[(df['unitId'] == unit_id) & (df['componentName'] == component)].copy()
    
    if filtered_df.empty:
        return go.Figure()
    
    filtered_df = filtered_df.sort_values('sampleDate')
    
    fig = go.Figure()
    
    # Add line for each essay
    for essay in essays:
        if essay in filtered_df.columns:
            fig.add_trace(go.Scatter(
                x=filtered_df['sampleDate'],
                y=filtered_df[essay],
                mode='lines+markers',
                name=essay,
                line=dict(width=2),
                marker=dict(size=6)
            ))
            
            # Add threshold lines if limits provided
            if limits:
                client = filtered_df['client'].iloc[0]
                machine = filtered_df['machineName'].iloc[0]
                
                essay_limits = limits.get(client, {}).get(machine, {}).get(component, {}).get(essay, {})
                
                if essay_limits:
                    # Critic threshold
                    critic = essay_limits.get('threshold_critic')
                    if critic and not pd.isna(critic):
                        fig.add_hline(
                            y=critic,
                            line_dash="dash",
                            line_color="#dc3545",
                            annotation_text=f"{essay} Crítico",
                            annotation_position="right"
                        )
    
    fig.update_layout(
        title=f"Time Series - {unit_id} / {component}",
        title_font_size=16,
        xaxis_title="Sample Date",
        yaxis_title="Value",
        hovermode='x unified',
        height=500,
        showlegend=True
    )
    
    return fig


def create_bar_chart(data: Dict[str, int], title: str, color: str = '#17a2b8') -> go.Figure:
    """
    Create simple bar chart.
    
    Args:
        data: Dictionary of {label: value}
        title: Chart title
        color: Bar color
    
    Returns:
        Plotly figure
    """
    fig = go.Figure(data=[go.Bar(
        x=list(data.keys()),
        y=list(data.values()),
        marker_color=color
    )])
    
    fig.update_layout(
        title=title,
        title_font_size=16,
        xaxis_title="",
        yaxis_title="Count",
        height=350
    )
    
    return fig
