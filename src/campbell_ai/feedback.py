"""Minimal append-only feedback persistence for Campbell AI responses."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from src.campbell_ai.models import DashboardPrincipal


class FeedbackStore:
    """Persist ratings without copying conversation contents or dashboard data."""

    def __init__(self, path: Path | str):
        self.path = Path(path).expanduser().resolve()
        self._lock = threading.RLock()
        self._recorded = self._load_recorded_keys()

    def _load_recorded_keys(self) -> set[tuple[str, str, str, str]]:
        recorded: set[tuple[str, str, str, str]] = set()
        if not self.path.exists():
            return recorded
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return recorded
        for line in lines:
            try:
                item = json.loads(line)
                recorded.add(
                    (
                        str(item.get("username", "")),
                        str(item.get("company_id", "")),
                        str(item.get("session_id", "")),
                        str(item.get("message_id", "")),
                    )
                )
            except (json.JSONDecodeError, TypeError):
                continue
        return recorded

    def record(
        self,
        principal: DashboardPrincipal,
        session_id: str,
        message_id: str,
        rating: str,
        comment: str | None = None,
    ) -> bool:
        key = (principal.username, principal.company_id, session_id, message_id)
        with self._lock:
            if key in self._recorded:
                return False
            payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "username": principal.username,
                "company_id": principal.company_id,
                "session_id": session_id,
                "message_id": message_id,
                "rating": rating,
                "comment": str(comment or "").strip()[:1000] or None,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._recorded.add(key)
            return True
