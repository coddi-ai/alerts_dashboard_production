"""W34-08 — Renombrar percentil X por Límite.

The chart's legend named baseline reference lines 'P95'/'P98'/'P5'/'P2' —
statistical notation with no meaning to a client. The parquet's own column
names (the data contract limits_df reads) are untouched; only the four
`name=` strings passed to go.Scatter change, matching the Stewart
four-limit vocabulary already shown in predictive_tables.py's status badges
("Superior Marginal", "Inferior Condenatorio").
"""

import re

import pandas as pd

from dashboard.components.telemetry_charts import build_signal_timeseries_card


def _raw_df() -> pd.DataFrame:
    dates = pd.date_range("2026-07-01", periods=10, freq="h")
    return pd.DataFrame({"Fecha": dates, "EngCoolTemp": [80.0 + i for i in range(10)]})


def _limits_df() -> pd.DataFrame:
    return pd.DataFrame([{
        "Unit": "CA-42",
        "Signal": "EngCoolTemp",
        "EstadoMaquina": "Operacional",
        "P2": 60.0,
        "P5": 65.0,
        "P95": 95.0,
        "P98": 98.0,
        "sample_count": 100,
    }])


def test_no_trace_uses_percentile_notation():
    fig = build_signal_timeseries_card(
        "EngCoolTemp", _raw_df(), _limits_df(), pd.DataFrame(), unit="CA-42",
    )
    percentile_pattern = re.compile(r"^P\d+$")
    offending = [trace.name for trace in fig.data if percentile_pattern.match(trace.name or "")]
    assert offending == []


def test_all_four_limit_labels_are_present():
    fig = build_signal_timeseries_card(
        "EngCoolTemp", _raw_df(), _limits_df(), pd.DataFrame(), unit="CA-42",
    )
    names = {trace.name for trace in fig.data}
    for expected in (
        "Límite superior marginal",
        "Límite superior condenatorio",
        "Límite inferior marginal",
        "Límite inferior condenatorio",
    ):
        assert expected in names


def test_limit_values_are_unchanged_from_the_parquet():
    """Only the legend text changes — the plotted y-values must be exactly
    the parquet's P2/P5/P95/P98 numbers."""
    fig = build_signal_timeseries_card(
        "EngCoolTemp", _raw_df(), _limits_df(), pd.DataFrame(), unit="CA-42",
    )
    values_by_name = {trace.name: list(trace.y) for trace in fig.data if trace.name in {
        "Límite superior marginal", "Límite superior condenatorio",
        "Límite inferior marginal", "Límite inferior condenatorio",
    }}
    assert values_by_name["Límite superior marginal"] == [95.0, 95.0]
    assert values_by_name["Límite superior condenatorio"] == [98.0, 98.0]
    assert values_by_name["Límite inferior marginal"] == [65.0, 65.0]
    assert values_by_name["Límite inferior condenatorio"] == [60.0, 60.0]


def test_legend_order_unchanged():
    """legendrank values (1=inferior condenatorio ... 4=superior
    condenatorio) are untouched — only the label text changed."""
    fig = build_signal_timeseries_card(
        "EngCoolTemp", _raw_df(), _limits_df(), pd.DataFrame(), unit="CA-42",
    )
    rank_by_name = {trace.name: trace.legendrank for trace in fig.data if trace.legendrank is not None}
    assert rank_by_name["Límite inferior condenatorio"] == 1
    assert rank_by_name["Límite inferior marginal"] == 2
    assert rank_by_name["Límite superior marginal"] == 3
    assert rank_by_name["Límite superior condenatorio"] == 4


def test_missing_limit_column_produces_no_trace_for_it():
    """A limits_df without P2 (no lower-condenatory limit for this
    signal/state) must simply omit that trace, not error or invent a value."""
    limits = _limits_df()
    limits = limits.drop(columns=["P2"])
    fig = build_signal_timeseries_card(
        "EngCoolTemp", _raw_df(), limits, pd.DataFrame(), unit="CA-42",
    )
    names = {trace.name for trace in fig.data}
    assert "Límite inferior condenatorio" not in names
    assert "Límite superior marginal" in names  # the other three still render
