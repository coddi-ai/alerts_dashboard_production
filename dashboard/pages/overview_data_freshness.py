import dash
from dashboard.tabs.tab_data_freshness import create_layout


def layout(**kwargs):
    return create_layout()


dash.register_page(__name__, path="/overview/data-freshness", title="Estado de Datos | Multi-Technical Alerts", layout=layout)
