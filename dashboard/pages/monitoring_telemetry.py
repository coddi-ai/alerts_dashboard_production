import dash
from dashboard.tabs.tab_telemetry import create_layout


def layout(**kwargs):
    return create_layout()


dash.register_page(__name__, path="/monitoring/telemetry", title="Telemetría | Multi-Technical Alerts", layout=layout)
