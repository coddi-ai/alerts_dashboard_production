"""Reactive callbacks for Conexión ERP (Validación de Avisos / Seguimiento de Avisos).

Both pages' content depends on the globally-selected client (client-selector
in the navbar) rather than a page-local dropdown (migration_guide.md §3).
List/KPI/chart callbacks (which have no other way to know which client to
load) resolve it the same way predictive_pages_callbacks.py._resolve_client
does: client-selector -> user-info-store's first client -> settings default.

Warning-scoped callbacks (view detail / approve / reject) instead resolve
client_id from the warning record itself via
erp_warning_store.find_by_id_any_client — the record is the source of truth
for which client a warning belongs to, and this keeps those actions working
regardless of what's currently selected in the client-selector.

Access to approve/reject is governed entirely by whether the operator can
reach this tab and see the warning at all (platform login + client access);
there's no separate identity/permission check layered on top of that.
"""
from __future__ import annotations

import logging

import dash
import dash_bootstrap_components as dbc
import plotly.express as px
from dash import Input, Output, State, callback, html

from config.settings import get_settings
from dashboard.tabs.tab_integration_validacion_avisos import (
    create_detail_form,
    create_detail_placeholder,
    create_pending_item,
)
from src.data import erp_warning_store
from src.data.erp_schemas import (
    CONDITION_LABEL_LABELS,
    ConditionLabel,
    Severity,
    SEVERITY_LABELS,
    Source,
    SOURCE_LABELS,
    System,
    SYSTEM_LABELS,
)
from src.data.erp_write_operations import MAX_TITLE_LENGTH, approve_and_send, can_approve, reject

logger = logging.getLogger(__name__)

# design-system semantic colors (ui_notes.md palette): Alerta=warning (caution), Anormal=danger
_LABEL_COLOR = {"Alerta": "#ffc107", "Anormal": "#dc3545"}
# pending-list sort priority (1.1): Anormal before Alerta before anything else, ties broken newest-first
_CRITICALITY_PRIORITY = {"anormal": 0, "alerta": 1, "normal": 2}
# validation-rate trend outcome labels (raw WarningStatus values, not the full STATUS_LABELS set —
# only "sent"/"rejected" ever appear here since validation_rate_trend restricts to terminal states)
_OUTCOME_LABELS = {"sent": "Enviado", "rejected": "Rechazado"}
# Registro de Avisos (2.2): presentation-only title-case for categorical columns. Identifiers
# (warning_id, asset_id, erp_reference), the operator name, and timestamps are left untouched.
_TITLECASE_TABLE_COLUMNS = ("source", "system", "condition_label", "severity", "status")


def _titlecase_display(df):
    display = df.copy()
    for col in _TITLECASE_TABLE_COLUMNS:
        if col in display.columns:
            display[col] = display[col].astype(str).str.title()
    return display


# categorical palette for the system distribution chart — distinct hues, colorblind-safe order
_SYSTEM_COLOR_SEQUENCE = [
    "#4c78a8", "#f58518", "#54a24b", "#e45756", "#72b7b2",
    "#eeca3b", "#b279a2", "#ff9da6", "#9d755d",
]


def _resolve_client(selected_client, user_data) -> str:
    """Resolve the active client the same way the predictive pages do."""
    if selected_client:
        return selected_client.lower()
    if user_data and user_data.get("clients"):
        return user_data["clients"][0].lower()
    settings = get_settings()
    return settings.clients[0].lower() if settings.clients else "cda"


# ---------------------------------------------------------------------------
# Validación de Avisos
# ---------------------------------------------------------------------------

@callback(
    Output("erp-validator-warning-list", "children"),
    Input("client-selector", "value"),
    Input("user-info-store", "data"),
    Input("erp-validator-selected-warning-id", "data"),
)
def _refresh_pending_list(selected_client, user_data, selected_warning_id):
    """Also triggered by selection changes (not just the client selector):
    after an approve/reject action resets erp-validator-selected-warning-id
    to None, this re-reads from disk so the just-actioned warning disappears
    from the list without a manual page refresh. The same selection also
    drives which card renders as selected (1.2)."""
    client_id = _resolve_client(selected_client, user_data)
    pending = erp_warning_store.read_warnings(client_id, "pending")
    logger.info("client=%s pending_count=%d", client_id, len(pending))
    if not pending:
        return html.P("No hay avisos pendientes.", className="text-muted p-2")
    pending = sorted(
        pending,
        key=lambda w: (
            _CRITICALITY_PRIORITY.get(w.condition_label.value, 99),
            -w.generated_at.timestamp(),
        ),
    )
    return [create_pending_item(w, is_selected=(w.warning_id == selected_warning_id)) for w in pending]


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
)
def _render_detail(warning_id):
    if not warning_id:
        return create_detail_placeholder("Seleccione un aviso pendiente.")
    found = erp_warning_store.find_by_id_any_client(warning_id)
    if found is None:
        logger.warning("warning_id=%s not found (no longer pending?)", warning_id)
        return create_detail_placeholder("El aviso ya no está pendiente.")
    warning, _client_id, _state = found
    return create_detail_form(warning)


@callback(
    Output("erp-validator-operator-input", "value"),
    Input("user-info-store", "data"),
    State("erp-validator-operator-store", "data"),
)
def _restore_operator(_user_data, stored_operator):
    """Populate the operator field from the session store on page (re)load.
    user-info-store is used purely as an on-load trigger (fires once when
    this page mounts, then again only on the rare login/logout in between) —
    the actual value always comes from the State read, not the Input."""
    return stored_operator or ""


@callback(
    Output("erp-validator-operator-store", "data"),
    Input("erp-validator-operator-input", "value"),
    prevent_initial_call=True,
)
def _save_operator(value):
    """One-directional: input -> store. Restoring the other way (store ->
    input) is handled by _restore_operator on an unrelated trigger, so this
    doesn't loop back into it."""
    return value


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
    Output("erp-validator-operator-feedback", "children"),
    Output("erp-validator-operator-input", "className"),
    Input("erp-validator-btn-approve", "n_clicks"),
    Input("erp-validator-btn-confirm-reject", "n_clicks"),
    State("erp-validator-selected-warning-id", "data"),
    State("erp-validator-operator-store", "data"),
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
    operator_name,
    title,
    description,
    recommended_action,
    operator_notes,
    severity,
    reject_reason,
):
    """Access to this action is governed entirely by whether the operator can
    reach this tab and see the warning at all (platform login + the warning
    existing under one of their clients) — no separate identity/permission
    check here. `client_id` comes from the warning record itself, not the
    client-selector, so this doesn't depend on that selector's state either.
    The operator's name comes from the session-scoped operator bar at the top
    of the page (erp-validator-operator-store) rather than a per-warning
    field, so it's reused across every approve/reject in the session."""
    if not warning_id:
        raise dash.exceptions.PreventUpdate

    found = erp_warning_store.find_by_id_any_client(warning_id)
    if found is None:
        logger.warning("warning_id=%s not found for action (no longer pending?)", warning_id)
        return "", False, "El aviso ya no está disponible.", True, None, "", ""

    _warning, client_id, _state = found
    operator_id = (operator_name or "").strip()

    if not operator_id:
        logger.warning("client=%s warning_id=%s action blocked: operator not provided", client_id, warning_id)
        return (
            "",
            False,
            "Debe indicar el nombre del operador.",
            True,
            dash.no_update,
            "Debe indicar el nombre del operador.",
            "is-invalid",
        )

    triggered = dash.ctx.triggered_id

    if triggered == "erp-validator-btn-approve":
        if not can_approve(title, warning_id, recommended_action):
            logger.warning(
                "client=%s warning_id=%s approve blocked: missing required field(s)", client_id, warning_id
            )
            return "", False, "Título, asset y acción recomendada son obligatorios.", True, dash.no_update, "", ""
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
                "",
                "",
            )
        logger.info(
            "client=%s warning_id=%s operator=%s approving and sending to ERP", client_id, warning_id, operator_id
        )
        result = approve_and_send(
            client_id,
            warning_id,
            operator_id=operator_id,
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
                "",
                "",
            )
        logger.error(
            "client=%s warning_id=%s ERP push failed: %s", client_id, warning_id, result.operator_notes
        )
        return "", False, f"Error al enviar al ERP: {result.operator_notes}", True, None, "", ""

    if triggered == "erp-validator-btn-confirm-reject":
        if not reject_reason:
            logger.warning("client=%s warning_id=%s reject blocked: no reason given", client_id, warning_id)
            return "", False, "Debe indicar un motivo de rechazo.", True, dash.no_update, "", ""
        reject(client_id, warning_id, operator_id=operator_id, reason=reject_reason)
        logger.info(
            "client=%s warning_id=%s operator=%s rejected reason=%r", client_id, warning_id, operator_id, reject_reason
        )
        return "Aviso rechazado.", True, "", False, None, "", ""

    raise dash.exceptions.PreventUpdate


# ---------------------------------------------------------------------------
# Seguimiento de Avisos
# ---------------------------------------------------------------------------

@callback(
    Output("erp-viewer-filter-asset", "options"),
    Output("erp-viewer-filter-asset", "value"),
    Input("client-selector", "value"),
    Input("user-info-store", "data"),
)
def _populate_asset_options(selected_client, user_data):
    """Asset ID is a dropdown, not free text — options come from that client's own data."""
    client_id = _resolve_client(selected_client, user_data)
    assets = sorted(erp_warning_store.load_all_warnings(client_id)["asset_id"].dropna().unique())
    logger.info("client=%s asset_options=%d", client_id, len(assets))
    return [{"label": a, "value": a} for a in assets], None


@callback(
    Output("erp-viewer-kpi-total", "children"),
    Output("erp-viewer-kpi-pending", "children"),
    Output("erp-viewer-kpi-sent", "children"),
    Output("erp-viewer-kpi-rejected", "children"),
    Output("erp-viewer-kpi-avg-hours", "children"),
    Output("erp-viewer-chart-by-label", "figure"),
    Output("erp-viewer-chart-by-severity", "figure"),
    Output("erp-viewer-chart-by-system", "figure"),
    Output("erp-viewer-chart-over-time", "figure"),
    Output("erp-viewer-chart-validation-rate", "figure"),
    Output("erp-viewer-table", "data"),
    Input("client-selector", "value"),
    Input("user-info-store", "data"),
    Input("erp-viewer-filter-source", "value"),
    Input("erp-viewer-filter-system", "value"),
    Input("erp-viewer-filter-label", "value"),
    Input("erp-viewer-filter-severity", "value"),
    Input("erp-viewer-filter-status", "value"),
    Input("erp-viewer-filter-asset", "value"),
    Input("erp-viewer-filter-dates", "start_date"),
    Input("erp-viewer-filter-dates", "end_date"),
)
def _refresh(selected_client, user_data, source, system, condition_label, severity, status, asset_id, start_date, end_date):
    client_id = _resolve_client(selected_client, user_data)
    empty_fig = px.bar()

    df = erp_warning_store.load_all_warnings(client_id)
    filtered = erp_warning_store.apply_filters(
        df, source, system, condition_label, severity, status, asset_id, start_date, end_date
    )
    logger.info(
        "client=%s loaded=%d after_filters=%d source=%s system=%s label=%s severity=%s status=%s asset=%s",
        client_id,
        len(df),
        len(filtered),
        source,
        system,
        condition_label,
        severity,
        status,
        asset_id,
    )

    kpis = erp_warning_store.compute_kpis(filtered)
    avg_hours_display = kpis["avg_hours_to_validation"] if kpis["avg_hours_to_validation"] is not None else "–"

    if filtered.empty:
        return (
            str(kpis["total"]),
            str(kpis["pending"]),
            str(kpis["validated_and_sent"]),
            str(kpis["rejected"]),
            str(avg_hours_display),
            empty_fig,
            empty_fig,
            empty_fig,
            empty_fig,
            empty_fig,
            [],
        )

    display = filtered.assign(
        source_label=filtered["source"].map(lambda s: SOURCE_LABELS.get(Source(s), s)),
        system_label=filtered["system"].map(lambda s: SYSTEM_LABELS.get(System(s), s)),
        condition_label_label=filtered["condition_label"].map(
            lambda s: CONDITION_LABEL_LABELS.get(ConditionLabel(s), s)
        ),
        severity_label=filtered["severity"].map(lambda s: SEVERITY_LABELS.get(Severity(s), s)),
    )

    by_label = px.bar(
        display.groupby(["source_label", "condition_label_label"]).size().reset_index(name="count"),
        x="source_label",
        y="count",
        color="condition_label_label",
        title=None,
        color_discrete_map=_LABEL_COLOR,
        labels={"source_label": "Fuente", "condition_label_label": "Clasificación", "count": "Cantidad de avisos"},
    )
    by_label.update_traces(
        hovertemplate="<b>Clasificación: %{fullData.name}</b><br>Fuente: %{x}<br>Cantidad de avisos: %{y}<extra></extra>"
    )
    by_severity = px.pie(
        display.groupby("severity_label").size().reset_index(name="count"),
        names="severity_label",
        values="count",
        labels={"severity_label": "Severidad", "count": "Cantidad de avisos"},
    )
    by_severity.update_traces(
        hovertemplate="<b>%{label}</b><br>Cantidad de avisos: %{value}<br>Porcentaje: %{percent}<extra></extra>"
    )
    by_system = px.pie(
        display.groupby("system_label").size().reset_index(name="count"),
        names="system_label",
        values="count",
        color_discrete_sequence=_SYSTEM_COLOR_SEQUENCE,
        labels={"system_label": "Sistema", "count": "Cantidad de avisos"},
    )
    by_system.update_traces(
        hovertemplate="<b>%{label}</b><br>Cantidad de avisos: %{value}<br>Porcentaje: %{percent}<extra></extra>"
    )
    over_time = (
        filtered.assign(day=filtered["generated_at"].dt.date).groupby("day").size().reset_index(name="count")
    )
    over_time_fig = px.line(
        over_time, x="day", y="count", markers=True, labels={"day": "Fecha", "count": "Cantidad de avisos"}
    )
    over_time_fig.update_traces(
        hovertemplate="<b>Fecha:</b> %{x|%d/%m/%Y}<br>Cantidad de avisos: %{y}<extra></extra>"
    )

    trend = erp_warning_store.validation_rate_trend(filtered)
    if not trend.empty:
        trend = trend.assign(outcome=trend["outcome"].map(_OUTCOME_LABELS).fillna(trend["outcome"]))
        validation_fig = px.line(
            trend,
            x="day",
            y="rate",
            color="outcome",
            labels={"day": "Fecha", "rate": "Tasa de Validación (%)", "outcome": "Estado"},
        )
        validation_fig.update_traces(
            hovertemplate="<b>%{fullData.name}</b><br>Fecha: %{x|%d/%m/%Y}<br>Tasa: %{y:.1f}%<extra></extra>"
        )
    else:
        validation_fig = px.line()

    for fig in (by_label, by_severity, by_system, over_time_fig, validation_fig):
        fig.update_layout(margin=dict(l=20, r=20, t=20, b=20))

    table_source = filtered[erp_warning_store.TABLE_COLUMNS].copy()
    table_source["generated_at"] = table_source["generated_at"].dt.strftime("%d/%m/%Y %H:%M")
    table_data = _titlecase_display(table_source.astype(str)).to_dict("records")
    return (
        str(kpis["total"]),
        str(kpis["pending"]),
        str(kpis["validated_and_sent"]),
        str(kpis["rejected"]),
        str(avg_hours_display),
        by_label,
        by_severity,
        by_system,
        over_time_fig,
        validation_fig,
        table_data,
    )


@callback(
    Output("erp-viewer-row-detail", "children"),
    Input("erp-viewer-table", "active_cell"),
    State("erp-viewer-table", "data"),
)
def _row_detail(active_cell, table_data):
    if not active_cell or not table_data:
        return ""
    row = table_data[active_cell["row"]]
    if (row.get("status") or "").lower() not in ("sent", "rejected"):
        return ""
    logger.info("row detail opened warning_id=%s status=%s", row.get("warning_id"), row.get("status"))
    return dbc.Card(dbc.CardBody(html.Pre(str(row))), className="shadow-sm mt-3")
