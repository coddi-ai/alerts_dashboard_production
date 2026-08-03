"""Campbell AI Dash layout, adapted from the former Streamlit chat."""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc


GREEN = "#10a37f"


def _capability_card(icon: str, title: str, description: str) -> dbc.Col:
    return dbc.Col(
        html.Div(
            [
                html.I(className=f"{icon} mb-3", style={"fontSize": "1.8rem", "color": GREEN}),
                html.H6(title, className="mb-2", style={"fontWeight": "700"}),
                html.P(
                    description,
                    className="text-muted mb-0",
                    style={"fontSize": "0.86rem", "lineHeight": "1.5"},
                ),
            ],
            style={
                "height": "100%",
                "padding": "1.15rem",
                "borderRadius": "12px",
                "background": "rgba(16, 163, 127, 0.05)",
                "border": "1px solid rgba(16, 163, 127, 0.18)",
            },
        ),
        width=12,
        md=4,
        className="mb-3",
    )


def create_campbell_ai_layout() -> html.Div:
    """Build the Campbell AI agent and visualization view."""
    return html.Div(
        [
            dcc.Store(id="campbell-ai-session-store", storage_type="session"),
            dcc.Store(id="campbell-ai-history-store", storage_type="session", data=[]),
            dcc.Store(id="campbell-ai-company-store", storage_type="session"),
            dcc.Store(id="campbell-ai-feedback-store", storage_type="session", data={}),
            dbc.Row(
                dbc.Col(
                    [
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.H2(
                                            [
                                                html.I(
                                                    className="fas fa-robot me-3",
                                                    style={"color": GREEN},
                                                ),
                                                "Campbell AI",
                                            ],
                                            className="mb-1",
                                            style={"fontWeight": "700"},
                                        ),
                                        html.P(
                                            "Asistente de mantenimiento basado en agentes",
                                            className="text-muted mb-0",
                                        ),
                                    ]
                                ),
                                dbc.Badge(
                                    "Inicializando…",
                                    id="campbell-ai-status",
                                    color="secondary",
                                    pill=True,
                                    className="px-3 py-2",
                                ),
                            ],
                            className="d-flex justify-content-between align-items-center flex-wrap gap-3",
                        ),
                        dbc.Alert(
                            id="campbell-ai-error",
                            color="danger",
                            is_open=False,
                            dismissable=True,
                            className="mt-3 mb-0",
                        ),
                        html.Div(
                            [
                                html.H4(
                                    "Bienvenido al Asistente de Mantenimiento",
                                    className="mb-2",
                                    style={"fontWeight": "650"},
                                ),
                                html.P(
                                    "Consulta alertas, mantenimiento, aceite y telemetría de la empresa activa. "
                                    "Campbell AI utiliza los mismos datos y permisos del dashboard.",
                                    className="text-muted mb-0",
                                    style={"maxWidth": "720px", "margin": "0 auto"},
                                ),
                            ],
                            className="text-center my-4",
                            style={
                                "padding": "1.6rem",
                                "borderRadius": "16px",
                                "background": "rgba(16, 163, 127, 0.08)",
                                "border": "1px solid rgba(16, 163, 127, 0.2)",
                            },
                        ),
                        dbc.Row(
                            [
                                _capability_card(
                                    "fas fa-database",
                                    "Análisis de datos",
                                    "Consulta fuentes de la empresa activa con trazabilidad y periodo.",
                                ),
                                _capability_card(
                                    "fas fa-chart-bar",
                                    "Gráficos interactivos",
                                    "Crea tendencias, Pareto, mapas de calor y comparaciones interactivas.",
                                ),
                                _capability_card(
                                    "fas fa-search",
                                    "Diagnóstico y 5 porqués",
                                    "Relaciona evidencia y propone validaciones y acciones de mantenimiento.",
                                ),
                            ],
                            className="g-3",
                        ),
                        dbc.Card(
                            [
                                dbc.CardHeader(
                                    html.Div(
                                        [
                                            html.Span(
                                                [
                                                    html.I(className="fas fa-comment-dots me-2"),
                                                    "Conversación",
                                                ],
                                                style={"fontWeight": "600"},
                                            ),
                                            dbc.Button(
                                                [
                                                    html.I(className="fas fa-trash-alt me-2"),
                                                    "Limpiar",
                                                ],
                                                id="campbell-ai-clear",
                                                color="link",
                                                size="sm",
                                                className="text-muted text-decoration-none",
                                                n_clicks=0,
                                            ),
                                        ],
                                        className="d-flex justify-content-between align-items-center",
                                    ),
                                    style={"backgroundColor": "white"},
                                ),
                                dbc.CardBody(
                                    dcc.Loading(
                                        html.Div(
                                            id="campbell-ai-messages",
                                            style={
                                                "minHeight": "250px",
                                                "maxHeight": "58vh",
                                                "overflowY": "auto",
                                                "padding": "0.5rem",
                                            },
                                        ),
                                        type="circle",
                                        color=GREEN,
                                    ),
                                    style={"padding": "1rem"},
                                ),
                                dbc.CardFooter(
                                    dbc.InputGroup(
                                        [
                                            dbc.Textarea(
                                                id="campbell-ai-input",
                                                placeholder="Pregúntame sobre mantenimiento o solicita un gráfico…",
                                                rows=2,
                                                maxLength=4000,
                                                style={
                                                    "resize": "none",
                                                    "borderRadius": "12px 0 0 12px",
                                                },
                                            ),
                                            dbc.Button(
                                                [
                                                    html.I(className="fas fa-paper-plane me-2"),
                                                    "Enviar",
                                                ],
                                                id="campbell-ai-send",
                                                color="success",
                                                n_clicks=0,
                                                style={
                                                    "backgroundColor": GREEN,
                                                    "borderColor": GREEN,
                                                },
                                            ),
                                        ]
                                    ),
                                    style={"backgroundColor": "white", "padding": "1rem"},
                                ),
                            ],
                            className="shadow-sm mt-2",
                            style={"borderRadius": "14px", "overflow": "hidden"},
                        ),
                        html.P(
                            "Incluye análisis, gráficos y feedback. Reportes, PDF, descargas y archivos están deshabilitados.",
                            className="text-muted text-center mt-3 mb-0",
                            style={"fontSize": "0.78rem"},
                        ),
                    ],
                    width=12,
                    xl=10,
                    className="mx-auto",
                )
            ),
        ],
        className="campbell-ai-view pb-4",
    )


def _render_visualizations(message: dict) -> list[html.Div]:
    charts: list[html.Div] = []
    for artifact in message.get("visualizations") or []:
        figure = artifact.get("figure")
        if not isinstance(figure, dict):
            continue
        charts.append(
            html.Div(
                [
                    dcc.Graph(
                        figure=figure,
                        config={"displayModeBar": False, "responsive": True},
                        style={"width": "100%"},
                    ),
                    html.P(
                        str(artifact.get("description", "")),
                        className="text-muted mb-0 px-2",
                        style={"fontSize": "0.78rem"},
                    ),
                ],
                className="mt-3",
                style={
                    "background": "white",
                    "border": "1px solid #dee2e6",
                    "borderRadius": "12px",
                    "padding": "0.35rem",
                },
            )
        )
    return charts


def _feedback_controls(message_id: str, selected: str | None) -> html.Div:
    disabled = selected in {"positive", "negative"}
    return html.Div(
        [
            html.Span(
                "¿Te sirvió esta respuesta?",
                className="text-muted me-2",
                style={"fontSize": "0.75rem"},
            ),
            dbc.Button(
                html.I(className="fas fa-thumbs-up"),
                id={
                    "type": "campbell-ai-feedback-button",
                    "message_id": message_id,
                    "rating": "positive",
                },
                n_clicks=0,
                size="sm",
                color="success",
                outline=selected != "positive",
                disabled=disabled,
                className="me-1",
                title="Respuesta útil",
            ),
            dbc.Button(
                html.I(className="fas fa-thumbs-down"),
                id={
                    "type": "campbell-ai-feedback-button",
                    "message_id": message_id,
                    "rating": "negative",
                },
                n_clicks=0,
                size="sm",
                color="danger",
                outline=selected != "negative",
                disabled=disabled,
                title="Respuesta no útil",
            ),
        ],
        className="d-flex align-items-center mt-3",
    )


def render_chat_history(
    messages: list[dict] | None, feedback: dict[str, str] | None = None
) -> list[html.Div]:
    """Render safe Markdown, Plotly charts and response feedback controls."""
    if not messages:
        return [
            html.Div(
                [
                    html.I(
                        className="fas fa-robot mb-3",
                        style={"fontSize": "2rem", "color": GREEN},
                    ),
                    html.P(
                        "La sesión está lista. Puedes consultar las últimas alertas, solicitar un "
                        "gráfico o analizar un problema con 5 porqués.",
                        className="text-muted mb-0",
                    ),
                ],
                className="text-center py-5",
            )
        ]

    ratings = feedback or {}
    bubbles: list[html.Div] = []
    for message in messages:
        is_user = message.get("role") == "user"
        message_id = str(message.get("message_id", ""))
        content: list = [
            html.Div(
                "Tú" if is_user else "Campbell AI",
                style={
                    "fontSize": "0.75rem",
                    "fontWeight": "700",
                    "marginBottom": "0.35rem",
                    "color": "#5f6368",
                },
            ),
            dcc.Markdown(
                str(message.get("content", "")),
                link_target="_blank",
                style={"marginBottom": "-0.8rem"},
            ),
        ]
        if not is_user:
            content.extend(_render_visualizations(message))
            if message_id:
                content.append(_feedback_controls(message_id, ratings.get(message_id)))
        bubbles.append(
            html.Div(
                content,
                style={
                    "maxWidth": "94%" if not is_user else "82%",
                    "marginLeft": "auto" if is_user else "0",
                    "marginRight": "0" if is_user else "auto",
                    "marginBottom": "0.9rem",
                    "padding": "0.85rem 1rem",
                    "borderRadius": "16px",
                    "backgroundColor": GREEN if is_user else "#f1f3f5",
                    "color": "white" if is_user else "#212529",
                    "boxShadow": "0 1px 3px rgba(0,0,0,0.08)",
                },
            )
        )
    return bubbles
