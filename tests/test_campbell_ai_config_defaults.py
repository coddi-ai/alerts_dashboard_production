"""Where a Campbell AI default is allowed to live, and where it is not.

Configuration is meant to happen *outside* the image: the code carries a working value
for every knob, and a deployment only names what it wants to change. That only holds if
each default is written once. When the same default exists in two places they drift
silently, and the drift is invisible until someone removes the copy that happened to be
winning.

That is not hypothetical. `max_concurrent_per_user` was declared as 5 on the field while
`from_env` still fell back to 2, and deployments only saw 5 because an `ENV` line in the
Dockerfile propped it up. Deleting that line as part of a cleanup would have quietly
halved the per-user limit, with nothing failing to point at it.

These tests pin both halves: the code's defaults agree with themselves, and the
Dockerfile does not silently re-specify them.
"""

from __future__ import annotations

import re
from dataclasses import MISSING, fields
from pathlib import Path

import pytest

from src.campbell_ai.config import CampbellSettings


ROOT = Path(__file__).resolve().parents[1]


# Settings where `from_env` intentionally differs from the field default. Direct
# construction — a test, an embedded consumer — gets a runtime that writes nothing and
# has to opt in to storage; a deployment gets storage on. Anything not listed here must
# agree, and adding to this list should require a reason as good as this one.
DEPLOYMENT_OVERRIDES = {
    "persistence_enabled",
    "persistence_local_dir",
    "conversation_summary_enabled",
}


@pytest.fixture
def clean_env(monkeypatch):
    """No CAMPBELL_* variables set, so only the code's own defaults are in play."""
    import os

    for name in list(os.environ):
        if name.startswith("CAMPBELL_"):
            monkeypatch.delenv(name, raising=False)
    return monkeypatch


def _matches(declared, resolved) -> bool:
    numeric = (
        isinstance(declared, (int, float))
        and not isinstance(declared, bool)
        and isinstance(resolved, (int, float))
    )
    return float(declared) == float(resolved) if numeric else declared == resolved


def test_from_env_falls_back_to_the_declared_field_defaults(clean_env):
    """One default per setting. Two copies drift; this is what catches it."""
    resolved = CampbellSettings.from_env()

    drifted = [
        (item.name, item.default, getattr(resolved, item.name))
        for item in fields(CampbellSettings)
        if item.default is not MISSING
        and item.name not in DEPLOYMENT_OVERRIDES
        and not _matches(item.default, getattr(resolved, item.name))
    ]

    assert not drifted, (
        "these settings declare one default on the field and a different one in "
        f"from_env: {drifted}. Read the fallback from `_declared()` instead of "
        "repeating the literal."
    )


def test_the_deployment_overrides_are_the_ones_we_expect(clean_env):
    """The allowlist must stay a short, deliberate list rather than a dumping ground."""
    resolved = CampbellSettings.from_env()

    for name in DEPLOYMENT_OVERRIDES:
        declared = next(item for item in fields(CampbellSettings) if item.name == name)
        assert not _matches(declared.default, getattr(resolved, name)), (
            f"{name} is listed as a deployment override but now agrees with its field "
            "default; drop it from DEPLOYMENT_OVERRIDES."
        )

    # Storage is off for a directly-constructed settings object and on for a deployment.
    assert resolved.persistence_enabled is True
    assert resolved.conversation_summary_enabled is True


def test_the_service_runs_with_no_campbell_variables_set(clean_env):
    """A deployment should only have to name what it wants to change.

    Every knob resolves to something usable with an empty environment. The internal
    token is the deliberate exception: it has no safe default, so it stays empty and the
    API answers 503 until the deployment supplies one.
    """
    resolved = CampbellSettings.from_env()

    assert resolved.enabled is True
    assert resolved.max_concurrent_requests > 0
    assert resolved.max_concurrent_per_user > 0
    assert resolved.answer_timeout_seconds > 0
    assert resolved.max_history_chars > 0
    assert resolved.session_backend == "memory"
    assert resolved.timezone == "America/Santiago"
    assert resolved.internal_token == "", (
        "the internal token must not have a baked-in default; it is a shared secret"
    )


def test_the_dockerfile_does_not_restate_defaults_the_code_already_has(clean_env):
    """The Dockerfile may only set what genuinely differs from the code default.

    An `ENV` line repeating a value the code already produces is dead weight that has to
    be edited — and rebuilt — in lockstep with the code, and it is exactly how the two
    fall out of step.
    """
    resolved = CampbellSettings.from_env()
    env_to_field = {
        "CAMPBELL_AI_ENABLED": "enabled",
        "CAMPBELL_AI_SESSION_TTL_SECONDS": "session_ttl_seconds",
        "CAMPBELL_AI_MAX_HISTORY_MESSAGES": "max_history_messages",
        "CAMPBELL_AI_MAX_MESSAGE_CHARS": "max_message_chars",
        "CAMPBELL_AI_MAX_TURNS_DATA_ANALYST": "max_turns_data_analyst",
        "CAMPBELL_AI_MAX_TURNS_HEAD": "max_turns_head",
        "CAMPBELL_AI_SESSION_BACKEND": "session_backend",
        "CAMPBELL_AI_STREAMING": "streaming_enabled",
        # Compared against what `from_env` resolves to, not against the field default,
        # so the deployment-override settings belong here too: if the Dockerfile states
        # the same value the deployment already gets, the line is still dead weight.
        "CAMPBELL_AI_PERSISTENCE": "persistence_enabled",
        "CAMPBELL_AI_SUMMARY": "conversation_summary_enabled",
        "CAMPBELL_AI_S3_PREFIX": "persistence_prefix",
        "CAMPBELL_AI_HISTORY_LIMIT": "history_list_limit",
        "CAMPBELL_AI_MODEL_SUMMARY": "model_summary",
        "CAMPBELL_AI_MAX_CONCURRENT_REQUESTS": "max_concurrent_requests",
        "CAMPBELL_AI_MAX_CONCURRENT_PER_USER": "max_concurrent_per_user",
        "CAMPBELL_AI_MAX_REQUESTS_PER_MINUTE": "max_requests_per_minute",
        "CAMPBELL_AI_QUEUE_TIMEOUT_SECONDS": "queue_timeout_seconds",
        "CAMPBELL_AI_RETRY_ATTEMPTS": "retry_attempts",
        "CAMPBELL_AI_RETRY_INITIAL_DELAY": "retry_initial_delay",
        "CAMPBELL_AI_RETRY_MAX_DELAY": "retry_max_delay",
        "CAMPBELL_AI_MODEL_GATEKEEPER": "model_gatekeeper",
        "CAMPBELL_AI_MODEL_HEAD": "model_head",
        "CAMPBELL_AI_MODEL_PLANNER": "model_planner",
        "CAMPBELL_AI_MODEL_DATA_ANALYST": "model_data_analyst",
        "CAMPBELL_AI_MODEL_TECHNICAL_EXPERT": "model_technical_expert",
        "CAMPBELL_AI_MODEL_DASHBOARD_GUIDE": "model_dashboard_guide",
        "CAMPBELL_AI_ANSWER_TIMEOUT_SECONDS": "answer_timeout_seconds",
        "CAMPBELL_AI_GATEKEEPER_TIMEOUT_SECONDS": "gatekeeper_timeout_seconds",
        "CAMPBELL_AI_MAX_HISTORY_CHARS": "max_history_chars",
        "CAMPBELL_AI_MAX_HISTORY_MESSAGE_CHARS": "max_history_message_chars",
        "CAMPBELL_AI_JOB_RETENTION_SECONDS": "job_retention_seconds",
    }

    def normalize(value) -> str:
        text = str(value).strip().lower()
        if text in {"true", "yes", "on"}:
            return "true"
        if text in {"false", "no", "off"}:
            return "false"
        try:
            return f"{float(text):.6f}"
        except ValueError:
            return text

    redundant = []
    for line in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines():
        match = re.match(r"^ENV\s+([A-Z0-9_]+)=(.*)$", line.strip())
        if not match:
            continue
        name, value = match.group(1), match.group(2).strip()
        field_name = env_to_field.get(name)
        if field_name is None:
            continue
        if normalize(value) == normalize(getattr(resolved, field_name)):
            redundant.append(name)

    assert not redundant, (
        "the Dockerfile restates defaults the code already provides: "
        f"{redundant}. Delete those ENV lines; configuration belongs in .env or "
        "docker-compose, not baked into the image."
    )
