"""Pydantic models for the Campbell AI internal API."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


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
    chart_type: Literal["bar", "line", "pie", "pareto", "heatmap", "stacked_bar"]
    figure: dict[str, Any]
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


class SessionRequest(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    company_id: str = Field(min_length=1, max_length=80)
    session_id: str = Field(min_length=1, max_length=100)


class FeedbackRequest(SessionRequest):
    message_id: str = Field(min_length=1, max_length=100)
    rating: Literal["positive", "negative"]
    comment: str | None = Field(default=None, max_length=1000)


class InitializeResponse(BaseModel):
    session_id: str
    company_id: str
    username: str
    data_ready: bool
    datasets: dict[str, Any]


class MessageResponse(BaseModel):
    response: str
    message_id: str
    session_id: str
    company_id: str
    request_type: str = "agents"
    visualizations: list[VisualizationArtifact] = Field(default_factory=list)


class HistoryResponse(BaseModel):
    session_id: str
    company_id: str
    messages: list[ConversationMessage]


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
    chart_types: list[str] = Field(
        default_factory=lambda: [
            "bar",
            "line",
            "pie",
            "pareto",
            "heatmap",
            "stacked_bar",
        ]
    )
    explicit_time_windows: bool = True
    feedback: bool = True
    five_whys: bool = True
    tables: bool = False
    files: bool = False
