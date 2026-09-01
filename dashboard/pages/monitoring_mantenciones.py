import dash
from dashboard.tabs.tab_mantenciones_general import layout_mantenciones_general


def layout(**kwargs):
    return layout_mantenciones_general()


# pages_folder="" disables Dash's auto-discovery "plug" step, which is what
# normally fills in page["layout"] from the module's `layout` attribute — so
# with manual registration, `layout=` must be passed explicitly here.
dash.register_page(__name__, path="/monitoring/mantenciones", title="Mantenciones | Multi-Technical Alerts", layout=layout)
