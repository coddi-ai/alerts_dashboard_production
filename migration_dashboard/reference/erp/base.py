"""ERP adapter interface (TRD §5.6, REQ-013)."""
from __future__ import annotations

from agent.envelope import Warning


class ERPAdapter:
    def build_payload(self, warning: Warning) -> dict:
        """Translate a validated Warning into the ERP-specific request payload."""
        raise NotImplementedError

    def parse_response(self, response: dict) -> str:
        """Extract the ERP reference number from the ERP's response."""
        raise NotImplementedError
