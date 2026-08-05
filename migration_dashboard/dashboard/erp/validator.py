"""Warning Validator dashboard page (TRD §10.1, design.md §1.1, REQ-021..026).

Left panel: pending warnings for the active client. Right panel: read-only
Coddi fields + editable ERP fields, wired directly to warning_writer + the SAP
adapter stub (no API hop — same in-process pattern as the CLI, design.md §1.1).

Registered as a page (`/erp/validacion-avisos`) in the shell app — run via
`python -m dashboard.app`.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import dash
import dash_bootstrap_components as dbc
from dash import Input, Output, State, callback, dcc, html

from agent import warning_writer
from agent.client_config import CLIENTS_DIR
from agent.envelope import (
    CONDITION_LABEL_LABELS,
    SEVERITY_LABELS,
    SOURCE_LABELS,
    SYSTEM_LABELS,
    Severity,
    Warning,
)

from dashboard.erp.write_operations import MAX_TITLE_LENGTH, approve_and_send, can_approve, reject

logger = logging.getLogger(__name__)

_SEVERITY_COLOR = {"low": "secondary", "medium": "info", "high": "warning", "critical": "danger"}
_LABEL_COLOR = {"alerta": "warning", "anormal": "danger"}
_LABEL_BORDER = {"alerta": "border-warning", "anormal": "border-danger"}


def list_client_ids() -> list[str]:
    if not CLIENTS_DIR.exists():
        return []
    return sorted(p.stem for p in CLIENTS_DIR.glob("*.yaml"))


def list_pending(client_id: str) -> list[Warning]:
    return warning_writer.read_warnings(client_id, "pending")


def _pending_item(warning: Warning) -> dbc.Card:
    age = datetime.now(timezone.utc) - warning.generated_at
    border = _LABEL_BORDER.get(warning.condition_label.value, "border-secondary")
    return html.Div(
        dbc.Card(
            dbc.CardBody(
                dbc.Row(
                    [
                        dbc.Col(
                            [
                                html.Strong(warning.asset_id, className="d-block"),
                                html.Small(
                                    f"{SOURCE_LABELS.get(warning.source, warning.source.value)} · "
                                    f"{SYSTEM_LABELS.get(warning.system, warning.system.value)}",
                                    className="text-muted",
                                ),
                            ],
                            width=5,
                        ),
                        dbc.Col(
                            [
                                dbc.Badge(
                                    CONDITION_LABEL_LABELS.get(warning.condition_label, warning.condition_label.value),
                                    color=_LABEL_COLOR.get(warning.condition_label.value, "secondary"),
                                    className="me-1",
                                ),
                                dbc.Badge(
                                    SEVERITY_LABELS.get(warning.severity, warning.severity.value),
                                    color=_SEVERITY_COLOR.get(warning.severity.value, "secondary"),
                                ),
                            ],
                            width=4,
                        ),
                        dbc.Col(
                            html.Small(f"{age.seconds // 3600}h ago", className="text-muted"),
                            width=3,
                            className="text-end",
                        ),
                    ],
                    align="center",
                ),
                className="py-2 px-3",
            ),
            className=f"border-start {border} border-3",
        ),
        id={"type": "erp-validator-select-pending", "index": warning.warning_id},
        n_clicks=0,
        className="mb-2",
        style={"cursor": "pointer"},
    )


def _detail_placeholder(message: str) -> html.Div:
    return html.Div(
        [html.I(className="fas fa-hand-pointer fa-2x text-muted mb-3"), html.P(message, className="text-muted")],
        className="text-center py-5",
    )


def _context_section(warning: Warning) -> html.Div:
    return html.Div(
        [
            html.H4(
                [html.I(className="fas fa-info-circle me-2"), "Contexto del Aviso"],
                className="text-primary mb-3 mt-2 pb-2 border-bottom",
            ),
            html.P("Información generada por el agente de IA. Solo lectura.", className="text-muted mb-3"),
            dbc.Row(
                [
                    dbc.Col(
                        [
                            html.Small("Fuente", className="text-muted fw-bold d-block"),
                            html.P(SOURCE_LABELS.get(warning.source, warning.source.value), className="mb-0"),
                        ],
                        md=2,
                    ),
                    dbc.Col(
                        [
                            html.Small("Sistema", className="text-muted fw-bold d-block"),
                            html.P(SYSTEM_LABELS.get(warning.system, warning.system.value), className="mb-0"),
                        ],
                        md=2,
                    ),
                    dbc.Col(
                        [
                            html.Small("Id Del Activo", className="text-muted fw-bold d-block"),
                            html.P(warning.asset_id, className="mb-0"),
                        ],
                        md=2,
                    ),
                    dbc.Col(
                        [
                            html.Small("Clasificación", className="text-muted fw-bold d-block"),
                            dbc.Badge(
                                CONDITION_LABEL_LABELS.get(warning.condition_label, warning.condition_label.value),
                                color=_LABEL_COLOR.get(warning.condition_label.value, "secondary"),
                            ),
                        ],
                        md=3,
                    ),
                    dbc.Col(
                        [
                            html.Small("Generado", className="text-muted fw-bold d-block"),
                            html.P(warning.generated_at.strftime("%d/%m/%Y %H:%M"), className="mb-0"),
                        ],
                        md=3,
                    ),
                ],
                className="g-2 mb-2",
            ),
            html.Small(
                f"Evidencia: {len(warning.supporting_data.get('raw_signal', []))} registro(s)",
                className="text-muted",
            ),
        ]
    )


def _erp_fields_section(warning: Warning) -> html.Div:
    return html.Div(
        [
            html.H4(
                [html.I(className="fas fa-paper-plane me-2"), "Datos para el ERP"],
                className="text-primary mb-3 mt-4 pb-2 border-bottom",
            ),
            html.P("Revise y complete la información antes de enviar al ERP.", className="text-muted mb-3"),
            html.Label(
                [html.I(className="fas fa-heading me-1"), " Título (Short Text SAP, ≤ 40 caracteres)"],
                className="fw-bold mb-1",
            ),
            dbc.Input(
                id="erp-validator-field-title",
                type="text",
                maxLength=MAX_TITLE_LENGTH,
                value=warning.title,
                className="mb-3",
            ),
            html.Label(
                [html.I(className="fas fa-align-left me-1"), " Descripción (Long Text SAP)"],
                className="fw-bold mb-1",
            ),
            dbc.Textarea(id="erp-validator-field-description", rows=4, value=warning.description, className="mb-3"),
            html.Label([html.I(className="fas fa-tools me-1"), " Acción recomendada"], className="fw-bold mb-1"),
            dbc.Textarea(
                id="erp-validator-field-action", rows=3, value=warning.recommended_action, className="mb-3"
            ),
            html.Label([html.I(className="fas fa-sticky-note me-1"), " Notas del operador"], className="fw-bold mb-1"),
            dbc.Textarea(
                id="erp-validator-field-notes", rows=2, value=warning.operator_notes or "", className="mb-3"
            ),
            html.Label(
                [html.I(className="fas fa-tachometer-alt me-1"), " Severidad (Prioridad SAP)"],
                className="fw-bold mb-1",
            ),
            dcc.Dropdown(
                id="erp-validator-field-severity",
                options=[{"label": SEVERITY_LABELS[s], "value": s.value} for s in Severity],
                value=warning.severity.value,
                clearable=False,
                className="mb-3",
            ),
        ]
    )


def _detail_form(warning: Warning) -> html.Div:
    return html.Div(
        [
            _context_section(warning),
            _erp_fields_section(warning),
            html.Div(
                [
                    dbc.Button(
                        [html.I(className="fas fa-paper-plane me-2"), "Aprobar y Enviar al ERP"],
                        id="erp-validator-btn-approve",
                        color="success",
                        size="lg",
                        className="me-3",
                    ),
                    dbc.Button(
                        [html.I(className="fas fa-times me-2"), "Rechazar"],
                        id="erp-validator-btn-reject",
                        color="danger",
                        outline=True,
                        size="lg",
                    ),
                ],
                className="d-flex mt-4 pt-3 border-top",
            ),
            dbc.Collapse(
                [
                    html.Label(
                        [html.I(className="fas fa-comment-alt me-1"), " Motivo de rechazo"],
                        className="fw-bold mb-1 mt-3 text-danger",
                    ),
                    dbc.Textarea(
                        id="erp-validator-field-rejection",
                        rows=2,
                        placeholder="Indique por qué se rechaza este aviso...",
                        className="border-danger",
                    ),
                    dbc.Button(
                        "Confirmar Rechazo", id="erp-validator-btn-confirm-reject", color="danger", className="mt-2"
                    ),
                ],
                id="erp-validator-rejection-collapse",
                is_open=False,
            ),
            dbc.Alert(
                id="erp-validator-success-alert",
                color="success",
                is_open=False,
                dismissable=True,
                className="mt-3",
            ),
            dbc.Alert(
                id="erp-validator-error-alert", color="danger", is_open=False, dismissable=True, className="mt-3"
            ),
        ]
    )


def layout(**_kwargs):
    client_ids = list_client_ids()
    return dbc.Container(
        [
            html.Div(
                [
                    html.H3(
                        [html.I(className="fas fa-clipboard-check me-2"), "Validación de Avisos"],
                        className="text-primary mb-2",
                    ),
                    html.P(
                        "Revise, edite y apruebe los avisos generados por el agente de IA antes de enviarlos al ERP.",
                        className="text-muted",
                    ),
                ],
                className="mb-4",
            ),
            dbc.Row(
                dbc.Col(
                    [
                        html.Label(
                            [html.I(className="fas fa-building me-1"), " Cliente"], className="fw-bold mb-2"
                        ),
                        dcc.Dropdown(
                            id="erp-validator-client-dropdown",
                            options=[{"label": c, "value": c} for c in client_ids],
                            value=client_ids[0] if client_ids else None,
                            clearable=False,
                        ),
                    ],
                    md=4,
                ),
                className="mb-4",
            ),
            dcc.Store(id="erp-validator-selected-warning-id"),
            dbc.Row(
                [
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.H5(
                                        [html.I(className="fas fa-list me-2"), "Avisos Pendientes"],
                                        className="mb-0",
                                    ),
                                    className="bg-primary text-white",
                                ),
                                dbc.CardBody(
                                    dcc.Loading(
                                        html.Div(
                                            id="erp-validator-warning-list",
                                            style={"maxHeight": "70vh", "overflowY": "auto"},
                                        ),
                                        type="circle",
                                    ),
                                    className="p-2",
                                ),
                            ],
                            className="shadow-sm h-100",
                        ),
                        md=4,
                    ),
                    dbc.Col(
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.H5(
                                        [html.I(className="fas fa-clipboard-check me-2"), "Detalle del Aviso"],
                                        className="mb-0",
                                    ),
                                    className="bg-light",
                                ),
                                dbc.CardBody(
                                    dcc.Loading(
                                        html.Div(
                                            id="erp-validator-form-content",
                                            children=_detail_placeholder("Seleccione un aviso pendiente."),
                                        ),
                                        type="circle",
                                    )
                                ),
                            ],
                            className="shadow-sm h-100",
                        ),
                        md=8,
                    ),
                ],
                className="gx-3",
            ),
        ],
        fluid=True,
        className="p-4",
    )


@callback(
    Output("erp-validator-warning-list", "children"),
    Input("erp-validator-client-dropdown", "value"),
    Input("erp-validator-selected-warning-id", "data"),
)
def _refresh_pending_list(client_id, _selected_warning_id):
    """Also triggered by selection changes (not just the client dropdown): after an approve/reject
    action resets `erp-validator-selected-warning-id` to None, this re-reads from disk so the
    just-actioned warning disappears from the list without a manual page refresh."""
    if not client_id:
        return html.P("No hay cliente seleccionado.", className="text-muted p-2")
    pending = list_pending(client_id)
    logger.info("client=%s pending_count=%d", client_id, len(pending))
    if not pending:
        return html.P("No hay avisos pendientes.", className="text-muted p-2")
    return [_pending_item(w) for w in pending]


@callback(
    Output("erp-validator-selected-warning-id", "data"),
    Input({"type": "erp-validator-select-pending", "index": dash.ALL}, "n_clicks"),
    prevent_initial_call=True,
)
def _select_pending(_n_clicks):
    triggered = dash.ctx.triggered_id
    if not triggered or not any(_n_clicks):
        raise dash.exceptions.PreventUpdate
    logger.info("warning_id=%s selected", triggered["index"])
    return triggered["index"]


@callback(
    Output("erp-validator-form-content", "children"),
    Input("erp-validator-selected-warning-id", "data"),
    State("erp-validator-client-dropdown", "value"),
)
def _render_detail(warning_id, client_id):
    if not warning_id or not client_id:
        return _detail_placeholder("Seleccione un aviso pendiente.")
    found = warning_writer.find_by_id(client_id, warning_id)
    if found is None:
        logger.warning("client=%s warning_id=%s not found (no longer pending?)", client_id, warning_id)
        return _detail_placeholder("El aviso ya no está pendiente.")
    warning, _state = found
    return _detail_form(warning)


@callback(
    Output("erp-validator-rejection-collapse", "is_open"),
    Input("erp-validator-btn-reject", "n_clicks"),
    State("erp-validator-rejection-collapse", "is_open"),
    prevent_initial_call=True,
)
def _toggle_rejection_collapse(_n_clicks, is_open):
    return not is_open


@callback(
    Output("erp-validator-success-alert", "children"),
    Output("erp-validator-success-alert", "is_open"),
    Output("erp-validator-error-alert", "children"),
    Output("erp-validator-error-alert", "is_open"),
    Output("erp-validator-selected-warning-id", "data", allow_duplicate=True),
    Input("erp-validator-btn-approve", "n_clicks"),
    Input("erp-validator-btn-confirm-reject", "n_clicks"),
    State("erp-validator-selected-warning-id", "data"),
    State("erp-validator-client-dropdown", "value"),
    State("erp-validator-field-title", "value"),
    State("erp-validator-field-description", "value"),
    State("erp-validator-field-action", "value"),
    State("erp-validator-field-notes", "value"),
    State("erp-validator-field-severity", "value"),
    State("erp-validator-field-rejection", "value"),
    prevent_initial_call=True,
)
def _handle_action(
    _approve_clicks,
    _confirm_reject_clicks,
    warning_id,
    client_id,
    title,
    description,
    recommended_action,
    operator_notes,
    severity,
    reject_reason,
):
    if not warning_id or not client_id:
        raise dash.exceptions.PreventUpdate
    triggered = dash.ctx.triggered_id

    if triggered == "erp-validator-btn-approve":
        if not can_approve(title, warning_id, recommended_action):
            logger.warning(
                "client=%s warning_id=%s approve blocked: missing required field(s)", client_id, warning_id
            )
            return "", False, "Título, asset y acción recomendada son obligatorios.", True, dash.no_update
        if len(title) > MAX_TITLE_LENGTH:
            logger.warning(
                "client=%s warning_id=%s approve blocked: title exceeds %d chars",
                client_id,
                warning_id,
                MAX_TITLE_LENGTH,
            )
            return (
                "",
                False,
                f"El título excede {MAX_TITLE_LENGTH} caracteres.",
                True,
                dash.no_update,
            )
        logger.info("client=%s warning_id=%s approving and sending to ERP", client_id, warning_id)
        result = approve_and_send(
            client_id,
            warning_id,
            operator_id="operator",
            title=title,
            description=description,
            recommended_action=recommended_action,
            operator_notes=operator_notes or None,
            severity=severity,
        )
        if result.status == "sent":
            logger.info(
                "client=%s warning_id=%s sent to ERP erp_reference=%s",
                client_id,
                warning_id,
                result.erp_reference,
            )
            return (
                ["Aviso enviado al ERP correctamente. Referencia SAP: ", html.Strong(result.erp_reference)],
                True,
                "",
                False,
                None,
            )
        logger.error(
            "client=%s warning_id=%s ERP push failed: %s", client_id, warning_id, result.operator_notes
        )
        return "", False, f"Error al enviar al ERP: {result.operator_notes}", True, None

    if triggered == "erp-validator-btn-confirm-reject":
        if not reject_reason:
            logger.warning("client=%s warning_id=%s reject blocked: no reason given", client_id, warning_id)
            return "", False, "Debe indicar un motivo de rechazo.", True, dash.no_update
        reject(client_id, warning_id, operator_id="operator", reason=reject_reason)
        logger.info("client=%s warning_id=%s rejected reason=%r", client_id, warning_id, reject_reason)
        return "Aviso rechazado.", True, "", False, None

    raise dash.exceptions.PreventUpdate
