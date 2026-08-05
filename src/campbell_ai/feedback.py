"""Append-only feedback persistence for Campbell AI responses.

Two things are recorded per answer, and they are separate events: the rating (thumbs up
or down) and, optionally, a written comment. Keeping them apart means a user can rate
first and explain afterwards without the second submission being discarded as a
duplicate — which is the whole value of asking for a comment.

Every event is written twice: to a local JSONL log for immediate inspection, and to the
durable archive for backup. What is deliberately *not* recorded is the question or the
answer: a rating is an opinion about a response, and copying the conversation into a
separate log would duplicate client data into a second retention path for no benefit.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.campbell_ai.models import DashboardPrincipal


logger = logging.getLogger("campbell_ai.feedback")


class FeedbackStore:
    """Persist ratings and comments without copying conversation contents."""

    def __init__(self, path: Path | str, archive: Any | None = None):
        self.path = Path(path).expanduser().resolve()
        self.archive = archive
        self._lock = threading.RLock()
        self._recorded = self._load_recorded_keys()

    @staticmethod
    def _key(
        username: str, company_id: str, session_id: str, message_id: str, kind: str
    ) -> tuple[str, str, str, str, str]:
        return (username, company_id, session_id, message_id, kind)

    def _load_recorded_keys(self) -> set[tuple[str, str, str, str, str]]:
        recorded: set[tuple[str, str, str, str, str]] = set()
        if not self.path.exists():
            return recorded
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return recorded
        for line in lines:
            try:
                item = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            recorded.add(
                self._key(
                    str(item.get("username", "")),
                    str(item.get("company_id", "")),
                    str(item.get("session_id", "")),
                    str(item.get("message_id", "")),
                    # Older lines predate the kind field; they were ratings.
                    str(item.get("kind", "rating")),
                )
            )
        return recorded

    def record(
        self,
        principal: DashboardPrincipal,
        session_id: str,
        message_id: str,
        rating: str,
        comment: str | None = None,
    ) -> bool:
        """Store one feedback event. False when it was already recorded."""
        text = str(comment or "").strip()[:1000]
        kind = "comment" if text else "rating"
        key = self._key(
            principal.username, principal.company_id, session_id, message_id, kind
        )
        with self._lock:
            if key in self._recorded:
                return False
            payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "username": principal.username,
                "company_id": principal.company_id,
                "session_id": session_id,
                "message_id": message_id,
                "kind": kind,
                "rating": rating,
                "comment": text or None,
            }
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            except OSError:
                # A read-only log directory must not lose the vote: the archive below is
                # the backup of record, and losing both is what would matter.
                logger.warning("Campbell AI no pudo escribir el log local de feedback")
            self._recorded.add(key)

        self._backup(principal, session_id, payload)
        return True

    def _backup(
        self, principal: DashboardPrincipal, session_id: str, payload: dict[str, Any]
    ) -> None:
        if self.archive is None:
            return
        try:
            self.archive.save_feedback(principal, session_id, payload)
        except Exception:
            # Already contained inside the archive; this is the belt on top of it.
            logger.warning("Campbell AI no pudo respaldar el feedback", exc_info=True)
