"""Shared Plotly theme and pure figure builders for dashboard and Campbell AI."""

from __future__ import annotations


# The chart vocabulary, declared here so the grammar, the response model and the
# capabilities endpoint cannot disagree about what is supported. Kept free of
# imports so any layer can read it without pulling in plotly.
CHART_KINDS: tuple[str, ...] = (
    "bar",
    "horizontal_bar",
    "line",
    "area",
    "pie",
    "pareto",
    "heatmap",
    "stacked_bar",
    "treemap",
    "histogram",
    "box",
    "scatter",
)

# Kinds only the named-chart registry produces: they need a curated data shape
# rather than a dataset × dimension combination.
REGISTRY_ONLY_KINDS: tuple[str, ...] = ("radar", "gauge")

ALL_CHART_KINDS: tuple[str, ...] = CHART_KINDS + REGISTRY_ONLY_KINDS
