"""Client-facing label normalization for dashboard entities."""

from __future__ import annotations

import re
from typing import Any


_COMPONENT_LABELS = {
    "engine": "Motor",
    "motor": "Motor",
    "post_engine": "Posterior al motor",
    "posterior_al_motor": "Posterior al motor",
    "rifle": "Conducto principal de aceite",
    "crankcase": "Cárter",
    "carter": "Cárter",
    "cárter": "Cárter",
    "lubrication": "Lubricación",
    "lubricacion": "Lubricación",
    "lubricación": "Lubricación",
}


def translate_component_label(value: Any) -> str:
    """Return a stable Spanish label while preserving unknown values.

    Source contracts may use English, Spanish, title case, spaces, or hyphens.
    The normalization is display-only; raw component values remain unchanged
    in the loaded data and are still used for joins and filters.
    """
    label = str(value or "").strip()
    if not label:
        return "Sin componente"

    key = re.sub(r"[\s-]+", "_", label.casefold())
    return _COMPONENT_LABELS.get(key, label)
