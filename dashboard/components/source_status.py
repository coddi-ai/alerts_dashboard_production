"""Client-facing source availability and provenance components."""

from __future__ import annotations

from dash import html

from src.data.catalog import SourceProbe, build_client_availability


SERVICE_SOURCES = {
    "overview-general": ("oil_machine_status", "alerts_consolidated", "data_freshness", "maintenance_contract"),
    "overview-data-freshness": ("data_freshness",),
    "monitoring-alerts": ("alerts_consolidated", "telemetry_alert_detail", "oil_classified"),
    "monitoring-telemetry": ("telemetry_unit_health", "telemetry_system_health", "telemetry_manifest"),
    "monitoring-oil": ("oil_classified", "oil_machine_status", "oil_limits_four"),
    "predictive": ("predictive_components", "predictive_ai"),
}

_STATUS = {
    "available": ("Disponible", "#198754", "var(--green-light)"),
    "partial": ("Parcial", "#946200", "var(--amber-light)"),
    "missing": ("Sin fuente", "#6c757d", "var(--surface-2)"),
}


def service_source_status(client: str, service_id: str) -> tuple[str, dict[str, SourceProbe]]:
    """Return the aggregate status and the probes relevant to a service."""

    availability = build_client_availability(client)
    names = SERVICE_SOURCES.get(service_id, ())
    selected = {name: availability[name] for name in names if name in availability}
    if not selected:
        return "missing", selected
    statuses = {probe.status for probe in selected.values()}
    if statuses == {"available"}:
        return "available", selected
    if "available" in statuses or "partial" in statuses:
        return "partial", selected
    return "missing", selected


def render_service_source_status(client: str, service_id: str, *, compact: bool = False):
    """Render a small, non-blocking provenance banner for a dashboard page."""

    aggregate, probes = service_source_status(client, service_id)
    label, color, background = _STATUS.get(aggregate, _STATUS["missing"])
    children = [
        html.Strong(f"Fuentes de datos: {label}"),
        html.Span(" · " if compact else "  "),
    ]
    for source, probe in probes.items():
        source_label = source.replace("_", " ").title()
        source_label, source_color, source_bg = _STATUS.get(probe.status, _STATUS["missing"])
        children.append(
            html.Span(
                f"{source.replace('_', ' ').title()}: {source_label}",
                title=probe.note or probe.path or "No se encontró una fuente compatible.",
                style={
                    "display": "inline-block",
                    "marginRight": "8px",
                    "padding": "2px 7px",
                    "borderRadius": "4px",
                    "backgroundColor": source_bg,
                    "color": source_color,
                    "fontSize": "11px",
                },
            )
        )
    return html.Div(
        children,
        className="mb-3",
        style={
            "padding": "8px 12px",
            "borderLeft": f"4px solid {color}",
            "backgroundColor": background,
            "fontSize": "12px",
        },
    )
