import dash
from dashboard.tabs.tab_integration_seguimiento_avisos import create_layout


def layout(**kwargs):
    return create_layout()


dash.register_page(__name__, path="/integration/seguimiento-avisos", title="Seguimiento de Avisos | Multi-Technical Alerts", layout=layout)
