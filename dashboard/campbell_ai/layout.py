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

# Background of the user's own chat bubble. Change this one value to test other
# colors — it defaults to the sidebar's blue-gray (dashboard/layout.py's left_menu).
USER_BUBBLE_COLOR = "#2290ff"

CAMPBELL_AI_VERSION = "1.2.0"

# Campbell AI typography. Tune these values to adjust normal UI text without
# changing titles or section headers.
CAMPBELL_AI_BODY_FONT_SIZE = "1.2rem"
CAMPBELL_AI_BODY_LINE_HEIGHT = "1.65"
CAMPBELL_AI_AUX_FONT_SIZE = "1.1rem"
CAMPBELL_AI_META_FONT_SIZE = "1.1rem"
CHAT_MESSAGE_FONT_SIZE = CAMPBELL_AI_BODY_FONT_SIZE
CHAT_MESSAGE_LINE_HEIGHT = "1.8"
SUGGESTED_QUESTION_FONT_SIZE = CAMPBELL_AI_BODY_FONT_SIZE
INPUT_FONT_SIZE = CAMPBELL_AI_BODY_FONT_SIZE

# Background-answer polling.
#
# The browser no longer waits inside one long request; it submits the question and asks
# for the result on this cadence. 1.5s is frequent enough that a finished answer appears
# promptly, and cheap enough that five users polling cost far less than five users
# holding connections open.
JOB_POLL_INTERVAL_MS = 1500
# How long an answer may run before the view offers a way out. Most answers land well
# inside this; past it, the user has no way to tell "still working" from "hung", and
# leaving them with a dead composer and no options is the freeze they reported.
SLOW_ANSWER_SECONDS = 20
# Each "seguir esperando" buys another stretch of this length before asking again.
KEEP_WAITING_EXTENSION_SECONDS = 30

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
        "Genera un mapa de calor de alertas por equipo y sistema para los últimos 90 días."
    ),
}


def service_error_content(
    title: str,
    guidance: str = "",
    pending_question: str = "",
) -> list:
    """Alert body for a service failure: what happened, what to do, and a way out.

    A bare error line leaves the user stuck repeating the same failing action. This
    states the cause and whether waiting helps. The retry action itself is a
    permanent, always-mounted button elsewhere in the layout (see
    `_retry_button` and `render_failure`'s style/label outputs) — Dash disables
    an entire callback when one of its plain (non-pattern-matching) Inputs never
    exists in the current layout, and this button is one of synchronize_chat's
    Inputs, so it cannot come and go with the failure state.
    """
    body: list = [
        html.Div(
            [
                html.I(className="fas fa-triangle-exclamation me-2"),
                html.Span(title, style={"fontWeight": "600"}),
            ],
            className="d-flex align-items-center",
        )
    ]
    if guidance:
        body.append(
            html.P(
                guidance,
                className="mb-0 mt-2",
                style={
                    "fontSize": CAMPBELL_AI_AUX_FONT_SIZE,
                    "lineHeight": CAMPBELL_AI_BODY_LINE_HEIGHT,
                },
            )
        )
    if pending_question:
        body.append(
            html.P(
                [
                    html.Span("Tu consulta se conservó: ", className="text-muted"),
                    html.Em(f"“{pending_question[:160]}”"),
                ],
                className="mb-0 mt-2",
                style={"fontSize": CAMPBELL_AI_META_FONT_SIZE},
            )
        )
    return body


def _retry_button() -> dbc.Button:
    """Permanent retry control, hidden until a retryable failure shows it.

    Must always be mounted: it is a plain-id Input of synchronize_chat, and Dash
    disables that whole callback if the id never appears anywhere in the layout.
    """
    return dbc.Button(
        [
            html.I(className="fas fa-rotate-right me-2"),
            html.Span("Reintentar", id="campbell-ai-retry-label"),
        ],
        id="campbell-ai-retry",
        color="danger",
        outline=True,
        size="sm",
        n_clicks=0,
        className="mt-3",
        style={"display": "none"},
    )


def _waiting_panel() -> dbc.Alert:
    """Escape hatch for an answer that is taking a long time.

    Hidden until the wait crosses `SLOW_ANSWER_SECONDS`. Before that it would be noise —
    most answers arrive well inside it. After it, the user needs to know the difference
    between "still working" and "hung", and needs a way out either way. Both controls
    are always mounted for the same reason as `_retry_button`: they are plain-id Inputs,
    and Dash disables an entire callback whose plain Input never exists in the layout.
    """
    return dbc.Alert(
        [
            html.Div(
                [
                    dbc.Spinner(size="sm", color="info", spinner_class_name="me-2"),
                    html.Span(id="campbell-ai-waiting-body", style={"fontWeight": "600"}),
                ],
                className="d-flex align-items-center",
            ),
            html.P(
                "La consulta sigue procesándose en el servidor. Puedes esperar, o "
                "cancelarla y reformularla de forma más acotada.",
                className="mb-0 mt-2",
                style={
                    "fontSize": CAMPBELL_AI_AUX_FONT_SIZE,
                    "lineHeight": CAMPBELL_AI_BODY_LINE_HEIGHT,
                },
            ),
            html.Div(
                [
                    dbc.Button(
                        [
                            html.I(className="fas fa-hourglass-half me-2"),
                            "Seguir esperando",
                        ],
                        id="campbell-ai-keep-waiting",
                        color="info",
                        outline=True,
                        size="sm",
                        n_clicks=0,
                    ),
                    dbc.Button(
                        [html.I(className="fas fa-xmark me-2"), "Cancelar consulta"],
                        id="campbell-ai-cancel-job",
                        color="secondary",
                        outline=True,
                        size="sm",
                        n_clicks=0,
                    ),
                ],
                className="d-flex gap-2 mt-3",
            ),
        ],
        id="campbell-ai-waiting",
        color="info",
        is_open=False,
        className="mt-3 mb-0 campbell-ai-alert",
    )


def unavailable_placeholder(title: str) -> html.Div:
    """Conversation-area state for a dead service, instead of a blank panel."""
    return html.Div(
        [
            html.I(
                className="fas fa-plug-circle-xmark mb-3",
                style={"fontSize": "2rem", "color": BRAND_MUTED},
            ),
            html.P(
                title or "Campbell AI no está disponible",
                className="mb-1",
                style={"fontWeight": "600", "color": BRAND_TITLE},
            ),
            html.P(
                "El resto del dashboard sigue funcionando con normalidad.",
                className="text-muted mb-0",
                style={"fontSize": CAMPBELL_AI_AUX_FONT_SIZE},
            ),
        ],
        className="text-center py-5",
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
                "fontSize": SUGGESTED_QUESTION_FONT_SIZE,
                "lineHeight": CAMPBELL_AI_BODY_LINE_HEIGHT,
            },
        ),
        width=12,
        lg=6,
    )


def _conversation_history_sidebar() -> list:
    """Off-canvas drawer (dbc.Offcanvas) listing the user's previous conversations.

    Slides in from the edge of the screen on demand instead of a card competing
    with the chat for vertical space.
    """
    trigger = dbc.Button(
        [
            html.I(className="fas fa-clock-rotate-left me-2"),
            "Conversaciones anteriores",
        ],
        id="campbell-ai-history-toggle",
        color="light",
        size="sm",
        n_clicks=0,
        className="mb-3",
        style={
            "border": f"1px solid {ACCENT_BORDER}",
            "fontWeight": "600",
            "color": BRAND_TITLE,
        },
    )
    offcanvas = dbc.Offcanvas(
        [
            html.Div(
                [
                    dbc.Button(
                        [html.I(className="fas fa-plus me-2"), "Nueva"],
                        id="campbell-ai-new-conversation",
                        color="link",
                        size="sm",
                        n_clicks=0,
                        className="text-decoration-none",
                        title="Iniciar una conversación nueva",
                    ),
                    dbc.Button(
                        html.I(className="fas fa-rotate-right me-2"),
                        id="campbell-ai-refresh-conversations",
                        color="link",
                        size="sm",
                        n_clicks=0,
                        className="text-muted text-decoration-none",
                        title="Actualizar la lista",
                    ),
                ],
                className="d-flex align-items-center gap-1 mb-3",
            ),
            html.Div(id="campbell-ai-conversation-list"),
        ],
        id="campbell-ai-history-offcanvas",
        title="Conversaciones anteriores",
        is_open=False,
        placement="end",
    )
    return [trigger, offcanvas]


def render_conversation_list(
    conversations: list[dict] | None, active_session_id: str | None = None
) -> list:
    """One row per archived conversation, labelled and dated.

    The label is the AI summary when the backup has one and the first user message
    otherwise, which is what makes a list of sessions recognizable at all — a session id
    tells the user nothing about what they asked.
    """
    items = [item for item in (conversations or []) if isinstance(item, dict)]
    if not items:
        return [
            html.P(
                "Aún no hay conversaciones respaldadas para esta empresa.",
                className="text-muted mb-0",
                style={"fontSize": CAMPBELL_AI_META_FONT_SIZE},
            )
        ]

    rows = []
    for item in items:
        session_id = str(item.get("session_id", ""))
        if not session_id:
            continue
        is_active = bool(active_session_id) and session_id == str(active_session_id)
        rows.append(
            dbc.Button(
                [
                    html.Div(
                        str(item.get("label") or item.get("title") or session_id),
                        style={
                            "fontWeight": "600" if is_active else "500",
                            "fontSize": CAMPBELL_AI_AUX_FONT_SIZE,
                            "whiteSpace": "normal",
                        },
                    ),
                    html.Div(
                        [
                            html.I(
                                className="fas fa-clock me-1",
                                style={"fontSize": "0.68rem"},
                            ),
                            _short_timestamp(str(item.get("updated_at", ""))),
                            html.Span(" · ", className="mx-1"),
                            f"{int(item.get('message_count', 0) or 0)} mensajes",
                            html.Span(
                                " · en curso" if is_active else "",
                                style={"color": ACCENT, "fontWeight": "600"},
                            ),
                        ],
                        className="text-muted mt-1",
                        style={"fontSize": "0.72rem"},
                    ),
                ],
                id={
                    "type": "campbell-ai-open-conversation",
                    "session_id": session_id,
                },
                n_clicks=0,
                color="light",
                className="text-start w-100 mb-2",
                disabled=is_active,
                style={
                    "border": f"1px solid {ACCENT_BORDER if is_active else BRAND_GRID}",
                    "background": ACCENT_SOFT if is_active else "white",
                    "borderRadius": "10px",
                    "padding": "0.6rem 0.75rem",
                },
            )
        )
    return rows


def _short_timestamp(value: str) -> str:
    """Render an ISO timestamp as date and time, without inventing a timezone."""
    text = str(value or "").strip()
    if len(text) < 16 or "T" not in text:
        return text or "sin fecha"
    date_part, time_part = text.split("T", 1)
    return f"{date_part} {time_part[:5]}"


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
            # Which company the stored session belongs to. Kept next to the session id in
            # session storage so returning to this tab can tell a reusable conversation
            # from one that belongs to a company the user is no longer viewing.
            dcc.Store(id="campbell-ai-session-company", storage_type="session"),
            # Archived conversations for the current user and company.
            dcc.Store(id="campbell-ai-conversations-store", storage_type="memory", data=[]),
            dcc.Store(
                id="campbell-ai-company-store",
                storage_type="memory",
                data=_initial_company_state(user_data),
            ),
            dcc.Store(id="campbell-ai-feedback-store", storage_type="session", data={}),
            dcc.Store(id="campbell-ai-pending-message-store", storage_type="memory", data=None),
            # Single source for every failure the view has to explain.
            dcc.Store(id="campbell-ai-failure-store", storage_type="memory", data=None),
            # Streaming plumbing: the browser reads the SSE proxy directly and parks
            # the final payload, which this interval lifts back into a Dash store.
            dcc.Store(id="campbell-ai-stream-store", storage_type="memory", data=None),
            dcc.Interval(
                id="campbell-ai-stream-poll",
                interval=350,
                disabled=True,
                n_intervals=0,
            ),
            # The background answer currently in flight: {job_id, question, ...}.
            #
            # Session storage, deliberately. The answer belongs to the job on the
            # server, not to this page load, so a refresh mid-question must be able to
            # pick the same job back up and collect its result. That is the difference
            # between the old behaviour — reload, and discover the question was answered
            # while the tab sat frozen — and simply resuming.
            dcc.Store(id="campbell-ai-job-store", storage_type="session", data=None),
            dcc.Interval(
                id="campbell-ai-job-poll",
                interval=JOB_POLL_INTERVAL_MS,
                disabled=True,
                n_intervals=0,
            ),
            # When the user last said "seguir esperando", so the panel can hide again
            # and re-appear if the next stretch is also slow.
            dcc.Store(id="campbell-ai-waiting-ack", storage_type="memory", data=0),
            # Dummy clientside-callback target: scrolling the chat to its newest
            # message is a pure DOM side effect with nothing meaningful to store.
            dcc.Store(id="campbell-ai-scroll-trigger", storage_type="memory", data=0),
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
                                            style={
                                                "fontSize": CAMPBELL_AI_AUX_FONT_SIZE,
                                                "lineHeight": CAMPBELL_AI_BODY_LINE_HEIGHT,
                                            },
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
                            [html.Div(id="campbell-ai-error-body"), _retry_button()],
                            id="campbell-ai-error",
                            color="danger",
                            is_open=False,
                            dismissable=True,
                            className="mt-3 mb-0 campbell-ai-alert",
                        ),
                        _waiting_panel(),
                        *_conversation_history_sidebar(),
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
                                            [
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
                                                    # Lives inside the same scrolling area as the
                                                    # messages below, so it scrolls out of view as
                                                    # the conversation grows instead of pinning a
                                                    # fixed block above the chat.
                                                    className="mb-3",
                                                ),
                                                html.Div(id="campbell-ai-messages"),
                                            ],
                                            id="campbell-ai-scroll-container",
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
                                                    "fontSize": INPUT_FONT_SIZE,
                                                    "lineHeight": CAMPBELL_AI_BODY_LINE_HEIGHT,
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
                                                    "fontSize": INPUT_FONT_SIZE,
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
        description = str(artifact.get("description", ""))
        # The backend archive downsamples each trace's point count once a
        # conversation is persisted (see persistence.py's _downsample_figure) but
        # keeps a real, interactive figure — so this stays the only branch needed.
        # A figure can still arrive genuinely empty from an older archive entry
        # written before that change (or any other legitimate failure upstream);
        # say so plainly instead of rendering an empty box.
        if not figure.get("data"):
            charts.append(
                html.Div(
                    [
                        html.I(
                            className="fas fa-chart-simple me-2",
                            style={"color": BRAND_MUTED},
                        ),
                        html.Span(
                            "El gráfico de este mensaje no se conservó al archivar la "
                            "conversación. Vuelve a pedirlo si lo necesitas.",
                            style={
                                "fontSize": CAMPBELL_AI_AUX_FONT_SIZE,
                                "color": BRAND_MUTED,
                                "lineHeight": CAMPBELL_AI_BODY_LINE_HEIGHT,
                            },
                        ),
                    ],
                    className="mt-3 d-flex align-items-center",
                    style={
                        "background": "#f6f8fa",
                        "border": f"1px solid {BRAND_GRID}",
                        "borderRadius": "12px",
                        "padding": "0.75rem 1rem",
                    },
                )
            )
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
                        description,
                        className="mb-0 px-2",
                        style={
                            "fontSize": CAMPBELL_AI_META_FONT_SIZE,
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


def _feedback_entry(entry) -> tuple[str | None, bool]:
    """Read a stored feedback entry, tolerating the older rating-only shape."""
    if isinstance(entry, dict):
        rating = str(entry.get("rating") or "").strip() or None
        return rating, bool(entry.get("comment"))
    rating = str(entry or "").strip() or None
    return rating, False


def _feedback_comment_box(message_id: str, rating: str, submitted: bool) -> html.Div:
    """Ask for the reason behind a vote, once a vote exists.

    Shown only after voting: asking why before knowing whether the answer helped is a
    question with no context, and an always-visible text box on every response reads as
    an obligation rather than an invitation.
    """
    if submitted:
        return html.Div(
            [
                html.I(className="fas fa-check me-2", style={"color": ACCENT}),
                "Gracias, registramos tu comentario.",
            ],
            className="text-muted mt-2",
            style={"fontSize": CAMPBELL_AI_META_FONT_SIZE},
        )
    prompt = (
        "¿Qué faltó o qué estuvo mal? (opcional)"
        if rating == "negative"
        else "¿Qué te resultó útil? (opcional)"
    )
    return html.Div(
        [
            dbc.Textarea(
                id={"type": "campbell-ai-feedback-comment", "message_id": message_id},
                placeholder=prompt,
                rows=2,
                maxLength=1000,
                style={
                    "fontSize": CAMPBELL_AI_AUX_FONT_SIZE,
                    "resize": "none",
                    "borderRadius": "10px",
                    "lineHeight": CAMPBELL_AI_BODY_LINE_HEIGHT,
                },
            ),
            dbc.Button(
                [html.I(className="fas fa-paper-plane me-2"), "Enviar comentario"],
                id={
                    "type": "campbell-ai-feedback-comment-send",
                    "message_id": message_id,
                },
                n_clicks=0,
                size="sm",
                color="light",
                className="mt-2",
                style={
                    "border": f"1px solid {ACCENT_BORDER}",
                    "fontSize": CAMPBELL_AI_META_FONT_SIZE,
                    "fontWeight": "600",
                },
            ),
        ],
        className="mt-2",
        style={"maxWidth": "420px"},
    )


def _feedback_controls(message_id: str, entry=None) -> html.Div:
    selected, comment_submitted = _feedback_entry(entry)
    disabled = selected in {"positive", "negative"}
    controls = html.Div(
        [
            html.Span(
                "¿Te sirvió esta respuesta?",
                className="text-muted me-2",
                style={"fontSize": CAMPBELL_AI_META_FONT_SIZE},
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
    if not disabled:
        return controls
    return html.Div(
        [controls, _feedback_comment_box(message_id, selected or "", comment_submitted)]
    )


def render_chat_history(
    messages: list[dict] | None, feedback: dict | None = None
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
                style={
                    "fontSize": CAMPBELL_AI_BODY_FONT_SIZE,
                    "lineHeight": CAMPBELL_AI_BODY_LINE_HEIGHT,
                },
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
                style={
                    "fontSize": CHAT_MESSAGE_FONT_SIZE,
                    "lineHeight": CHAT_MESSAGE_LINE_HEIGHT,
                    "marginBottom": "-0.8rem",
                },
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
                    "backgroundColor": USER_BUBBLE_COLOR if is_user else "#f6f8fa",
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
    """Assistant bubble shown while a message is pending, inside the chat window.

    `campbell_ai_stream.js`'s setPlaceholderText() does `node.textContent = ...`,
    which replaces whatever is here — including this default spinner — the
    moment real streamed text (or a status update) arrives. When streaming is
    disabled (or the request hasn't reached the backend yet), nothing ever calls
    that function, so without a visible default here the bubble rendered but
    stayed empty: present in the DOM, but indistinguishable from nothing to the
    user. The spinner/label below is what fills that gap.
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
                [
                    html.I(
                        className="fas fa-circle-notch fa-spin me-2",
                        style={"color": ACCENT},
                    ),
                    html.Span("Pensando…"),
                ],
                id="campbell-ai-stream-placeholder",
                style={
                    "whiteSpace": "pre-wrap",
                    "minHeight": "1.2rem",
                    "color": BRAND_MUTED,
                    "fontSize": CHAT_MESSAGE_FONT_SIZE,
                    "lineHeight": CHAT_MESSAGE_LINE_HEIGHT,
                },
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
