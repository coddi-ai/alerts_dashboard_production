"""Validación de Avisos page layout (Conexión ERP).

Left panel: pending warnings for the globally-selected client (client-selector
in the navbar). Right panel: read-only Coddi fields + editable ERP fields.
Reactive logic lives in dashboard/callbacks/integration_avisos_callbacks.py —
client comes from the global selector, not a page-local dropdown (this page's
content is identical across clients, only the data feeding it changes).
"""
from __future__ import annotations

from datetime import datetime, timezone

import dash_bootstrap_components as dbc
from dash import dcc, html

from src.data.erp_schemas import (
    CONDITION_LABEL_LABELS,
    SEVERITY_LABELS,
    SOURCE_LABELS,
    SYSTEM_LABELS,
    Severity,
    Warning,
)
from src.data.erp_write_operations import MAX_TITLE_LENGTH

_SEVERITY_COLOR = {"low": "secondary", "medium": "info", "high": "warning", "critical": "danger"}
_LABEL_COLOR = {"alerta": "warning", "anormal": "danger"}
_LABEL_BORDER = {"alerta": "border-warning", "anormal": "border-danger"}


def create_pending_item(warning: Warning) -> html.Div:
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


def create_detail_placeholder(message: str) -> html.Div:
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


def create_detail_form(warning: Warning) -> html.Div:
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


def create_layout() -> dbc.Container:
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
                                            children=create_detail_placeholder("Seleccione un aviso pendiente."),
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
