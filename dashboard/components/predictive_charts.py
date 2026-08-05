"""
Componentes de gráficos para la página de evidencia.
"""
import plotly.graph_objects as go
import pandas as pd

from dashboard.components.oil_charts import (
    get_essay_limits_four,
    consolidate_limit_entries,
    limit_line_color,
)


def _oil_date_col(df) -> str:
    """
    Nombre de la columna de fecha de las muestras de aceite.
    CDA usa 'sampleDate'; Capstone no la tiene y usa 'Fecha' para todo.
    """
    if "sampleDate" in df.columns:
        return "sampleDate"
    return "Fecha"


def create_fleet_scatter(df_latest, selected_unit, status_colors, p80_30d):
    """
    Crear scatter de ranking vs ranking_acum_90d con todos los equipos.
    Destaca el equipo seleccionado.
    """
    x_all = df_latest["ranking"].astype(float)
    y_all = df_latest["ranking_acum_90d"].astype(float)

    x_min, x_max = float(x_all.min()), float(x_all.max())
    y_min, y_max = float(y_all.min()), float(y_all.max())
    x_pad = max((x_max - x_min) * 0.12, 5)
    y_pad = max((y_max - y_min) * 0.12, 2)
    x0, x1 = max(0, x_min - x_pad), x_max + x_pad
    y0, y1 = max(0, y_min - y_pad), y_max + y_pad

    x_thresh = 80.0
    y_thresh = p80_30d

    fig = go.Figure()

    # Quadrant fills
    for (qx0, qy0, qx1, qy1), color in [
        ((x_thresh, y_thresh, x1, y1), "rgba(226,75,74,0.05)"),
        ((x_thresh, y0, x1, y_thresh), "rgba(239,159,39,0.05)"),
        ((x0, y_thresh, x_thresh, y1), "rgba(239,159,39,0.05)"),
        ((x0, y0, x_thresh, y_thresh), "rgba(29,158,117,0.05)"),
    ]:
        fig.add_shape(
            type="rect", x0=qx0, y0=qy0, x1=qx1, y1=qy1,
            fillcolor=color, line_width=0, layer="below"
        )

    # Dividers
    fig.add_shape(
        type="line", x0=x_thresh, y0=y0, x1=x_thresh, y1=y1,
        line=dict(color="rgba(0,0,0,0.12)", width=1, dash="dot")
    )
    fig.add_shape(
        type="line", x0=x0, y0=y_thresh, x1=x1, y1=y_thresh,
        line=dict(color="rgba(0,0,0,0.12)", width=1, dash="dot")
    )

    # Quadrant labels
    ql = dict(
        showarrow=False, font=dict(size=9, color="rgba(0,0,0,0.2)"),
        xanchor="center", yanchor="middle"
    )
    fig.add_annotation(x=(x_thresh + x1) / 2, y=(y_thresh + y1) / 2, text="Crítica sostenida", **ql)
    fig.add_annotation(x=(x_thresh + x1) / 2, y=(y0 + y_thresh) / 2, text="Empeoró de golpe", **ql)
    fig.add_annotation(x=(x0 + x_thresh) / 2, y=(y_thresh + y1) / 2, text="Mejoró recientemente", **ql)
    fig.add_annotation(x=(x0 + x_thresh) / 2, y=(y0 + y_thresh) / 2, text="Zona saludable", **ql)

    # Fleet points (all units except selected)
    for st, color in status_colors.items():
        mask = (df_latest["status"] == st) & (df_latest["Unit"] != selected_unit)
        subset = df_latest[mask]
        if subset.empty:
            continue
        fig.add_trace(go.Scatter(
            x=subset["ranking"].astype(float),
            y=subset["ranking_acum_90d"].astype(float),
            mode="markers+text",
            name=st,
            text=subset["Unit"],
            textposition="top center",
            textfont=dict(size=9, color=color),
            marker=dict(
                color=color, size=8,
                line=dict(color="white", width=1.2), opacity=0.5
            ),
            hovertemplate="<b>%{text}</b><br>Ranking: %{x:.0f}<br>Acum 90d: %{y:.1f}<extra></extra>",
        ))

    # Selected unit — highlighted
    sel = df_latest[df_latest["Unit"] == selected_unit]
    if not sel.empty:
        fig.add_trace(go.Scatter(
            x=sel["ranking"].astype(float),
            y=sel["ranking_acum_90d"].astype(float),
            mode="markers+text",
            name=selected_unit,
            text=[selected_unit],
            textposition="top center",
            textfont=dict(size=11, color="#2563EB", family="DM Sans"),
            marker=dict(
                color="#2563EB", size=14,
                line=dict(color="white", width=2), opacity=1.0
            ),
            hovertemplate=f"<b>{selected_unit}</b><br>Ranking: %{{x:.0f}}<br>Acum 90d: %{{y:.1f}}<extra></extra>",
        ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        height=380,
        margin=dict(l=60, r=20, t=20, b=50),
        showlegend=False,
        xaxis=dict(
            title="Ranking actual",
            showgrid=True, gridcolor="rgba(0,0,0,0.05)",
            zeroline=False, tickfont=dict(size=10), range=[x0, x1]
        ),
        yaxis=dict(
            title="Ranking 90 días",
            showgrid=True, gridcolor="rgba(0,0,0,0.05)",
            zeroline=False, tickfont=dict(size=10), range=[y0, y1]
        ),
        hovermode="closest",
    )

    return fig


def create_comparative_bars(unit_row, df_latest, failure_modes):
    """
    Crear gráfico de barras horizontales comparativas para modos de falla.
    Reemplaza el radar por mejor legibilidad.
    """
    fm_keys = list(failure_modes.keys())
    fm_labels = [failure_modes[k] for k in fm_keys]
    
    # Valores del equipo seleccionado (use 30d averages for consistency)
    unit_vals = [
        float(unit_row[f"{k}_30d"]) if f"{k}_30d" in unit_row.index and pd.notna(unit_row[f"{k}_30d"]) else 0.0
        for k in fm_keys
    ]
    
    # Valores promedio de la flota (use 30d averages)
    fleet_vals = [
        float(df_latest[f"{k}_30d"].mean()) if f"{k}_30d" in df_latest.columns else 0.0
        for k in fm_keys
    ]
    
    # Crear dataframe para ordenar por valor de unidad (descendente)
    data = pd.DataFrame({
        'mode': fm_labels,
        'unit': unit_vals,
        'fleet': fleet_vals,
        'diff': [u - f for u, f in zip(unit_vals, fleet_vals)]
    })
    data = data.sort_values('unit', ascending=True)  # True para que el mayor quede arriba
    
    fig = go.Figure()
    
    # Barra: Promedio flota
    fig.add_trace(go.Bar(
        y=data['mode'],
        x=data['fleet'],
        name='Promedio flota',
        orientation='h',
        marker=dict(color='rgba(0,0,0,0.15)'),
        hovertemplate='<b>%{y}</b><br>Promedio flota: %{x:.1f}<extra></extra>',
    ))
    
    # Barra: Unidad seleccionada
    fig.add_trace(go.Bar(
        y=data['mode'],
        x=data['unit'],
        name=unit_row["Unit"],
        orientation='h',
        marker=dict(color='#2563EB'),
        hovertemplate='<b>%{y}</b><br>' + unit_row["Unit"] + ': %{x:.1f}<extra></extra>',
    ))
    
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        margin=dict(l=20, r=20, t=20, b=40),
        height=380,
        barmode='group',
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        xaxis=dict(
            title="Score de riesgo por modo de falla",
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)",
            zeroline=True,
            zerolinecolor="rgba(0,0,0,0.2)",
            tickfont=dict(size=10),
        ),
        yaxis=dict(
            showgrid=False,
            tickfont=dict(size=10),
        ),
    )
    
    return fig


def create_radar_comparison(unit_row, df_latest, failure_modes):
    """
    Crear gráfico radar comparando el equipo seleccionado vs promedio de la flota.
    """
    fm_labels = [failure_modes[k] for k in failure_modes.keys()]
    fm_keys = list(failure_modes.keys())

    # Valores del equipo seleccionado (use 30d averages for consistency)
    fm_vals = [
        float(unit_row[f"{k}_30d"]) if f"{k}_30d" in unit_row.index and pd.notna(unit_row[f"{k}_30d"]) else 0.0
        for k in fm_keys
    ]

    # Valores promedio de la flota (use 30d averages)
    avg_vals = [
        float(df_latest[f"{k}_30d"].mean()) if f"{k}_30d" in df_latest.columns else 0.0
        for k in fm_keys
    ]

    # Cerrar el polígono
    fm_labels_closed = fm_labels + [fm_labels[0]]
    fm_vals_closed = fm_vals + [fm_vals[0]]
    avg_vals_closed = avg_vals + [avg_vals[0]]

    fig = go.Figure()

    # Promedio de la flota
    fig.add_trace(go.Scatterpolar(
        r=avg_vals_closed,
        theta=fm_labels_closed,
        fill="toself",
        name="Promedio flota",
        line=dict(color="rgba(0,0,0,0.15)", width=1),
        fillcolor="rgba(0,0,0,0.04)",
    ))

    # Equipo seleccionado
    fig.add_trace(go.Scatterpolar(
        r=fm_vals_closed,
        theta=fm_labels_closed,
        fill="toself",
        name=unit_row["Unit"],
        line=dict(color="#2563EB", width=2),
        fillcolor="rgba(37,99,235,0.12)",
    ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=10, color="#6C7280"),
        margin=dict(l=40, r=40, t=40, b=40),
        height=320,
        polar=dict(
            bgcolor="rgba(0,0,0,0)",
            radialaxis=dict(
                visible=True,
                range=[0, 100],
                tickfont=dict(size=9),
                gridcolor="rgba(0,0,0,0.08)",
                linecolor="rgba(0,0,0,0.08)",
            ),
            angularaxis=dict(
                tickfont=dict(size=10),
                gridcolor="rgba(0,0,0,0.08)",
                linecolor="rgba(0,0,0,0.08)",
            ),
        ),
        legend=dict(
            orientation="h", yanchor="bottom", y=-0.15,
            xanchor="center", x=0.5,
            font=dict(size=10),
        ),
        showlegend=True,
    )

    return fig


def create_oil_timeseries_90d(df_unit, variables, oil_labels, oil_limits_four=None, oil_range=None):
    """
    Crear serie temporal de variables de aceite.
    Ventana: max(últimos 90 días, últimas 3 muestras reales).
    Usa sampleDate como identificador de muestra real.

    Si hay 1 sola variable y existen límites, muestra líneas de límite
    (fuente: stewart_limits_four.parquet, LIC/LIM/LSM/LSC - contrato v2.8).
    """

    if not variables:
        return None

    date_col = _oil_date_col(df_unit)
    df_sorted = df_unit.sort_values(date_col)
    if df_sorted.empty:
        return None
    
    # Calcular ventana de 90 días
    fecha_fin = pd.to_datetime(df_sorted[date_col].max())
    fecha_inicio_90d = fecha_fin - pd.Timedelta(days=90)
    
    # Identificar últimas 3 muestras REALES (deduplicar por fecha de muestra)
    muestras_reales = df_sorted.drop_duplicates(subset=[date_col], keep="last").sort_values(date_col)
    
    if len(muestras_reales) >= 3:
        # Tomar las últimas 3 muestras reales
        ultimas_3_muestras = muestras_reales.tail(3)
        fecha_inicio_3_muestras = pd.to_datetime(ultimas_3_muestras[date_col].min())
        
        # Ventana final: lo que cubra más hacia atrás
        fecha_inicio = min(fecha_inicio_90d, fecha_inicio_3_muestras)
    else:
        # Si hay menos de 3 muestras, usar todas las disponibles
        fecha_inicio = pd.to_datetime(muestras_reales[date_col].min()) if not muestras_reales.empty else fecha_inicio_90d
    
    # Filtrar datos con la ventana expandida
    df_filtered = df_sorted[pd.to_datetime(df_sorted[date_col]) >= fecha_inicio]
    
    if df_filtered.empty:
        return None
    
    fig = go.Figure()

    show_limits = (len(variables) == 1 and oil_limits_four and oil_range is not None)

    for var in variables:
        if var not in df_filtered.columns:
            continue

        series = df_filtered[[date_col, var]].dropna(subset=[var])
        if series.empty:
            continue

        x_dates = pd.to_datetime(series[date_col])
        y_values = series[var].astype(float)

        # Main trace: values
        fig.add_trace(go.Scatter(
            x=x_dates,
            y=y_values,
            mode="lines+markers",
            name=oil_labels.get(var, var),
            line=dict(width=2),
            marker=dict(size=6),
            hovertemplate="%{x|%d %b %Y}<br><b>%{y:.2f}</b><extra></extra>",
        ))

        # Threshold lines (only for single variable mode) - four-limit Stewart
        # output (LIC/LIM/LSM/LSC, v2.8). Equal/near-equal limits are
        # consolidated into one line with a user-friendly label, null lower
        # limits are never plotted, and lower-limit lines use the shared
        # purple color - same helpers as every other oil chart in the app.
        if show_limits:
            essay_limits = get_essay_limits_four(oil_limits_four, var, oil_range)
            if essay_limits:
                feature_label = oil_labels.get(var, var)
                tier_entries = [
                    {'value': essay_limits.get('LIC'), 'tier': 'LIC', 'feature': feature_label},
                    {'value': essay_limits.get('LIM'), 'tier': 'LIM', 'feature': feature_label},
                    {'value': essay_limits.get('LSM'), 'tier': 'LSM', 'feature': feature_label},
                    {'value': essay_limits.get('LSC'), 'tier': 'LSC', 'feature': feature_label},
                ]
                if essay_limits.get('LIC') is None or essay_limits.get('LIM') is None:
                    tier_entries = [e for e in tier_entries if e['tier'] not in ('LIC', 'LIM')]

                x_range = [x_dates.min(), x_dates.max()]
                for line in consolidate_limit_entries(tier_entries):
                    fig.add_trace(go.Scatter(
                        x=x_range, y=[line['value'], line['value']],
                        mode="lines", name=line['label'],
                        line=dict(width=1.5, dash="dot", color=limit_line_color(line['tiers'])),
                        hoverinfo="skip",
                    ))
    
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        height=320,
        margin=dict(l=60, r=24, t=24, b=50),
        showlegend=True,
        hovermode="x unified",
        xaxis=dict(
            title="",
            showgrid=False,
            zeroline=False,
            tickfont=dict(size=10),
            tickformat="%d %b",
        ),
        yaxis=dict(
            title="Valor",
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)",
            zeroline=False,
            tickfont=dict(size=10),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )
    
    return fig


def create_oil_timeseries(df_unit, variables, oil_labels):
    """
    Crear serie temporal de variables de aceite.
    """
    if not variables:
        return None

    date_col = _oil_date_col(df_unit)
    fig = go.Figure()

    for var in variables:
        if var not in df_unit.columns:
            continue

        series = df_unit[[date_col, var]].dropna(subset=[var])
        if series.empty:
            continue

        fig.add_trace(go.Scatter(
            x=pd.to_datetime(series[date_col]),
            y=series[var].astype(float),
            mode="lines+markers",
            name=oil_labels.get(var, var),
            line=dict(width=2),
            marker=dict(size=6),
            hovertemplate="%{x|%d %b %Y}<br><b>%{y:.2f}</b><extra></extra>",
        ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        height=320,
        margin=dict(l=60, r=24, t=24, b=50),
        showlegend=True,
        hovermode="x unified",
        xaxis=dict(
            title="",
            showgrid=False,
            zeroline=False,
            tickfont=dict(size=10),
            tickformat="%b %Y",
        ),
        yaxis=dict(
            title="Valor",
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)",
            zeroline=False,
            tickfont=dict(size=10),
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )

    return fig


def create_telemetry_signal_chart(df_unit, signal, telemetry_labels):
    """
    Crear gráfico individual para una señal de telemetría.
    Muestra alert_rate y critic_rate separados.
    """
    # Buscar columnas de alert_rate y critic_rate para esta señal
    alert_cols = [col for col in df_unit.columns if f"_{signal}_alert_rate" in col]
    critic_cols = [col for col in df_unit.columns if f"_{signal}_critic_rate" in col]
    
    if not alert_cols and not critic_cols:
        return None
    
    # Agrupar por fecha y sumar todas las tasas (diferentes modos operacionales)
    df_grouped = df_unit.groupby("Fecha").agg({
        **{col: 'sum' for col in alert_cols},
        **{col: 'sum' for col in critic_cols}
    }).reset_index()
    
    # Calcular tasas totales
    df_grouped['alert_rate_total'] = df_grouped[alert_cols].sum(axis=1) if alert_cols else 0
    df_grouped['critic_rate_total'] = df_grouped[critic_cols].sum(axis=1) if critic_cols else 0
    
    # Normalizar (las tasas están por modo operacional, promediamos)
    if alert_cols:
        df_grouped['alert_rate_total'] = df_grouped['alert_rate_total'] / len(alert_cols)
    if critic_cols:
        df_grouped['critic_rate_total'] = df_grouped['critic_rate_total'] / len(critic_cols)
    
    fig = go.Figure()
    
    # Barras: Alert rate
    if alert_cols:
        fig.add_trace(go.Bar(
            x=df_grouped["Fecha"],
            y=df_grouped["alert_rate_total"],
            name="Alert",
            marker=dict(color="#ef9f27"),
            hovertemplate="%{x|%d %b %Y}<br>Alert: %{y:.1%}<extra></extra>",
        ))
    
    # Barras: Critic rate
    if critic_cols:
        fig.add_trace(go.Bar(
            x=df_grouped["Fecha"],
            y=df_grouped["critic_rate_total"],
            name="Crítico",
            marker=dict(color="#e24b4a"),
            hovertemplate="%{x|%d %b %Y}<br>Crítico: %{y:.1%}<extra></extra>",
        ))
    
    signal_label = telemetry_labels.get(signal, signal)
    
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        height=250,
        margin=dict(l=60, r=24, t=40, b=50),
        showlegend=True,
        barmode="stack",
        title=dict(
            text=signal_label,
            font=dict(size=13, weight="bold"),
            x=0,
            xanchor="left",
        ),
        xaxis=dict(
            title="",
            showgrid=False,
            zeroline=False,
            tickfont=dict(size=10),
            tickformat="%d %b",
        ),
        yaxis=dict(
            title="Tasa",
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)",
            zeroline=False,
            tickfont=dict(size=10),
            tickformat=".0%",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )
    
    return fig


def create_telemetry_alerts_timeseries(df_unit, telemetry_vars, telemetry_labels):
    """
    Crear serie temporal de alertas de telemetría.
    Cuenta alertas por fecha para las variables especificadas.
    """
    if not telemetry_vars:
        return None

    # Preparar datos de alertas
    alert_data = []

    for var in telemetry_vars:
        # Buscar columnas de alertas para esta variable
        for col in df_unit.columns:
            if f"_{var}_alert_rate" in col or f"_{var}_critic_rate" in col:
                series = df_unit[["Fecha", col]].dropna(subset=[col])
                if not series.empty:
                    for _, row in series.iterrows():
                        if row[col] > 0:
                            alert_data.append({
                                "Fecha": row["Fecha"],
                                "Variable": telemetry_labels.get(var, var),
                                "Rate": float(row[col])
                            })

    if not alert_data:
        return None

    df_alerts = pd.DataFrame(alert_data)
    
    # Agrupar por fecha y variable
    df_grouped = df_alerts.groupby(["Fecha", "Variable"])["Rate"].sum().reset_index()

    fig = go.Figure()

    for var_label in df_grouped["Variable"].unique():
        subset = df_grouped[df_grouped["Variable"] == var_label]
        fig.add_trace(go.Bar(
            x=subset["Fecha"],
            y=subset["Rate"],
            name=var_label,
            hovertemplate="%{x|%d %b %Y}<br><b>%{y:.2%}</b><extra></extra>",
        ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, sans-serif", size=11, color="#6C7280"),
        height=280,
        margin=dict(l=60, r=24, t=24, b=50),
        showlegend=True,
        hovermode="x unified",
        barmode="stack",
        xaxis=dict(
            title="",
            showgrid=False,
            zeroline=False,
            tickfont=dict(size=10),
            tickformat="%b %Y",
        ),
        yaxis=dict(
            title="Tasa de alertas",
            showgrid=True,
            gridcolor="rgba(0,0,0,0.05)",
            zeroline=False,
            tickfont=dict(size=10),
            tickformat=".0%",
        ),
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )

    return fig