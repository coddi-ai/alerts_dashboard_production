"""SAP IW21 adapter for Conexión ERP — payload build + stub send (data_contract.md §2).

Ported from migration_dashboard/reference/erp/{base,sap_adapter}.py.
`SAPAdapter.send()` is a stub: it logs the payload and returns a synthetic
notification number (or a SAP-style error), it does not call real SAP. See
data_contract.md §2.4 for the exact stub response shapes.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone

from src.data import erp_warning_store
from src.data.erp_client_config import AssetIdFormat, ClientConfig, load_client_config
from src.data.erp_schemas import ConditionLabel, Severity, Source, Warning

_PRIORITY_BY_SEVERITY = {
    Severity.low: "4",
    Severity.medium: "3",
    Severity.high: "2",
    Severity.critical: "1",
}


class ERPAdapter:
    def build_payload(self, warning: Warning) -> dict:
        """Translate a validated Warning into the ERP-specific request payload."""
        raise NotImplementedError

    def parse_response(self, response: dict) -> str:
        """Extract the ERP reference number from the ERP's response."""
        raise NotImplementedError


def _build_long_text(warning: Warning) -> str:
    blocks = [
        f"[DETALLE DEL HALLAZGO]\n{warning.description}",
        f"[ACCIÓN RECOMENDADA]\n{warning.recommended_action}",
    ]
    if warning.operator_notes:
        blocks.append(f"[NOTAS DEL OPERADOR]\n{warning.operator_notes}")
    blocks.append(
        "[TRAZABILIDAD CODDI]\n"
        f"Fuente: {warning.source.value} | Clasificación: {warning.condition_label.value} | "
        f"ID: {warning.warning_id}"
    )
    return "\n\n".join(blocks)


class SAPAdapter(ERPAdapter):
    def __init__(self, client_config: ClientConfig):
        self.client_config = client_config

    def build_payload(self, warning: Warning) -> dict:
        sap = self.client_config.sap
        if self.client_config.asset_id_format == AssetIdFormat.equipment:
            equipment, functional_location = warning.asset_id, None
        else:
            equipment, functional_location = None, warning.asset_id

        malfunction_start = None
        if warning.source == Source.alertas or warning.condition_label == ConditionLabel.anormal:
            malfunction_start = warning.generated_at.isoformat()

        notification_date = (warning.validated_at or warning.generated_at).date().isoformat()

        return {
            "notificationType": sap.notification_type,
            "referenceNotification": None,
            "technicalObject": {
                "equipment": equipment,
                "functionalLocation": functional_location,
            },
            "subject": {
                "shortText": warning.title,
                "longText": _build_long_text(warning),
            },
            "responsibility": {
                "planningPlant": sap.planning_plant,
                "plannerGroup": sap.planner_group,
                "mainWorkCenter": sap.main_work_center,
                "reportedBy": warning.validated_by,
            },
            "dates": {
                "notificationDate": notification_date,
                "requiredStart": None,
                "requiredEnd": None,
                "malfunctionStart": malfunction_start,
                "malfunctionEnd": None,
            },
            "priority": _PRIORITY_BY_SEVERITY[warning.severity],
            "attachments": [],
        }

    def parse_response(self, response: dict) -> str:
        return response["notificationNumber"]

    def send(self, warning: Warning, force_failure: bool = False) -> dict:
        """Stub ERP push: logs the payload, returns a synthetic notification
        number on success, or a SAP-style error on the forced-failure path."""
        payload = self.build_payload(warning)
        print(f"[SAPAdapter.send] warning_id={warning.warning_id} payload={payload}")

        if force_failure:
            return {
                "success": False,
                "notificationNumber": None,
                "status": "ERROR",
                "message": f"Equipment {warning.asset_id} not found in plant {self.client_config.sap.planning_plant}",
            }
        notification_number = "9" + "".join(str(random.randint(0, 9)) for _ in range(9))
        return {
            "success": True,
            "notificationNumber": notification_number,
            "status": "CREATED",
            "message": "Maintenance notification created successfully",
        }


def push_to_erp(client_id: str, warning_id: str, force_failure: bool = False) -> Warning:
    """Shared ERP-push flow for the Validación page's Approve button: on
    success, transitions `validated` -> `sent` with `erp_reference` set; on
    failure, stays `validated` with the ERP's error message written to
    `operator_notes`.
    """
    found = erp_warning_store.find_by_id(client_id, warning_id)
    if found is None:
        raise ValueError(f"Warning {warning_id} not found for client {client_id}")
    warning, state = found
    if state != "validated":
        raise ValueError(f"Warning {warning_id} is '{state}', not 'validated' — cannot send")

    client_config = load_client_config(client_id)
    if client_config.client_erp_type != "sap":
        raise NotImplementedError(f"No ERP adapter implemented for '{client_config.client_erp_type}'")

    adapter = SAPAdapter(client_config)
    response = adapter.send(warning, force_failure=force_failure)

    if response["success"]:
        return erp_warning_store.transition(
            client_id,
            warning_id,
            "validated",
            "sent",
            erp_reference=adapter.parse_response(response),
            sent_at=datetime.now(timezone.utc),
        )

    warning.operator_notes = response["message"]
    erp_warning_store.write(client_id, "validated", warning)
    return warning
