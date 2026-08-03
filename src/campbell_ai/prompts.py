"""Versioned prompt loader for the Campbell AI agent profile."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.campbell_ai.errors import CampbellConfigurationError


PROMPTS_ROOT = (Path(__file__).resolve().parent / "prompts").resolve()


@lru_cache(maxsize=16)
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
