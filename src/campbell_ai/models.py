"""Pydantic models for the Campbell AI internal API."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from src.charts import ALL_CHART_KINDS, CHART_KINDS


class DashboardPrincipal(BaseModel):
    username: str
    role: str
    company_id: str
    allowed_clients: list[str]


class VisualizationArtifact(BaseModel):
    chart_id: str = Field(default_factory=lambda: f"chart_{uuid.uuid4().hex}")
    title: str
    description: str
    dataset: str
    # Validated against the shared vocabulary rather than a duplicated Literal, so
    # adding a chart kind does not require editing three files.
    chart_type: str

    @field_validator("chart_type")
    @classmethod
    def _known_chart_type(cls, value: str) -> str:
        if value not in ALL_CHART_KINDS:
            raise ValueError(
                f"chart_type no soportado: {value!r}. "
                f"Disponibles: {', '.join(ALL_CHART_KINDS)}"
            )
        return value
    figure: dict[str, Any]
    # Inputs needed to recreate the chart without treating the rendered Plotly JSON
    # as the durable source of truth.
    parameters: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)


class ConversationMessage(BaseModel):
    message_id: str = Field(default_factory=lambda: f"msg_{uuid.uuid4().hex}")
    role: Literal["user", "assistant"]
    content: str
    visualizations: list[VisualizationArtifact] = Field(default_factory=list)


class InitializeRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    company_id: str = Field(min_length=1, max_length=80)
    session_id: str | None = Field(default=None, max_length=100)


class MessageRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    company_id: str = Field(min_length=1, max_length=80)
    session_id: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=4000)


class SubmitMessageRequest(MessageRequest):
    """A message to answer in the background.

    `client_message_id` is chosen by the caller and is the idempotency key: resending
    the same one for the same session attaches to the run already in progress instead of
    starting a second one. Optional so an ad-hoc consumer need not care, but the
    dashboard always sends it — it is what stops a refresh or a double click from
    producing two answers to one question.
    """

    client_message_id: str | None = Field(default=None, max_length=100)


class JobStatusRequest(BaseModel):
    job_id: str = Field(min_length=1, max_length=100)


class JobStatusResponse(BaseModel):
    job_id: str
    # queued | running | done | error | cancelled
    status: str
    # Time the answer has been running, so a consumer can decide when to offer the user
    # a way out without having to track the wait itself.
    elapsed_seconds: float = 0.0
    session_id: str | None = None
    result: MessageResponse | None = None
    error: dict[str, Any] | None = None


class SessionRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    company_id: str = Field(min_length=1, max_length=80)
    session_id: str = Field(min_length=1, max_length=100)


class FeedbackRequest(SessionRequest):
    message_id: str = Field(min_length=1, max_length=100)
    rating: Literal["positive", "negative"]
    comment: str | None = Field(default=None, max_length=1000)


class ConversationsRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    company_id: str = Field(min_length=1, max_length=80)
    # Re-read the stored conversations instead of the cached index. What the sidebar's
    # refresh button asks for, and the only way a deletion made directly in the bucket
    # shows up here. Off by default: every page load lists conversations, and that path
    # should stay a single cheap read.
    refresh: bool = False


class InitializeResponse(BaseModel):
    session_id: str
    company_id: str
    username: str
    temporal_context: dict[str, str] = Field(default_factory=dict)
    data_ready: bool
    datasets: dict[str, Any]
    # Which analyses this client's data supports. Surfaced at initialization so a
    # consumer knows the limits before the first question, not after a failure.
    capabilities: dict[str, Any] = Field(default_factory=dict)
    # How many messages were recovered from the durable backup into this session, so a
    # consumer knows to render a thread it did not have in memory.
    restored_messages: int = 0


class MessageResponse(BaseModel):
    response: str
    message_id: str
    session_id: str
    company_id: str
    temporal_context: dict[str, str] = Field(default_factory=dict)
    request_type: str = "agents"
    visualizations: list[VisualizationArtifact] = Field(default_factory=list)
    # Full conversation after the exchange, so a consumer can render the thread without
    # a follow-up history call.
    messages: list[ConversationMessage] = Field(default_factory=list)
    # Traceability of the numeric claims in `response`. Diagnostic metadata for the
    # quality suite and operators; not rendered to the user.
    grounding: dict[str, Any] = Field(default_factory=dict)


class HistoryResponse(BaseModel):
    session_id: str
    company_id: str
    messages: list[ConversationMessage]


class ConversationListResponse(BaseModel):
    company_id: str
    conversations: list[dict[str, Any]] = Field(default_factory=list)


class FeedbackResponse(BaseModel):
    accepted: bool
    message_id: str
    rating: Literal["positive", "negative"]


class SecurityDecision(BaseModel):
    safe: bool
    reason: str = ""
    threat_type: str | None = None


class CapabilitiesResponse(BaseModel):
    profile: str = "campbell_agents"
    agents: list[str]
    reports: bool = False
    visualizations: bool = True
    chart_types: list[str] = Field(default_factory=lambda: list(CHART_KINDS))
    explicit_time_windows: bool = True
    feedback: bool = True
    five_whys: bool = True
    streaming: bool = False
    session_backend: str = "memory"
    named_charts: list[str] = Field(default_factory=list)
    tables: bool = False
    files: bool = False
    # Durable backup and browsable per-user history.
    persistence: bool = False
    conversation_history: bool = False
    # Current admission-control load. Counts only, no identities.
    concurrency: dict[str, Any] = Field(default_factory=dict)
    temporal_context: dict[str, str] = Field(default_factory=dict)
