"""All state-mutating logic used by the Validator page (REQ-024/025).

Isolated from validator.py on purpose: this is the net-new piece for a platform that already has
its own read path for warnings and only needs the write path (approve/reject/send-to-ERP) added.
See migration_guide.md §3.
"""
from __future__ import annotations

from datetime import datetime, timezone

from agent import warning_writer
from agent.envelope import Warning
from agent.erp.sap_adapter import push_to_erp

MAX_TITLE_LENGTH = 40


def can_approve(title: str, asset_id: str, recommended_action: str) -> bool:
    """REQ-024: required for approval, title recommended <= 40 chars (soft warning elsewhere)."""
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
    """REQ-024: apply operator edits, transition pending -> validated, then push to ERP."""
    now = datetime.now(timezone.utc)
    warning_writer.transition(
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
    """REQ-025: reject with a reason, no ERP push."""
    now = datetime.now(timezone.utc)
    return warning_writer.transition(
        client_id,
        warning_id,
        "pending",
        "rejected",
        operator_notes=reason,
        validated_by=operator_id,
        validated_at=now,
    )
