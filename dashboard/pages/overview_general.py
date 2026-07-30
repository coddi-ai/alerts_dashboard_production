import dash
from dashboard.tabs.tab_overview_general import create_layout


def layout(**kwargs):
    return create_layout()


# pages_folder="" disables Dash's auto-discovery "plug" step, which is what
# normally fills in page["layout"] from the module's `layout` attribute — so
# with manual registration, `layout=` must be passed explicitly here.
dash.register_page(__name__, path="/overview/general", title="General | Multi-Technical Alerts", layout=layout)
