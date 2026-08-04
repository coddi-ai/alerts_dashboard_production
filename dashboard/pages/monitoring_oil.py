import dash
from dashboard.tabs.tab_oil import create_layout


def layout(**kwargs):
    return create_layout()


dash.register_page(__name__, path="/monitoring/oil", title="Aceite | Multi-Technical Alerts", layout=layout)
