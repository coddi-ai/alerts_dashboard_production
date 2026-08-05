"""SAP IW21 adapter — build_payload (REQ-014/015/016) + send stub (REQ-017/018)."""
from __future__ import annotations

import random
from datetime import datetime, timezone

from agent import warning_writer
from agent.client_config import AssetIdFormat, ClientConfig, load_client_config
from agent.envelope import ConditionLabel, Severity, Source, Warning
from agent.erp.base import ERPAdapter

_PRIORITY_BY_SEVERITY = {
    Severity.low: "4",
    Severity.medium: "3",
    Severity.high: "2",
    Severity.critical: "1",
}


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
        """Stub ERP push (REQ-017/018): logs the payload, returns a synthetic
        notification number on success, or a SAP-style error on the forced-failure path."""
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
    """Shared ERP-push flow for the API's `/send` route and the dashboard's
    Approve button (REQ-017/018): on success, transitions `validated` -> `sent`
    with `erp_reference` set; on failure, stays `validated` with the ERP's
    error message written to `operator_notes`.
    """
    found = warning_writer.find_by_id(client_id, warning_id)
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
        return warning_writer.transition(
            client_id,
            warning_id,
            "validated",
            "sent",
            erp_reference=adapter.parse_response(response),
            sent_at=datetime.now(timezone.utc),
        )

    warning.operator_notes = response["message"]
    warning_writer.write(client_id, "validated", warning)
    return warning
