"""State-mutating logic for the Validación de Avisos page.

Ported from migration_dashboard/dashboard/erp/write_operations.py.
Isolated from the page/callback code on purpose — this is the only piece
that writes data; everything else in Conexión ERP is read/display.
"""
from __future__ import annotations

from datetime import datetime, timezone

from src.data import erp_warning_store
from src.data.erp_sap_adapter import push_to_erp
from src.data.erp_schemas import Warning

MAX_TITLE_LENGTH = 40


def can_approve(title: str, asset_id: str, recommended_action: str) -> bool:
    """Required for approval; title recommended <= 40 chars (checked separately)."""
    return bool(title) and bool(asset_id) and bool(recommended_action)


def approve_and_send(
    client_id: str,
    warning_id: str,
    operator_id: str,
    title: str,
    description: str,
    recommended_action: str,
    operator_notes: str | None,
    severity: str,
) -> Warning:
    """Apply operator edits, transition pending -> validated, then push to ERP."""
    now = datetime.now(timezone.utc)
    erp_warning_store.transition(
        client_id,
        warning_id,
        "pending",
        "validated",
        title=title,
        description=description,
        recommended_action=recommended_action,
        operator_notes=operator_notes,
        severity=severity,
        validated_by=operator_id,
        validated_at=now,
    )
    return push_to_erp(client_id, warning_id)


def reject(client_id: str, warning_id: str, operator_id: str, reason: str) -> Warning:
    """Reject with a reason, no ERP push."""
    now = datetime.now(timezone.utc)
    return erp_warning_store.transition(
        client_id,
        warning_id,
        "pending",
        "rejected",
        operator_notes=reason,
        validated_by=operator_id,
        validated_at=now,
    )
