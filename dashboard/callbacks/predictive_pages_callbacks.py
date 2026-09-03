"""
Callbacks for the predictive pages (dashboard/pages/predictive_*.py).

Those pages register a single placeholder container per component
(id={'type': 'predictive-page-content', 'component': <name>}) because the
content depends on the globally-selected client (client-selector in the
navbar) and must refresh live when the client changes, without a page
reload. This mirrors what the old section-content routing callback used to
do for the 'predictive-{component}' sections.
"""

from dash import Input, Output, State, html
from dash.dependencies import ALL
import dash

from dashboard.layout import create_placeholder_content
from config.settings import get_settings
from config.client_services import is_service_enabled
from src.data import predictive_v2
from src.utils.logger import get_logger

logger = get_logger(__name__)


def _resolve_client(selected_client, user_data) -> str:
    """Resolve the active client the same way the legacy section router did."""
    if selected_client:
        return selected_client.lower()
    if user_data and user_data.get('clients'):
        return user_data['clients'][0].lower()
    settings = get_settings()
    return settings.clients[0].lower() if settings.clients else 'cda'


def _render_component(client: str, component: str):
    if not is_service_enabled(client, f'predictive-{component}'):
        logger.warning(f"Predictive module accessed by client without access: {client}")
        return create_placeholder_content('Predictivo (no disponible para este cliente)')

    # Change 1: single shared discovery function - no more inline CSV-only
    # existence check. A component is available whether it's on the new
    # partitioned layout (risk_scores) or still legacy-CSV-only.
    layout = predictive_v2.discover_predictive_layout(client)
    availability = layout.get(component)
    has_data = availability is not None and (
        availability.risk_scores or availability.legacy_csv is not None
    )

    if not has_data:
        logger.warning(
            f"No predictive data found for client {client}, component {component}"
        )
        return html.Div([
            html.Div([
                html.Div([
                    html.I(className="fas fa-database fa-3x mb-3 text-muted"),
                    html.H4("Sin datos predictivos disponibles", className="text-muted"),
                    html.P(
                        f"No se encontraron datos predictivos de {component.title()} para el cliente {client.upper()}.",
                        className="text-muted mb-2"
                    ),
                    html.P(
                        "Los datos se generarán cuando exista historial suficiente de aceite y telemetría para este componente.",
                        className="text-muted small"
                    )
                ], className="text-center py-5")
            ], className="card shadow-sm", style={"marginTop": "16px"})
        ])

    from dashboard.tabs.tab_predictive_component import layout as predictive_component_layout
    return predictive_component_layout(client, component)


def register_predictive_pages_callbacks(app: dash.Dash) -> None:
    """Register the reactive content callback for predictive component pages."""

    # Output uses ALL (not MATCH): the triggering inputs (client-selector,
    # user-info-store) are plain, non-pattern ids, so Dash fans this callback
    # out across every currently-mounted 'predictive-page-content' container
    # in one dispatch and expects a list of results back, one per container
    # (in practice at most one, since only one page is ever mounted at a time).
    @app.callback(
        Output({'type': 'predictive-page-content', 'component': ALL}, 'children'),
        [Input('client-selector', 'value'),
         Input('user-info-store', 'data')],
        [State({'type': 'predictive-page-content', 'component': ALL}, 'id')],
    )
    def render_predictive_component(selected_client, user_data, container_ids):
        client = _resolve_client(selected_client, user_data)
        return [_render_component(client, container_id['component']) for container_id in container_ids]
