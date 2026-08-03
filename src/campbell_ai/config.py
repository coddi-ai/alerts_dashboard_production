"""Central configuration for the Campbell AI API and agent runtime."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class CampbellSettings:
    """Environment-backed settings shared by API and agent logic."""

    enabled: bool
    data_root: Path
    feedback_path: Path
    internal_token: str
    session_ttl_seconds: int
    max_history_messages: int
    max_message_chars: int
    model_gatekeeper: str
    model_head: str
    model_planner: str
    model_data_analyst: str
    model_technical_expert: str

    @classmethod
    def from_env(cls) -> "CampbellSettings":
        return cls(
            enabled=_env_bool("CAMPBELL_AI_ENABLED", True),
            data_root=Path(
                os.getenv("CAMPBELL_AI_DATA_ROOT", str(_project_root() / "data"))
            ).expanduser().resolve(),
            feedback_path=Path(
                os.getenv(
                    "CAMPBELL_AI_FEEDBACK_PATH",
                    str(_project_root() / "logs" / "campbell_ai_feedback.jsonl"),
                )
            ).expanduser().resolve(),
            internal_token=os.getenv("CAMPBELL_AI_INTERNAL_TOKEN", "").strip(),
            session_ttl_seconds=int(os.getenv("CAMPBELL_AI_SESSION_TTL_SECONDS", "1800")),
            max_history_messages=int(os.getenv("CAMPBELL_AI_MAX_HISTORY_MESSAGES", "20")),
            max_message_chars=int(os.getenv("CAMPBELL_AI_MAX_MESSAGE_CHARS", "4000")),
            model_gatekeeper=os.getenv("CAMPBELL_AI_MODEL_GATEKEEPER", "gpt-4.1-mini"),
            model_head=os.getenv("CAMPBELL_AI_MODEL_HEAD", "gpt-4.1-mini"),
            model_planner=os.getenv("CAMPBELL_AI_MODEL_PLANNER", "gpt-4.1-mini"),
            model_data_analyst=os.getenv("CAMPBELL_AI_MODEL_DATA_ANALYST", "gpt-4.1"),
            model_technical_expert=os.getenv(
                "CAMPBELL_AI_MODEL_TECHNICAL_EXPERT", "gpt-4.1-mini"
            ),
        )


@lru_cache(maxsize=1)
def get_campbell_settings() -> CampbellSettings:
    return CampbellSettings.from_env()


def reset_campbell_settings() -> None:
    """Clear cached settings; intended for tests and controlled reloads."""
    get_campbell_settings.cache_clear()
