"""Small server-to-server client for the Campbell AI internal API."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class CampbellAPIClientError(RuntimeError):
    """Error safe to surface in the Campbell AI Dash view.

    Carries a `kind` so the view can react differently per cause instead of showing
    one dead-end message: a service that is not running is recoverable by retrying,
    a misconfigured token is not, and an unauthorized company is a user-level fact.
    """

    def __init__(
        self,
        message: str,
        kind: str = "unknown",
        retryable: bool = False,
        guidance: str = "",
    ):
        super().__init__(message)
        self.kind = kind
        self.retryable = retryable
        self.guidance = guidance

    @property
    def title(self) -> str:
        return str(self)


# Per-cause guidance. The user cannot fix a deployment problem, but they should be
# told whether waiting and retrying is worth it or someone has to be called.
_FAILURE_GUIDANCE: dict[str, tuple[str, bool, str]] = {
    "unreachable": (
        "No fue posible conectar con el servicio de Campbell AI",
        True,
        "El servicio no está respondiendo. Puedes reintentar en unos segundos; si el "
        "problema persiste, avisa al equipo de plataforma.",
    ),
    "timeout": (
        "Campbell AI tardó demasiado en responder",
        True,
        "La consulta excedió el tiempo de espera. Reintenta; si vuelve a ocurrir, "
        "acota el periodo o divide la pregunta en partes.",
    ),
    "credentials": (
        "Campbell AI rechazó la credencial interna",
        False,
        "Es un problema de configuración del despliegue, no de tu cuenta. El dashboard "
        "y la API deben compartir el mismo token interno.",
    ),
    "not_configured": (
        "Campbell AI no está configurado",
        False,
        "Falta la credencial interna del servicio. Contacta al equipo de plataforma.",
    ),
    "forbidden": (
        "No tienes acceso a la empresa seleccionada",
        False,
        "Selecciona una empresa sobre la que tengas permisos.",
    ),
    "busy": (
        "Campbell AI está atendiendo muchas consultas",
        True,
        "El asistente alcanzó su límite de consultas simultáneas. Espera unos segundos "
        "y reintenta: tu consulta se conservó.",
    ),
    "expired": (
        "La consulta ya no está en curso",
        True,
        "El asistente perdió el seguimiento de esta consulta. Si alcanzó a responder, "
        "la respuesta está en la conversación; si no aparece, vuelve a preguntarla.",
    ),
    "too_slow": (
        "La consulta tardó más de lo permitido",
        True,
        "Acota el periodo o divide la pregunta en partes: una consulta muy amplia, o "
        "una conversación muy larga, hacen que el asistente supere su tiempo máximo.",
    ),
    "unavailable": (
        "Campbell AI o sus datos no están disponibles",
        True,
        "El servicio respondió pero no pudo atender la consulta, normalmente por datos "
        "faltantes para esta empresa. Reintenta o prueba con otra empresa.",
    ),
    "invalid_request": (
        "La solicitud enviada a Campbell AI no es válida",
        False,
        "Vuelve a cargar la página para reiniciar la sesión del asistente.",
    ),
    "server_error": (
        "Campbell AI respondió con un error interno",
        True,
        "El servicio falló procesando la consulta. Reintenta; si persiste, avisa al "
        "equipo de plataforma.",
    ),
    "unknown": (
        "Campbell AI respondió con un error",
        True,
        "Reintenta la operación. Si el problema persiste, avisa al equipo de plataforma.",
    ),
}


def _failure(kind: str, detail: str = "") -> CampbellAPIClientError:
    title, retryable, guidance = _FAILURE_GUIDANCE.get(kind, _FAILURE_GUIDANCE["unknown"])
    return CampbellAPIClientError(
        detail or title, kind=kind, retryable=retryable, guidance=guidance
    )


@dataclass(frozen=True)
class CampbellAPIClient:
    base_url: str
    internal_token: str
    timeout_seconds: float = 60.0

    @classmethod
    def from_env(cls) -> "CampbellAPIClient":
        return cls(
            base_url=os.getenv(
                "CAMPBELL_AI_API_URL", "http://127.0.0.1:8000"
            ).rstrip("/"),
            internal_token=os.getenv("CAMPBELL_AI_INTERNAL_TOKEN", "").strip(),
            timeout_seconds=float(os.getenv("CAMPBELL_AI_API_TIMEOUT_SECONDS", "90")),
        )

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Call the internal API.

        `timeout` overrides the per-message budget for calls that are supposed to be
        fast. Submitting and polling a background answer must never inherit the long
        budget sized for a full agent run: if a submit has not been acknowledged in
        seconds, the service is unhealthy and waiting a further minute only delays
        telling the user so.
        """
        if not self.internal_token:
            raise _failure("not_configured")

        data = None
        headers = {
            "Accept": "application/json",
            "X-Campbell-Token": self.internal_token,
        }
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = Request(
            f"{self.base_url}{path}", data=data, headers=headers, method=method
        )
        try:
            with urlopen(
                request, timeout=timeout if timeout is not None else self.timeout_seconds
            ) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except HTTPError as exc:
            detail = ""
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail", "")
            except (json.JSONDecodeError, UnicodeDecodeError, OSError):
                pass
            kinds = {
                401: "credentials",
                403: "forbidden",
                # A polled job the service no longer knows about. Distinct from a bad
                # request: the answer may well exist, just in the history rather than
                # in the job.
                404: "expired",
                422: "invalid_request",
                # Load, not failure: the same request will work once a slot frees up.
                429: "busy",
                # The answer outran its budget on the server. Retrying the identical
                # question is unlikely to help; narrowing it is.
                504: "too_slow",
                503: "unavailable",
            }
            kind = kinds.get(exc.code) or ("server_error" if exc.code >= 500 else "unknown")
            raise _failure(kind, detail) from exc
        except TimeoutError as exc:
            raise _failure("timeout") from exc
        except URLError as exc:
            # A socket timeout arrives wrapped in URLError, so the cause decides.
            if isinstance(getattr(exc, "reason", None), TimeoutError):
                raise _failure("timeout") from exc
            raise _failure("unreachable") from exc

    @staticmethod
    def _identity(username: str, company_id: str) -> dict[str, str]:
        return {"username": username, "company_id": company_id}

    def health(self) -> dict[str, Any]:
        """Cheap liveness probe. Needs no token, so it isolates 'service down'."""
        request = Request(
            f"{self.base_url}/api/v1/campbell-ai/health",
            headers={"Accept": "application/json"},
            method="GET",
        )
        try:
            # Short timeout on purpose: this runs to decide what to tell the user,
            # so it must not inherit the long per-message budget.
            with urlopen(request, timeout=min(10.0, self.timeout_seconds)) as response:
                body = response.read().decode("utf-8")
            return json.loads(body) if body else {}
        except HTTPError as exc:
            raise _failure("server_error" if exc.code >= 500 else "unknown") from exc
        except TimeoutError as exc:
            raise _failure("timeout") from exc
        except (URLError, json.JSONDecodeError) as exc:
            raise _failure("unreachable") from exc

    def initialize(
        self, username: str, company_id: str, session_id: str | None = None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = self._identity(username, company_id)
        if session_id:
            payload["session_id"] = session_id
        return self._request("POST", "/api/v1/campbell-ai/initialize", payload)

    def send_message(
        self, username: str, company_id: str, session_id: str, message: str
    ) -> dict[str, Any]:
        payload = self._identity(username, company_id)
        payload.update({"session_id": session_id, "message": message})
        return self._request("POST", "/api/v1/campbell-ai/message", payload)

    # -- background answers ---------------------------------------------------
    # Submitting and polling replace waiting inside one long request. Both calls are
    # short, so neither can be killed by a proxy's idle timeout mid-answer, and a
    # browser that reloads mid-question resumes by polling the same job id.

    def submit_message(
        self,
        username: str,
        company_id: str,
        session_id: str,
        message: str,
        client_message_id: str,
    ) -> dict[str, Any]:
        """Queue the answer and return its job handle.

        `client_message_id` makes this idempotent: resending the same one attaches to
        the run already in progress rather than starting a second one.
        """
        payload = self._identity(username, company_id)
        payload.update(
            {
                "session_id": session_id,
                "message": message,
                "client_message_id": client_message_id,
            }
        )
        return self._request(
            "POST", "/api/v1/campbell-ai/message/submit", payload, timeout=15.0
        )

    def message_status(self, job_id: str) -> dict[str, Any]:
        """Poll a background answer. Raises kind='expired' once the job is unknown."""
        return self._request(
            "POST",
            "/api/v1/campbell-ai/message/status",
            {"job_id": job_id},
            timeout=15.0,
        )

    def cancel_message(self, job_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/campbell-ai/message/cancel",
            {"job_id": job_id},
            timeout=15.0,
        )

    def history(
        self, username: str, company_id: str, session_id: str
    ) -> dict[str, Any]:
        payload = self._identity(username, company_id)
        payload["session_id"] = session_id
        return self._request("POST", "/api/v1/campbell-ai/history", payload)

    def list_conversations(self, username: str, company_id: str) -> dict[str, Any]:
        return self._request(
            "POST",
            "/api/v1/campbell-ai/conversations",
            self._identity(username, company_id),
        )

    def open_conversation(
        self, username: str, company_id: str, session_id: str
    ) -> dict[str, Any]:
        payload = self._identity(username, company_id)
        payload["session_id"] = session_id
        return self._request(
            "POST", "/api/v1/campbell-ai/conversations/open", payload
        )

    def clear(self, username: str, company_id: str, session_id: str) -> None:
        payload = self._identity(username, company_id)
        payload["session_id"] = session_id
        self._request("DELETE", "/api/v1/campbell-ai/clear", payload)

    def submit_feedback(
        self,
        username: str,
        company_id: str,
        session_id: str,
        message_id: str,
        rating: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        payload = self._identity(username, company_id)
        payload.update(
            {
                "session_id": session_id,
                "message_id": message_id,
                "rating": rating,
            }
        )
        if comment:
            payload["comment"] = comment
        return self._request("POST", "/api/v1/campbell-ai/feedback", payload)
