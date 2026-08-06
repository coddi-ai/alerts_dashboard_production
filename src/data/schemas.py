"""
Pydantic data models for Multi-Technical-Alerts.

Defines schemas for:
- OilSample: Silver layer (harmonized data)
- ClassifiedReport: Golden layer (classified with AI recommendations)
- MachineStatus: Machine aggregation from golden layer
- StewartLimits: Statistical thresholds for essay classification
"""

from datetime import datetime, date
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator
import pandas as pd


class OilSample(BaseModel):
    """
    Schema for harmonized oil sample (Silver layer).
    
    All data from different labs (CDA, EMIN) is transformed to this schema.
    Based on DATA_CONTRACTS.md Silver Layer specification.
    """
    # Identifiers
    client: str = Field(..., description="Client identifier (CDA, EMIN)")
    sampleNumber: str = Field(..., description="Unique sample ID")
    sampleDate: date = Field(..., description="Sample collection date")
    unitId: str = Field(..., description="Equipment unit ID")
    machineName: str = Field(..., description="Normalized machine type (camion, pala, etc.)")
    machineModel: Optional[str] = Field(None, description="Machine model")
    machineBrand: Optional[str] = Field(None, description="Machine brand")
    machineHours: Optional[float] = Field(None, description="Operating hours")
    machineSerialNumber: Optional[str] = Field(None, description="Machine serial number")
    
    # Component information
    componentName: str = Field(..., description="Component analyzed (motor diesel, transmision, etc.)")
    componentNameNormalized: str = Field(..., description="Component normalized for Stewart Limits (mando final, motor diesel, etc.)")
    componentHours: Optional[float] = Field(None, description="Component hours")
    componentSerialNumber: Optional[str] = Field(None, description="Component serial number")
    
    # Oil information
    oilMeter: Optional[float] = Field(None, description="Oil meter reading")
    oilBrand: Optional[str] = Field(None, description="Oil brand")
    oilType: Optional[str] = Field(None, description="Oil type")
    oilWeight: Optional[str] = Field(None, description="Oil weight")
    
    # Previous sample tracking
    previousSampleNumber: Optional[str] = Field(None, description="Previous sample ID")
    previousSampleDate: Optional[date] = Field(None, description="Previous sample date")
    daysSincePrevious: Optional[int] = Field(None, description="Days between samples")
    
    # Essay classification
    group_element: Optional[str] = Field(None, description="Essay group (Desgaste, Contaminacion, etc.)")
    
    # Essay values (21 total essay columns as dynamic fields)
    # These would be individual fields: Hierro, Cobre, Silicio, etc.
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "client": "CDA",
                "sampleNumber": "CDA-2024-001",
                "sampleDate": "2024-01-15",
                "unitId": "CAT-001",
                "machineName": "camion",
                "machineModel": "CAT 797F",
                "machineBrand": "Caterpillar",
                "machineHours": 15420.5,
                "componentName": "motor diesel",
                "componentHours": 8230.0,
                "previousSampleNumber": "CDA-2023-998",
                "previousSampleDate": "2023-12-20",
                "daysSincePrevious": 26,
                "group_element": "Desgaste"
            }
        }
    }


class ClassifiedReport(BaseModel):
    """
    Schema for classified oil report (Golden layer).
    
    Includes all Silver layer columns plus classification results and AI recommendations.
    Based on DATA_CONTRACTS.md Golden Layer classified.parquet specification.
    """
    # All columns from Silver layer (base columns)
    client: str
    sampleNumber: str
    sampleDate: date
    unitId: str
    machineName: str
    machineModel: Optional[str] = None
    machineBrand: Optional[str] = None
    machineHours: Optional[float] = None
    machineSerialNumber: Optional[str] = None
    componentName: str
    componentNameNormalized: str
    componentHours: Optional[float] = None
    componentSerialNumber: Optional[str] = None
    oilMeter: Optional[float] = None
    oilBrand: Optional[str] = None
    oilType: Optional[str] = None
    oilWeight: Optional[str] = None
    previousSampleNumber: Optional[str] = None
    previousSampleDate: Optional[date] = None
    daysSincePrevious: Optional[int] = None
    group_element: Optional[str] = None
    
    # Essay columns (dynamic - Hierro, Cobre, Silicio, etc. - 21 total)
    # These are in the actual DataFrame as individual columns
    
    # Essay classification results (essay_status_{essay} columns)
    # Format: essay_status_Hierro, essay_status_Cobre, etc.
    # Values: 'Normal', 'Marginal', 'Condenatorio', 'Critico'
    
    # Classification summary
    breached_essays: List[str] = Field(default_factory=list, description="Essays exceeding thresholds")
    essay_score: int = Field(default=0, description="Total essay points")
    report_status: str = Field(default="Normal", description="Overall report status: Normal, Alerta, Anormal")
    
    # AI-generated insights
    ai_recommendation: Optional[str] = Field(None, description="AI-generated maintenance recommendation")
    ai_analysis: Optional[str] = Field(None, description="AI analysis of breached essays")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "client": "CDA",
                "sampleNumber": "CDA-2024-001",
                "sampleDate": "2024-01-15",
                "unitId": "CAT-001",
                "machineName": "camion",
                "componentName": "motor diesel",
                "breached_essays": ["Hierro", "Cobre"],
                "essay_score": 8,
                "report_status": "Alerta",
                "ai_recommendation": "Se recomienda programar inspección preventiva...",
                "ai_analysis": "Niveles elevados de hierro y cobre indican desgaste progresivo..."
            }
        }
    }


class MachineStatus(BaseModel):
    """
    Schema for machine-level status aggregation (Golden layer).
    
    Aggregated current health status per equipment unit.
    Based on DATA_CONTRACTS.md Golden Layer machine_status.parquet specification.
    """
    client: str = Field(..., description="Client identifier")
    unitId: str = Field(..., description="Equipment unit ID")
    machineName: str = Field(..., description="Machine type (camion, pala, etc.)")
    machineModel: Optional[str] = Field(None, description="Machine model")
    componentName: str = Field(..., description="Component name")
    componentNameNormalized: str = Field(..., description="Component normalized for Stewart Limits")
    
    # Latest sample information
    lastSampleNumber: str = Field(..., description="Most recent sample ID")
    lastSampleDate: date = Field(..., description="Most recent sample date")
    lastReportStatus: str = Field(..., description="Latest status: Normal, Alerta, Anormal")
    
    # Aggregated counts
    totalSamples: int = Field(..., description="Total samples for this unit/component")
    normalCount: int = Field(default=0, description="Count of Normal reports")
    alertaCount: int = Field(default=0, description="Count of Alerta reports")
    anormalCount: int = Field(default=0, description="Count of Anormal reports")
    
    # Average metrics
    avgEssayScore: float = Field(default=0.0, description="Average essay score")
    
    # AI insights
    lastAiRecommendation: Optional[str] = Field(None, description="Latest AI recommendation")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "client": "CDA",
                "unitId": "CAT-001",
                "machineName": "camion",
                "machineModel": "CAT 797F",
                "componentName": "motor diesel",
                "lastSampleNumber": "CDA-2024-100",
                "lastSampleDate": "2024-02-01",
                "lastReportStatus": "Alerta",
                "totalSamples": 45,
                "normalCount": 38,
                "alertaCount": 5,
                "anormalCount": 2,
                "avgEssayScore": 2.3,
                "lastAiRecommendation": "Programar inspección preventiva..."
            }
        }
    }


class StewartLimits(BaseModel):
    """
    Schema for Stewart Limits (Golden layer).
    
    Statistical thresholds for essay classification per client.
    Based on DATA_CONTRACTS.md Golden Layer stewart_limits.parquet specification.
    """
    client: str = Field(..., description="Client identifier")
    machine: str = Field(..., description="Normalized machine name")
    component: str = Field(..., description="Component name")
    essay: str = Field(..., description="Essay name")
    
    # Thresholds (percentiles)
    threshold_normal: float = Field(..., description="90th percentile threshold")
    threshold_alert: float = Field(..., description="95th percentile threshold (Marginal/Condenatorio)")
    threshold_critic: float = Field(..., description="98th percentile threshold (Critico)")
    
    model_config = {
        "json_schema_extra": {
            "example": {
                "client": "CDA",
                "machine": "camion",
                "component": "motor diesel",
                "essay": "Hierro",
                "threshold_normal": 45.2,
                "threshold_alert": 58.7,
                "threshold_critic": 72.1
            }
        }
    }


class StewartLimitsFour(BaseModel):
    """
    Schema for the four-limit Stewart output (Golden layer, v2.8).

    Uses the main service's own field names (LIC/LIM/LSM/LSC) directly - no limit-name
    transformation required downstream. Based on data_contracts.md v2.8
    stewart_limits_four.parquet specification.
    """
    client: str = Field(..., description="Client identifier")
    machine: str = Field(..., description="Normalized machine name")
    component: str = Field(..., description="Component name")
    essay: str = Field(..., description="Essay name")
    oilHourRange: str = Field(..., description="Oil age category: 'LT_1000', 'GE_1000', 'UNKNOWN'")
    GroupElement: Optional[str] = Field(default=None, description="Essay classification from essays_elements.xlsx")
    min_value: Optional[float] = Field(default=None, description="Minimum observed (non-null) value for this essay/component/oilHourRange")

    # Lower limits (2nd/5th percentile) - null when lower limits don't apply
    LIC: Optional[float] = Field(default=None, description="Límite Inferior Condenatorio (2nd percentile)")
    LIM: Optional[float] = Field(default=None, description="Límite Inferior Marginal (5th percentile)")

    # Upper limits (95th/98th percentile) - always calculated
    LSM: float = Field(..., description="Límite Superior Marginal (95th percentile)")
    LSC: float = Field(..., description="Límite Superior Condenatorio (98th percentile)")

    sample_count: int = Field(default=0, description="Number of samples used for calculation")
    calculation_date: Optional[str] = Field(default=None, description="ISO timestamp of calculation")

    model_config = {
        "json_schema_extra": {
            "example": {
                "client": "CDA",
                "machine": "camion",
                "component": "motor diesel",
                "essay": "Hierro",
                "oilHourRange": "GE_1000",
                "GroupElement": "Desgaste",
                "min_value": 12.0,
                "LIC": None,
                "LIM": None,
                "LSM": 45.0,
                "LSC": 58.0,
                "sample_count": 450
            }
        }
    }


def dataframe_to_oil_samples(df: pd.DataFrame) -> List[OilSample]:
    """
    Convert DataFrame to list of OilSample models.
    
    Args:
        df: DataFrame with OilSample schema
    
    Returns:
        List of validated OilSample instances
    """
    samples = []
    for _, row in df.iterrows():
        sample = OilSample(**row.to_dict())
        samples.append(sample)
    return samples


def oil_samples_to_dataframe(samples: List[OilSample]) -> pd.DataFrame:
    """
    Convert list of OilSample models to DataFrame.
    
    Args:
        samples: List of OilSample instances
    
    Returns:
        DataFrame
    """
    data = [sample.model_dump() for sample in samples]
    return pd.DataFrame(data)
