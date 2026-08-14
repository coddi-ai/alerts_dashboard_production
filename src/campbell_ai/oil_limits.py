"""Four-limit oil thresholds and element grouping, for Campbell AI's oil visuals.

The dashboard already owns this logic in ``dashboard/components/oil_charts.py`` and
``dashboard/callbacks/alerts_callbacks.py``. This module deliberately re-states the parts
Campbell AI needs instead of importing them, for a concrete deployment reason: the API
container mounts ``./src``, ``./config`` and ``./data``, but **not** ``./dashboard`` - that
package only reaches the image through the Dockerfile's ``COPY``. An import across that
boundary would work on a fresh build and then silently serve stale code the moment someone
edits the dashboard without rebuilding, because ``src`` is live-mounted and ``dashboard`` is
not. ``src`` has never imported from ``dashboard``; this keeps it that way.

The consequence is that the two copies can drift, so the pieces reproduced here are the ones
that are stable and few: the classification boundaries, the ring radii and the group split.
Anything richer stays in the dashboard.

Three ideas carry the whole module:

- **The four-limit contract (v2.8).** LIC/LIM/LSM/LSC bound five states: Normal, Inferior and
  Superior Marginal, Inferior and Superior Condenatorio. ``LIC``/``LIM`` are ``None`` for
  whole element groups (wear metals, additives) and a missing lower limit is never a lower
  limit of zero.
- **Normalization to fixed radii.** Every threshold lands on the same radius across axes, so
  the rings are circles. Scaling by a single threshold cannot do this: measured on CDA the
  ratio LSC/LSM spans 1.0 to 8.5, which would draw the outer ring as a jagged shape.
- **Element groups.** Wear metals, contaminants and additives answer different questions and
  are read separately in any oil report, so they get one radar each rather than sharing axes.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

import plotly.graph_objects as go

logger = logging.getLogger("campbell_ai.oil_limits")


# Reading order: what is wearing first, then what explains it.
OIL_GROUP_ORDER = ("Desgaste", "Contaminante", "Aditivo", "Fisico Quimico", "Conteo")

# Radii for the four thresholds on the 0-100 scale, matching the dashboard's radar.
RING_RADII = {"LIC": 20, "LIM": 40, "LSM": 60, "LSC": 80}

# Shared with the rest of the oil visuals: red for the condemning limit, orange for the
# marginal one, purple for anything on the lower side.
UPPER_LIMIT_COLOR = "#dc3545"
MARGINAL_LIMIT_COLOR = "orange"
LOWER_LIMIT_COLOR = "#6f42c1"

_RING_SPECS_WITH_LOWER = (
    (80, "LSC (Superior Condenatorio)", UPPER_LIMIT_COLOR),
    (60, "LSM (Superior Marginal)", MARGINAL_LIMIT_COLOR),
    (40, "LIM (Inferior Marginal)", LOWER_LIMIT_COLOR),
    (20, "LIC (Inferior Condenatorio)", LOWER_LIMIT_COLOR),
)
_RING_SPECS_UPPER_ONLY = _RING_SPECS_WITH_LOWER[:2]

_FILL_BY_STATUS = {
    "Anormal": "#dc3545",
    "Condenatorio": "#fd7e14",
    "Critico": "#dc3545",
    "Normal": "#28a745",
}

# Diagnostic pairs for the oil time-series grid, replicated from
# `dashboard/components/oil_charts.py::TIME_SERIES_CHARTS`.
#
# These are *not* the element groups. They are the pairs an analyst reads together: iron with
# the particle index (both say ferrous wear), silicon with aluminium (dirt ingress), sodium
# with potassium (coolant), soot with oxidation (oil condition). Splitting them by
# GroupElement instead would separate exactly the variables that only mean something side by
# side. The two additive panels are derived at render time from the spreadsheet.
OIL_TIME_SERIES_PAIRS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Hierro & PQ", ("Hierro", "Índice PQ")),
    ("Cobre & Estaño", ("Cobre", "Estaño")),
    ("Cromo & Plomo", ("Cromo", "Plomo")),
    ("Silicio & Aluminio", ("Silicio", "Aluminio")),
    ("Sodio & Potasio", ("Sodio", "Potasio")),
    ("Combustible & Agua", ("Combustible", "Agua")),
    ("Viscocidad", ("Viscocidad",)),
    ("Hollín & Oxidación", ("Hollín", "Oxidación")),
)

# Additives split into two panels so the lines stay readable; same split the dashboard uses.
PRIMARY_ADDITIVES = ("Calcio", "Zinc", "Fósforo")

# Colourblind-safe, for the additive panels which carry more series than a pair.
ADDITIVE_PALETTE = (
    "#0072B2", "#009E73", "#56B4E9", "#332288",
    "#44AA99", "#88CCEE", "#117733", "#999933",
)

# Essays that carry a limit but are keyed by code in essays_elements.xlsx, so they do not
# join by Spanish name. `Hollín` is absent from that file altogether and is grouped here.
_EXTRA_GROUPS = {
    "Viscocidad": "Fisico Quimico",   # V100
    "Índice PQ": "Fisico Quimico",    # PQI
    "Numero Total Basico": "Fisico Quimico",  # TBN
    "Oxidación": "Fisico Quimico",    # OXI (el .xlsx lo lista bajo "Conteo")
    "Hollín": "Contaminante",
}


@lru_cache(maxsize=4)
def oil_element_groups(essays_file: str = "data/oil/essays_elements.xlsx") -> dict[str, str]:
    """Map each essay name to its element group, from the shared spreadsheet.

    Cached because it is read on every radar render and the file changes about never. An
    unreadable file degrades to the manual overrides rather than failing the chart: a radar
    with fewer groups is worth more than an error.
    """
    groups: dict[str, str] = {}
    path = Path(essays_file)
    try:
        import pandas as pd

        frame = pd.read_excel(path).dropna(subset=["ElementNameSpanish", "GroupElement"])
        groups = {
            str(row["ElementNameSpanish"]): str(row["GroupElement"])
            for _, row in frame.iterrows()
        }
    except Exception:
        logger.warning(
            "No fue posible leer %s; se usan solo los grupos declarados en el codigo", path
        )
    groups.update(_EXTRA_GROUPS)
    return groups


def four_limit_for_essay(
    component_limits: dict[str, Any], essay: str, oil_hour_range: str
) -> Optional[dict[str, Any]]:
    """Thresholds for one essay, with the same oil-hour fallback the dashboard uses.

    Exact range, then ``ALL``, then the average across ranges. Falling back rather than
    returning nothing matters: a sample whose ``oilHourRange`` has no calibrated limits still
    has to be plotted against something, and the averaged band is closer to right than no
    band at all.
    """
    if not component_limits or essay not in component_limits:
        return None
    per_range = component_limits[essay]
    if not per_range:
        return None
    if oil_hour_range in per_range:
        return per_range[oil_hour_range]
    if "ALL" in per_range:
        return per_range["ALL"]

    averaged: dict[str, Any] = {}
    for key in ("LIC", "LIM", "LSM", "LSC"):
        values = [
            entry[key]
            for entry in per_range.values()
            if isinstance(entry, dict) and entry.get(key) is not None
        ]
        averaged[key] = sum(values) / len(values) if values else None
    return averaged if averaged.get("LSM") is not None else None


def classify_four_limit(value: float, lic, lim, lsm: float, lsc: float) -> str:
    """Five-tier classification of the v2.8 contract.

    Boundaries match ``dashboard/components/oil_charts.py::classify_four_limit_value``
    exactly; a value that reads "Superior Marginal" in the chat must not read "Normal" in the
    dashboard for the same sample.
    """
    has_lower = lic is not None and lim is not None
    if has_lower:
        if value < lic:
            return "Inferior Condenatorio"
        if value < lim:
            return "Inferior Marginal"
    if value <= lsm:
        return "Normal"
    if value <= lsc:
        return "Superior Marginal"
    return "Superior Condenatorio"


def normalize_four_limit(value: float, lic, lim, lsm: float, lsc: float) -> float:
    """Scale a measurement to 0-100 with each threshold pinned to its ring radius.

    Without lower limits the 0-60 stretch covers everything below LSM, which is why a wear
    radar shows two rings and a physico-chemical one shows four.
    """
    has_lower = lic is not None and lim is not None
    if has_lower:
        if value < lic:
            scaled = max((value / lic) * 20, 0.0) if lic else 0.0
        elif value < lim:
            scaled = 20 + (value - lic) / max(lim - lic, 1e-9) * 20
        elif value <= lsm:
            scaled = 40 + (value - lim) / max(lsm - lim, 1e-9) * 20
        elif value <= lsc:
            scaled = 60 + (value - lsm) / max(lsc - lsm, 1e-9) * 20
        else:
            scaled = min(80 + (value - lsc) / max(lsc, 1e-9) * 20, 100)
    else:
        if value <= lsm:
            scaled = (value / lsm) * 60 if lsm else 0.0
        elif value <= lsc:
            scaled = 60 + (value - lsm) / max(lsc - lsm, 1e-9) * 20
        else:
            scaled = min(80 + (value - lsc) / max(lsc, 1e-9) * 20, 100)
    return min(max(scaled, 0.0), 100)


def additive_panels(groups: dict[str, str]) -> list[tuple[str, tuple[str, ...]]]:
    """The two additive panels, derived from the spreadsheet like the dashboard does."""
    additives = [essay for essay, group in groups.items() if group == "Aditivo"]
    if not additives:
        return []
    primary = [essay for essay in PRIMARY_ADDITIVES if essay in additives]
    others = [essay for essay in sorted(additives) if essay not in primary]
    panels: list[tuple[str, tuple[str, ...]]] = []
    if primary:
        panels.append(("Aditivos: Calcio, Zinc & Fósforo", tuple(primary)))
    if others:
        panels.append(("Aditivos: Otros", tuple(others)))
    return panels


def build_oil_time_series_grid(
    history: "Any",
    component_limits: dict[str, Any],
    oil_hour_range: str,
    groups: dict[str, str],
    title: str,
) -> tuple[go.Figure, dict[str, Any]]:
    """The oil history as one figure of paired panels, with each essay's limits drawn.

    One figure rather than the dashboard's grid of separate charts, because an artifact
    carries a single figure: the pairs become subplots in the same two-column layout.

    A panel whose essays have no thresholds is still drawn. `Combustible` and `Agua` have no
    limits by contract, and showing the series without reference lines is the honest result;
    dropping the panel would suggest the data is missing when it is the threshold that is.
    """
    from plotly.subplots import make_subplots

    panels = [
        (title_panel, essays)
        for title_panel, essays in (*OIL_TIME_SERIES_PAIRS, *additive_panels(groups))
        if any(essay in history.columns and history[essay].notna().any() for essay in essays)
    ]
    if not panels:
        return go.Figure(), {"panels": []}

    columns = 2
    rows = (len(panels) + columns - 1) // columns
    figure = make_subplots(
        rows=rows, cols=columns,
        subplot_titles=[name for name, _ in panels],
        vertical_spacing=0.07, horizontal_spacing=0.09,
    )

    dates = history["sampleDate"]
    rendered: dict[str, list[str]] = {}
    limits_drawn: dict[str, float] = {}

    for index, (name, essays) in enumerate(panels):
        row, col = divmod(index, columns)
        row, col = row + 1, col + 1
        plotted: list[str] = []
        for position, essay in enumerate(essays):
            if essay not in history.columns or not history[essay].notna().any():
                continue
            plotted.append(essay)
            figure.add_trace(
                go.Scatter(
                    x=dates, y=history[essay], name=essay, mode="lines+markers",
                    line=dict(color=ADDITIVE_PALETTE[position % len(ADDITIVE_PALETTE)], width=1.6),
                    marker=dict(size=4),
                    legendgroup=name, showlegend=True,
                ),
                row=row, col=col,
            )
            thresholds = four_limit_for_essay(component_limits, essay, oil_hour_range)
            if not thresholds:
                continue
            for key, color in (("LSC", UPPER_LIMIT_COLOR), ("LIC", LOWER_LIMIT_COLOR)):
                value = thresholds.get(key)
                if value is None:
                    continue
                figure.add_hline(
                    y=float(value), row=row, col=col,
                    line=dict(color=color, width=1.1, dash="dash"),
                    annotation_text=f"{key} {essay}",
                    annotation_position="top right",
                    annotation_font=dict(size=9, color=color),
                )
                limits_drawn[f"{essay}.{key}"] = float(value)
        rendered[name] = plotted

    figure.update_layout(
        title=dict(text=title, x=0.5, xanchor="center", font=dict(size=15)),
        height=260 * rows,
        showlegend=False,
        margin=dict(l=55, r=45, t=90, b=45),
    )
    figure.update_annotations(font_size=11)
    return figure, {"panels": rendered, "limits": limits_drawn}


def build_four_limit_radar(
    axes: list[str],
    values: list[float],
    raw: list[float],
    statuses: list[str],
    group: str,
    has_lower: bool,
    report_status: str,
) -> go.Figure:
    """The dashboard's oil radar: threshold rings plus the sample, on a 0-100 scale."""
    figure = go.Figure()
    rings = _RING_SPECS_WITH_LOWER if has_lower else _RING_SPECS_UPPER_ONLY
    for radius, name, color in rings:
        figure.add_trace(
            go.Scatterpolar(
                r=[radius] * len(axes),
                theta=axes,
                name=name,
                line=dict(color=color, dash="dash", width=2),
                fill=None,
                mode="lines",
            )
        )

    fill_color = _FILL_BY_STATUS.get(report_status, "#17a2b8")
    figure.add_trace(
        go.Scatterpolar(
            r=values,
            theta=axes,
            name="Valores Actuales",
            line=dict(color=fill_color, width=3),
            fill="toself",
            fillcolor=fill_color,
            opacity=0.4,
            customdata=[[value, status] for value, status in zip(raw, statuses)],
            # The raw measurement leads the tooltip: the normalized radius exists to make the
            # rings readable, and is never the number to quote back to a user.
            hovertemplate=(
                "<b>%{theta}</b><br>Valor real: %{customdata[0]}"
                "<br>Estado: %{customdata[1]}"
                "<br>Normalizado: %{r:.1f}<extra></extra>"
            ),
        )
    )
    figure.update_layout(
        polar=dict(
            radialaxis=dict(
                visible=True,
                range=[0, 100],
                tickvals=[0, 25, 50, 75, 100],
                ticktext=["0", "25", "50", "75", "100"],
            ),
            angularaxis=dict(rotation=90, direction="clockwise"),
        ),
        title=dict(text=group, x=0.5, xanchor="center", font=dict(size=14)),
        showlegend=True,
        legend=dict(
            orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5,
            font=dict(size=10),
        ),
        height=400,
        margin=dict(l=50, r=50, t=50, b=80),
    )
    return figure
