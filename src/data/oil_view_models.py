"""
View-model transformation layer for Oil data.

This module transforms Golden layer data schemas into UI-friendly objects,
following GR-04: Introduce a shared view-model layer between loaders and UI components.

This ensures UI components are decoupled from raw parquet schemas and can adapt
to contract changes without breaking the UI.
"""

import pandas as pd
import json
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class MachineStatusViewModel:
    """
    UI-friendly representation of machine status.
    
    Maps from golden layer machine_status.parquet schema to UI requirements.
    """
    unit_id: str
    client: str
    overall_status: str
    machine_score: float
    priority_score: float
    components_normal: int
    components_alerta: int
    components_anormal: int
    total_components: int
    latest_sample_date: Optional[str]
    machine_ai_recommendation: Optional[str]
    component_details: List[Dict]
    
    @property
    def status_badge_color(self) -> str:
        """Return Bootstrap color for status badge."""
        return {
            'Normal': 'success',
            'Alerta': 'warning',
            'Anormal': 'danger'
        }.get(self.overall_status, 'secondary')
    
    @property
    def ai_recommendation_summary(self) -> str:
        """Return truncated AI recommendation for table display."""
        if not self.machine_ai_recommendation:
            return "No recommendation available"
        # Truncate to first 100 chars
        rec = self.machine_ai_recommendation
        return rec[:100] + "..." if len(rec) > 100 else rec
    
    @property
    def component_burden_text(self) -> str:
        """Return formatted component burden summary."""
        return f"N:{self.components_normal} | A:{self.components_alerta} | An:{self.components_anormal}"


@dataclass
class ComponentStatusViewModel:
    """
    UI-friendly representation of component status from classified reports.
    
    Maps from golden layer classified.parquet schema to UI requirements.
    """
    unit_id: str
    component_name: str
    component_name_display: str  # Title-cased for display
    report_status: str
    severity_score: float
    essays_broken: int
    breached_essays: List[str]
    ai_recommendation: Optional[str]
    sample_date: str
    
    @property
    def status_badge_color(self) -> str:
        """Return Bootstrap color for status badge."""
        return {
            'Normal': 'success',
            'Alerta': 'warning',
            'Anormal': 'danger'
        }.get(self.report_status, 'secondary')
    
    @property
    def breached_essays_text(self) -> str:
        """Return comma-separated list of breached essays."""
        if not self.breached_essays:
            return "None"
        return ", ".join(self.breached_essays)
    
    @property
    def ai_recommendation_summary(self) -> str:
        """Return truncated AI recommendation for table display."""
        if not self.ai_recommendation:
            return "No recommendation"
        rec = self.ai_recommendation
        return rec[:80] + "..." if len(rec) > 80 else rec


def transform_machine_status_to_viewmodel(df: pd.DataFrame) -> List[MachineStatusViewModel]:
    """
    Transform golden layer machine_status.parquet to view models.
    
    Args:
        df: Raw DataFrame from machine_status.parquet
    
    Returns:
        List of MachineStatusViewModel objects
    """
    view_models = []
    
    for _, row in df.iterrows():
        # Parse component_details JSON
        component_details = []
        if pd.notna(row.get('component_details')):
            try:
                component_details = json.loads(row['component_details'])
            except (json.JSONDecodeError, TypeError):
                component_details = []
        
        vm = MachineStatusViewModel(
            unit_id=str(row['unit_id']).upper(),
            client=str(row['client']).upper(),
            overall_status=row['overall_status'],
            machine_score=float(row['machine_score']),
            priority_score=float(row['priority_score']),
            components_normal=int(row['components_normal']),
            components_alerta=int(row['components_alerta']),
            components_anormal=int(row['components_anormal']),
            total_components=int(row['total_components']),
            latest_sample_date=str(row['latest_sample_date']) if pd.notna(row.get('latest_sample_date')) else None,
            machine_ai_recommendation=row.get('machine_ai_recommendation'),
            component_details=component_details
        )
        view_models.append(vm)
    
    return view_models


def transform_classified_reports_to_viewmodel(df: pd.DataFrame) -> List[ComponentStatusViewModel]:
    """
    Transform golden layer classified.parquet to component view models.
    
    Args:
        df: Raw DataFrame from classified.parquet
    
    Returns:
        List of ComponentStatusViewModel objects
    """
    view_models = []
    
    for _, row in df.iterrows():
        # Parse breached_essays JSON
        breached_essays = []
        if pd.notna(row.get('breached_essays')):
            try:
                breached_essays = json.loads(row['breached_essays'])
            except (json.JSONDecodeError, TypeError):
                breached_essays = []
        
        vm = ComponentStatusViewModel(
            unit_id=str(row['unitId']).upper(),
            component_name=row['componentName'],
            component_name_display=str(row['componentName']).title(),
            report_status=row['report_status'],
            severity_score=float(row['severity_score']),
            essays_broken=int(row['essays_broken']),
            breached_essays=breached_essays,
            ai_recommendation=row.get('ai_recommendation'),
            sample_date=str(row['sampleDate'])
        )
        view_models.append(vm)
    
    return view_models


def prepare_machine_status_for_table(view_models: List[MachineStatusViewModel], 
                                      status_filter: Optional[str] = None) -> pd.DataFrame:
    """
    Prepare machine status view models for DataTable display.
    
    Args:
        view_models: List of MachineStatusViewModel objects
        status_filter: Optional filter by overall_status ('Normal', 'Alerta', 'Anormal')
    
    Returns:
        DataFrame ready for dash_table.DataTable
    """
    # Apply filter if provided
    if status_filter:
        view_models = [vm for vm in view_models if vm.overall_status == status_filter]
    
    # Convert to DataFrame
    data = [{
        'unit_id': vm.unit_id,
        'overall_status': vm.overall_status,
        'machine_score': round(vm.machine_score, 2),
        'components_normal': vm.components_normal,
        'components_alerta': vm.components_alerta,
        'components_anormal': vm.components_anormal,
        'priority_score': round(vm.priority_score, 2),
        'ai_recommendation_summary': vm.ai_recommendation_summary,
        'latest_sample_date': vm.latest_sample_date or 'N/A'
    } for vm in view_models]
    
    return pd.DataFrame(data)


def prepare_component_status_for_table(view_models: List[ComponentStatusViewModel]) -> pd.DataFrame:
    """
    Prepare component status view models for DataTable display.
    
    Args:
        view_models: List of ComponentStatusViewModel objects
    
    Returns:
        DataFrame ready for dash_table.DataTable
    """
    data = [{
        'component_name': vm.component_name_display,
        'report_status': vm.report_status,
        'severity_score': round(vm.severity_score, 2),
        'essays_broken': vm.essays_broken,
        'breached_essays': vm.breached_essays_text,
        'ai_recommendation': vm.ai_recommendation_summary,
        'sample_date': vm.sample_date
    } for vm in view_models]
    
    return pd.DataFrame(data)


def get_status_distribution(view_models: List[MachineStatusViewModel]) -> Dict[str, int]:
    """
    Calculate status distribution for donut chart.
    
    Args:
        view_models: List of MachineStatusViewModel objects
    
    Returns:
        Dictionary mapping status to count
    """
    distribution = {'Normal': 0, 'Alerta': 0, 'Anormal': 0}
    
    for vm in view_models:
        if vm.overall_status in distribution:
            distribution[vm.overall_status] += 1
    
    return distribution
