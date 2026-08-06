"""Capability guard and deterministic security checks for Campbell AI."""

from __future__ import annotations

import re

from src.campbell_ai.models import SecurityDecision


_SECURITY_RULES: tuple[tuple[str, str, str], ...] = (
    (
        r"\b(ignore|disregard|forget|override|bypass|ignora|olvida|omite|desactiva)\b"
        r".{0,80}\b(prompt|instructions?|security|rules?|instrucciones|seguridad|reglas)\b",
        "Intento de modificar las instrucciones de seguridad",
        "prompt_injection",
    ),
    (
        r"\b(access_key|secret_key|api_key|bucket_name|environment variables?|variables de entorno)\b",
        "Intento de acceder a secretos internos",
        "data_exfiltration",
    ),
    (
        r"(?:\.\.[/\\]|\bdata[/\\]|\boutputs[/\\]|\bconfig[/\\]users)",
        "Intento de acceder a rutas internas",
        "path_access",
    ),
    (
        r"\b(otra empresa|otro cliente|todos los clientes|todas las empresas|other company|all clients)\b",
        "Intento de consultar informacion fuera de la empresa activa",
        "cross_company_access",
    ),
)

_UNSUPPORTED_CAPABILITY = re.compile(
    r"\b(genera|crear?|crea|haz|dame|prepara|construye|muestra|produce|exporta|descarga|"
    r"generate|create|prepare|build|show|export|download)\b"
    r".{0,60}\b(reporte|report|pdf|tabla|table|archivo|file|exportacion|exportación|"
    r"spreadsheet|excel|csv)\b",
    re.IGNORECASE | re.DOTALL,
)


def deterministic_guard(
    message: str,
    active_company: str | None = None,
    known_companies: list[str] | None = None,
) -> SecurityDecision:
    normalized = " ".join(str(message or "").strip().split())
    if not normalized:
        return SecurityDecision(
            safe=False,
            reason="La consulta esta vacia",
            threat_type="empty_query",
        )

    for pattern, reason, threat_type in _SECURITY_RULES:
        if re.search(pattern, normalized, re.IGNORECASE | re.DOTALL):
            return SecurityDecision(safe=False, reason=reason, threat_type=threat_type)

    active = str(active_company or "").strip().casefold()
    for company in known_companies or []:
        normalized_company = str(company).strip().casefold()
        if normalized_company and normalized_company != active:
            if re.search(rf"\b{re.escape(normalized_company)}\b", normalized, re.IGNORECASE):
                return SecurityDecision(
                    safe=False,
                    reason="La consulta menciona una empresa distinta a la empresa activa",
                    threat_type="cross_company_access",
                )
    return SecurityDecision(safe=True)


def requests_unsupported_capability(message: str) -> bool:
    return bool(_UNSUPPORTED_CAPABILITY.search(str(message or "")))


UNSUPPORTED_CAPABILITY_MESSAGE = (
    "Campbell AI puede analizar datos, generar gráficos dentro de la conversación y entregar "
    "recomendaciones técnicas. En esta versión no genero reportes, PDF, tablas descargables ni archivos."
)
