import dash
from dashboard.campbell_ai.layout import create_campbell_ai_layout


def layout(**kwargs):
    # No user_data is available here: this is called per-navigation by Dash's
    # page router, not from the user-info-store callback chain. The layout
    # resolves the authenticated identity itself from the live Flask session.
    return create_campbell_ai_layout()


dash.register_page(__name__, path="/agents/campbell-ai", title="Campbell AI | Multi-Technical Alerts", layout=layout)
