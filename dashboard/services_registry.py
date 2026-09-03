"""
Central nav/service registry.

Single source of truth mapping each client-gated service id to its URL,
label, icon, and parent nav section - used by both the sidebar builder
(dashboard/layout.py) and the centralized route guard
(dashboard/callbacks/access_control_callbacks.py), so the two never drift.

Admin routes (admin-main, admin-user-registry) are role-gated, not
client-service-gated, and are kept separate from KNOWN_SERVICE_IDS.
"""

from typing import Optional

from config.client_services import KNOWN_SERVICE_IDS, is_service_dummy, is_service_enabled

# Nav sections in display order. Each service id here must be one of
# config.client_services.KNOWN_SERVICE_IDS. 'predictive' is a section on its
# own, built dynamically per client from the per-component
# `predictive-<component>` service ids (dashboard/layout.py::build_navigation_items),
# not listed here.
SERVICE_SECTIONS = [
    {
        "section": "overview",
        "label": "Resumen",
        "icon": "fas fa-tachometer-alt",
        "services": ["overview-general", "overview-data-freshness"],
    },
    {
        "section": "monitoring",
        "label": "Monitoreo",
        "icon": "fas fa-chart-line",
        "services": ["monitoring-alerts", "monitoring-telemetry", "monitoring-oil", "monitoring-mantenciones"],
    },
    {
        "section": "agents",
        "label": "Agentes",
        "icon": "fas fa-robot",
        "services": ["agents-campbell-ai"],
    },
    {
        "section": "integration",
        "label": "Conexión ERP",
        "icon": "fas fa-plug",
        "services": ["integration-validacion-avisos", "integration-seguimiento-avisos"],
    },
    {
        "section": "reporting",
        "label": "Reportes",
        "icon": "fas fa-file-alt",
        "services": ["reporting-main"],
    },
]

SERVICE_LABELS = {
    "overview-general": "General",
    "overview-data-freshness": "Estado de Datos",
    "monitoring-alerts": "Alertas",
    "monitoring-telemetry": "Telemetría",
    "monitoring-oil": "Aceite",
    "monitoring-mantenciones": "Mantenciones",
    "predictive-motor": "Predictivo - Motor",
    "predictive-transmision": "Predictivo - Transmisión",
    "agents-campbell-ai": "Campbell AI",
    "integration-validacion-avisos": "Validación de Avisos",
    "integration-seguimiento-avisos": "Seguimiento de Avisos",
    "reporting-main": "Reportabilidad",
}

# service id / admin nav id -> URL path.
NAV_PATHS = {
    "overview-general": "/overview/general",
    "overview-data-freshness": "/overview/data-freshness",
    "monitoring-alerts": "/monitoring/alerts",
    "monitoring-telemetry": "/monitoring/telemetry",
    "monitoring-oil": "/monitoring/oil",
    "monitoring-mantenciones": "/monitoring/mantenciones",
    "predictive-motor": "/predictive/motor",
    "predictive-transmision": "/predictive/transmision",
    "agents-campbell-ai": "/agents/campbell-ai",
    "integration-validacion-avisos": "/integration/validacion-avisos",
    "integration-seguimiento-avisos": "/integration/seguimiento-avisos",
    "reporting-main": "/reporting",
    "admin-main": "/admin",
    "admin-user-registry": "/admin/registro-usuarios",
}

# Route guard resolution: stripped pathname ('dash.strip_relative_path' form,
# no leading/trailing slash) -> service id.
SERVICE_EXACT_ROUTES = {
    "overview/general": "overview-general",
    "overview/data-freshness": "overview-data-freshness",
    "monitoring/alerts": "monitoring-alerts",
    "monitoring/telemetry": "monitoring-telemetry",
    "monitoring/oil": "monitoring-oil",
    "monitoring/mantenciones": "monitoring-mantenciones",
    "agents/campbell-ai": "agents-campbell-ai",
    "integration/validacion-avisos": "integration-validacion-avisos",
    "integration/seguimiento-avisos": "integration-seguimiento-avisos",
    "reporting": "reporting-main",
}


def nav_path(nav_id: str) -> str:
    """Resolve a nav-item id to its URL path (predictive component ids are dynamic)."""
    if nav_id.startswith("predictive-"):
        return f"/predictive/{nav_id.split('predictive-', 1)[1]}"
    return NAV_PATHS[nav_id]


def resolve_service_id_for_pathname(rel_path: str) -> Optional[str]:
    """
    Resolve a stripped pathname (as returned by dash.strip_relative_path) to
    a service id, or None if it isn't a client-service-gated route.

    /predictive/<component> resolves to its own `predictive-<component>`
    service id, one per component, so access can be granted independently
    per component instead of via a single umbrella service.
    """
    if rel_path in SERVICE_EXACT_ROUTES:
        return SERVICE_EXACT_ROUTES[rel_path]

    if rel_path.startswith("predictive/"):
        component = rel_path.split("/", 2)[1]
        if component:
            return f"predictive-{component}"

    return None


def first_enabled_service_path(client_id: str) -> Optional[str]:
    """
    First enabled, non-dummy service's path for a client, in canonical
    order, or None if none qualify. Dummy services are skipped here since
    landing on one would just bounce straight to /sin-servicios anyway (see
    access_control_callbacks.py).
    """
    for service_id in KNOWN_SERVICE_IDS:
        if is_service_enabled(client_id, service_id) and not is_service_dummy(client_id, service_id):
            return NAV_PATHS[service_id]
    return None
