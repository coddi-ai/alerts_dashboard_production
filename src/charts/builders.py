"""Pure figure builders shared by the dashboard tabs and Campbell AI.

Plan section 14 asks for the figure construction to be extracted into pure
functions returning `plotly.graph_objects.Figure`, so the same visual can be
rendered by a Dash callback or by the agent without duplicating logic and without
FastAPI importing Dash components.

Every function here takes plain data and returns a themed figure. None of them
touch the filesystem, Dash, or request state.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from src.charts.theme import (
    BRAND_MUTED,
    BRAND_TITLE,
    CUMULATIVE_LINE,
    SEQUENTIAL_SCALE,
    apply_dashboard_theme,
    axis_style,
    is_semantic_dimension,
    series_color,
    status_palette,
)


# Order used whenever statuses are stacked or listed, worst first.
STATUS_ORDER: tuple[str, ...] = ("Anormal", "Alerta", "Insuficiente", "InsufficientData", "Normal")


def sort_statuses(values: list[str]) -> list[str]:
    """Order status labels by severity, keeping unknown labels at the end."""
    known = [status for status in STATUS_ORDER if status in values]
    return known + [value for value in values if value not in known]


def build_status_donut(
    counts: dict[str, int],
    *,
    title: str,
    total_label: str = "Total",
    subtitle: str = "",
) -> go.Figure:
    """Donut of status counts with the total in the centre (GR-02, OIL-M-01)."""
    labels = sort_statuses([str(label) for label in counts])
    values = [int(counts[label]) for label in labels]
    total = sum(values)
    figure = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.5,
            marker={"colors": status_palette(labels)},
            textinfo="label+percent",
            sort=False,
            hovertemplate="<b>%{label}</b><br>Cantidad: %{value}<br>%{percent}<extra></extra>",
        )
    )
    if total:
        figure.add_annotation(
            text=f"<b>{total}</b><br><span style='font-size:11px'>{total_label}</span>",
            x=0.5,
            y=0.5,
            font={"size": 20, "color": BRAND_TITLE},
            showarrow=False,
            xref="paper",
            yref="paper",
        )
    return apply_dashboard_theme(
        figure, title=title, subtitle=subtitle, height=420, show_legend=True
    )


def build_category_bar(
    labels: list[str],
    values: list[float],
    *,
    title: str,
    dimension_label: str,
    value_label: str,
    subtitle: str = "",
    horizontal: bool = False,
) -> go.Figure:
    """Ranking bar chart, coloured semantically when the labels carry meaning."""
    color = (
        status_palette(labels) if is_semantic_dimension(labels) else series_color(0)
    )
    if horizontal:
        figure = go.Figure(
            go.Bar(
                x=values,
                y=labels,
                orientation="h",
                marker={"color": color},
                hovertemplate=(
                    f"{dimension_label}: %{{y}}<br>{value_label}: %{{x}}<extra></extra>"
                ),
            )
        )
        apply_dashboard_theme(
            figure, title=title, subtitle=subtitle, height=max(360, len(labels) * 28)
        )
        figure.update_layout(
            xaxis={**axis_style(value_label), "rangemode": "tozero"},
            yaxis={**axis_style(dimension_label), "autorange": "reversed"},
        )
        return figure

    figure = go.Figure(
        go.Bar(
            x=labels,
            y=values,
            marker={"color": color},
            hovertemplate=(
                f"{dimension_label}: %{{x}}<br>{value_label}: %{{y}}<extra></extra>"
            ),
        )
    )
    apply_dashboard_theme(figure, title=title, subtitle=subtitle)
    figure.update_layout(
        xaxis=axis_style(dimension_label),
        yaxis={**axis_style(value_label), "rangemode": "tozero"},
    )
    return figure


def build_pareto(
    labels: list[str],
    values: list[float],
    *,
    title: str,
    dimension_label: str,
    value_label: str,
    subtitle: str = "",
) -> go.Figure:
    """Bars plus a cumulative percentage line on a dedicated secondary axis."""
    total = float(sum(values))
    cumulative: list[float] = []
    running = 0.0
    for value in values:
        running += float(value)
        cumulative.append((running / total * 100) if total else 0.0)

    figure = go.Figure()
    figure.add_trace(
        go.Bar(
            x=labels,
            y=values,
            name=value_label,
            marker={"color": series_color(0)},
            hovertemplate=(
                f"{dimension_label}: %{{x}}<br>{value_label}: %{{y}}<extra></extra>"
            ),
        )
    )
    figure.add_trace(
        go.Scatter(
            x=labels,
            y=cumulative,
            name="% acumulado",
            mode="lines+markers",
            yaxis="y2",
            line={"color": CUMULATIVE_LINE, "width": 3},
            marker={"size": 7},
            hovertemplate=(
                f"{dimension_label}: %{{x}}<br>Acumulado: %{{y:.1f}}%<extra></extra>"
            ),
        )
    )
    apply_dashboard_theme(figure, title=title, subtitle=subtitle, show_legend=True)
    figure.update_layout(
        xaxis=axis_style(dimension_label),
        yaxis={**axis_style(value_label), "rangemode": "tozero"},
        yaxis2={
            **axis_style("% acumulado"),
            "overlaying": "y",
            "side": "right",
            "range": [0, 105],
            "ticksuffix": "%",
            "showgrid": False,
        },
    )
    return figure


def build_time_series(
    labels: list[str],
    values: list[float],
    *,
    title: str,
    dimension_label: str,
    value_label: str,
    subtitle: str = "",
) -> go.Figure:
    """Single-series trend over an ordered time dimension."""
    figure = go.Figure(
        go.Scatter(
            x=labels,
            y=values,
            mode="lines+markers",
            name=value_label,
            line={"color": series_color(0), "width": 3},
            marker={"size": 7},
            hovertemplate=(
                f"{dimension_label}: %{{x}}<br>{value_label}: %{{y}}<extra></extra>"
            ),
        )
    )
    apply_dashboard_theme(figure, title=title, subtitle=subtitle)
    figure.update_layout(
        xaxis=axis_style(dimension_label),
        yaxis={**axis_style(value_label), "rangemode": "tozero"},
    )
    return figure


def build_stacked_bar(
    matrix: pd.DataFrame,
    *,
    title: str,
    dimension_label: str,
    secondary_label: str,
    value_label: str,
    subtitle: str = "",
) -> go.Figure:
    """Composition of a secondary dimension inside each primary category."""
    columns = [str(column) for column in matrix.columns]
    if is_semantic_dimension(columns):
        columns = sort_statuses(columns)
        matrix = matrix.reindex(columns=columns, fill_value=0)
        colors = status_palette(columns)
    else:
        colors = [series_color(index) for index in range(len(columns))]

    figure = go.Figure()
    for index, column in enumerate(matrix.columns):
        figure.add_trace(
            go.Bar(
                name=str(column),
                x=[str(value) for value in matrix.index],
                y=[float(value) for value in matrix[column].values],
                marker={"color": colors[index]},
                hovertemplate=(
                    f"{dimension_label}: %{{x}}<br>{secondary_label}: {column}"
                    f"<br>{value_label}: %{{y}}<extra></extra>"
                ),
            )
        )
    apply_dashboard_theme(figure, title=title, subtitle=subtitle, show_legend=True)
    figure.update_layout(
        barmode="stack",
        xaxis=axis_style(dimension_label),
        yaxis={**axis_style(value_label), "rangemode": "tozero"},
    )
    return figure


def build_heatmap(
    matrix: pd.DataFrame,
    *,
    title: str,
    dimension_label: str,
    secondary_label: str,
    value_label: str,
    subtitle: str = "",
) -> go.Figure:
    """Two-dimensional concentration on the brand sequential scale."""
    figure = go.Figure(
        go.Heatmap(
            x=[str(value) for value in matrix.columns],
            y=[str(value) for value in matrix.index],
            z=matrix.astype(float).values.tolist(),
            colorscale=[list(stop) for stop in SEQUENTIAL_SCALE],
            colorbar={"title": {"text": value_label, "side": "right"}},
            hovertemplate=(
                f"{dimension_label}: %{{y}}<br>{secondary_label}: %{{x}}"
                f"<br>{value_label}: %{{z}}<extra></extra>"
            ),
        )
    )
    apply_dashboard_theme(figure, title=title, subtitle=subtitle, height=470)
    figure.update_layout(
        xaxis={**axis_style(secondary_label), "showgrid": False},
        yaxis={**axis_style(dimension_label), "showgrid": False},
    )
    return figure


def build_pie(
    labels: list[str],
    values: list[float],
    *,
    title: str,
    value_label: str,
    subtitle: str = "",
) -> go.Figure:
    """Distribution across a small number of categories."""
    figure = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            hole=0.5,
            marker={"colors": status_palette(labels)},
            textinfo="label+percent",
            hovertemplate=(
                f"%{{label}}<br>{value_label}: %{{value}}<br>%{{percent}}<extra></extra>"
            ),
        )
    )
    return apply_dashboard_theme(
        figure, title=title, subtitle=subtitle, show_legend=True
    )


def empty_figure(message: str) -> go.Figure:
    """Placeholder that states why there is nothing to draw."""
    figure = go.Figure()
    figure.add_annotation(
        text=message,
        x=0.5,
        y=0.5,
        xref="paper",
        yref="paper",
        showarrow=False,
        font={"size": 13, "color": BRAND_MUTED},
    )
    figure.update_layout(
        xaxis={"visible": False},
        yaxis={"visible": False},
        height=260,
        paper_bgcolor="#ffffff",
        plot_bgcolor="#ffffff",
        margin={"l": 20, "r": 20, "t": 20, "b": 20},
    )
    return figure
