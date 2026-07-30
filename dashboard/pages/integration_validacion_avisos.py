import dash
from dashboard.layout import create_placeholder_content


def layout(**kwargs):
    return create_placeholder_content("Validación de Avisos")


dash.register_page(__name__, path="/integration/validacion-avisos", title="Validación de Avisos | Multi-Technical Alerts", layout=layout)
