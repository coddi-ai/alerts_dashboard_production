"""Central configuration for the Campbell AI API and agent runtime."""

from __future__ import annotations

import os
from dataclasses import MISSING, dataclass, fields
from functools import lru_cache
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _env_int(name: str, default: int) -> int:
    return int(_env_str(name, str(default)))


def _env_float(name: str, default: float) -> float:
    return float(_env_str(name, str(default)))


def _declared() -> dict[str, object]:
    """Defaults declared on the dataclass fields.

    `from_env` reads its fallbacks from here rather than repeating a literal, so each
    default is written exactly once. Two copies drift: this file already had
    `max_concurrent_per_user` declared as 5 on the field while `from_env` still fell
    back to 2, and the only reason deployments got 5 was an `ENV` line in the Dockerfile
    propping it up. Removing that line would have silently halved the limit.

    Fields with no declared default are not listed; for those the literal inside
    `from_env` is the single default and cannot drift.
    """
    return {
        item.name: item.default
        for item in fields(CampbellSettings)
        if item.default is not MISSING
    }


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
    model_dashboard_guide: str
    max_turns_data_analyst: int
    max_turns_head: int
    session_backend: str
    redis_url: str
    redis_namespace: str
    session_lock_timeout_seconds: int
    streaming_enabled: bool
    timezone: str = "America/Santiago"
    # Durable conversation and feedback backup. The bucket and its credentials are read
    # from the environment by the storage backend, never carried in settings.
    #
    # These carry defaults so a caller constructing settings directly — a test, an
    # embedded consumer — gets a runtime that writes nothing and admits everything, and
    # has to opt in to storage. `from_env` sets the deployment defaults instead, where
    # persistence is on.
    persistence_enabled: bool = False
    persistence_prefix: str = "campbellAI"
    persistence_local_dir: Path | None = None
    history_list_limit: int = 50
    conversation_summary_enabled: bool = False
    model_summary: str = "gpt-4.1-mini"
    # Admission control for parallel users. These two are the only thing bounding
    # concurrency now, and they have to be chosen together:
    #
    #   max_concurrent_requests  >=  max_concurrent_per_user  x  simultaneous people
    #
    # Left mismatched, the per-user bound stops protecting anyone: at 6 and 10, two
    # people fill the pool and the third is told the service is busy.
    #
    # The per-user bound used to be beside the point, because the session lock
    # serialized a conversation regardless of what it said — raising it only moved a
    # rejection from admission control to a 20-second wait on the lock. Now that the
    # lock covers just the read-modify-write (see `_commit_exchange`), this number is
    # what actually decides how many questions one account can have in flight, so it is
    # worth setting deliberately rather than inheriting.
    #
    # Six per user and fifteen overall: one person can fire a screenful of questions at
    # once, and two can do it simultaneously before anyone waits. Above roughly this
    # range the binding constraint stops being these counters and becomes the upstream
    # model quota — `max_requests_per_minute` is the guard for that, and the symptom of
    # overshooting is 429s from the provider rather than "servicio ocupado" from us.
    max_concurrent_requests: int = 15
    max_concurrent_per_user: int = 6
    max_requests_per_minute: int = 200
    queue_timeout_seconds: float = 20.0
    retry_attempts: int = 3
    retry_initial_delay: float = 1.0
    retry_max_delay: float = 30.0
    # Wall-clock budget for one exchange, retries included. An agent run is otherwise
    # unbounded: `max_turns` caps the number of model calls, not how long they take.
    answer_timeout_seconds: float = 180.0
    gatekeeper_timeout_seconds: float = 30.0
    # Size budget for the conversation replayed into each turn. `max_history_messages`
    # counts messages, which says nothing about cost: twenty answers containing markdown
    # tables is a far larger prompt than twenty one-line ones, and it is the character
    # count — not the message count — that makes a long conversation slow enough to hit
    # the timeout above. Both bounds apply; whichever binds first wins.
    max_history_chars: int = 24000
    # Longest single archived message replayed into a prompt. One enormous table would
    # otherwise consume the whole budget above and evict the rest of the conversation.
    max_history_message_chars: int = 4000
    # How long a finished background answer stays readable after it completes, so a
    # browser that reconnects late still collects its result instead of re-asking.
    job_retention_seconds: float = 900.0

    @classmethod
    def from_env(cls) -> "CampbellSettings":
        """Build settings from the environment, falling back to the declared defaults.

        Nothing here needs to be set for the service to run correctly — except
        `CAMPBELL_AI_INTERNAL_TOKEN`, which has no safe default and must come from the
        deployment. Everything else is a knob with a working value already declared on
        the field above, so an image or a compose file only has to name what it wants to
        change.
        """
        declared = _declared()
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
            model_dashboard_guide=os.getenv(
                "CAMPBELL_AI_MODEL_DASHBOARD_GUIDE", "gpt-4.1-mini"
            ),
            # The analyst now owns ten data tools; cross-source questions need room to
            # chain calls before answering.
            max_turns_data_analyst=int(
                os.getenv("CAMPBELL_AI_MAX_TURNS_DATA_ANALYST", "10")
            ),
            max_turns_head=int(os.getenv("CAMPBELL_AI_MAX_TURNS_HEAD", "10")),
            # Conversation state lives in-process by default. Any deployment with more
            # than one worker or replica must switch this to redis.
            session_backend=os.getenv("CAMPBELL_AI_SESSION_BACKEND", "memory"),
            redis_url=os.getenv("CAMPBELL_AI_REDIS_URL", ""),
            redis_namespace=os.getenv(
                "CAMPBELL_AI_REDIS_NAMESPACE", "campbell:sessions"
            ),
            session_lock_timeout_seconds=int(
                os.getenv("CAMPBELL_AI_SESSION_LOCK_TIMEOUT_SECONDS", "300")
            ),
            streaming_enabled=_env_bool("CAMPBELL_AI_STREAMING", False),
            timezone=_env_str("CAMPBELL_AI_TIMEZONE", declared["timezone"]),
            # Deliberately not the field default; see `conversation_summary_enabled`.
            persistence_enabled=_env_bool("CAMPBELL_AI_PERSISTENCE", True),
            # One owned folder inside the bucket the dashboard already uses, so backups
            # and logs never mix with the analytics data.
            persistence_prefix=_env_str(
                "CAMPBELL_AI_S3_PREFIX", declared["persistence_prefix"]
            ),
            persistence_local_dir=Path(
                os.getenv(
                    "CAMPBELL_AI_BACKUP_DIR",
                    str(_project_root() / "logs" / "campbell_ai_backup"),
                )
            ).expanduser().resolve(),
            history_list_limit=_env_int("CAMPBELL_AI_HISTORY_LIMIT", declared["history_list_limit"]),
            # Deliberately not the field default. A caller building settings directly —
            # a test, an embedded consumer — gets storage off and has to opt in; a
            # deployment gets it on. See the field comments above.
            conversation_summary_enabled=_env_bool("CAMPBELL_AI_SUMMARY", True),
            model_summary=_env_str("CAMPBELL_AI_MODEL_SUMMARY", declared["model_summary"]),
            max_concurrent_requests=_env_int(
                "CAMPBELL_AI_MAX_CONCURRENT_REQUESTS", declared["max_concurrent_requests"]
            ),
            max_concurrent_per_user=_env_int(
                "CAMPBELL_AI_MAX_CONCURRENT_PER_USER", declared["max_concurrent_per_user"]
            ),
            max_requests_per_minute=_env_int(
                "CAMPBELL_AI_MAX_REQUESTS_PER_MINUTE", declared["max_requests_per_minute"]
            ),
            queue_timeout_seconds=_env_float(
                "CAMPBELL_AI_QUEUE_TIMEOUT_SECONDS", declared["queue_timeout_seconds"]
            ),
            retry_attempts=_env_int("CAMPBELL_AI_RETRY_ATTEMPTS", declared["retry_attempts"]),
            retry_initial_delay=_env_float(
                "CAMPBELL_AI_RETRY_INITIAL_DELAY", declared["retry_initial_delay"]
            ),
            retry_max_delay=_env_float(
                "CAMPBELL_AI_RETRY_MAX_DELAY", declared["retry_max_delay"]
            ),
            answer_timeout_seconds=_env_float(
                "CAMPBELL_AI_ANSWER_TIMEOUT_SECONDS", declared["answer_timeout_seconds"]
            ),
            gatekeeper_timeout_seconds=_env_float(
                "CAMPBELL_AI_GATEKEEPER_TIMEOUT_SECONDS",
                declared["gatekeeper_timeout_seconds"],
            ),
            max_history_chars=_env_int(
                "CAMPBELL_AI_MAX_HISTORY_CHARS", declared["max_history_chars"]
            ),
            max_history_message_chars=_env_int(
                "CAMPBELL_AI_MAX_HISTORY_MESSAGE_CHARS",
                declared["max_history_message_chars"],
            ),
            job_retention_seconds=_env_float(
                "CAMPBELL_AI_JOB_RETENTION_SECONDS", declared["job_retention_seconds"]
            ),
        )


@lru_cache(maxsize=1)
def get_campbell_settings() -> CampbellSettings:
    return CampbellSettings.from_env()


def reset_campbell_settings() -> None:
    """Clear cached settings; intended for tests and controlled reloads."""
    get_campbell_settings.cache_clear()
