import dash
from dashboard.tabs.tab_integration_validacion_avisos import create_layout


def layout(**kwargs):
    return create_layout()


dash.register_page(__name__, path="/integration/validacion-avisos", title="Validación de Avisos | Multi-Technical Alerts", layout=layout)
