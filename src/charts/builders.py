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
from plotly.subplots import make_subplots

from src.charts.theme import (
    BRAND_AXIS,
    BRAND_GRID,
    BRAND_MUTED,
    BRAND_TITLE,
    FONT_FAMILY,
    STATUS_COLORS,
    CUMULATIVE_LINE,
    SEQUENTIAL_SCALE,
    apply_dashboard_theme,
    axis_style,
    is_semantic_dimension,
    series_color,
    status_palette,
)


# Aliases keep the polar/gauge layouts readable next to the axis_style helper.
BRAND_GRID_COLOR = BRAND_GRID
BRAND_AXIS_COLOR = BRAND_AXIS


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


def build_histogram(
    values: list[float],
    *,
    title: str,
    value_label: str,
    bins: int = 20,
    subtitle: str = "",
) -> go.Figure:
    """Distribution of one numeric metric, for spread rather than ranking."""
    figure = go.Figure(
        go.Histogram(
            x=values,
            nbinsx=max(3, min(int(bins), 60)),
            marker={"color": series_color(0), "line": {"width": 1, "color": "#ffffff"}},
            hovertemplate=f"{value_label}: %{{x}}<br>Frecuencia: %{{y}}<extra></extra>",
        )
    )
    apply_dashboard_theme(figure, title=title, subtitle=subtitle)
    figure.update_layout(
        bargap=0.05,
        xaxis=axis_style(value_label),
        yaxis={**axis_style("Frecuencia"), "rangemode": "tozero"},
    )
    return figure


def build_box(
    groups: dict[str, list[float]],
    *,
    title: str,
    dimension_label: str,
    value_label: str,
    subtitle: str = "",
) -> go.Figure:
    """Spread of a metric per category: median, quartiles and outliers."""
    labels = list(groups)
    colors = (
        status_palette(labels)
        if is_semantic_dimension(labels)
        else [series_color(index) for index in range(len(labels))]
    )
    figure = go.Figure()
    for index, label in enumerate(labels):
        figure.add_trace(
            go.Box(
                y=groups[label],
                name=str(label),
                marker={"color": colors[index]},
                boxmean=True,
                hovertemplate=f"{dimension_label}: {label}<br>{value_label}: %{{y}}<extra></extra>",
            )
        )
    apply_dashboard_theme(
        figure, title=title, subtitle=subtitle, show_legend=len(labels) > 1
    )
    figure.update_layout(
        xaxis=axis_style(dimension_label),
        yaxis=axis_style(value_label),
    )
    return figure


def build_treemap(
    labels: list[str],
    values: list[float],
    *,
    title: str,
    dimension_label: str,
    value_label: str,
    subtitle: str = "",
) -> go.Figure:
    """Share of a whole, where relative area reads faster than bar length."""
    colors = (
        status_palette(labels)
        if is_semantic_dimension(labels)
        else [series_color(index) for index in range(len(labels))]
    )
    figure = go.Figure(
        go.Treemap(
            labels=labels,
            parents=[""] * len(labels),
            values=values,
            marker={"colors": colors},
            texttemplate="<b>%{label}</b><br>%{value}<br>%{percentRoot}",
            hovertemplate=(
                f"{dimension_label}: %{{label}}<br>{value_label}: %{{value}}"
                "<br>%{percentRoot}<extra></extra>"
            ),
            branchvalues="total",
        )
    )
    return apply_dashboard_theme(figure, title=title, subtitle=subtitle, height=440)


def build_scatter(
    points: list[dict],
    *,
    title: str,
    x_label: str,
    y_label: str,
    subtitle: str = "",
) -> go.Figure:
    """Two metrics per entity, to separate level from trend or size.

    Each point is ``{"label": str, "x": float, "y": float, "status": str | None}``.
    """
    labels = [str(point.get("label", "")) for point in points]
    statuses = [str(point.get("status") or "") for point in points]
    colors = (
        status_palette(statuses)
        if any(statuses) and is_semantic_dimension([s for s in statuses if s])
        else series_color(0)
    )
    figure = go.Figure(
        go.Scatter(
            x=[float(point["x"]) for point in points],
            y=[float(point["y"]) for point in points],
            mode="markers+text",
            text=labels,
            textposition="top center",
            textfont={"size": 10},
            marker={"size": 13, "color": colors, "line": {"width": 1, "color": "#ffffff"}},
            hovertemplate=(
                f"%{{text}}<br>{x_label}: %{{x}}<br>{y_label}: %{{y}}<extra></extra>"
            ),
        )
    )
    apply_dashboard_theme(figure, title=title, subtitle=subtitle, height=460)
    figure.update_layout(
        xaxis={**axis_style(x_label), "rangemode": "tozero"},
        yaxis={**axis_style(y_label), "rangemode": "tozero"},
    )
    return figure


def build_radar(
    series: list[dict],
    axes: list[str],
    *,
    title: str,
    value_label: str,
    subtitle: str = "",
) -> go.Figure:
    """Multi-axis comparison, for a profile across several metrics at once.

    Each series is ``{"label": str, "values": list[float], "status": str | None}``.
    Radar only reads well with 3+ axes and a handful of series.
    """
    figure = go.Figure()
    closed_axes = axes + axes[:1]
    for index, item in enumerate(series):
        values = [float(value) for value in item["values"]]
        status = str(item.get("status") or "")
        color = (
            status_palette([status])[0] if status else series_color(index)
        )
        figure.add_trace(
            go.Scatterpolar(
                r=values + values[:1],
                theta=closed_axes,
                name=str(item.get("label", "")),
                fill="toself" if item.get("fill", index == 0) else None,
                line={"color": color, "width": 2},
                hovertemplate=(
                    f"%{{theta}}<br>{value_label}: %{{r}}<extra>"
                    f"{item.get('label', '')}</extra>"
                ),
            )
        )
    apply_dashboard_theme(
        figure, title=title, subtitle=subtitle, height=470, show_legend=len(series) > 1
    )
    figure.update_layout(
        polar={
            "radialaxis": {
                "visible": True,
                "gridcolor": BRAND_GRID_COLOR,
                "linecolor": BRAND_AXIS_COLOR,
            },
            "angularaxis": {"gridcolor": BRAND_GRID_COLOR},
            "bgcolor": "#ffffff",
        }
    )
    return figure


def build_gauge(
    value: float,
    *,
    title: str,
    value_label: str,
    minimum: float = 0.0,
    maximum: float = 100.0,
    bands: list[tuple[float, float, str]] | None = None,
    subtitle: str = "",
) -> go.Figure:
    """Single indicator against its bands, for one headline number."""
    steps = [
        {"range": [start, end], "color": color} for start, end, color in (bands or [])
    ]
    figure = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=float(value),
            number={"font": {"size": 34, "color": BRAND_TITLE}},
            gauge={
                "axis": {"range": [minimum, maximum], "tickcolor": BRAND_AXIS_COLOR},
                "bar": {"color": BRAND_TITLE, "thickness": 0.28},
                "steps": steps,
                "borderwidth": 0,
            },
            title={"text": value_label, "font": {"size": 12, "color": BRAND_MUTED}},
        )
    )
    return apply_dashboard_theme(figure, title=title, subtitle=subtitle, height=340)


def build_area(
    labels: list[str],
    values: list[float],
    *,
    title: str,
    dimension_label: str,
    value_label: str,
    subtitle: str = "",
) -> go.Figure:
    """Filled trend, when the accumulated volume matters as much as the shape."""
    figure = go.Figure(
        go.Scatter(
            x=labels,
            y=values,
            mode="lines",
            fill="tozeroy",
            line={"color": series_color(0), "width": 2},
            fillcolor="rgba(52, 152, 219, 0.22)",
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


def build_signal_panels(
    panels: list[dict],
    *,
    title: str,
    time_label: str = "Fecha y hora",
    subtitle: str = "",
) -> go.Figure:
    """Stacked time series, one panel per signal, each against its own limits.

    Replaces the previous dashboard's per-alert sensor chart. One shared x axis keeps
    the episodes aligned across signals, and each panel carries its own y scale
    because the signals are not comparable (temperature, pressure, filter state).

    Each panel is ``{"signal": str, "label": str, "times": list, "values": list,
    "upper": list | None, "lower": list | None}``.
    """
    if not panels:
        return empty_figure("Sin señales con valores capturados para esta alerta")

    figure = make_subplots(
        rows=len(panels),
        cols=1,
        shared_xaxes=True,
        vertical_spacing=min(0.12, 0.35 / len(panels)),
        subplot_titles=[panel.get("label") or panel["signal"] for panel in panels],
    )

    for index, panel in enumerate(panels, start=1):
        times = panel["times"]
        upper, lower = panel.get("upper"), panel.get("lower")
        # Band first so the measured line stays legible on top of it.
        if upper and lower:
            figure.add_trace(
                go.Scatter(
                    x=times,
                    y=lower,
                    mode="lines",
                    line={"width": 0},
                    hoverinfo="skip",
                    showlegend=False,
                ),
                row=index,
                col=1,
            )
            figure.add_trace(
                go.Scatter(
                    x=times,
                    y=upper,
                    mode="lines",
                    line={"width": 0},
                    fill="tonexty",
                    fillcolor="rgba(52, 152, 219, 0.10)",
                    hoverinfo="skip",
                    name="Rango permitido",
                    showlegend=index == 1,
                ),
                row=index,
                col=1,
            )
        for values, name, color in (
            (upper, "Límite superior", STATUS_COLORS["Anormal"]),
            (lower, "Límite inferior", STATUS_COLORS["Alerta"]),
        ):
            if values:
                figure.add_trace(
                    go.Scatter(
                        x=times,
                        y=values,
                        mode="lines",
                        line={"color": color, "width": 1.5, "dash": "dash"},
                        name=name,
                        showlegend=index == 1,
                        hovertemplate=f"{name}: %{{y}}<extra></extra>",
                    ),
                    row=index,
                    col=1,
                )
        figure.add_trace(
            go.Scatter(
                x=times,
                y=panel["values"],
                mode="lines",
                line={"color": series_color(0), "width": 2},
                name="Valor medido",
                showlegend=index == 1,
                hovertemplate=(
                    f"{panel['signal']}<br>%{{x}}<br>Valor: %{{y}}<extra></extra>"
                ),
            ),
            row=index,
            col=1,
        )
        figure.update_yaxes(axis_style(""), row=index, col=1)

    apply_dashboard_theme(
        figure,
        title=title,
        subtitle=subtitle,
        height=max(320, 230 * len(panels)),
        show_legend=True,
    )
    figure.update_xaxes(axis_style(time_label), row=len(panels), col=1)
    for index in range(1, len(panels)):
        figure.update_xaxes({**axis_style(""), "showticklabels": False}, row=index, col=1)
    # Subplot titles are annotations; keep them in the brand type scale.
    for annotation in figure.layout.annotations:
        annotation.font = {"size": 12, "color": BRAND_TITLE, "family": FONT_FAMILY}
    return figure


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
