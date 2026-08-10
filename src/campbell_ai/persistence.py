"""Conversation and feedback archiving for Campbell AI.

The session store keeps the *active* conversation and expires it. This module keeps
the *durable* copy: every interaction is written to S3 under a single owned prefix
(``campbellAI``), in a per-user folder, so a user can come back tomorrow — or after a
service restart — and reopen the thread.

Key layout, with ``<base>`` defaulting to ``campbellAI``::

    <base>/conversations/<company>/<user>/index.json
    <base>/conversations/<company>/<user>/<session>/conversation.json
    <base>/conversations/<company>/<user>/<session>/batches/<count>.json
    <base>/logs/feedback/<company>/<user>/<date>/<session>__<message>__<kind>.json

Three decisions worth stating, because they are not the obvious ones:

- **Messages are written in batches, not one object per message.** Each interaction
  writes one small object holding only the messages new since the last flush, plus
  the full snapshot. If the snapshot write fails the exchange still survives in its
  batch, and a retry cannot duplicate anything because the batch key is derived from
  the message count, which only grows.
- **The per-user index is a real object.** Listing a user's conversations by reading
  every ``conversation.json`` costs one GET per session; the sidebar would get slower
  with every conversation. One index object answers the listing with a single GET, and
  it can be rebuilt from a prefix listing if it is ever lost.
- **Nothing here can break a conversation.** Archiving is a side effect of answering.
  Every backend call is contained: failures are logged and counted, the local mirror
  still runs, and the user gets their answer either way.

Keys are always derived from the authenticated principal, never from client input, so
one user's folder is unreachable from another user's session by construction.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from src.campbell_ai.models import ConversationMessage, DashboardPrincipal


logger = logging.getLogger("campbell_ai.persistence")


DEFAULT_BASE_PREFIX = "campbellAI"
CONVERSATION_FILE = "conversation.json"
INDEX_FILE = "index.json"
# Conversation titles are shown in a narrow sidebar; a long first message would push
# the rest of the row out of view.
TITLE_MAX_CHARS = 90


def normalize_segment(value: str | None, default: str = "default") -> str:
    """Normalize one app-controlled key segment.

    Segments come from usernames, company ids and session ids. Everything outside a
    conservative alphabet becomes ``_`` so no value can introduce a path separator,
    walk up a prefix, or produce an unreachable key.
    """
    raw = str(value or "").strip()
    normalized = "".join(
        ch if (ch.isalnum() or ch in ("-", "_", ".")) else "_" for ch in raw
    )
    normalized = normalized.strip("._")
    if normalized in ("", ".", ".."):
        return default
    return normalized[:120]


def normalize_prefix(prefix: str | None, default: str = DEFAULT_BASE_PREFIX) -> str:
    """Normalize a multi-segment prefix while preserving segment boundaries."""
    raw = str(prefix or "").replace("\\", "/").strip().strip("/")
    segments = [
        normalize_segment(segment) for segment in raw.split("/") if segment.strip()
    ]
    if not segments:
        return normalize_segment(default, DEFAULT_BASE_PREFIX)
    return "/".join(segments)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def conversation_title(messages: Sequence[ConversationMessage]) -> str:
    """Title a thread by its first user message.

    Deterministic and free of invention: the label is the user's own words. An AI
    summary, when one is available, is stored separately and preferred for display.
    """
    for message in messages:
        if message.role == "user" and str(message.content).strip():
            text = " ".join(str(message.content).split())
            if len(text) <= TITLE_MAX_CHARS:
                return text
            return text[: TITLE_MAX_CHARS - 1].rstrip() + "…"
    return "Conversación sin título"


# --------------------------------------------------------------------- backends


class ArchiveBackend(ABC):
    """Object storage primitives the archive needs, and nothing more."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short name used in logs and diagnostics."""

    @abstractmethod
    def put_json(self, key: str, payload: dict[str, Any]) -> None:
        """Write a JSON document, overwriting any previous value."""

    @abstractmethod
    def get_json(self, key: str) -> dict[str, Any] | None:
        """Read a JSON document, or None when it is absent or unreadable."""

    @abstractmethod
    def list_keys(self, prefix: str) -> list[str]:
        """List every key under a prefix. Used only to rebuild a lost index."""


class S3ArchiveBackend(ArchiveBackend):
    """Durable backend. Credentials come from the environment, never from settings."""

    def __init__(
        self,
        bucket: str,
        *,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str = "us-east-1",
    ):
        import boto3
        from botocore.config import Config

        self.bucket = bucket
        # botocore retries transient 5xx and throttling itself; the archive only has to
        # handle the permanent failures that survive it.
        config = Config(retries={"max_attempts": 3, "mode": "standard"})
        if access_key and secret_key:
            self._client = boto3.client(
                "s3",
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
                config=config,
            )
        else:
            self._client = boto3.client("s3", region_name=region, config=config)

    @property
    def name(self) -> str:
        return "s3"

    def put_json(self, key: str, payload: dict[str, Any]) -> None:
        self._client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"),
            ContentType="application/json; charset=utf-8",
        )

    def get_json(self, key: str) -> dict[str, Any] | None:
        try:
            response = self._client.get_object(Bucket=self.bucket, Key=key)
        except Exception:
            # A missing object is the normal case for a new conversation.
            return None
        try:
            document = json.loads(response["Body"].read())
        except (json.JSONDecodeError, KeyError, UnicodeDecodeError, OSError):
            return None
        return document if isinstance(document, dict) else None

    def list_keys(self, prefix: str) -> list[str]:
        keys: list[str] = []
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
                for item in page.get("Contents", []):
                    key = item.get("Key")
                    if key:
                        keys.append(str(key))
        except Exception:
            logger.warning("No fue posible listar el archivo de conversaciones en S3")
        return keys


class LocalArchiveBackend(ArchiveBackend):
    """Mirror on disk, so a conversation survives even when S3 is unreachable."""

    def __init__(self, root: Path | str):
        self.root = Path(root).expanduser().resolve()

    @property
    def name(self) -> str:
        return "local"

    def _path(self, key: str) -> Path:
        # Keys are already normalized; joining cannot escape the root.
        return self.root.joinpath(*[segment for segment in key.split("/") if segment])

    def put_json(self, key: str, payload: dict[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # A long-lived conversation's snapshot can take a moment to serialize and
        # write; writing straight to `path` leaves a truncated, unparseable file
        # behind if the process is interrupted mid-write (timeout, restart, disk
        # pressure). get_json() then silently treats that as "no conversation",
        # which is exactly the "importación se rompe" failure for long threads.
        # Write to a sibling temp file first and rename, which is atomic on both
        # POSIX and Windows within the same directory/volume.
        tmp_path = path.with_name(f"{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(tmp_path, path)

    def get_json(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            return None
        return document if isinstance(document, dict) else None

    def list_keys(self, prefix: str) -> list[str]:
        base = self._path(prefix)
        if not base.exists():
            return []
        keys: list[str] = []
        for path in base.rglob("*.json"):
            keys.append("/".join(path.relative_to(self.root).parts))
        return keys


# ---------------------------------------------------------------- archive facade


@dataclass
class ConversationSummary:
    """One row of the per-user conversation list."""

    session_id: str
    company_id: str
    title: str
    summary: str = ""
    created_at: str = ""
    updated_at: str = ""
    message_count: int = 0

    @property
    def label(self) -> str:
        """What the sidebar shows: the AI summary when there is one, else the title."""
        return self.summary.strip() or self.title.strip() or self.session_id

    def as_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "company_id": self.company_id,
            "title": self.title,
            "summary": self.summary,
            "label": self.label,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": self.message_count,
        }


@dataclass
class ArchiveWriteResult:
    """Outcome of one archiving attempt, for logs and diagnostics."""

    written: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    batch_key: str = ""
    new_messages: int = 0

    @property
    def ok(self) -> bool:
        return bool(self.written)


class ConversationArchive:
    """Durable conversation and feedback storage across one or more backends.

    Methods never raise on backend failure: archiving must not be able to turn a good
    answer into an error. Read methods return empty results instead.
    """

    def __init__(
        self,
        backends: Sequence[ArchiveBackend],
        *,
        base_prefix: str = DEFAULT_BASE_PREFIX,
        list_limit: int = 50,
    ):
        self.backends = list(backends)
        self.base_prefix = normalize_prefix(base_prefix)
        self.list_limit = max(1, int(list_limit))
        self._lock = threading.RLock()

    # -- keys ---------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return bool(self.backends)

    def user_prefix(self, principal: DashboardPrincipal) -> str:
        company = normalize_segment(principal.company_id, "sin_empresa")
        user = normalize_segment(principal.username, "anonimo")
        return f"{self.base_prefix}/conversations/{company}/{user}"

    def index_key(self, principal: DashboardPrincipal) -> str:
        return f"{self.user_prefix(principal)}/{INDEX_FILE}"

    def session_prefix(self, principal: DashboardPrincipal, session_id: str) -> str:
        session = normalize_segment(session_id, "sin_sesion")
        return f"{self.user_prefix(principal)}/{session}"

    def conversation_key(self, principal: DashboardPrincipal, session_id: str) -> str:
        return f"{self.session_prefix(principal, session_id)}/{CONVERSATION_FILE}"

    def feedback_key(
        self,
        principal: DashboardPrincipal,
        session_id: str,
        message_id: str,
        kind: str,
        stamp: str,
    ) -> str:
        company = normalize_segment(principal.company_id, "sin_empresa")
        user = normalize_segment(principal.username, "anonimo")
        day = stamp[:10] or "sin_fecha"
        name = "__".join(
            [
                normalize_segment(session_id, "sin_sesion"),
                normalize_segment(message_id, "sin_mensaje"),
                normalize_segment(kind, "rating"),
            ]
        )
        return (
            f"{self.base_prefix}/logs/feedback/{company}/{user}/"
            f"{normalize_segment(day, 'sin_fecha')}/{name}.json"
        )

    # -- backend fan-out ----------------------------------------------------

    def _put(self, key: str, payload: dict[str, Any], result: ArchiveWriteResult) -> None:
        for backend in self.backends:
            try:
                backend.put_json(key, payload)
                if backend.name not in result.written:
                    result.written.append(backend.name)
            except Exception:
                logger.warning(
                    "Campbell AI no pudo escribir el respaldo en %s", backend.name,
                    exc_info=True,
                )
                if backend.name not in result.failed:
                    result.failed.append(backend.name)

    def _get(self, key: str) -> dict[str, Any] | None:
        """First backend that answers wins; S3 is listed first, disk is the fallback."""
        for backend in self.backends:
            try:
                document = backend.get_json(key)
            except Exception:
                logger.warning(
                    "Campbell AI no pudo leer el respaldo desde %s", backend.name,
                    exc_info=True,
                )
                continue
            if document:
                return document
        return None

    # -- writing ------------------------------------------------------------

    def save_exchange(
        self,
        principal: DashboardPrincipal,
        session_id: str,
        messages: Sequence[ConversationMessage],
        *,
        summary: str | None = None,
    ) -> ArchiveWriteResult:
        """Persist one interaction: the new messages as a batch, then the snapshot."""
        result = ArchiveWriteResult()
        if not self.enabled or not messages:
            return result

        with self._lock:
            record, meta = self._load_record(principal, session_id)

            known = {str(item.get("message_id")) for item in record}
            fresh = [
                message.model_dump(mode="json")
                for message in messages
                if message.message_id not in known
            ]
            # Charts are large and already reproducible from the data; the archive keeps
            # the conversation, not the rendered figures.
            fresh = [_without_figures(item) for item in fresh]
            record.extend(fresh)
            result.new_messages = len(fresh)

            created_at = str(meta.get("created_at") or "") or _utc_now()
            updated_at = _utc_now()
            title = conversation_title(messages) if not meta.get("title") else str(meta["title"])
            resolved_summary = str(
                summary if summary is not None else meta.get("summary", "")
            ).strip()
            meta.update(
                {
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "title": title,
                    "summary": resolved_summary,
                    "message_count": len(record),
                }
            )
            snapshot_record = list(record)

        if fresh:
            # Keyed by message count: a retry rewrites the same object instead of
            # duplicating the exchange, and the sequence is recoverable with no state.
            result.batch_key = (
                f"{self.session_prefix(principal, session_id)}/batches/"
                f"{len(snapshot_record):05d}.json"
            )
            self._put(
                result.batch_key,
                {
                    "session_id": session_id,
                    "company_id": principal.company_id,
                    "username": principal.username,
                    "saved_at": updated_at,
                    "from_message": len(snapshot_record) - len(fresh) + 1,
                    "messages": fresh,
                },
                result,
            )

        self._put(
            self.conversation_key(principal, session_id),
            {
                "session_id": session_id,
                "company_id": principal.company_id,
                "username": principal.username,
                "saved_at": updated_at,
                "metadata": {
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "title": title,
                    "summary": resolved_summary,
                    "message_count": len(snapshot_record),
                },
                "conversation": snapshot_record,
            },
            result,
        )
        self._update_index(
            principal,
            ConversationSummary(
                session_id=session_id,
                company_id=principal.company_id,
                title=title,
                summary=resolved_summary,
                created_at=created_at,
                updated_at=updated_at,
                message_count=len(snapshot_record),
            ),
            result,
        )
        return result

    def set_summary(
        self, principal: DashboardPrincipal, session_id: str, summary: str
    ) -> ArchiveWriteResult:
        """Attach an AI-generated summary to an already archived conversation."""
        result = ArchiveWriteResult()
        cleaned = " ".join(str(summary or "").split())[:TITLE_MAX_CHARS]
        if not self.enabled or not cleaned:
            return result

        with self._lock:
            record, meta = self._load_record(principal, session_id)
            if not record:
                return result
            meta["summary"] = cleaned
            meta.setdefault("title", "Conversación sin título")
            meta["updated_at"] = _utc_now()
            snapshot = dict(meta)
            snapshot_record = list(record)

        self._put(
            self.conversation_key(principal, session_id),
            {
                "session_id": session_id,
                "company_id": principal.company_id,
                "username": principal.username,
                "saved_at": snapshot["updated_at"],
                "metadata": snapshot,
                "conversation": snapshot_record,
            },
            result,
        )
        self._update_index(
            principal,
            ConversationSummary(
                session_id=session_id,
                company_id=principal.company_id,
                title=str(snapshot.get("title", "")),
                summary=cleaned,
                created_at=str(snapshot.get("created_at", "")),
                updated_at=str(snapshot["updated_at"]),
                message_count=len(snapshot_record),
            ),
            result,
        )
        return result

    def has_summary(self, principal: DashboardPrincipal, session_id: str) -> bool:
        _record, meta = self._load_record(principal, session_id)
        return bool(str(meta.get("summary", "")).strip())

    def save_feedback(
        self,
        principal: DashboardPrincipal,
        session_id: str,
        payload: dict[str, Any],
    ) -> ArchiveWriteResult:
        """Back up one rating or written comment as its own object.

        One object per event rather than an appended log: S3 has no append, and a
        read-modify-write of a shared file would lose votes under concurrency. The key
        is derived from the event, so a duplicate submission overwrites itself.
        """
        result = ArchiveWriteResult()
        if not self.enabled:
            return result
        stamp = str(payload.get("timestamp") or _utc_now())
        kind = "comment" if str(payload.get("comment") or "").strip() else "rating"
        self._put(
            self.feedback_key(
                principal,
                session_id,
                str(payload.get("message_id", "")),
                kind,
                stamp,
            ),
            {**payload, "kind": kind},
            result,
        )
        return result

    # -- reading ------------------------------------------------------------

    def _load_record(
        self, principal: DashboardPrincipal, session_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        document = self._get(self.conversation_key(principal, session_id)) or {}
        conversation = document.get("conversation")
        record = [item for item in conversation if isinstance(item, dict)] if isinstance(
            conversation, list
        ) else []
        metadata = document.get("metadata")
        meta = dict(metadata) if isinstance(metadata, dict) else {}
        return record, meta

    def load_conversation(
        self, principal: DashboardPrincipal, session_id: str
    ) -> list[ConversationMessage]:
        """Return an archived conversation, or an empty list when there is none."""
        if not self.enabled:
            return []
        record, _meta = self._load_record(principal, session_id)
        if not record:
            return []
        messages: list[ConversationMessage] = []
        for item in record:
            try:
                messages.append(ConversationMessage.model_validate(item))
            except Exception:
                # One unreadable message must not cost the user the whole thread.
                continue
        return messages

    def list_conversations(
        self, principal: DashboardPrincipal, limit: int | None = None
    ) -> list[ConversationSummary]:
        """List the user's conversations for the active company, newest first."""
        if not self.enabled:
            return []
        document = self._get(self.index_key(principal)) or {}
        entries = document.get("sessions")
        rows = self._parse_index(entries if isinstance(entries, list) else [])
        if not rows:
            rows = self._rebuild_index(principal)
        company = str(principal.company_id or "").strip().lower()
        rows = [
            row
            for row in rows
            if not row.company_id or row.company_id.strip().lower() == company
        ]
        rows.sort(key=lambda row: row.updated_at, reverse=True)
        return rows[: (limit or self.list_limit)]

    @staticmethod
    def _parse_index(entries: Iterable[Any]) -> list[ConversationSummary]:
        rows: list[ConversationSummary] = []
        for item in entries:
            if not isinstance(item, dict) or not item.get("session_id"):
                continue
            rows.append(
                ConversationSummary(
                    session_id=str(item.get("session_id", "")),
                    company_id=str(item.get("company_id", "")),
                    title=str(item.get("title", "")),
                    summary=str(item.get("summary", "")),
                    created_at=str(item.get("created_at", "")),
                    updated_at=str(item.get("updated_at", "")),
                    message_count=int(item.get("message_count", 0) or 0),
                )
            )
        return rows

    def _rebuild_index(
        self, principal: DashboardPrincipal
    ) -> list[ConversationSummary]:
        """Recover the listing from stored conversations when the index is missing."""
        prefix = self.user_prefix(principal)
        seen: set[str] = set()
        rows: list[ConversationSummary] = []
        for backend in self.backends:
            try:
                keys = backend.list_keys(f"{prefix}/")
            except Exception:
                continue
            for key in keys:
                if not key.endswith(f"/{CONVERSATION_FILE}"):
                    continue
                session_id = key.split("/")[-2]
                if session_id in seen:
                    continue
                seen.add(session_id)
                document = self._get(key) or {}
                meta = document.get("metadata")
                meta = meta if isinstance(meta, dict) else {}
                conversation = document.get("conversation")
                count = len(conversation) if isinstance(conversation, list) else 0
                if not count:
                    continue
                rows.append(
                    ConversationSummary(
                        session_id=str(document.get("session_id") or session_id),
                        company_id=str(document.get("company_id", "")),
                        title=str(meta.get("title", "")) or session_id,
                        summary=str(meta.get("summary", "")),
                        created_at=str(meta.get("created_at", "")),
                        updated_at=str(
                            meta.get("updated_at") or document.get("saved_at", "")
                        ),
                        message_count=count,
                    )
                )
            if rows:
                break
        return rows

    def _update_index(
        self,
        principal: DashboardPrincipal,
        entry: ConversationSummary,
        result: ArchiveWriteResult,
    ) -> None:
        """Merge one conversation into the per-user index.

        Read-modify-write: two tabs of the same user could interleave, so the remote
        index is merged rather than replaced and the newest ``updated_at`` per session
        wins. A dropped row is recoverable from the prefix listing.
        """
        key = self.index_key(principal)
        document = self._get(key) or {}
        existing = document.get("sessions")
        rows = {
            row.session_id: row
            for row in self._parse_index(existing if isinstance(existing, list) else [])
        }
        previous = rows.get(entry.session_id)
        if previous and previous.created_at and not entry.created_at:
            entry.created_at = previous.created_at
        rows[entry.session_id] = entry
        ordered = sorted(rows.values(), key=lambda row: row.updated_at, reverse=True)
        self._put(
            key,
            {
                "username": principal.username,
                "updated_at": _utc_now(),
                "sessions": [row.as_dict() for row in ordered[: self.list_limit * 4]],
            },
            result,
        )

    def forget(self, principal: DashboardPrincipal, session_id: str) -> None:
        """Keep stored objects and retain no in-process archive state.

        Called when a user clears a conversation: the visible thread restarts, but the
        backup of what was already said is not rewritten or deleted.
        """
        return None


_ARCHIVE_MAX_POINTS_PER_TRACE = 300


def _downsample_figure(figure: dict[str, Any]) -> dict[str, Any]:
    """Evenly decimate each trace to a bounded point count for the archive.

    A live chart's series can carry thousands of samples (a multi-week telemetry
    window easily passes 10k), and storing every point would make each archive
    write slower and the archive itself grow without bound. Sampling evenly keeps
    the shape recognizable — peaks and trend are still visible — while capping
    size to a fixed multiple of the trace count regardless of the source window.
    The figure stays a real, interactive Plotly figure; nothing else changes.
    """
    data = figure.get("data")
    if not isinstance(data, list):
        return figure
    trimmed_traces = []
    for trace in data:
        if not isinstance(trace, dict):
            trimmed_traces.append(trace)
            continue
        trace = dict(trace)
        length = max(
            (len(values) for key in ("x", "y") if isinstance(values := trace.get(key), list)),
            default=0,
        )
        if length > _ARCHIVE_MAX_POINTS_PER_TRACE:
            step = length / _ARCHIVE_MAX_POINTS_PER_TRACE
            indices = [int(i * step) for i in range(_ARCHIVE_MAX_POINTS_PER_TRACE)]
            for key in ("x", "y", "text", "customdata"):
                values = trace.get(key)
                if isinstance(values, list) and len(values) == length:
                    trace[key] = [values[i] for i in indices]
        trimmed_traces.append(trace)
    return {**figure, "data": trimmed_traces}


def _without_figures(item: dict[str, Any]) -> dict[str, Any]:
    """Store chart metadata without making rendered Plotly JSON durable.

    The live session can carry the full figure so the user sees it immediately. The
    archive keeps chart identity, parameters, caption and summary, which are enough
    to regenerate the chart without keeping old figure payloads in memory or storage.
    """
    visualizations = item.get("visualizations")
    if not isinstance(visualizations, list) or not visualizations:
        return item
    trimmed = []
    for artifact in visualizations:
        if not isinstance(artifact, dict):
            continue
        trimmed.append({**artifact, "figure": {}})
    return {**item, "visualizations": trimmed}


def build_conversation_archive(settings) -> ConversationArchive:
    """Assemble the archive declared by configuration.

    S3 is attempted first so it answers reads, with the local mirror as the fallback.
    A missing bucket or missing credentials is not fatal: the local mirror alone still
    preserves conversations, and the failure is logged once at startup instead of on
    every interaction.
    """
    if not bool(getattr(settings, "persistence_enabled", True)):
        return ConversationArchive([])

    backends: list[ArchiveBackend] = []
    bucket = str(os.getenv("BUCKET_NAME", "")).strip()
    if bucket:
        try:
            backends.append(
                S3ArchiveBackend(
                    bucket,
                    access_key=os.getenv("ACCESS_KEY", "").strip() or None,
                    secret_key=os.getenv("SECRET_KEY", "").strip() or None,
                    region=os.getenv("AWS_REGION", "us-east-1").strip() or "us-east-1",
                )
            )
        except Exception:
            logger.warning(
                "Campbell AI no pudo inicializar el respaldo en S3; se usará solo el "
                "respaldo local",
                exc_info=True,
            )
    else:
        logger.info(
            "Campbell AI sin bucket configurado: las conversaciones se respaldan solo "
            "en disco"
        )

    local_dir = getattr(settings, "persistence_local_dir", None)
    if local_dir:
        try:
            backends.append(LocalArchiveBackend(local_dir))
        except Exception:  # pragma: no cover - unwritable path
            logger.warning("Campbell AI no pudo preparar el respaldo local", exc_info=True)

    return ConversationArchive(
        backends,
        base_prefix=getattr(settings, "persistence_prefix", DEFAULT_BASE_PREFIX),
        list_limit=int(getattr(settings, "history_list_limit", 50)),
    )
