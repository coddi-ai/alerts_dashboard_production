import dash
from dashboard.layout import create_placeholder_content


def layout(**kwargs):
    return create_placeholder_content("Seguimiento de Avisos")


dash.register_page(__name__, path="/integration/seguimiento-avisos", title="Seguimiento de Avisos | Multi-Technical Alerts", layout=layout)
