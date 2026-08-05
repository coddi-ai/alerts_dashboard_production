"""Pydantic schema for Conexión ERP warnings (data_contract.md §1).

Ported from the ERP Connection team's `agent/envelope.py` handoff
(migration_dashboard/reference/envelope.py). The pipeline-only
`SignalEnvelope` model is intentionally omitted — the dashboard only ever
reads/writes already-formed `Warning` records.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Source(str, Enum):
    alertas = "alertas"
    telemetria = "telemetria"
    aceites = "aceites"
    predictivo = "predictivo"


SOURCE_LABELS: dict[Source, str] = {
    Source.alertas: "Alertas",
    Source.telemetria: "Telemetría",
    Source.aceites: "Aceites",
    Source.predictivo: "Predictivo",
}


class System(str, Enum):
    motor = "motor"
    transmision = "transmision"
    diferencial = "diferencial"
    hidraulico = "hidraulico"
    convertidor = "convertidor"
    direccion = "direccion"
    mando_final = "mando_final"
    rueda = "rueda"
    frenos = "frenos"


SYSTEM_LABELS: dict[System, str] = {
    System.motor: "Motor",
    System.transmision: "Transmisión",
    System.diferencial: "Diferencial",
    System.hidraulico: "Hidráulico",
    System.convertidor: "Convertidor",
    System.direccion: "Dirección",
    System.mando_final: "Mando Final",
    System.rueda: "Rueda",
    System.frenos: "Frenos",
}


class ConditionLabel(str, Enum):
    normal = "normal"
    alerta = "alerta"
    anormal = "anormal"


CONDITION_LABEL_LABELS: dict[ConditionLabel, str] = {
    ConditionLabel.normal: "Normal",
    ConditionLabel.alerta: "Alerta",
    ConditionLabel.anormal: "Anormal",
}


class Severity(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


SEVERITY_LABELS: dict[Severity, str] = {
    Severity.low: "Bajo",
    Severity.medium: "Medio",
    Severity.high: "Alto",
    Severity.critical: "Crítico",
}


class WarningStatus(str, Enum):
    pending = "pending"
    validated = "validated"
    rejected = "rejected"
    sent = "sent"


STATUS_LABELS: dict[WarningStatus, str] = {
    WarningStatus.pending: "Pendiente",
    WarningStatus.validated: "Validado",
    WarningStatus.rejected: "Rechazado",
    WarningStatus.sent: "Enviado",
}


class ErpType(str, Enum):
    sap = "sap"
    ellipse = "ellipse"
    maximo = "maximo"
    stub = "stub"


class Warning(BaseModel):
    model_config = {"validate_assignment": True}

    warning_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    client_id: str
    asset_id: str
    source: Source
    system: System
    condition_label: Literal[ConditionLabel.alerta, ConditionLabel.anormal]
    severity: Severity
    title: str
    description: str
    recommended_action: str
    supporting_data: dict[str, Any] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: WarningStatus = WarningStatus.pending
    validated_by: str | None = None
    validated_at: datetime | None = None
    operator_notes: str | None = None
    sent_at: datetime | None = None
    erp_type: ErpType
    erp_reference: str | None = None
