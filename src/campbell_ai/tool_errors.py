"""Actionable tool errors so an agent can correct itself instead of giving up.

A tool failure used to come back as ``"Fuente no disponible para el cliente
activo"`` regardless of what actually went wrong. That message is often simply
untrue — the source exists and the argument was wrong — and it gives the agent no
way forward, so it either abandons the question or invents an answer. Both outcomes
are worse than the real error.

Domain errors (`CampbellAIError`) are written for the agent, so they are passed
through verbatim and paired with the inspection call that resolves them. Unexpected
errors are reported as internal without leaking implementation detail, and marked
non-retryable so a broken call is not attempted in a loop.
"""

from __future__ import annotations

import json
import re

from src.campbell_ai.errors import CampbellAIError
from src.campbell_ai.data import TOOL_DATASETS


# Defence in depth: these messages now reach the model, so scrub anything that
# looks like a filesystem path even though the raisers only use bare filenames.
_PATH_LIKE = re.compile(r"(?:[A-Za-z]:)?[\\/][^\s'\"]+")


def sanitize(detail: str) -> str:
    return _PATH_LIKE.sub("[ruta interna]", str(detail or "")).strip()


def _inspection_call(tool_name: str, dataset: str | None) -> str:
    resolved = dataset or TOOL_DATASETS.get(tool_name)
    if resolved:
        return f'inspect_dataset(dataset="{resolved}")'
    return "inspect_dataset()"


# A source that does not exist for the client cannot be fixed by retrying.
_MISSING_SOURCE = re.compile(
    r"(fuente de datos no disponible|la fuente no existe|no hay fuentes de datos"
    r"|no esta habilitado|no está habilitado)",
    re.IGNORECASE,
)

_RETRY_HINT = (
    "Revisa en inspect_dataset las columnas y los valores permitidos, corrige los "
    "argumentos y reintenta una sola vez. Si el valor buscado no aparece en la "
    "fuente, informalo; no lo aproximes con otro."
)
_MISSING_HINT = (
    "La fuente no existe o no esta habilitada para el cliente activo. No reintentes: "
    "informa que ese analisis no esta disponible para esta empresa y continua con las "
    "fuentes que si existen."
)
_INTERNAL_HINT = (
    "No reintentes con los mismos argumentos. Informa que la fuente no pudo leerse y "
    "continua con la evidencia disponible."
)


def tool_failure(
    tool_name: str,
    exc: Exception,
    dataset: str | None = None,
    hint: str = "",
    extra: dict[str, object] | None = None,
) -> str:
    """Build the JSON a failing tool returns to the agent."""
    expected = isinstance(exc, CampbellAIError)
    if expected:
        detail = sanitize(str(exc)) or (
            "La operacion no pudo completarse con los argumentos entregados"
        )
    else:
        detail = "Error interno al leer la fuente"

    if not expected:
        retry_allowed, default_hint = False, _INTERNAL_HINT
    elif _MISSING_SOURCE.search(detail):
        # Distinguished on purpose: telling the agent to retry a source that is not
        # deployed for this client wastes a turn and invites a fabricated answer.
        retry_allowed, default_hint = False, _MISSING_HINT
    else:
        retry_allowed, default_hint = True, _RETRY_HINT

    payload: dict[str, object] = {
        "ok": False,
        "tool": tool_name,
        "error": type(exc).__name__,
        "detail": detail,
        "recovery": {
            "retry_allowed": retry_allowed,
            "inspect_with": _inspection_call(tool_name, dataset),
            "hint": hint or default_hint,
        },
    }
    payload.update(extra or {})
    return json.dumps(payload, ensure_ascii=False)
