"""Single Plotly theme shared by the dashboard tabs and Campbell AI.

This module is the one source of truth for the accent, typography, axes and the
status design language (GR-05). It lives under `src/` rather than `dashboard/` so
the FastAPI service can import it without pulling in Dash.

`dashboard/components/charts.py` re-exports `STATUS_COLORS` from here, so a figure
rendered inside the chat and one rendered in a tab agree on what "Anormal" looks
like. Some older modules still carry their own local palette; see
`src/campbell_ai/README.md` for the remaining divergence.
"""

from __future__ import annotations

from typing import Any

import plotly.graph_objects as go


# Brand surface colors, taken from the dashboard navbar and chart modules.
BRAND_DARK = "#1a252f"
BRAND_ACCENT = "#3498db"
BRAND_TITLE = "#2c3e50"
BRAND_MUTED = "#7f8c8d"
BRAND_GRID = "#ecf0f1"
BRAND_AXIS = "#dfe4e6"
BRAND_SURFACE = "#ffffff"
FONT_FAMILY = "Arial, Helvetica, sans-serif"

# Status language shared with the dashboard (GR-05: one status design language).
STATUS_COLORS: dict[str, str] = {
    "Normal": "#28a745",
    "Alerta": "#ffc107",
    "Anormal": "#dc3545",
    "Critico": "#dc3545",
    "Crítico": "#dc3545",
    "Insuficiente": "#6c757d",
    "InsufficientData": "#6c757d",
    "Saludable": "#28a745",
    "Monitoreo": "#ffc107",
    "Prioridad alta": "#fd7e14",
    "Sin información": "#adb5bd",
}

# Mining system colors already used by the alerts tab.
SYSTEM_COLORS: dict[str, str] = {
    "Tren de Fuerza": "#1f77b4",
    "Tren de fuerza": "#1f77b4",
    "Motor": "#ff7f0e",
    "Frenos": "#2ca02c",
    "Direccion": "#d62728",
    "Dirección": "#d62728",
}

# Categorical sequence for dimensions with no semantic color.
CATEGORICAL_COLORS: tuple[str, ...] = (
    "#3498db",
    "#2c3e50",
    "#16a085",
    "#f39c12",
    "#8e44ad",
    "#e74c3c",
    "#27ae60",
    "#d35400",
    "#2980b9",
    "#7f8c8d",
)

# Sequential scale for heatmaps, anchored on the dashboard accent instead of Viridis.
SEQUENTIAL_SCALE: tuple[tuple[float, str], ...] = (
    (0.0, "#f7fbff"),
    (0.25, "#d6e9f8"),
    (0.5, "#9ecae8"),
    (0.75, "#4a9fd8"),
    (1.0, "#1a5f8f"),
)

CUMULATIVE_LINE = "#e74c3c"


def status_palette(labels: list[str]) -> list[str]:
    """Colors for a status-like dimension, falling back to the categorical sequence."""
    colors: list[str] = []
    for index, label in enumerate(labels):
        colors.append(
            STATUS_COLORS.get(str(label))
            or SYSTEM_COLORS.get(str(label))
            or CATEGORICAL_COLORS[index % len(CATEGORICAL_COLORS)]
        )
    return colors


def is_semantic_dimension(labels: list[str]) -> bool:
    """True when most labels carry a shared status or system meaning."""
    if not labels:
        return False
    known = sum(
        1
        for label in labels
        if str(label) in STATUS_COLORS or str(label) in SYSTEM_COLORS
    )
    return known >= max(1, len(labels) // 2)


def series_color(index: int = 0) -> str:
    return CATEGORICAL_COLORS[index % len(CATEGORICAL_COLORS)]


def apply_dashboard_theme(
    figure: go.Figure,
    *,
    title: str,
    subtitle: str = "",
    height: int = 410,
    show_legend: bool = False,
) -> go.Figure:
    """Apply the shared dashboard look to a Campbell AI figure."""
    heading = title
    if subtitle:
        heading = (
            f"{title}<br><span style='font-size:11px;color:{BRAND_MUTED}'>{subtitle}</span>"
        )
    figure.update_layout(
        title={
            "text": heading,
            "font": {"size": 16, "color": BRAND_TITLE, "family": FONT_FAMILY},
            "x": 0.01,
            "xanchor": "left",
        },
        font={"family": FONT_FAMILY, "size": 12, "color": BRAND_TITLE},
        paper_bgcolor=BRAND_SURFACE,
        plot_bgcolor=BRAND_SURFACE,
        margin={"l": 60, "r": 55, "t": 78 if subtitle else 62, "b": 80},
        height=height,
        showlegend=show_legend,
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
            "font": {"size": 11},
        },
        hovermode="closest",
        hoverlabel={
            "bgcolor": BRAND_SURFACE,
            "bordercolor": BRAND_AXIS,
            "font": {"size": 12, "family": FONT_FAMILY},
        },
    )
    return figure


def axis_style(title: str) -> dict[str, Any]:
    """Axis styling shared by every Campbell AI chart."""
    return {
        "title": {"text": title, "font": {"size": 12, "color": BRAND_TITLE}},
        "gridcolor": BRAND_GRID,
        "linecolor": BRAND_AXIS,
        "zerolinecolor": BRAND_GRID,
        "automargin": True,
    }
