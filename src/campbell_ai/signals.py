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

import unicodedata
from typing import Any

import pandas as pd
import plotly.graph_objects as go

from src.campbell_ai.errors import CampbellDataError
from src.charts.signals import signal_label
from src.charts.theme import BRAND_ACCENT, CATEGORICAL_COLORS, STATUS_COLORS


# Candidate columns, across both telemetry sources. The alert evidence names them in English
# (`State`, `SubState`); the raw weekly source - which lives in a directory literally called
# `Telemetry_Wide_With_States` - names them in Spanish (`Estado`, `EstadoMaquina`).
#
# The order here is a starting point, not the decision: which column is the *operating* state
# differs by client. For CDA `Estado` holds Operacional / Ralenti, while for capstone the same
# column holds HABILITADO / PREPARACION / RPM_BAJA - a gate state, unrelated to whether the
# machine is working - and it is `EstadoMaquina` that carries Potencia / Ralenti / Transicion.
# `state_column` resolves that from the values, not from the name.
STATE_COLUMNS: tuple[str, ...] = ("State", "Estado", "SubState", "EstadoMaquina")

# Colours for the operating states seen in the data. Deliberately semantic rather than
# arbitrary: the question the colour answers is "was the machine actually working when this
# reading was taken", and a high temperature at idle means something different from the same
# temperature under load.
#
# The vocabulary is per client, not global: CDA reports Operacional / Ralenti / ND, capstone
# reports Potencia / Transicion / Ralenti and carries no `PayloadState` at all. Anything not
# listed here still gets a stable colour from `CATEGORICAL_COLORS`, so a client with a third
# vocabulary renders with a full legend instead of silently collapsing to one colour.
STATE_COLORS: dict[str, str] = {
    "Operacional": "#28a745",
    "Potencia": "#28a745",
    "Ralenti": "#fd7e14",
    "Ralentí": "#fd7e14",
    "Transicion": "#3498db",
    "Transición": "#3498db",
    # Undetermined. Blue rather than grey, but a desaturated one: `Transicion` - a real capstone
    # state - already holds the bright accent blue, and two blues that read as the same colour
    # would be worse than the grey this replaced.
    "ND": "#5b8ba8",
}

# Same colour for the undetermined state whatever it is called, so a client that writes it as an
# empty cell and one that writes "ND" look alike.
UNDETERMINED_STATE_COLOR = STATE_COLORS["ND"]

# Shown when the state column exists but the value is empty. Named rather than dropped: a gap
# in the state is itself evidence, and silently plotting those samples in the colour of the
# previous state would be a fabrication.
UNKNOWN_STATE_LABEL = "Sin dato"

# The triggering signal gets its own hue family, so the panel that caused the alert is
# identifiable at a glance and not just by reading the subplot title. Saturated reds and oranges
# against the companions' status palette (green for working, amber for idle), which keeps the
# reading "this is the one that fired" separate from "this is what the machine was doing".
#
# One entry per semantic class, not per state, and not one flat colour either: the state
# distinction is the point of the colour in the first place, and losing it on the most important
# panel would be a strange trade. When two distinct states fall in the same class, the second
# gets a lighter tint of it - see `_lighten` - because two legend entries in one colour read as
# a rendering bug.
#
# The trigger's working red sits close to the upper limit's red, and that proximity is measured
# rather than assumed: ~81 on a redmean scale where confusion starts around 60, with the limit
# further separated by being dashed and half the width. Close enough to be worth re-checking if
# either colour moves; not close enough to be a problem today.
TRIGGER_STATE_COLORS: dict[str, str] = {
    "activo": "#e01b1b",
    "ralenti": "#ec954d",
    # Undetermined. A deeper tone of the same blue the companions use for it, so "no se sabe"
    # reads the same on the trigger as anywhere else instead of joining the alarm family.
    "otro": "#1f4e79",
}

# Limits get separate colours by side, because one shared colour left the legend unable to tell
# them apart.
#
# Lower is purple, which is the convention the rest of the repository already uses for a lower
# limit (`oil_limits.py`, `dashboard/components/oil_charts.py`). It was orange here, which both
# diverged from that and collided: with the trigger drawn in dark orange at idle and the idle
# state itself in orange, a third orange line was one too many to read.
UPPER_LIMIT_COLOR = STATUS_COLORS.get("Anormal", "#dc3545")
LOWER_LIMIT_COLOR = "#6f42c1"

# Marker for the moment the alert fired. The window extends about an hour past it, so without
# this the reader cannot tell which part of the curve is the alert and which is what came after.
ALERT_MARK_COLOR = "#2c3e50"


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


def signal_limit_series(frame: pd.DataFrame, signal: str) -> dict[str, pd.Series]:
    """Upper and lower limit of a signal as series over time, not as single numbers.

    Most limits are constant for the length of an alert - 17 of the 20 that appear in CDA's
    evidence - and for those this returns a flat series that draws as a straight line, which
    is what a fixed threshold should look like.

    The other three are not constant, and that is the reason this exists.
    ``EngOilPres_Lower_Limit`` is a function of engine speed: it moves on *every* episode that
    carries it, taking up to 149 distinct values inside a single seven-hour window. Drawing it
    from one sampled value - which is what a horizontal line does - puts the threshold in the
    wrong place for most of the chart, and the whole point of the panel is to show when the
    reading crossed it.
    """
    found: dict[str, pd.Series] = {}
    for label, suffix in (("superior", "_Upper_Limit"), ("inferior", "_Lower_Limit")):
        column = f"{signal}{suffix}"
        if column in frame.columns:
            values = pd.to_numeric(frame[column], errors="coerce")
            if values.notna().any():
                found[label] = values
    return found


def _fold(text: object) -> str:
    """Lower-case and strip accents, so `Ralentí` and `Ralenti` are the same word."""
    normalized = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).strip().lower()


def _lighten(color: str, amount: float) -> str:
    """Move a hex colour toward white by ``amount`` (0 leaves it untouched, 1 is white)."""
    if amount <= 0:
        return color
    raw = color.lstrip("#")
    channels = (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    blended = tuple(
        min(255, round(value + (255 - value) * min(1.0, amount))) for value in channels
    )
    return "#%02x%02x%02x" % blended


def state_kind(state: str) -> str:
    """Classify a state as ``activo``, ``ralenti`` or ``otro``.

    Substring matching on the folded value rather than a lookup table, because the vocabularies
    do not enumerate: CDA alone ships `Ralenti`, `Ralenti Alto` and `Ralenti Bajo` for the same
    condition, capstone writes it with an accent, and both name the working state differently
    (`Operacional`, `Potencia`). What every vocabulary shares is the word for idle.
    """
    folded = _fold(state)
    if not folded or folded in {"nd", _fold(UNKNOWN_STATE_LABEL)}:
        return "otro"
    if "ralent" in folded:
        return "ralenti"
    return "activo"


def state_column(frame: pd.DataFrame) -> str:
    """Name of the column that carries the *operating* state, or "" if none does.

    Resolved from the values, not the column name: a candidate only qualifies if it actually
    distinguishes idle from working, which is the single distinction the colour exists to show.
    `Estado` holds that for CDA and something unrelated for capstone (HABILITADO / PREPARACION),
    so picking by name would silently colour capstone by a gate state.

    Falls back to the first populated candidate when none names idle - a window where the
    machine simply never idled is normal, and refusing to colour it would be wrong too.
    """
    populated = [
        candidate
        for candidate in STATE_COLUMNS
        if candidate in frame.columns and frame[candidate].notna().any()
    ]
    for candidate in populated:
        values = frame[candidate].dropna().unique()
        if any(state_kind(value) == "ralenti" for value in values):
            return candidate
    return populated[0] if populated else ""


def state_series(frame: pd.DataFrame) -> pd.Series:
    """The operating state per sample, normalized and never null."""
    column = state_column(frame)
    if not column:
        return pd.Series(UNKNOWN_STATE_LABEL, index=frame.index, dtype=object)
    values = frame[column].astype("string").str.strip()
    return values.replace({"": pd.NA}).fillna(UNKNOWN_STATE_LABEL).astype(object)


def state_palette(states: list[str], *, highlight: bool = False) -> dict[str, str]:
    """A colour per state. ``highlight`` switches to the triggering signal's hue family.

    Exact value, then the same value ignoring accents, then a spare colour. Deliberately *not*
    falling back to the semantic class here: `Ralenti Alto` and `Ralenti Bajo` are both idle, and
    giving them the class colour would put two legend entries on screen in the same colour -
    which is worse than an unexpected hue, because it reads as a rendering bug.

    The semantic class does drive ``highlight``, where collapsing is the whole intent: the
    triggering signal is one hue family in two tints, working and idle.
    """
    if highlight:
        # Lightened per repeat within a class, so capstone - whose `Potencia` and `Transicion`
        # are both working states - gets two distinguishable tints instead of one colour under
        # two legend entries.
        highlighted: dict[str, str] = {}
        seen_kinds: dict[str, int] = {}
        for state in states:
            kind = state_kind(state)
            repeat = seen_kinds.get(kind, 0)
            seen_kinds[kind] = repeat + 1
            highlighted[state] = _lighten(TRIGGER_STATE_COLORS[kind], 0.28 * repeat)
        return highlighted

    folded = {_fold(known): color for known, color in STATE_COLORS.items()}
    palette: dict[str, str] = {}
    spare = [color for color in CATEGORICAL_COLORS if color not in STATE_COLORS.values()]
    for state in states:
        if state in STATE_COLORS:
            palette[state] = STATE_COLORS[state]
        elif _fold(state) in folded:
            palette[state] = folded[_fold(state)]
        elif state_kind(state) == "otro":
            palette[state] = UNDETERMINED_STATE_COLOR
        else:
            # Assigned by position, so the same client always gets the same colours across
            # calls rather than colours that depend on row order.
            palette[state] = spare[len(palette) % len(spare)]
    return palette


def _state_masked(values: pd.Series, states: pd.Series, state: str) -> pd.Series:
    """`values` with everything outside `state` blanked, plus one sample of overlap.

    Blanking is what breaks the line into coloured runs: Plotly lifts the pen at a gap, so a
    trace per state draws only that state's stretches and needs no segment bookkeeping.

    The overlap matters. Without it every transition leaves a one-sample hole and a chart with
    sixty state changes - the median for these alerts - reads as a dashed line rather than a
    continuous signal. Extending each run to the first sample of the next one closes the hole
    from the left, so consecutive runs meet instead of nearly touching.
    """
    belongs = states == state
    return values.where(belongs | belongs.shift(-1, fill_value=False))


def _legend_gate(seen: set[str], key: str) -> bool:
    """True the first time ``key`` is asked for, False after.

    The legend must show every distinct series *once*, wherever it first appears. Keying it to
    the first panel instead - which is what this replaced - meant a lower limit that only exists
    on the third signal never got a legend entry at all, and the reader had no way to tell which
    dashed line was which.
    """
    if key in seen:
        return False
    seen.add(key)
    return True


def _add_state_line(
    figure: go.Figure,
    *,
    row: int,
    times: Any,
    values: pd.Series,
    states: pd.Series,
    palette: dict[str, str],
    order: list[str],
    width: float,
    label: str,
    prefix: str,
    seen: set[str],
) -> None:
    """One trace per state, so the line's colour is the machine's operating state.

    An empty state means the source did not compute one. The trace then carries the signal's
    own name instead, and the hover drops the state line: there is nothing true to put there.
    """
    for state in order:
        name = f"{prefix}{state}" if state else label
        suffix = f"<br>{state}" if state else ""
        figure.add_trace(
            go.Scatter(
                x=times,
                y=_state_masked(values, states, state),
                name=name,
                legendgroup=name,
                showlegend=_legend_gate(seen, name),
                mode="lines",
                line=dict(width=width, color=palette[state]),
                connectgaps=False,
                hovertemplate=(
                    f"%{{x|%d-%m %H:%M}}<br>{label}: %{{y:.4~g}}{suffix}<extra></extra>"
                ),
            ),
            row=row,
            col=1,
        )


def build_state_signal_panels(
    panels: list[dict[str, Any]],
    *,
    title: str,
    subtitle: str = "",
    alert_time: Any = None,
) -> go.Figure:
    """Stacked signal panels, each line coloured by the machine's operating state.

    The one builder behind every telemetry figure Campbell AI produces - the alert context, the
    triggering signal on its own, and a free-standing series - so the state colouring, the
    legend and the alert marker cannot drift between them.

    Each panel is ``{"signal", "label", "times", "values", "states", "upper", "lower",
    "highlight"}``. ``highlight`` marks the signal that fired the alert, drawn in its own hue
    family. ``upper``/``lower`` are series, not scalars: most limits hold one value for the whole
    window and draw flat, but some are a function of engine speed and move within it.

    Panels whose signal has no readings must be filtered out by the caller; an empty panel is a
    blank band that reads as broken rendering rather than as missing data.
    """
    from plotly.subplots import make_subplots

    if not panels:
        return go.Figure()

    figure = make_subplots(
        rows=len(panels),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=min(0.06, 0.30 / len(panels)),
        subplot_titles=[panel.get("label") or panel["signal"] for panel in panels],
    )

    seen: set[str] = set()
    for row, panel in enumerate(panels, start=1):
        times = panel["times"]
        values = pd.Series(panel["values"]).reset_index(drop=True)
        raw_states = panel.get("states")
        states = (
            pd.Series(list(raw_states)).reset_index(drop=True)
            if raw_states is not None
            else pd.Series([UNKNOWN_STATE_LABEL] * len(values))
        )
        highlight = bool(panel.get("highlight"))
        # Ordered by coverage, so the legend reads as a summary of the window and the dominant
        # state is not listed under a two-sample outlier.
        order = list(states.value_counts().index)

        # When nothing is known about the state, say nothing about it. Colouring the whole
        # series grey and putting a lone "ND" in the legend claims the machine was in a state
        # called ND; it was not - the state simply was not computed. One unit in CDA is like
        # this for 100% of its samples, and the chart read as broken rather than as incomplete.
        if all(state_kind(state) == "otro" for state in order):
            order = [""]
            palette = {"": TRIGGER_STATE_COLORS["activo"] if highlight else BRAND_ACCENT}
            states = pd.Series([""] * len(values))
        else:
            palette = state_palette(order, highlight=highlight)

        _add_state_line(
            figure,
            row=row,
            times=times,
            values=values,
            states=states,
            palette=palette,
            order=order,
            width=2.6 if highlight else 1.5,
            label=panel.get("hover_label") or panel.get("label") or panel["signal"],
            prefix="Gatillo · " if highlight else "",
            seen=seen,
        )

        for side, color, name in (
            ("upper", UPPER_LIMIT_COLOR, "Límite superior"),
            ("lower", LOWER_LIMIT_COLOR, "Límite inferior"),
        ):
            series = panel.get(side)
            if series is None or not len(pd.Series(list(series)).dropna()):
                continue
            figure.add_trace(
                go.Scatter(
                    x=times,
                    y=list(series),
                    name=name,
                    legendgroup=name,
                    showlegend=_legend_gate(seen, name),
                    mode="lines",
                    # Held between samples rather than interpolated: a threshold changes at a
                    # moment and stays put, so a sloped segment would claim values it never took.
                    line=dict(color=color, width=1.3, dash="dash", shape="hv"),
                    hovertemplate=f"{name}: %{{y:.4~g}}<extra></extra>",
                ),
                row=row,
                col=1,
            )

    if alert_time is not None and pd.notna(alert_time):
        # Drawn across every panel so the instant lines up vertically with each signal. The
        # window runs about an hour past the alert, so without this the reader cannot separate
        # what led to it from what followed.
        figure.add_vline(
            x=alert_time,
            line=dict(color=ALERT_MARK_COLOR, width=1.6, dash="dot"),
            annotation_text="alerta",
            annotation_position="top left",
            annotation_font=dict(size=10, color=ALERT_MARK_COLOR),
        )

    figure.update_layout(
        title=dict(
            text=title if not subtitle else f"{title}<br><sub>{subtitle}</sub>",
            x=0.5,
            xanchor="center",
            font=dict(size=15),
        ),
        height=200 + 155 * len(panels),
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
            font=dict(size=11),
        ),
        margin=dict(l=60, r=45, t=115, b=45),
    )
    figure.update_annotations(font_size=11)
    return figure


def build_alert_context_panels(
    frame: pd.DataFrame,
    signals: list[str],
    trigger: str,
    alert_id: str,
    unit_id: str,
) -> tuple[go.Figure, dict[str, Any]]:
    """The trigger and its companion signals, on one time axis, coloured by machine state.

    Stacked panels rather than one axis: the signals are on incomparable scales (pressure in
    bar, temperature in degrees), so overlaying them would flatten whichever has the smaller
    range. A shared x-axis is what makes them comparable - the question is always whether the
    companion moved *at the same moment*.

    The colour carries the operating state, because the same reading means different things
    depending on it: engine temperature climbing under load is the machine working, the same
    curve at idle is a cooling problem. That fact is in the evidence for every sample, and
    plotting the signal without it discards the context that decides the diagnosis.

    Signals with no readings in this alert are dropped rather than drawn empty. The companion
    list comes from the trigger, not from the data, so a signal this machine simply does not
    report is expected - and a blank panel would read as a broken chart instead of an absence.
    """
    time = frame["__time"] if "__time" in frame.columns else frame["TimeStart"]
    states = state_series(frame)

    panels: list[dict[str, Any]] = []
    dropped: list[str] = []
    limits: dict[str, dict[str, float]] = {}
    varying: list[str] = []
    for signal in signals:
        column = f"{signal}_Value"
        values = (
            pd.to_numeric(frame[column], errors="coerce")
            if column in frame.columns
            else None
        )
        if values is None or not values.notna().any():
            dropped.append(signal)
            continue
        series = signal_limit_series(frame, signal)
        limits[signal] = signal_limits(frame, signal)
        if any(value.nunique(dropna=True) > 1 for value in series.values()):
            varying.append(signal)
        detail = ", ".join(f"lím. {name}" for name in series) or "sin límite definido"
        marker = "GATILLO · " if signal == trigger else ""
        panels.append(
            {
                "signal": signal,
                # The subplot title carries the trigger marker and which limits exist; the hover
                # keeps the plain signal name, where that extra text would only be noise.
                "label": f"{marker}{signal_display_label(signal)}  ({detail})",
                "hover_label": signal_display_label(signal),
                "times": time,
                "values": values,
                "states": states,
                "upper": series.get("superior"),
                "lower": series.get("inferior"),
                "highlight": signal == trigger,
            }
        )

    if not panels:
        raise CampbellDataError(
            f"Ninguna señal de {signal_display_label(trigger)} tiene valores capturados "
            f"en la alerta {alert_id}"
        )

    alert_time = None
    if "Alert_TimeStart" in frame.columns:
        stamps = pd.to_datetime(frame["Alert_TimeStart"], errors="coerce").dropna()
        if not stamps.empty:
            alert_time = stamps.iloc[0]

    figure = build_state_signal_panels(
        panels,
        title=f"Alerta {alert_id} · {unit_id} · gatillo {signal_display_label(trigger)}",
        alert_time=alert_time,
    )

    counts = states.value_counts()
    return figure, {
        "limits": limits,
        "limits_vary": sorted(varying),
        "state_column": state_column(frame),
        "state_share_pct": {
            state: round(float(counts[state]) / float(len(states)) * 100, 1)
            for state in counts.index
        },
        "signals_plotted": [panel["signal"] for panel in panels],
        "signals_without_values": dropped,
        "alert_time": alert_time.isoformat() if alert_time is not None else "",
    }
