import dash
from dashboard.tabs.tab_user_registry import create_layout


def layout(**kwargs):
    return create_layout()


dash.register_page(
    __name__,
    path="/admin/registro-usuarios",
    title="Registro de usuarios | Multi-Technical Alerts",
    layout=layout,
)
