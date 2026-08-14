"""Campbell AI's signal vocabulary: readable names and diagnostic companions.

Two things live here, both about how a telemetry signal is *presented* rather than how it is
stored.

**Readable names.** The translation table itself is `src/charts/signals.py::SIGNAL_LABELS`,
shared with the dashboard, and this module does not touch it. It only wraps the lookup,
because `signal_label` returns ``None`` for a code it does not know: calling it directly puts
the literal string "None" on an axis. `signal_display_label` never does that.

**Companion signals.** `TRIGGER_COMPANION_SIGNALS` maps the variable that fired an alert to
the variables worth plotting beside it. An alert on coolant temperature is not read alone:
oil pressure, aftercooler temperature and the transmission and differential temperatures say
whether the engine is actually overheating or a sensor drifted. Reading a trigger without its
companions is how a single high reading turns into the wrong work order.

The map is placed here, next to the naming, because both answer "how do we show this signal
to a person" - and neither belongs in the shared chart library, which the dashboard also
imports and which this package does not own.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.graph_objects as go

from src.charts.signals import signal_label
from src.charts.theme import BRAND_ACCENT, STATUS_COLORS


# Signals the shared table has no entry for. All three are operational context rather than
# alarm variables - none of them carries a limit in `alerts_detail` - which is why they were
# never named there.
_EXTRA_LABELS = {
    "GroundSpd": "Velocidad de desplazamiento",
    "Payload": "Carga útil",
    "EngLoad": "Carga del motor",
}


# Trigger → signals to plot alongside it, in order of diagnostic relevance rather than
# alphabetically. An empty list means the signal is read on its own.
#
# Validated against CDA's `alerts_detail`: every key has a `<key>_Value` column, and every
# value that actually appears as a `Trigger` is a key here. Seven keys never fire as triggers
# (EngOilFltr, EngSpd, GroundSpd, LtExhTemp, Payload, RAftrclrTemp, RtExhTemp) and exist only
# as companions, which is expected.
TRIGGER_COMPANION_SIGNALS: dict[str, tuple[str, ...]] = {
    "AirFltr": ("RtExhTemp", "LtExhTemp", "RtLtExhTemp", "RAftrclrTemp"),
    "CnkcasePres": ("EngOilPres",),
    "DiffLubePres": ("DiffTemp", "TrnLubeTemp", "GroundSpd"),
    "DiffTemp": ("DiffLubePres", "TrnLubeTemp", "TCOutTemp", "EngCoolTemp"),
    "EngCoolTemp": ("EngOilPres", "RAftrclrTemp", "DiffTemp", "TrnLubeTemp", "TCOutTemp"),
    "EngOilFltr": ("EngCoolTemp", "EngOilPres", "CnkcasePres"),
    "EngOilPres": ("EngCoolTemp", "EngSpd", "EngOilFltr", "CnkcasePres"),
    "EngSpd": (),
    "GroundSpd": (),
    "LtExhTemp": ("RtExhTemp", "RtLtExhTemp", "RAftrclrTemp", "EngCoolTemp"),
    "LtFBrkTemp": ("RtRBrkTemp", "RtFBrkTemp", "LtRBrkTemp"),
    "LtRBrkTemp": ("RtRBrkTemp", "RtFBrkTemp", "LtFBrkTemp"),
    "Payload": (),
    "RAftrclrTemp": ("RtExhTemp", "LtExhTemp", "AirFltr"),
    "RtExhTemp": ("RtLtExhTemp", "LtExhTemp", "RAftrclrTemp", "EngCoolTemp"),
    "RtFBrkTemp": ("RtRBrkTemp", "LtRBrkTemp", "LtFBrkTemp"),
    "RtLtExhTemp": ("RtExhTemp", "LtExhTemp", "RAftrclrTemp", "EngCoolTemp"),
    "RtRBrkTemp": ("LtRBrkTemp", "RtFBrkTemp", "LtFBrkTemp"),
    "StrgOilTemp": ("EngCoolTemp",),
    "TCOutTemp": ("DiffTemp", "TrnLubeTemp"),
    "TrnLubeTemp": ("EngCoolTemp", "DiffTemp", "TCOutTemp"),
}


def signal_display_label(code: str) -> str:
    """Readable name for a signal code, never ``None`` and never empty.

    Falls back to the code itself: an axis reading "EngLoad" is worse than "Carga del motor"
    but far better than one reading "None", which is what the shared lookup returns for a
    code it has no entry for.
    """
    normalized = str(code or "").strip()
    if not normalized:
        return ""
    return signal_label(normalized) or _EXTRA_LABELS.get(normalized) or normalized


def companions_for(trigger: str, include_trigger: bool = True) -> list[str]:
    """Signals to plot for an alert fired by ``trigger``.

    The trigger leads, because it is the one to read first; the companions follow in the
    order declared above, which is an order of relevance. An unknown trigger yields just
    itself rather than nothing: a chart of the signal that fired is still the right answer,
    only without context.
    """
    normalized = str(trigger or "").strip()
    if not normalized:
        return []
    companions = list(TRIGGER_COMPANION_SIGNALS.get(normalized, ()))
    return ([normalized] + companions) if include_trigger else companions


_LIMIT_COLOR = STATUS_COLORS.get("Anormal", "#e74c3c")


def signal_limits(frame: pd.DataFrame, signal: str) -> dict[str, float]:
    """Upper and lower limit of a signal inside `alerts_detail`, whichever exist.

    Only 17 of the 22 signals carry an upper limit and just three carry a lower one - the
    pressures, which alarm on the low side. Temperatures alarm high, and `Payload`,
    `GroundSpd` and `EngLoad` carry none at all because they are operational context rather
    than alarm variables. A missing limit is therefore a fact about the signal, not a gap.
    """
    found: dict[str, float] = {}
    for label, suffix in (("superior", "_Upper_Limit"), ("inferior", "_Lower_Limit")):
        column = f"{signal}{suffix}"
        if column in frame.columns:
            values = pd.to_numeric(frame[column], errors="coerce").dropna()
            if not values.empty:
                found[label] = float(values.iloc[0])
    return found


def build_alert_context_panels(
    frame: pd.DataFrame,
    signals: list[str],
    trigger: str,
    alert_id: str,
    unit_id: str,
) -> tuple[go.Figure, dict[str, Any]]:
    """Trigger on top, companions below, one shared time axis and each limit drawn.

    Stacked panels rather than one axis: the signals are on incomparable scales (pressure in
    bar, temperature in degrees), so overlaying them would flatten whichever has the smaller
    range. A shared x-axis is what makes them comparable - the question is always whether the
    companion moved *at the same moment*.
    """
    from plotly.subplots import make_subplots

    time = frame["__time"] if "__time" in frame.columns else frame["TimeStart"]
    titles, limits = [], {}
    for signal in signals:
        bounds = signal_limits(frame, signal)
        limits[signal] = bounds
        marker = "GATILLO · " if signal == trigger else ""
        detail = (
            ", ".join(f"lím. {name}" for name in bounds) if bounds else "sin límite definido"
        )
        titles.append(f"{marker}{signal_display_label(signal)}  ({detail})")

    figure = make_subplots(
        rows=len(signals), cols=1, shared_xaxes=True, vertical_spacing=0.05,
        subplot_titles=titles,
    )
    for index, signal in enumerate(signals, start=1):
        is_trigger = signal == trigger
        figure.add_trace(
            go.Scatter(
                x=time,
                y=pd.to_numeric(frame[f"{signal}_Value"], errors="coerce"),
                name=signal_display_label(signal),
                mode="lines",
                line=dict(
                    width=2.4 if is_trigger else 1.5,
                    color=_LIMIT_COLOR if is_trigger else BRAND_ACCENT,
                ),
            ),
            row=index, col=1,
        )
        for label, value in limits[signal].items():
            figure.add_hline(
                y=value, row=index, col=1,
                line=dict(color=_LIMIT_COLOR, width=1.2, dash="dash"),
                annotation_text=f"{label} {value:g}",
                annotation_position="top left",
                annotation_font=dict(size=10, color=_LIMIT_COLOR),
            )

    figure.update_layout(
        title=dict(
            text=f"Alerta {alert_id} · {unit_id} · gatillo {signal_display_label(trigger)}",
            x=0.5, xanchor="center", font=dict(size=15),
        ),
        height=200 + 155 * len(signals),
        showlegend=False,
        margin=dict(l=60, r=45, t=95, b=45),
    )
    figure.update_annotations(font_size=11)
    return figure, {"limits": limits}
