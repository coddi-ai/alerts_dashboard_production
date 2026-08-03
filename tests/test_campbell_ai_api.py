"""Contract and internal-authentication tests for the Campbell AI FastAPI API."""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.campbell_ai.api import app
from src.campbell_ai.config import reset_campbell_settings
from src.campbell_ai.models import (
    FeedbackResponse,
    HistoryResponse,
    InitializeResponse,
    MessageResponse,
)


class FakeService:
    async def initialize(self, username, company_id, session_id=None):
        return InitializeResponse(
            session_id=session_id or "campbell_test",
            company_id=company_id.lower(),
            username=username,
            data_ready=True,
            datasets={"data_ready": True},
        )

    async def send_message(self, username, company_id, session_id, message):
        return MessageResponse(
            response=f"Respuesta para {message}",
            message_id="msg_test",
            session_id=session_id,
            company_id=company_id.lower(),
        )

    async def history(self, username, company_id, session_id):
        return HistoryResponse(
            session_id=session_id,
            company_id=company_id.lower(),
            messages=[],
        )

    async def clear(self, username, company_id, session_id):
        return None

    async def submit_feedback(
        self, username, company_id, session_id, message_id, rating, comment=None
    ):
        return FeedbackResponse(
            accepted=True,
            message_id=message_id,
            rating=rating,
        )


def test_api_requires_internal_token(monkeypatch):
    monkeypatch.setenv("CAMPBELL_AI_INTERNAL_TOKEN", "secret-token")
    reset_campbell_settings()
    app.state.service = FakeService()
    client = TestClient(app)

    assert client.post(
        "/api/v1/campbell-ai/initialize",
        json={"username": "user", "company_id": "CDA"},
    ).status_code == 401


def test_api_initialize_message_history_and_clear(monkeypatch):
    monkeypatch.setenv("CAMPBELL_AI_INTERNAL_TOKEN", "secret-token")
    reset_campbell_settings()
    app.state.service = FakeService()
    client = TestClient(app)
    headers = {"X-Campbell-Token": "secret-token"}

    capabilities = client.get(
        "/api/v1/campbell-ai/capabilities", headers=headers
    )

    initialized = client.post(
        "/api/v1/campbell-ai/initialize",
        headers=headers,
        json={"username": "user", "company_id": "CDA"},
    )
    session_id = initialized.json()["session_id"]
    sent = client.post(
        "/api/v1/campbell-ai/message",
        headers=headers,
        json={
            "username": "user",
            "company_id": "CDA",
            "session_id": session_id,
            "message": "Estado del equipo",
        },
    )
    history = client.post(
        "/api/v1/campbell-ai/history",
        headers=headers,
        json={"username": "user", "company_id": "CDA", "session_id": session_id},
    )
    feedback = client.post(
        "/api/v1/campbell-ai/feedback",
        headers=headers,
        json={
            "username": "user",
            "company_id": "CDA",
            "session_id": session_id,
            "message_id": sent.json()["message_id"],
            "rating": "positive",
        },
    )
    cleared = client.request(
        "DELETE",
        "/api/v1/campbell-ai/clear",
        headers=headers,
        json={"username": "user", "company_id": "CDA", "session_id": session_id},
    )

    assert initialized.status_code == 200
    assert capabilities.status_code == 200
    assert "pareto" in capabilities.json()["chart_types"]
    assert "heatmap" in capabilities.json()["chart_types"]
    assert capabilities.json()["explicit_time_windows"] is True
    assert sent.status_code == 200
    assert sent.json()["request_type"] == "agents"
    assert history.status_code == 200
    assert feedback.status_code == 200
    assert feedback.json()["accepted"] is True
    assert cleared.status_code == 200
