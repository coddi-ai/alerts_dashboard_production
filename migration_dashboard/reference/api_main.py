"""Local FastAPI app wrapping agent/evaluate.py + warning_writer.py (design.md §1.1, REQ-032..035).

No auth, no public exposure — Phase 1 only (NFR-002). Run via:
    uvicorn api.main:app --reload
"""
from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agent import warning_writer
from agent.condition import NormalConditionRejected
from agent.envelope import Severity, Source, SignalEnvelope, WarningStatus
from agent.erp.sap_adapter import push_to_erp
from agent.evaluate import DuplicateWarningError, evaluate

app = FastAPI(title="Coddi Warning Agent API")


class WarningPatchBody(BaseModel):
    operator_id: str
    title: str | None = None
    description: str | None = None
    recommended_action: str | None = None
    operator_notes: str | None = None
    severity: Severity | None = None
    condition_label: str | None = None  # accepted, always ignored — immutable (REQ-006)


@app.post("/evaluate")
def post_evaluate(envelope: SignalEnvelope):
    try:
        warning = evaluate(envelope)
    except NormalConditionRejected as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except DuplicateWarningError as exc:
        return JSONResponse(
            status_code=409,
            content={"detail": "duplicate", "existing_warning_id": exc.existing_warning_id},
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return {
        "warning_id": warning.warning_id,
        "status": warning.status,
        "condition_label": warning.condition_label,
        "title": warning.title,
        "description": warning.description,
        "recommended_action": warning.recommended_action,
        "severity": warning.severity,
    }


@app.get("/warnings")
def get_warnings(
    client_id: str,
    status: WarningStatus | None = None,
    source: Source | None = None,
    asset_id: str | None = None,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
):
    states = [status.value] if status else list(warning_writer.STATES)
    warnings = [w for state in states for w in warning_writer.read_warnings(client_id, state)]

    if source:
        warnings = [w for w in warnings if w.source == source]
    if asset_id:
        warnings = [w for w in warnings if w.asset_id == asset_id]
    if from_date:
        warnings = [w for w in warnings if w.generated_at >= from_date]
    if to_date:
        warnings = [w for w in warnings if w.generated_at <= to_date]

    return [w.model_dump(mode="json") for w in warnings]


@app.patch("/warnings/{warning_id}")
def patch_warning(warning_id: str, patch: WarningPatchBody):
    found = warning_writer.find_by_id_any_client(warning_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"warning '{warning_id}' not found")
    warning, client_id, state = found

    updates = patch.model_dump(exclude={"operator_id", "condition_label"}, exclude_none=True)
    for field, value in updates.items():
        setattr(warning, field, value)
    warning.validated_by = patch.operator_id
    warning.validated_at = datetime.now(warning.generated_at.tzinfo)

    warning_writer.write(client_id, state, warning)
    return warning.model_dump(mode="json")


@app.post("/warnings/{warning_id}/send")
def send_warning(warning_id: str):
    found = warning_writer.find_by_id_any_client(warning_id)
    if found is None:
        raise HTTPException(status_code=404, detail=f"warning '{warning_id}' not found")
    _, client_id, state = found
    if state != "validated":
        raise HTTPException(
            status_code=400, detail=f"warning is '{state}', not 'validated' — cannot send"
        )

    try:
        result = push_to_erp(client_id, warning_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if result.status != "sent":
        raise HTTPException(status_code=502, detail=result.operator_notes)
    return {"erp_reference": result.erp_reference, "status": result.status}
