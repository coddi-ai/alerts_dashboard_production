"""
Tab: Mantenciones General
Vista general consolidada de mantenciones con KPIs, gráficos y tablas.
"""

import dash_bootstrap_components as dbc
from dash import html, dcc, dash_table
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime

# Pareto chart (Mantenciones por Sistema) styling: bars are not segmented
# further, so a single accent color is used for the count bars and a
# contrasting color for the cumulative-percentage line - matches the
# convention used by the alerts-per-unit Pareto (dashboard/components/alerts_charts.py).
PARETO_BAR_COLOR = '#355c7d'
PARETO_LINE_COLOR = '#d08c60'


def create_kpi_card(title: str, value: str, icon: str = "fa-info-circle", color: str = "primary", scope_label: str = None):
    """
    Create a KPI card component.

    Args:
        title: Card title
        value: Card value to display
        icon: FontAwesome icon class
        color: Bootstrap color theme
        scope_label: Optional small label clarifying the KPI's time scope
            (e.g. "Estado actual" vs "Acumulado MTD"), shown under the title.

    Returns:
        dbc.Card component
    """
    return dbc.Card([
        dbc.CardBody([
            html.Div([
                html.I(className=f"fas {icon} fa-2x mb-2 text-{color}"),
                html.H3(value, className="mb-0", id=f"kpi-{title.lower().replace(' ', '-')}"),
                html.P(title, className="text-muted mb-0"),
                html.P(scope_label, className="text-muted small mb-0 fst-italic") if scope_label else None,
            ], className="text-center")
        ])
    ], className="shadow-sm h-100")


def layout_mantenciones_general():
    """
    Create the Mantenciones General tab layout.
    
    Returns:
        html.Div with complete layout
    """
    return html.Div([
        # Header
        dbc.Row([
            dbc.Col([
                html.H2([
                    html.I(className="fas fa-wrench me-2"),
                    "Mantenciones - Ventana General"
                ]),
                html.P("Vista consolidada de estado de equipos y trabajos de mantenimiento", 
                       className="text-muted")
            ], width=8),
            dbc.Col([
                html.Div([
                    html.Span([
                        html.I(className="fas fa-info-circle me-2"),
                        html.Span("Última actualización: ", className="text-muted"),
                        html.Span("N/A", id="text-last-update", className="text-muted fw-bold"),
                    ], className="me-3"),
                    dbc.Button([
                        html.I(className="fas fa-sync-alt me-2"),
                        "Refrescar"
                    ], id="btn-refresh-general", color="primary"),
                ], className="d-flex align-items-center justify-content-end")
            ], width=4)
        ], className="mb-4"),

        # Filters: apply to all panels below. Default (nothing selected) is
        # the full, unfiltered dataset - the same behavior as before filters
        # existed.
        dbc.Row([
            dbc.Col([
                html.Label("Rango de Fechas", className="small text-muted mb-1"),
                dcc.DatePickerRange(
                    id="filter-date-range",
                    display_format="YYYY-MM-DD",
                    className="w-100",
                ),
            ], width=4),
            dbc.Col([
                html.Label("Sistema", className="small text-muted mb-1"),
                dcc.Dropdown(
                    id="filter-system",
                    multi=True,
                    placeholder="Todos los sistemas",
                ),
            ], width=4),
            dbc.Col([
                html.Label("Equipo", className="small text-muted mb-1"),
                dcc.Dropdown(
                    id="filter-equipment",
                    multi=True,
                    placeholder="Todos los equipos",
                ),
            ], width=4),
        ], className="mb-4"),

        # Hidden stores for data caching
        dcc.Store(id="store-general-data"),
        dcc.Store(id="store-general-timestamp"),
        dcc.Store(id="store-general-loaded", data=False),  # Track if data is loaded

        # Loading overlay
        dcc.Loading(
            id="loading-general",
            type="default",
            children=[
                # Row 1: KPIs
                dbc.Row([
                    dbc.Col(create_kpi_card(
                        "Equipos Totales",
                        "0",
                        "fa-industry",
                        "info",
                        scope_label="Estado actual"
                    ), width=3),
                    dbc.Col(create_kpi_card(
                        "Equipos Sanos",
                        "0",
                        "fa-check-circle",
                        "success",
                        scope_label="Estado actual"
                    ), width=3),
                    dbc.Col(create_kpi_card(
                        "Equipos Detenidos",
                        "0",
                        "fa-exclamation-triangle",
                        "danger",
                        scope_label="Estado actual"
                    ), width=3),
                    dbc.Col(dbc.Card([
                        dbc.CardBody([
                            html.Div([
                                html.I(className="fas fa-clock fa-2x mb-2 text-warning"),
                                html.H3("0", className="mb-0", id="kpi-horas-detenidas-mtd"),
                                html.P(id="kpi-horas-detenidas-label", children="Horas Detenidas", className="text-muted mb-0"),
                                html.P("Acumulado MTD", className="text-muted small mb-0 fst-italic"),
                            ], className="text-center")
                        ])
                    ], className="shadow-sm h-100"), width=3),
                ], className="mb-4", id="row-kpis"),
                
                # Row 2: Visualizations
                dbc.Row([
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.I(className="fas fa-chart-pie me-2"),
                                "Estado de Equipos"
                            ]),
                            dbc.CardBody([
                                dcc.Graph(
                                    id="chart-status-distribution",
                                    config={"displayModeBar": False},
                                    style={"height": "300px"}
                                )
                            ])
                        ], className="shadow-sm h-100")
                    ], width=4),
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.I(className="fas fa-chart-bar me-2"),
                                "Mantenciones por Sistema (Pareto)"
                            ]),
                            dbc.CardBody([
                                dcc.Graph(
                                    id="chart-system-pareto",
                                    config={"displayModeBar": False},
                                    style={"height": "300px"}
                                )
                            ])
                        ], className="shadow-sm h-100")
                    ], width=4),
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.I(className="fas fa-chart-line me-2"),
                                "Horas Detenidas por Día (MTD)"
                            ]),
                            dbc.CardBody([
                                dcc.Graph(
                                    id="chart-downtime-trend",
                                    config={"displayModeBar": False},
                                    style={"height": "300px"}
                                )
                            ])
                        ], className="shadow-sm h-100")
                    ], width=4),
                ], className="mb-4"),

                # Row 3: Tables
                dbc.Row([
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.I(className="fas fa-history me-2"),
                                "Últimos Periodos de Detención por Equipo"
                            ]),
                            dbc.CardBody([
                                html.Div(id="table-last-detentions")
                            ])
                        ], className="shadow-sm")
                    ], width=12),
                ], className="mb-4"),
                
                dbc.Row([
                    dbc.Col([
                        dbc.Card([
                            dbc.CardHeader([
                                html.I(className="fas fa-tasks me-2"),
                                "Trabajos Realizados - Última Semana"
                            ]),
                            dbc.CardBody([
                                html.Div(id="table-jobs-last-week")
                            ])
                        ], className="shadow-sm")
                    ], width=12),
                ], className="mb-4"),
            ]
        ),
    ], className="p-4")


def create_empty_figure(message: str = "No hay datos disponibles"):
    """
    Create an empty plotly figure with a message.
    
    Args:
        message: Message to display
        
    Returns:
        plotly.graph_objects.Figure
    """
    fig = go.Figure()
    fig.add_annotation(
        text=message,
        xref="paper",
        yref="paper",
        x=0.5,
        y=0.5,
        showarrow=False,
        font=dict(size=14, color="gray")
    )
    fig.update_layout(
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        plot_bgcolor="white",
        margin=dict(l=20, r=20, t=20, b=20)
    )
    return fig


def create_status_donut_chart(df_status: pd.DataFrame) -> go.Figure:
    """
    Create a donut chart for machine status distribution.
    
    Args:
        df_status: DataFrame with columns machine_status, n_machines
        
    Returns:
        plotly.graph_objects.Figure
    """
    if df_status.empty:
        return create_empty_figure()
    
    colors = {
        "SANO": "#28a745",
        "DETENIDO": "#dc3545"
    }
    
    fig = go.Figure(data=[go.Pie(
        labels=df_status["machine_status"],
        values=df_status["n_machines"],
        hole=0.4,
        marker=dict(colors=[colors.get(status, "#6c757d") for status in df_status["machine_status"]]),
        # In-chart slices carry the numbers (value + %); the legend is left as
        # a plain color-to-category key so the same figures aren't repeated
        # in both places.
        textinfo="value+percent",
        textposition="auto",
        hoverinfo="label+value+percent",
    )])

    fig.update_layout(
        showlegend=True,
        margin=dict(l=20, r=20, t=20, b=20),
        height=300
    )
    
    return fig


def create_downtime_trend_chart(df_trend: pd.DataFrame, period_label: str = "Período") -> go.Figure:
    """
    Create a line chart for downtime trend by day.
    
    Args:
        df_trend: DataFrame with columns date, downtime_hours
        period_label: Label for the period (e.g., "Febrero 2024")
        
    Returns:
        plotly.graph_objects.Figure
    """
    if df_trend.empty:
        return create_empty_figure()

    fig = go.Figure()

    fig.add_trace(go.Scatter(
        x=df_trend["date"],
        y=df_trend["downtime_hours"],
        mode="lines+markers",
        name="Horas Detenidas",
        line=dict(color="#ffc107", width=3),
        marker=dict(size=8),
        fill="tozeroy",
        fillcolor="rgba(255, 193, 7, 0.2)"
    ))

    # The trend only ever covers days elapsed so far in the period (MTD), not
    # the full month - make that explicit with the last plotted day instead
    # of letting the month name alone imply full-month coverage.
    last_day = pd.to_datetime(df_trend["date"]).max()
    day_suffix = f" (al día {last_day.day})" if pd.notna(last_day) else ""

    fig.update_layout(
        title=dict(
            text=f"Horas Detenidas por Día - {period_label}{day_suffix}",
            font=dict(size=14),
            x=0.5,
            xanchor='center'
        ),
        xaxis_title="Fecha",
        yaxis_title="Horas Detenidas",
        hovermode="x unified",
        margin=dict(l=40, r=20, t=40, b=40),
        height=300,
        plot_bgcolor="white"
    )
    
    fig.update_xaxes(showgrid=True, gridcolor="lightgray")
    fig.update_yaxes(showgrid=True, gridcolor="lightgray")
    
    return fig


def create_system_pareto_chart(df_system: pd.DataFrame) -> go.Figure:
    """
    Create a Pareto chart of maintenance record counts by system: systems on
    the X-axis sorted by descending count (bars, primary Y-axis) with a
    cumulative-percentage line (secondary Y-axis, fixed 0-100%).

    Args:
        df_system: DataFrame with columns system_name, count, cumulative_pct
            (see MaintenanceRepository.get_maintenance_by_system)

    Returns:
        plotly.graph_objects.Figure
    """
    if df_system.empty:
        return create_empty_figure("No hay datos de sistemas disponibles")

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=df_system["system_name"],
            y=df_system["count"],
            name="Registros",
            marker_color=PARETO_BAR_COLOR,
            # Bar count labels always sit above the bar (never inside) so they
            # can't land at the same height as the cumulative-% line, which
            # tends to cross through the bars partway up.
            text=df_system["count"].map(lambda value: f"{int(value)}"),
            textposition="outside",
            cliponaxis=False,
            hovertemplate="Registros: %{y}<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=df_system["system_name"],
            y=df_system["cumulative_pct"],
            name="% acumulado",
            mode="lines+markers",
            line=dict(color=PARETO_LINE_COLOR, width=2),
            marker=dict(size=6, color=PARETO_LINE_COLOR),
            hovertemplate="%% acumulado: %{y:.1f}%<extra></extra>",
        ),
        secondary_y=True,
    )

    # Cumulative-% labels are drawn as annotations rather than trace text: a
    # fixed pixel yshift (independent of the two traces' different data
    # scales) plus an opaque background keeps them legible even where the
    # line crosses close to a bar's outside label.
    for system_name, pct in zip(df_system["system_name"], df_system["cumulative_pct"]):
        fig.add_annotation(
            x=system_name,
            y=pct,
            yref="y2",
            text=f"{pct:.0f}%",
            showarrow=False,
            yshift=16,
            font=dict(size=10, color=PARETO_LINE_COLOR),
            bgcolor="rgba(255,255,255,0.85)",
            bordercolor=PARETO_LINE_COLOR,
            borderwidth=1,
            borderpad=2,
        )

    max_count = int(df_system["count"].max())
    fig.update_xaxes(title_text=None, tickangle=-45, tickfont=dict(size=9))
    fig.update_yaxes(
        title_text="N° de Registros",
        # Extra headroom (vs. a plain 1.15x) so outside bar labels never get
        # clipped against the top of the plot area.
        range=[0, max_count * 1.3 if max_count else 1],
        nticks=6,
        secondary_y=False,
    )
    fig.update_yaxes(
        title_text="% Acum.",
        range=[0, 100],
        tickvals=[0, 20, 40, 60, 80, 100],
        ticksuffix="%",
        secondary_y=True,
    )
    fig.update_layout(
        template="plotly_white",
        showlegend=False,
        height=300,
        margin=dict(l=45, r=45, t=20, b=70),
        hovermode="x unified",
    )

    return fig


def create_detentions_table(df_detentions: pd.DataFrame) -> dash_table.DataTable:
    """
    Create a DataTable for last detentions.
    
    Args:
        df_detentions: DataFrame with detention data
        
    Returns:
        dash_table.DataTable
    """
    if df_detentions.empty:
        return html.P("No hay datos de detenciones disponibles", className="text-muted text-center p-3")
    
    # Format data
    df = df_detentions.copy()
    # Mostrar fecha y hora completa
    df["start_date"] = pd.to_datetime(df["start_date"]).dt.strftime("%Y-%m-%d %H:%M")
    
    # Solo mostrar duración estimada (basada en número de acciones)
    df["duration_hours"] = df["duration_hours"].round(1)
    
    # Asegurarse de que n_actions existe
    if "n_actions" not in df.columns:
        df["n_actions"] = 1  # Default para compatibilidad
    
    return dash_table.DataTable(
        data=df.to_dict("records"),
        columns=[
            {"name": "Equipo", "id": "machine_code"},
            {"name": "Fecha y Hora", "id": "start_date"},
            {"name": "N° Acciones", "id": "n_actions"},
            {"name": "Duración Est. (hrs)", "id": "duration_hours"},
            {"name": "Tipos de Trabajo", "id": "job_types"},
        ],
        style_table={"overflowX": "auto"},
        style_cell={
            "textAlign": "left",
            "padding": "10px",
            "fontSize": "14px"
        },
        style_header={
            "backgroundColor": "#f8f9fa",
            "fontWeight": "bold"
        },
        style_data_conditional=[
            {
                "if": {"row_index": "odd"},
                "backgroundColor": "#f8f9fa"
            }
        ],
        # Sin paginación - mostrar todos los equipos
        sort_action="native",
        filter_action="native",
        tooltip_header={
            "duration_hours": "Duración estimada: 1.5 hrs por acción",
            "n_actions": "Número de acciones registradas en este periodo"
        }
    )


def create_jobs_table(df_jobs: pd.DataFrame) -> dash_table.DataTable:
    """
    Create a DataTable for recent jobs.
    
    Args:
        df_jobs: DataFrame with jobs data
        
    Returns:
        dash_table.DataTable
    """
    if df_jobs.empty:
        return html.P("No hay trabajos registrados en la última semana", className="text-muted text-center p-3")
    
    # Format data
    df = df_jobs.copy()
    df["start_date"] = pd.to_datetime(df["start_date"]).dt.strftime("%Y-%m-%d %H:%M")
    df["subsystem_name"] = df["subsystem_name"].fillna("N/A")
    
    return dash_table.DataTable(
        data=df.to_dict("records"),
        columns=[
            {"name": "Equipo", "id": "machine_code"},
            {"name": "Sistema", "id": "system_name"},
            {"name": "Subsistema", "id": "subsystem_name"},
            {"name": "Tipo", "id": "job_type"},
            {"name": "Inicio", "id": "start_date"},
            {"name": "Notas", "id": "notes"},
        ],
        style_table={"overflowX": "auto"},
        style_cell={
            "textAlign": "left",
            "padding": "10px",
            "fontSize": "14px"
        },
        style_header={
            "backgroundColor": "#f8f9fa",
            "fontWeight": "bold"
        },
        style_data_conditional=[
            {
                "if": {"row_index": "odd"},
                "backgroundColor": "#f8f9fa"
            }
        ],
        page_size=10,
        sort_action="native",
        filter_action="native"
    )
