import dash
from dashboard.layout import create_placeholder_content


def layout(**kwargs):
    return create_placeholder_content("Administración")


dash.register_page(__name__, path="/admin", title="Administración | Multi-Technical Alerts", layout=layout)
