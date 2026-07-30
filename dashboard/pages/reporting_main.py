import dash
from dashboard.layout import create_placeholder_content


def layout(**kwargs):
    return create_placeholder_content("Reportabilidad")


dash.register_page(__name__, path="/reporting", title="Reportes | Multi-Technical Alerts", layout=layout)
