"""Small server-to-server client for the Campbell AI internal API."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class CampbellAPIClientError(RuntimeError):
    """Error safe to surface in the Campbell AI Dash view."""


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
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self.internal_token:
            raise CampbellAPIClientError(
                "Campbell AI no tiene configurada su credencial interna"
            )

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
            with urlopen(request, timeout=self.timeout_seconds) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except HTTPError as exc:
            detail = ""
            try:
                detail = json.loads(exc.read().decode("utf-8")).get("detail", "")
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
            messages = {
                401: "La API de Campbell AI rechazó la credencial interna",
                403: "No tienes acceso a la empresa seleccionada",
                422: "La solicitud enviada a Campbell AI no es válida",
                503: "Campbell AI o sus datos no están disponibles",
            }
            raise CampbellAPIClientError(
                detail or messages.get(exc.code, "Campbell AI respondió con un error")
            ) from exc
        except (URLError, TimeoutError) as exc:
            raise CampbellAPIClientError(
                "No fue posible conectar con la API de Campbell AI"
            ) from exc

    @staticmethod
    def _identity(username: str, company_id: str) -> dict[str, str]:
        return {"username": username, "company_id": company_id}

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

    def history(
        self, username: str, company_id: str, session_id: str
    ) -> dict[str, Any]:
        payload = self._identity(username, company_id)
        payload["session_id"] = session_id
        return self._request("POST", "/api/v1/campbell-ai/history", payload)

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
