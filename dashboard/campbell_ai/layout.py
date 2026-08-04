"""Campbell AI Dash layout, adapted from the former Streamlit chat."""

from __future__ import annotations

from dash import dcc, html
import dash_bootstrap_components as dbc

from dashboard.auth import IDENTITY_PROOF_FIELD, current_dashboard_user_data
from src.charts.theme import (
    BRAND_ACCENT,
    BRAND_DARK,
    BRAND_GRID,
    BRAND_MUTED,
    BRAND_TITLE,
)


# Campbell AI reuses the dashboard palette instead of carrying its own accent.
ACCENT = BRAND_ACCENT
ACCENT_SOFT = "rgba(52, 152, 219, 0.08)"
ACCENT_BORDER = "rgba(52, 152, 219, 0.22)"

CAMPBELL_AI_VERSION = "1.0.1"

ALERT_SUGGESTIONS = {
    "weekly-summary": (
        "¿Cuántas alertas se registraron en los últimos 7 días y qué sistemas "
        "concentran más?"
    ),
    "top-equipment": (
        "¿Cuál es el equipo con más alertas durante el último mes?"
    ),
    "equipment-pareto": (
        "Genera un Pareto de alertas por equipo para los últimos 30 días."
    ),
    "equipment-system-heatmap": (
        "Genera un mapa de calor de alertas por equipo y sistema para los últimos 30 días."
    ),
}


def _capability_card(icon: str, title: str, description: str) -> dbc.Col:
    return dbc.Col(
        html.Div(
            [
                html.I(className=f"{icon} mb-3", style={"fontSize": "1.8rem", "color": ACCENT}),
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
                "background": ACCENT_SOFT,
                "border": f"1px solid {ACCENT_BORDER}",
            },
        ),
        width=12,
        md=6,
        className="mb-3",
    )


def _suggested_question_button(question_id: str, question: str) -> dbc.Col:
    return dbc.Col(
        dbc.Button(
            [
                html.I(
                    className="fas fa-arrow-right me-2",
                    style={"color": ACCENT},
                ),
                question,
            ],
            id={
                "type": "campbell-ai-suggested-question",
                "question_id": question_id,
            },
            n_clicks=0,
            color="light",
            className="text-start w-100 h-100",
            title="Enviar esta pregunta",
            style={
                "border": f"1px solid {ACCENT_BORDER}",
                "borderRadius": "10px",
                "background": "white",
                "padding": "0.8rem 0.95rem",
                "fontSize": "0.86rem",
            },
        ),
        width=12,
        lg=6,
    )


def _initial_company_state(user_data: dict | None) -> dict:
    identity = None
    if not isinstance(user_data, dict) or not user_data.get(IDENTITY_PROOF_FIELD):
        user_data = current_dashboard_user_data()
    if isinstance(user_data, dict):
        username = str(user_data.get("username", "")).strip()
        proof = str(user_data.get(IDENTITY_PROOF_FIELD, "")).strip()
        if username and proof:
            identity = {
                "username": username,
                IDENTITY_PROOF_FIELD: proof,
            }
    return {"company_id": None, "identity": identity}


def create_campbell_ai_layout(user_data: dict | None = None) -> html.Div:
    """Build the Campbell AI agent and visualization view."""
    return html.Div(
        [
            dcc.Store(id="campbell-ai-session-store", storage_type="session"),
            dcc.Store(id="campbell-ai-history-store", storage_type="session", data=[]),
            dcc.Store(
                id="campbell-ai-company-store",
                storage_type="memory",
                data=_initial_company_state(user_data),
            ),
            dcc.Store(id="campbell-ai-feedback-store", storage_type="session", data={}),
            dcc.Store(id="campbell-ai-pending-message-store", storage_type="memory", data=None),
            # Streaming plumbing: the browser reads the SSE proxy directly and parks
            # the final payload, which this interval lifts back into a Dash store.
            dcc.Store(id="campbell-ai-stream-store", storage_type="memory", data=None),
            dcc.Interval(
                id="campbell-ai-stream-poll",
                interval=350,
                disabled=True,
                n_intervals=0,
            ),
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
                                                    style={"color": ACCENT},
                                                ),
                                                "Campbell AI",
                                            ],
                                            className="mb-1",
                                            style={"fontWeight": "700", "color": BRAND_DARK},
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
                                "background": ACCENT_SOFT,
                                "border": f"1px solid {ACCENT_BORDER}",
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
                            ],
                            className="g-3",
                        ),
                        html.Div(
                            [
                                html.Div(
                                    [
                                        html.I(
                                            className="fas fa-lightbulb me-2",
                                            style={"color": ACCENT},
                                        ),
                                        html.Span(
                                            "Preguntas sugeridas sobre alertas",
                                            style={"fontWeight": "650"},
                                        ),
                                    ],
                                    className="mb-2",
                                ),
                                dbc.Row(
                                    [
                                        _suggested_question_button(question_id, question)
                                        for question_id, question in ALERT_SUGGESTIONS.items()
                                    ],
                                    className="g-2",
                                ),
                            ],
                            className="mb-4",
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
                                        color=ACCENT,
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
                                                submit_on_enter=True,
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
                                                color="primary",
                                                n_clicks=0,
                                                style={
                                                    "backgroundColor": ACCENT,
                                                    "borderColor": ACCENT,
                                                    "fontWeight": "600",
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
                            f"Campbell AI v{CAMPBELL_AI_VERSION}",
                            className="text-muted text-center mt-3 mb-0",
                            style={"fontSize": "0.75rem"},
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
                        className="mb-0 px-2",
                        style={
                            "fontSize": "0.78rem",
                            "color": BRAND_MUTED,
                            "lineHeight": "1.45",
                        },
                    ),
                ],
                className="mt-3",
                style={
                    "background": "white",
                    "border": f"1px solid {BRAND_GRID}",
                    "borderRadius": "12px",
                    "padding": "0.35rem 0.35rem 0.6rem",
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
                        style={"fontSize": "2rem", "color": ACCENT},
                    ),
                    html.P(
                        "La sesión está lista. Puedes consultar las últimas alertas o solicitar "
                        "un gráfico.",
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
                    "color": "rgba(255,255,255,0.85)" if is_user else BRAND_MUTED,
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
                    "backgroundColor": BRAND_DARK if is_user else "#f6f8fa",
                    "color": "white" if is_user else BRAND_TITLE,
                    "border": "none" if is_user else f"1px solid {BRAND_GRID}",
                    "boxShadow": "0 1px 3px rgba(26,37,47,0.08)",
                },
            )
        )
    if messages and messages[-1].get("pending"):
        bubbles.append(_streaming_placeholder())
    return bubbles


def _streaming_placeholder() -> html.Div:
    """Assistant bubble the stream script writes incoming text into.

    Rendered only while a message is pending. It shows plain text rather than
    Markdown; the canonical Markdown render arrives with the final Dash update.
    """
    return html.Div(
        [
            html.Div(
                "Campbell AI",
                style={
                    "fontSize": "0.75rem",
                    "fontWeight": "700",
                    "marginBottom": "0.35rem",
                    "color": BRAND_MUTED,
                },
            ),
            html.Div(
                id="campbell-ai-stream-placeholder",
                style={"whiteSpace": "pre-wrap", "minHeight": "1.2rem"},
            ),
        ],
        style={
            "maxWidth": "94%",
            "marginRight": "auto",
            "marginBottom": "0.9rem",
            "padding": "0.85rem 1rem",
            "borderRadius": "16px",
            "backgroundColor": "#f6f8fa",
            "color": BRAND_TITLE,
            "border": f"1px solid {BRAND_GRID}",
            "boxShadow": "0 1px 3px rgba(26,37,47,0.08)",
        },
    )
