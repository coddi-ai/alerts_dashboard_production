"""Versioned prompt loader for the Campbell AI agent profile."""

from __future__ import annotations

from pathlib import Path

from src.campbell_ai.errors import CampbellConfigurationError
from src.campbell_ai.resources import registered_lru_cache


PROMPTS_ROOT = (Path(__file__).resolve().parent / "prompts").resolve()


# Registered, so a memory reclaim can drop it and diagnostics can report whether prompts
# are loaded. The saving is small - a handful of markdown files - and the cost of a miss
# is re-reading them, so this is included for visibility more than for bytes.
#
# Not every lru_cache in this package belongs here. `get_campbell_settings` is
# configuration, not data, and has `reset_campbell_settings` for deliberate reloads; a
# memory reclaim silently re-reading the environment would be a surprising side effect.
# `get_service` must never be registered at all: it owns the session store and the job
# registry, so clearing it would discard live conversations and answers in flight.
@registered_lru_cache("campbell_ai.prompts", maxsize=16)
def load_prompt(name: str) -> str:
    """Load one Markdown prompt without allowing paths outside the prompt folder."""
    filename = str(name or "").strip()
    if not filename or Path(filename).name != filename or not filename.endswith(".md"):
        raise CampbellConfigurationError("Nombre de prompt Campbell AI no valido")
    path = (PROMPTS_ROOT / filename).resolve()
    try:
        path.relative_to(PROMPTS_ROOT)
    except ValueError as exc:
        raise CampbellConfigurationError("Prompt fuera del directorio autorizado") from exc
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise CampbellConfigurationError(f"Prompt Campbell AI no disponible: {filename}") from exc
    if not content:
        raise CampbellConfigurationError(f"Prompt Campbell AI vacio: {filename}")
    return content


def clear_prompt_cache() -> None:
    """Clear cached prompts for tests and controlled application reloads."""
    load_prompt.cache_clear()
