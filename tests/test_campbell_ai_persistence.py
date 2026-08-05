"""Tests for durable conversation and feedback backup.

The session store expires conversations and lives in one process. These tests cover what
has to remain true anyway: an interaction is on durable storage before the answer is
delivered, a user's folder is unreachable from another user's session, a storage outage
degrades instead of failing the chat, and a thread can be listed and reopened after the
live session is gone.
"""

from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from src.campbell_ai.api import app
from src.campbell_ai.config import reset_campbell_settings
from src.campbell_ai.feedback import FeedbackStore
from src.campbell_ai.models import (
    ConversationMessage,
    DashboardPrincipal,
    HistoryResponse,
    VisualizationArtifact,
)
from src.campbell_ai.persistence import (
    ArchiveBackend,
    ConversationArchive,
    LocalArchiveBackend,
    build_conversation_archive,
    conversation_title,
    normalize_prefix,
    normalize_segment,
)
from src.campbell_ai.summary import sanitize_summary


PRINCIPAL = DashboardPrincipal(
    username="ana.perez", role="analyst", company_id="cda", allowed_clients=["cda"]
)
OTHER = DashboardPrincipal(
    username="bruno.diaz", role="analyst", company_id="cda", allowed_clients=["cda"]
)


class MemoryBackend(ArchiveBackend):
    """Records every write so tests can assert on keys, not on side effects."""

    def __init__(self, name: str = "memory", fail_on: str = ""):
        self._name = name
        self.objects: dict[str, dict] = {}
        self.writes: list[str] = []
        self.fail_on = fail_on

    @property
    def name(self) -> str:
        return self._name

    def put_json(self, key, payload):
        if self.fail_on and self.fail_on in key:
            raise RuntimeError("almacenamiento no disponible")
        self.objects[key] = json.loads(json.dumps(payload))
        self.writes.append(key)

    def get_json(self, key):
        return self.objects.get(key)

    def list_keys(self, prefix):
        return [key for key in self.objects if key.startswith(prefix)]


def _exchange(question: str, answer: str) -> list[ConversationMessage]:
    return [
        ConversationMessage(role="user", content=question),
        ConversationMessage(role="assistant", content=answer),
    ]


# ------------------------------------------------------------------ key layout


def test_keys_live_under_one_owned_folder_per_user_and_company():
    archive = ConversationArchive([MemoryBackend()])

    key = archive.conversation_key(PRINCIPAL, "campbell_abc")

    assert key == "campbellAI/conversations/cda/ana.perez/campbell_abc/conversation.json"
    assert archive.index_key(PRINCIPAL).startswith("campbellAI/conversations/cda/ana.perez/")


def test_key_segments_cannot_escape_the_prefix():
    """Identity is trusted, but a traversal attempt must not produce a reachable key."""
    hostile = DashboardPrincipal(
        username="../../root", role="analyst", company_id="cda", allowed_clients=["cda"]
    )
    archive = ConversationArchive([MemoryBackend()])

    key = archive.conversation_key(hostile, "../secret")

    assert ".." not in key
    assert key.startswith("campbellAI/conversations/cda/")


def test_prefix_normalization_keeps_boundaries_and_rejects_empties():
    assert normalize_prefix("campbellAI") == "campbellAI"
    assert normalize_prefix("/campbellAI/logs/") == "campbellAI/logs"
    assert normalize_prefix("") == "campbellAI"
    assert normalize_segment("  ", "anonimo") == "anonimo"


# ------------------------------------------------------------------- batching


def test_each_interaction_writes_a_batch_and_the_snapshot():
    backend = MemoryBackend()
    archive = ConversationArchive([backend])
    messages = _exchange("¿Cuántas alertas hay?", "Se registraron alertas.")

    first = archive.save_exchange(PRINCIPAL, "s1", messages)

    assert first.ok
    assert first.new_messages == 2
    # The batch is named by message count, so a retry overwrites instead of duplicating.
    assert first.batch_key.endswith("/batches/00002.json")
    snapshot = backend.objects[archive.conversation_key(PRINCIPAL, "s1")]
    assert len(snapshot["conversation"]) == 2

    messages += _exchange("¿Y en el motor?", "El motor tiene alertas.")
    second = archive.save_exchange(PRINCIPAL, "s1", messages)

    # Only the new pair is written again; the first exchange is not resent.
    assert second.new_messages == 2
    assert second.batch_key.endswith("/batches/00004.json")
    batch = backend.objects[second.batch_key]
    assert [item["content"] for item in batch["messages"]] == [
        "¿Y en el motor?",
        "El motor tiene alertas.",
    ]
    assert batch["from_message"] == 3


def test_replaying_the_same_messages_writes_no_new_batch():
    backend = MemoryBackend()
    archive = ConversationArchive([backend])
    messages = _exchange("hola", "respuesta")

    archive.save_exchange(PRINCIPAL, "s1", messages)
    repeated = archive.save_exchange(PRINCIPAL, "s1", messages)

    assert repeated.new_messages == 0
    assert repeated.batch_key == ""
    assert len([key for key in backend.writes if "/batches/" in key]) == 1


def test_snapshot_keeps_messages_the_live_session_already_trimmed():
    """The session store keeps a tail; the backup has to keep the whole thread."""
    backend = MemoryBackend()
    archive = ConversationArchive([backend])

    first = _exchange("pregunta uno", "respuesta uno")
    archive.save_exchange(PRINCIPAL, "s1", first)
    # A trimmed window: the first exchange is gone from the live conversation.
    trimmed = _exchange("pregunta dos", "respuesta dos")
    archive.save_exchange(PRINCIPAL, "s1", trimmed)

    stored = backend.objects[archive.conversation_key(PRINCIPAL, "s1")]["conversation"]
    assert [item["content"] for item in stored] == [
        "pregunta uno",
        "respuesta uno",
        "pregunta dos",
        "respuesta dos",
    ]


def test_figures_are_not_copied_into_the_backup():
    """A stored Plotly figure would dominate the archive and is reproducible."""
    backend = MemoryBackend()
    archive = ConversationArchive([backend])
    messages = _exchange("grafica alertas", "Aquí está el gráfico.")
    messages[1] = ConversationMessage(
        role="assistant",
        content="Aquí está el gráfico.",
        visualizations=[
            VisualizationArtifact(
                title="Alertas por equipo",
                description="Conteo por equipo",
                dataset="alerts",
                chart_type="bar",
                figure={"data": [{"y": list(range(500))}], "layout": {}},
            )
        ],
    )

    archive.save_exchange(PRINCIPAL, "s1", messages)

    stored = backend.objects[archive.conversation_key(PRINCIPAL, "s1")]["conversation"]
    artifact = stored[1]["visualizations"][0]
    assert artifact["figure"] == {}
    # Identity and caption survive, so the answer still reads correctly.
    assert artifact["title"] == "Alertas por equipo"


# ------------------------------------------------------------- listing, titles


def test_the_index_labels_a_conversation_by_its_first_message():
    backend = MemoryBackend()
    archive = ConversationArchive([backend])
    archive.save_exchange(
        PRINCIPAL, "s1", _exchange("¿Cuántas alertas de refrigerante hubo?", "Cinco.")
    )

    rows = archive.list_conversations(PRINCIPAL)

    assert len(rows) == 1
    assert rows[0].session_id == "s1"
    assert rows[0].title == "¿Cuántas alertas de refrigerante hubo?"
    # With no AI summary the label falls back to the title, never to the session id.
    assert rows[0].label == rows[0].title
    assert rows[0].message_count == 2


def test_an_ai_summary_replaces_the_label_without_losing_the_title():
    archive = ConversationArchive([MemoryBackend()])
    archive.save_exchange(PRINCIPAL, "s1", _exchange("hola, una duda", "Dime."))

    archive.set_summary(PRINCIPAL, "s1", "Causa raíz de alerta de refrigerante")

    row = archive.list_conversations(PRINCIPAL)[0]
    assert row.label == "Causa raíz de alerta de refrigerante"
    assert row.title == "hola, una duda"
    assert archive.has_summary(PRINCIPAL, "s1") is True


def test_long_first_messages_are_truncated_for_the_sidebar():
    title = conversation_title(_exchange("palabra " * 60, "respuesta"))

    assert len(title) <= 90
    assert title.endswith("…")


def test_the_listing_is_newest_first_and_scoped_to_the_active_company():
    backend = MemoryBackend()
    archive = ConversationArchive([backend])
    other_company = DashboardPrincipal(
        username="ana.perez", role="analyst", company_id="emin", allowed_clients=["emin"]
    )

    archive.save_exchange(PRINCIPAL, "s1", _exchange("primera", "respuesta"))
    archive.save_exchange(PRINCIPAL, "s2", _exchange("segunda", "respuesta"))
    archive.save_exchange(other_company, "s3", _exchange("otra empresa", "respuesta"))

    sessions = [row.session_id for row in archive.list_conversations(PRINCIPAL)]

    assert sessions == ["s2", "s1"]
    assert [row.session_id for row in archive.list_conversations(other_company)] == ["s3"]


def test_a_lost_index_is_rebuilt_from_the_stored_conversations():
    """The index is a cache of the objects; losing it must not lose the history."""
    backend = MemoryBackend()
    archive = ConversationArchive([backend])
    archive.save_exchange(PRINCIPAL, "s1", _exchange("pregunta", "respuesta"))
    backend.objects.pop(archive.index_key(PRINCIPAL))

    rows = archive.list_conversations(PRINCIPAL)

    assert [row.session_id for row in rows] == ["s1"]
    assert rows[0].message_count == 2


# -------------------------------------------------------------- isolation, IO


def test_a_user_cannot_read_another_users_conversation():
    backend = MemoryBackend()
    archive = ConversationArchive([backend])
    archive.save_exchange(PRINCIPAL, "s1", _exchange("dato confidencial", "respuesta"))

    # Same session id, different authenticated user: keys are derived from the principal.
    assert archive.load_conversation(OTHER, "s1") == []
    assert archive.list_conversations(OTHER) == []


def test_a_conversation_can_be_restored_after_the_session_is_gone():
    backend = MemoryBackend()
    archive = ConversationArchive([backend])
    archive.save_exchange(PRINCIPAL, "s1", _exchange("¿Estado del motor?", "Normal."))

    # A fresh archive stands in for a restarted process with empty caches.
    restored = ConversationArchive([backend]).load_conversation(PRINCIPAL, "s1")

    assert [message.content for message in restored] == ["¿Estado del motor?", "Normal."]
    assert [message.role for message in restored] == ["user", "assistant"]


def test_a_failing_backend_does_not_lose_the_conversation():
    """S3 down must degrade to the local mirror, not break the chat."""
    broken = MemoryBackend("s3", fail_on="conversation.json")
    mirror = MemoryBackend("local")
    archive = ConversationArchive([broken, mirror])

    result = archive.save_exchange(PRINCIPAL, "s1", _exchange("pregunta", "respuesta"))

    assert result.ok
    assert result.failed == ["s3"]
    assert "local" in result.written
    assert archive.conversation_key(PRINCIPAL, "s1") in mirror.objects


def test_an_archive_with_no_backends_is_inert():
    archive = ConversationArchive([])

    assert archive.enabled is False
    assert archive.save_exchange(PRINCIPAL, "s1", _exchange("a", "b")).ok is False
    assert archive.list_conversations(PRINCIPAL) == []


def test_the_local_mirror_writes_readable_files(tmp_path):
    archive = ConversationArchive([LocalArchiveBackend(tmp_path)])

    archive.save_exchange(PRINCIPAL, "s1", _exchange("pregunta", "respuesta"))

    stored = tmp_path / "campbellAI" / "conversations" / "cda" / "ana.perez" / "s1"
    document = json.loads((stored / "conversation.json").read_text(encoding="utf-8"))
    assert document["username"] == "ana.perez"
    assert len(list((stored / "batches").glob("*.json"))) == 1


def test_persistence_can_be_switched_off_by_configuration():
    class Settings:
        persistence_enabled = False

    assert build_conversation_archive(Settings()).enabled is False


# --------------------------------------------------------------------- feedback


def test_rating_and_comment_are_two_events_and_both_reach_the_backup(tmp_path):
    """A user who votes first and explains later must not lose the explanation."""
    backend = MemoryBackend()
    archive = ConversationArchive([backend])
    store = FeedbackStore(tmp_path / "feedback.jsonl", archive=archive)

    assert store.record(PRINCIPAL, "s1", "msg_1", "negative") is True
    assert store.record(PRINCIPAL, "s1", "msg_1", "negative") is False
    assert store.record(PRINCIPAL, "s1", "msg_1", "negative", "faltó el periodo") is True

    lines = [
        json.loads(line)
        for line in (tmp_path / "feedback.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [item["kind"] for item in lines] == ["rating", "comment"]
    assert lines[1]["comment"] == "faltó el periodo"

    keys = [key for key in backend.objects if "/logs/feedback/" in key]
    assert len(keys) == 2
    assert all(key.startswith("campbellAI/logs/feedback/cda/ana.perez/") for key in keys)


def test_the_feedback_log_never_copies_the_conversation(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.jsonl")
    store.record(PRINCIPAL, "s1", "msg_1", "positive", "muy claro")

    payload = json.loads((tmp_path / "feedback.jsonl").read_text(encoding="utf-8"))

    assert set(payload) == {
        "timestamp",
        "username",
        "company_id",
        "session_id",
        "message_id",
        "kind",
        "rating",
        "comment",
    }


def test_feedback_survives_a_backup_outage(tmp_path):
    class Exploding:
        def save_feedback(self, *_args, **_kwargs):
            raise RuntimeError("sin conexión")

    store = FeedbackStore(tmp_path / "feedback.jsonl", archive=Exploding())

    assert store.record(PRINCIPAL, "s1", "msg_1", "positive") is True
    assert (tmp_path / "feedback.jsonl").exists()


# -------------------------------------------------------------- summary safety


def test_a_summary_that_invents_a_figure_is_discarded():
    """The grounding rule applies to labels too, and a title is not worth verifying."""
    transcript = "Usuario: ¿Cuántas alertas hubo?\nAsistente: Se registraron 5 alertas."

    assert sanitize_summary("Cinco alertas de refrigerante", transcript)
    assert sanitize_summary("Resumen de 12 alertas críticas", transcript) == ""
    assert sanitize_summary("5 alertas en el periodo", transcript) == "5 alertas en el periodo"


def test_a_summary_is_trimmed_and_stripped_of_decoration():
    transcript = "Usuario: hola"

    assert sanitize_summary('"Título: consulta de alertas"', transcript) == (
        "consulta de alertas"
    )
    assert len(sanitize_summary(" ".join(["palabra"] * 20), transcript).split()) == 8


# ----------------------------------------------------------------- API surface


class FakeConversationService:
    def __init__(self):
        self.opened: list[str] = []

    async def conversations(self, username, company_id):
        from src.campbell_ai.models import ConversationListResponse

        return ConversationListResponse(
            company_id=company_id.lower(),
            conversations=[
                {
                    "session_id": "s1",
                    "company_id": company_id.lower(),
                    "title": "¿Cuántas alertas hubo?",
                    "label": "¿Cuántas alertas hubo?",
                    "message_count": 2,
                    "updated_at": "2026-08-01T10:00:00+00:00",
                }
            ],
        )

    async def open_conversation(self, username, company_id, session_id):
        self.opened.append(session_id)
        return HistoryResponse(
            session_id=session_id,
            company_id=company_id.lower(),
            messages=[ConversationMessage(role="user", content="¿Cuántas alertas hubo?")],
        )


def test_the_api_lists_and_reopens_archived_conversations(monkeypatch):
    monkeypatch.setenv("CAMPBELL_AI_INTERNAL_TOKEN", "secret-token")
    reset_campbell_settings()
    service = FakeConversationService()
    app.state.service = service
    client = TestClient(app)
    headers = {"X-Campbell-Token": "secret-token"}

    listed = client.post(
        "/api/v1/campbell-ai/conversations",
        headers=headers,
        json={"username": "ana.perez", "company_id": "CDA"},
    )
    opened = client.post(
        "/api/v1/campbell-ai/conversations/open",
        headers=headers,
        json={"username": "ana.perez", "company_id": "CDA", "session_id": "s1"},
    )

    assert listed.status_code == 200
    assert listed.json()["conversations"][0]["label"] == "¿Cuántas alertas hubo?"
    assert opened.status_code == 200
    assert opened.json()["messages"][0]["content"] == "¿Cuántas alertas hubo?"
    assert service.opened == ["s1"]


def test_conversation_endpoints_require_the_internal_token(monkeypatch):
    monkeypatch.setenv("CAMPBELL_AI_INTERNAL_TOKEN", "secret-token")
    reset_campbell_settings()
    app.state.service = FakeConversationService()
    client = TestClient(app)

    assert client.post(
        "/api/v1/campbell-ai/conversations",
        json={"username": "ana.perez", "company_id": "CDA"},
    ).status_code == 401


# ------------------------------------------------------------ dashboard client


def test_the_dashboard_client_calls_the_conversation_endpoints(monkeypatch):
    """The view must not invent paths or forget to send the internal token."""
    import dashboard.campbell_ai.client as module

    calls: list[tuple[str, str, dict, dict]] = []

    class _Response:
        def __init__(self, payload):
            self._payload = payload

        def read(self):
            return json.dumps(self._payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(request, timeout=None):
        calls.append(
            (
                request.full_url,
                request.method,
                dict(request.headers),
                json.loads(request.data.decode()) if request.data else {},
            )
        )
        return _Response({"conversations": [], "messages": [], "session_id": "s1"})

    monkeypatch.setattr(module, "urlopen", fake_urlopen)
    client = module.CampbellAPIClient(base_url="http://api", internal_token="token")

    client.list_conversations("ana.perez", "cda")
    client.open_conversation("ana.perez", "cda", "s1")

    assert [call[0] for call in calls] == [
        "http://api/api/v1/campbell-ai/conversations",
        "http://api/api/v1/campbell-ai/conversations/open",
    ]
    assert all(call[1] == "POST" for call in calls)
    assert all(call[2].get("X-campbell-token") == "token" for call in calls)
    # Identity travels in the body and the session id only on the open call.
    assert calls[0][3] == {"username": "ana.perez", "company_id": "cda"}
    assert calls[1][3]["session_id"] == "s1"


# ------------------------------------------------------- runtime integration


def test_the_runtime_archives_every_exchange_and_can_restore_it(tmp_path):
    from src.campbell_ai.agents_runtime import CampbellAgentRuntime
    from src.campbell_ai.data import DashboardDataRepository
    from src.campbell_ai.sessions import InMemorySessionStore
    from tests.test_campbell_ai import _settings

    backend = MemoryBackend()
    archive = ConversationArchive([backend])
    runtime = CampbellAgentRuntime(
        DashboardDataRepository(tmp_path),
        _settings(tmp_path),
        session_store=InMemorySessionStore(ttl_seconds=1800),
        archive=archive,
    )

    async def scenario():
        await runtime.record_exchange(PRINCIPAL, "s1", "¿Estado?", "Normal.")
        # A session that expired leaves nothing in memory.
        await runtime.sessions.write(("ana.perez", "cda", "s1"), [])
        archived = await runtime.archived_conversation(PRINCIPAL, "s1")
        await runtime.restore(PRINCIPAL, "s1", archived)
        return await runtime.history(PRINCIPAL, "s1")

    restored = asyncio.run(scenario())

    assert [message.content for message in restored] == ["¿Estado?", "Normal."]
    assert archive.conversation_key(PRINCIPAL, "s1") in backend.objects


def test_a_storage_failure_never_breaks_an_exchange(tmp_path):
    from src.campbell_ai.agents_runtime import CampbellAgentRuntime
    from src.campbell_ai.data import DashboardDataRepository
    from src.campbell_ai.sessions import InMemorySessionStore
    from tests.test_campbell_ai import _settings

    class Exploding(ConversationArchive):
        def save_exchange(self, *_args, **_kwargs):
            raise RuntimeError("S3 no responde")

    runtime = CampbellAgentRuntime(
        DashboardDataRepository(tmp_path),
        _settings(tmp_path),
        session_store=InMemorySessionStore(ttl_seconds=1800),
        archive=Exploding([MemoryBackend()]),
    )

    message_id = asyncio.run(
        runtime.record_exchange(PRINCIPAL, "s1", "¿Estado?", "Normal.")
    )

    assert message_id
    assert asyncio.run(runtime.history(PRINCIPAL, "s1"))


def test_restoring_never_overwrites_a_live_thread(tmp_path):
    from src.campbell_ai.agents_runtime import CampbellAgentRuntime
    from src.campbell_ai.data import DashboardDataRepository
    from src.campbell_ai.sessions import InMemorySessionStore
    from tests.test_campbell_ai import _settings

    runtime = CampbellAgentRuntime(
        DashboardDataRepository(tmp_path),
        _settings(tmp_path),
        session_store=InMemorySessionStore(ttl_seconds=1800),
        archive=ConversationArchive([MemoryBackend()]),
    )

    async def scenario():
        await runtime.record_exchange(PRINCIPAL, "s1", "en curso", "respuesta actual")
        await runtime.restore(PRINCIPAL, "s1", _exchange("viejo", "respuesta vieja"))
        return await runtime.history(PRINCIPAL, "s1")

    messages = asyncio.run(scenario())

    assert [item.content for item in messages] == ["en curso", "respuesta actual"]


def test_clearing_a_conversation_keeps_the_backup(tmp_path):
    from src.campbell_ai.agents_runtime import CampbellAgentRuntime
    from src.campbell_ai.data import DashboardDataRepository
    from src.campbell_ai.sessions import InMemorySessionStore
    from tests.test_campbell_ai import _settings

    backend = MemoryBackend()
    archive = ConversationArchive([backend])
    runtime = CampbellAgentRuntime(
        DashboardDataRepository(tmp_path),
        _settings(tmp_path),
        session_store=InMemorySessionStore(ttl_seconds=1800),
        archive=archive,
    )

    async def scenario():
        await runtime.record_exchange(PRINCIPAL, "s1", "pregunta", "respuesta")
        await runtime.clear(PRINCIPAL, "s1")
        return await runtime.history(PRINCIPAL, "s1")

    assert asyncio.run(scenario()) == []
    # "Limpiar" empties the visible thread; it is not a deletion request.
    assert archive.load_conversation(PRINCIPAL, "s1")
