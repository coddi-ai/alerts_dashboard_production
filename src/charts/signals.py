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

from collections.abc import Mapping
from types import MappingProxyType


# Signal code -> Spanish description. Kept in sync with
# dashboard/components/telemetry_charts.py's SIGNAL_TRANSLATION and
# dashboard/components/alerts_charts.py's FEATURE_NAMES_ES, which both re-export
# this exact object (`is`, not just `==` — see
# tests/test_campbell_ai_grounding.py::test_dashboard_and_agents_share_the_signal_catalogue)
# as their single source of truth — do not let the two drift apart again.
#
# W34-11: this used to be a plain, mutable dict, and alerts_charts.py injected
# Capstone's ~40 canonical signal codes into it via `FEATURE_NAMES_ES.update(...)`
# at import time. Because `FEATURE_NAMES_ES is SIGNAL_LABELS`, that mutated the
# catalogue every other importer (Campbell AI included) sees, with the final
# contents depending on *import order* — whichever module ran its `.update()`
# last effectively decided what the whole app considers "catalogued". The
# Capstone codes are merged in below instead, and the exported name is a
# read-only view so the mistake can't be repeated: any `.update()`/`__setitem__`
# against `SIGNAL_LABELS` (or `FEATURE_NAMES_ES`, the same object) now raises
# `TypeError` instead of silently mutating shared state.
_SIGNAL_LABELS: dict[str, str] = {
    "EngCoolTemp": "Temperatura del refrigerante del motor",
    "EngOilPres": "Presión de aceite del motor",
    "EngOilFltr": "Filtro de aceite del motor",
    "EngSpd": "Velocidad del motor",
    "TCOutTemp": "Temperatura de salida del convertidor de torque",
    "RAftrclrTemp": "Temperatura del posenfriador derecho",
    "LtExhTemp": "Temperatura de escape izquierda",
    "RtExhTemp": "Temperatura de escape derecha",
    "RtLtExhTemp": "Diferencia de temperatura de escape (derecha-izquierda)",
    # W34-12: DeltaExh (telemetry-only code) confirmed by domain decision to be
    # the same concept as RtLtExhTemp, just a different code from the raw
    # telemetry column names — same label, not a separate catalogued entry.
    "DeltaExh": "Diferencia de temperatura de escape (derecha-izquierda)",
    "AirFltr": "Restricción del filtro de aire",
    "CnkcasePres": "Presión del cárter",
    "CompInPres1": "Presión de entrada del compresor 1",
    "CompInPres2": "Presión de entrada del compresor 2",
    "TrboInPres": "Presión de entrada del turbocompresor",
    "TrboOutPres": "Presión de salida del turbocompresor",
    "TrnLubeTemp": "Temperatura del aceite de transmisión",
    "LckupSlip": "Deslizamiento del embrague de bloqueo",
    "TrnSlip": "Deslizamiento de la transmisión",
    "TrnGear": "Marcha de la transmisión",
    "GearSelect": "Selección de marcha",
    "DiffTemp": "Temperatura del diferencial",
    "DiffLubePres": "Presión de lubricación del diferencial",
    "LtFBrkTemp": "Temperatura del freno delantero izquierdo",
    "RtFBrkTemp": "Temperatura del freno delantero derecho",
    "LtRBrkTemp": "Temperatura del freno trasero izquierdo",
    "RtRBrkTemp": "Temperatura del freno trasero derecho",
    "StrgOilTemp": "Temperatura del aceite de dirección",
    # Tribology variables that can appear alongside a telemetry signal in a
    # mixed-trigger alert. Mapped to themselves: already Spanish, listed here so
    # describe_signals()/signal_label() recognize them as catalogued.
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
    # Capstone canonical signal names (QSK60 source, snake_case, temperatures in
    # Celsius). Additive: none of these keys collide with the CDA-style codes
    # above, and none of the established CDA labels change. Moved here from
    # dashboard/components/alerts_charts.py's `FEATURE_NAMES_ES.update()` call
    # (W34-11) so the catalogue has exactly one definition instead of a static
    # base plus a runtime patch.
    "engine_speed_rpm": "Velocidad del motor",
    "engine_load_pct": "Carga del motor",
    "coolant_temp_c": "Temperatura del refrigerante",
    "coolant_pressure_psi": "Presión del refrigerante",
    "ecu_temp_c": "Temperatura de la ECU",
    "crankcase_pressure_inh2o": "Presión del cárter",
    "compressor_intake_temp_c": "Temperatura de admisión del compresor",
    "turbo_speed_rpm": "Velocidad del turbo",
    "oil_filter_dp_psi": "Presión diferencial del filtro de aceite",
    "oil_filter_dp_mcrs_psi": "Presión diferencial del filtro de aceite (MCRS)",
    "oil_temp_c": "Temperatura del aceite",
    "fuel_pump_intake_pressure_psi": "Presión de admisión de la bomba de combustible",
    # W34-12 (Fase 9 follow-up): confirmed distinct from oil_filter_dp_psi
    # above — that one is the filter's differential pressure specifically;
    # this one is the engine oil's differential pressure. Both used to
    # collide on "...del filtro de aceite" after the original W34-12 domain
    # decision, before this distinction was confirmed.
    "oil_diff_pressure_psi": "Presión diferencial del aceite de motor",
    "pre_filter_oil_pressure_psi": "Presión de aceite pre-filtro",
    "rifle_oil_pressure_psi": "Presión de aceite del rifle",
    "post_engine_pressure_psi": "Presión de aceite post-motor",
    "oil_level_pct": "Nivel de aceite",
    "oil_priming_state": "Estado de cebado del aceite",
    "fan_speed_rpm": "Velocidad del ventilador",
    "power_hp": "Potencia del motor",
    "imp_lb_psi": "Presión de admisión banco izquierdo",
    "imp_rb_psi": "Presión de admisión banco derecho",
    "imt_lbf_c": "Temperatura de admisión banco izquierdo frontal",
    "imt_lbr_c": "Temperatura de admisión banco izquierdo trasero",
    "imt_rbf_c": "Temperatura de admisión banco derecho frontal",
    "imt_rbr_c": "Temperatura de admisión banco derecho trasero",
    "egt_avg_c": "Temperatura promedio de gases de escape",
    "egt_lb_c": "Temperatura de escape banco izquierdo",
    "egt_rb_c": "Temperatura de escape banco derecho",
    **{f"egt_{index:02d}_c": f"Temperatura de escape cilindro {index:02d}" for index in range(1, 17)},
}

# Read-only view: the single source of truth for signal labels, shared by
# Alertas, Telemetría and Campbell AI. See the W34-11 note above `_SIGNAL_LABELS`
# for why this must never be a plain mutable dict again.
SIGNAL_LABELS: Mapping[str, str] = MappingProxyType(_SIGNAL_LABELS)

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
