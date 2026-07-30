import dash
from dashboard.layout import create_placeholder_content


def layout(**kwargs):
    return create_placeholder_content("Campbell AI")


dash.register_page(__name__, path="/agents/campbell-ai", title="Campbell AI | Multi-Technical Alerts", layout=layout)
