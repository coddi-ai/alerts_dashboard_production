"""Canonical catalogue of telemetry signal names.

The datasets store signal codes (`EngCoolTemp`, `AirFltr`) and never a human label
or a unit of measure. This module is the project's authoritative mapping from code
to Spanish description, shared by the dashboard charts and Campbell AI so neither
has to guess.

**Units are deliberately absent.** No dataset in this repository publishes a unit
of measure for any signal, so there is nothing to read. An agent that writes "°C"
or "kPa" is asserting model knowledge as if it were a measurement, which is exactly
what must not happen: a wrong unit turns a correct reading into a wrong diagnosis.
If units become available upstream, add them here and the agents can cite them.
"""

from __future__ import annotations


# Signal code -> Spanish description. Mirrors the labels the alerts tab renders.
SIGNAL_LABELS: dict[str, str] = {
    "EngCoolTemp": "Temperatura del refrigerante del motor",
    "RAftrclrTemp": "Temperatura del post-enfriador del motor",
    "EngOilPres": "Presión del aceite del motor",
    "EngOilFltr": "Estado del filtro de aceite del motor",
    "CnkcasePres": "Presión del cárter del motor",
    "RtLtExhTemp": "Diferencia de temperatura del escape derecho e izquierdo",
    "RtExhTemp": "Temperatura del escape derecho del motor",
    "LtExhTemp": "Temperatura del escape izquierdo del motor",
    "AirFltr": "Estado del filtro de aire del motor",
    "DiffLubePres": "Presión del lubricante del diferencial",
    "DiffTemp": "Temperatura del diferencial",
    "TrnLubeTemp": "Temperatura del lubricante de la transmisión",
    "TCOutTemp": "Temperatura de salida del convertidor de par",
    "RtRBrkTemp": "Temperatura del freno trasero derecho",
    "RtFBrkTemp": "Temperatura del freno delantero derecho",
    "LtRBrkTemp": "Temperatura del freno trasero izquierdo",
    "LtFBrkTemp": "Temperatura del freno delantero izquierdo",
    "StrgOilTemp": "Temperatura del aceite de dirección",
    "EngSpd": "Velocidad del motor",
    "LckupSlip": "Deslizamiento del embrague de bloqueo",
    "TrnSlip": "Deslizamiento de la transmisión",
    # Tribology variables that can appear alongside a telemetry signal in a
    # mixed-trigger alert.
    "Hierro": "Hierro",
    "Aluminio": "Aluminio",
    "Zinc": "Zinc",
    "Calcio": "Calcio",
    "Fósforo": "Fósforo",
    "Índice PQ": "Índice PQ",
    "Oxidación": "Oxidación",
    "Hollín": "Hollín",
    "Silicio": "Silicio",
    "Potasio": "Potasio",
    "Níquel": "Níquel",
    "Cobre": "Cobre",
    "Cromo": "Cromo",
    "Plomo": "Plomo",
    "Estaño": "Estaño",
}

# Signals the dashboard omits from its views.
OMITTED_SIGNALS: tuple[str, ...] = ("GroundSpd", "EngLoad")


def signal_label(code: str) -> str | None:
    """Spanish description for a signal code, or None when it is not catalogued."""
    return SIGNAL_LABELS.get(str(code or "").strip())


def describe_signals(codes: list[str] | None = None) -> dict[str, dict[str, object]]:
    """Describe signals, stating explicitly that no unit of measure is available."""
    selected = (
        [str(code).strip() for code in codes if str(code or "").strip()]
        if codes
        else sorted(SIGNAL_LABELS)
    )
    described: dict[str, dict[str, object]] = {}
    for code in selected:
        label = signal_label(code)
        described[code] = {
            "label": label,
            "catalogued": label is not None,
            # Repeated per signal on purpose: the agent sees the absence at the point
            # of use, not only in a prompt it may have drifted from.
            "unit": None,
            "unit_note": "La fuente no publica unidad de medida; no la infieras.",
        }
    return described
