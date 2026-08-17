"""Contract and internal-authentication tests for the Campbell AI FastAPI API."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from src.campbell_ai import progress
from src.campbell_ai.api import app
from src.campbell_ai.config import reset_campbell_settings
from src.campbell_ai.errors import CampbellConfigurationError
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

    async def stream_message(self, username, company_id, session_id, message):
        yield {"type": "status", "stage": "analyzing"}
        yield {"type": "delta", "text": f"Respuesta para {message}"}
        yield {
            "type": "done",
            "response": f"Respuesta para {message}",
            "request_type": "agents",
            "message_id": "msg_test",
            "visualizations": [],
            "session_id": session_id,
            "company_id": company_id.lower(),
            "messages": [],
        }

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

    identity = {"username": "user", "company_id": "CDA"}

    assert client.post(
        "/api/v1/campbell-ai/initialize", json=identity
    ).status_code == 401
    # Same trust boundary, including the cheap side channels. A progress endpoint that
    # answered without the token would tell an unauthenticated caller which companies are
    # in use and when someone is working.
    assert client.post(
        "/api/v1/campbell-ai/initialize/progress", json=identity
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
    assert capabilities.json()["temporal_context"]["today"]
    assert capabilities.json()["temporal_context"]["timezone"] == "America/Santiago"
    # The catalogue and session backend are declared so a deployment can assert them.
    assert "telemetry_fleet_status" in capabilities.json()["named_charts"]
    assert capabilities.json()["session_backend"] in {"memory", "redis"}
    assert sent.status_code == 200
    assert sent.json()["request_type"] == "agents"
    assert history.status_code == 200
    assert feedback.status_code == 200
    assert feedback.json()["accepted"] is True
    assert cleared.status_code == 200


def test_api_streams_events_and_ends_with_done(monkeypatch):
    """Streaming must emit SSE frames and finish with a `done` payload."""
    monkeypatch.setenv("CAMPBELL_AI_INTERNAL_TOKEN", "secret-token")
    reset_campbell_settings()
    app.state.service = FakeService()
    client = TestClient(app)

    response = client.post(
        "/api/v1/campbell-ai/message/stream",
        headers={"X-Campbell-Token": "secret-token"},
        json={
            "username": "user",
            "company_id": "CDA",
            "session_id": "campbell_test",
            "message": "Estado del equipo",
        },
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = [
        json.loads(block.split("data:", 1)[1].strip())
        for block in response.text.split("\n\n")
        if "data:" in block
    ]
    assert [event["type"] for event in events] == ["status", "delta", "done"]
    final = events[-1]
    assert final["response"] == "Respuesta para Estado del equipo"
    # The final event carries history so a consumer needs no follow-up call.
    assert final["messages"] == []
    assert final["session_id"] == "campbell_test"


def test_api_reports_a_configuration_error_before_streaming_starts(monkeypatch):
    """A failure raised before the first event must be a real HTTP status."""
    monkeypatch.setenv("CAMPBELL_AI_INTERNAL_TOKEN", "secret-token")
    reset_campbell_settings()

    class DisabledStreamService(FakeService):
        async def stream_message(self, *args, **kwargs):
            raise CampbellConfigurationError("El streaming de Campbell AI está deshabilitado")
            yield  # pragma: no cover - makes this an async generator

    app.state.service = DisabledStreamService()
    client = TestClient(app)

    response = client.post(
        "/api/v1/campbell-ai/message/stream",
        headers={"X-Campbell-Token": "secret-token"},
        json={
            "username": "user",
            "company_id": "CDA",
            "session_id": "campbell_test",
            "message": "Estado del equipo",
        },
    )

    assert response.status_code == 503
    assert "streaming" in response.json()["detail"].lower()


def test_progress_endpoint_reports_the_phase_of_a_call_in_flight(monkeypatch):
    """The badge's source of truth: what is running right now, for this user.

    Written against the registry rather than against a real initialization on purpose -
    the property under test is that a *second, concurrent* request can read the phase the
    first one is in, and a test that waited for the first to finish would prove the
    opposite of what it claims.
    """
    monkeypatch.setenv("CAMPBELL_AI_INTERNAL_TOKEN", "secret-token")
    reset_campbell_settings()
    app.state.service = FakeService()
    client = TestClient(app)
    headers = {"X-Campbell-Token": "secret-token"}
    body = {"username": "User", "company_id": "CDA"}

    progress.reset()
    # Nothing in flight: not an error, and no phase invented to fill the gap.
    idle = client.post(
        "/api/v1/campbell-ai/initialize/progress", headers=headers, json=body
    )
    assert idle.status_code == 200
    assert idle.json()["active"] is False
    assert idle.json()["label"] == ""

    # The same identity the poll uses, in the casing the API normalizes to.
    key = progress.progress_key("user", "cda")
    progress.begin(key, resuming=True)
    progress.advance(key, "rehydrate")

    running = client.post(
        "/api/v1/campbell-ai/initialize/progress", headers=headers, json=body
    ).json()
    assert running["active"] is True
    assert running["phase"] == "rehydrate"
    # The badge shows this string, so it is part of the contract, not a debug field.
    assert running["label"] == progress.PHASE_LABELS["rehydrate"]
    assert running["resuming"] is True

    progress.finish(key)
    assert (
        client.post(
            "/api/v1/campbell-ai/initialize/progress", headers=headers, json=body
        ).json()["active"]
        is False
    )
