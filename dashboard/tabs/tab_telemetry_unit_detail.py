"""Hierarchical telemetry unit detail layout."""

from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc


_STATE_RULES = [
    {"if": {"filter_query": '{system_status} = "Anormal"'}, "backgroundColor": "rgba(220,53,69,.10)", "color": "#b42318", "fontWeight": "600"},
    {"if": {"filter_query": '{system_status} = "Alerta"'}, "backgroundColor": "rgba(245,158,11,.12)", "color": "#8a5a00", "fontWeight": "600"},
    {"if": {"filter_query": '{system_status} = "InsufficientData"'}, "backgroundColor": "rgba(149,165,166,.15)", "color": "#657174"},
    {"if": {"filter_query": '{system_status} = "Normal"'}, "color": "#247a3d"},
]


def create_telemetry_unit_detail_layout() -> html.Div:
    """Create the unit -> system -> signal report flow."""
    return html.Div([
        dbc.Card([
            dbc.CardHeader([
                html.H5([html.I(className="fas fa-fingerprint me-2"), "Resumen de la unidad"], className="mb-0")
            ], className="bg-light"),
            dbc.CardBody([
                dbc.Row([
                    dbc.Col([
                        html.Label("Unidad", className="fw-bold small"),
                        dcc.Dropdown(
                            id="telemetry-detail-unit-selector",
                            placeholder="Seleccione una unidad...",
                            clearable=False,
                            searchable=True,
                        ),
                    ], md=4),
                    dbc.Col([
                        html.Div("Caso seleccionado", className="small text-muted fw-bold"),
                        html.Div("El estado y la recomendación corresponden a la unidad completa.", className="small text-muted mt-1"),
                    ], md=8),
                ]),
                html.Div(id="telemetry-detail-ai-comment", className="mt-3"),
            ]),
        ], className="shadow-sm mb-4"),

        html.Div([
            html.H4([html.I(className="fas fa-cogs me-2"), "Estado por sistema"], className="text-primary mb-2 mt-4 pb-2 border-bottom"),
            html.P("Revise el estado de todos los sistemas y seleccione uno para ver su evaluación IA.", className="text-muted mb-3"),
        ]),
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col(html.Label("Sistema seleccionado", className="small fw-bold"), md=3),
                    dbc.Col(dcc.Dropdown(id="telemetry-detail-system-selector", placeholder="Seleccione un sistema...", clearable=False), md=9),
                ], className="align-items-center mb-3"),
                dcc.Loading(
                    dash_table.DataTable(
                        id="telemetry-detail-system-table",
                        columns=[
                            {"name": "Sistema", "id": "system"},
                            {"name": "Estado", "id": "system_status"},
                            {"name": "Señales afectadas", "id": "signals_in_alert", "type": "numeric"},
                            {"name": "Señal principal", "id": "top_signal_display"},
                        ],
                        data=[],
                        row_selectable="single",
                        selected_rows=[],
                        sort_action="native",
                        page_size=10,
                        style_table={"overflowX": "auto"},
                        style_header={"backgroundColor": "#34495e", "color": "white", "fontWeight": "bold", "textAlign": "center"},
                        style_cell={"textAlign": "center", "padding": "10px", "fontSize": "14px", "whiteSpace": "normal", "height": "auto"},
                        style_cell_conditional=[
                            {"if": {"column_id": "system"}, "textAlign": "left", "fontWeight": "600"},
                            {"if": {"column_id": "top_signal_display"}, "textAlign": "left"},
                        ],
                        style_data_conditional=_STATE_RULES + [{"if": {"state": "active"}, "border": "2px solid #2f80ed"}],
                    ),
                    type="circle",
                ),
            ]),
        ], className="shadow-sm mb-3"),
        dcc.Loading(html.Div(id="telemetry-detail-system-analysis"), type="circle"),

        html.Div([
            html.H4([html.I(className="fas fa-wave-square me-2"), "Señales del sistema"], className="text-primary mb-2 mt-4 pb-2 border-bottom"),
            html.P("Seleccione una señal para abrir únicamente su evidencia técnica.", className="text-muted mb-3"),
        ]),
        dbc.Card([
            dbc.CardBody([
                dbc.Row([
                    dbc.Col(html.Label("Señal seleccionada", className="small fw-bold"), md=3),
                    dbc.Col(dcc.Dropdown(id="telemetry-detail-signal-selector", placeholder="Seleccione una señal...", clearable=False), md=9),
                ], className="align-items-center mb-3"),
                dcc.Loading(
                    dash_table.DataTable(
                        id="telemetry-detail-signal-table",
                        columns=[
                            {"name": "Señal", "id": "signal"},
                            {"name": "Estado", "id": "status"},
                            {"name": "Fuera de rango", "id": "abnormal_pct_display"},
                            {"name": "Eventos", "id": "total_events", "type": "numeric"},
                            {"name": "Episodio máx. (min)", "id": "longest_episode", "type": "numeric"},
                            {"name": "Tendencia", "id": "trend_direction"},
                            {"name": "signal_raw", "id": "signal_raw"},
                        ],
                        data=[],
                        row_selectable="single",
                        selected_rows=[],
                        sort_action="native",
                        page_size=15,
                        style_table={"overflowX": "auto"},
                        style_header={"backgroundColor": "#34495e", "color": "white", "fontWeight": "bold", "textAlign": "center"},
                        style_cell={"textAlign": "center", "padding": "9px", "fontSize": "13px", "whiteSpace": "normal", "height": "auto"},
                        style_cell_conditional=[
                            {"if": {"column_id": "signal"}, "textAlign": "left", "fontWeight": "600"},
                            {"if": {"column_id": "signal_raw"}, "display": "none"},
                        ],
                        style_data_conditional=[
                            {"if": {"filter_query": '{status} = "Anormal"'}, "backgroundColor": "rgba(220,53,69,.10)", "color": "#b42318", "fontWeight": "600"},
                            {"if": {"filter_query": '{status} = "Alerta"'}, "backgroundColor": "rgba(245,158,11,.12)", "color": "#8a5a00", "fontWeight": "600"},
                            {"if": {"filter_query": '{status} = "InsufficientData"'}, "backgroundColor": "rgba(149,165,166,.15)", "color": "#657174"},
                            {"if": {"state": "active"}, "border": "2px solid #2f80ed"},
                        ],
                    ),
                    type="circle",
                ),
            ]),
        ], className="shadow-sm mb-3"),
        html.Div([
            html.H4([html.I(className="fas fa-chart-line me-2"), "Evidencia de la señal seleccionada"], className="text-primary mb-2 mt-4 pb-2 border-bottom"),
            # W34-09: simplified view — starts at 1 day, no event overlays;
            # the buttons below only change the window width, never
            # unit/sistema/señal.
            html.P("Serie temporal con límites y tendencia. Amplíe la ventana con los botones si necesita más contexto.", className="text-muted mb-2"),
            dbc.RadioItems(
                id="telemetry-detail-window-days",
                options=[
                    {"label": "1 día", "value": 1},
                    {"label": "7 días", "value": 7},
                    {"label": "30 días", "value": 30},
                ],
                value=1,
                inline=True,
                className="btn-group mb-3",
                inputClassName="btn-check",
                labelClassName="btn btn-outline-primary btn-sm",
                labelCheckedClassName="active",
            ),
        ]),
        dcc.Loading(html.Div(id="telemetry-detail-signal-cards"), type="circle"),
    ])
