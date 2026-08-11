"""
Curva acumulada de ranking vs. horas de componente.

Portado desde el notebook ERS_acumulada.ipynb:
  - fill_hours_progressive : rellena horas faltantes y detecta ciclos de vida
  - build_accumulated_data : merge ranking + horas y calcula ranking acumulado
  - build_reference_band   : media de flota +- K*sigma (sobre la TASA por hora)
  - build_accumulated_figure : figura Plotly con zonas de salud
  - render_accumulated_section : tarjeta lista para insertar en el overview

El parquet de horas ya viene limpio (cleaned_component_hours.parquet), por lo
que la funcion clean_component_hours del notebook no se replica aqui.
"""

import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

# =============================================================================
# CONFIG
# =============================================================================

# Unidades excluidas del calculo de la banda de referencia por componente.
# Son fallas conocidas: si se incluyen, inflan sigma y ensanchan la banda
# justo con las curvas de las que se quiere distinguir.
EXCLUDE_FROM_REFERENCE = {
    "motor": ["T_11"],
    "transmision": ["T_09"],
}

K_SIGMA = 2       # ancho de la banda, en desviaciones estandar
N_GRID = 200      # puntos de la grilla de horas
MIN_SUPPORT = 3   # minimo de curvas para considerar un punto de la grilla

# Paleta consistente con el resto del dashboard
PALETTE = [
    "#2563EB", "#e24b4a", "#1d9e75", "#ef9f27", "#7C3AED",
    "#0891B2", "#DB2777", "#65A30D", "#EA580C", "#4F46E5",
    "#0D9488",
]

ZONE_COLORS = {
    "Normal": "rgba(29,158,117,0.10)",
    "Alerta": "rgba(239,159,39,0.13)",
    "Anormal": "rgba(226,75,74,0.10)",
}

# Etiquetas al final de cada curva
LABEL_X_PAD = 1.09      # aire a la derecha del eje X para los rotulos
LABEL_MIN_GAP = 0.03    # separacion vertical minima entre rotulos (fraccion del rango)


# =============================================================================
# HELPERS
# =============================================================================

def _normalize_unit(unit_id):
    """T_09 -> T_9 (mismo criterio que app.py / overview.py)."""
    if pd.isna(unit_id):
        return unit_id
    unit_str = str(unit_id)
    match = re.match(r"^([A-Za-z]+)_(0+)(\d+)$", unit_str)
    if match:
        return f"{match.group(1)}_{match.group(3)}"
    return unit_str


# =============================================================================
# 1. RELLENO DE HORAS + DETECCION DE CICLOS  (notebook celda 8)
# =============================================================================

def fill_hours_progressive(df, hours_col="componentHours_cleaned", unit_col="Unit"):
    """
    Rellena horas faltantes progresivamente por unidad.
      - Si hay un reset real (valor baja >50%), empieza un nuevo ciclo desde 0.
      - Si hay una pequena bajada imposible, se mantiene el valor anterior.
      - Si el primer valor conocido no es 0, interpola desde 0.
      - Agrega columna 'ciclo' indicando el ciclo de vida (1, 2, ...).
    """
    df = df.sort_values([unit_col, "Fecha"]).copy()
    result = []

    for unit, group in df.groupby(unit_col):
        group = group.reset_index(drop=True)
        raw = group[hours_col].copy()

        known_idx = raw.dropna().index.tolist()

        if len(known_idx) == 0:
            group["componentHours_filled"] = np.nan
            group["ciclo"] = 1
            result.append(group)
            continue

        # ── Detectar resets y asignar ciclos ──
        adjusted = raw.copy()
        ciclos = pd.Series(1, index=group.index, dtype="float64")
        prev_val = None
        current_cycle = 1
        reset_threshold = 0.5

        for i in known_idx:
            val = raw[i]
            if prev_val is not None and val < prev_val:
                if val < prev_val * reset_threshold:
                    current_cycle += 1          # reset real: nuevo ciclo
                else:
                    val = prev_val              # bajada imposible: mantener
            adjusted[i] = val
            ciclos[i] = current_cycle
            prev_val = val

        # Propagar ciclos a las filas sin dato conocido
        ciclos_filled = pd.Series(np.nan, index=group.index, dtype="float64")
        for i in known_idx:
            ciclos_filled[i] = ciclos[i]
        ciclos_filled = ciclos_filled.ffill().bfill().fillna(1).astype(int)

        # ── Interpolar horas dentro de cada ciclo ──
        hours_filled = pd.Series(np.nan, index=group.index, dtype="float64")

        for cycle in range(1, current_cycle + 1):
            cycle_idx = group.index[ciclos_filled == cycle]
            if len(cycle_idx) == 0:
                continue

            cycle_known = [i for i in known_idx if ciclos_filled[i] == cycle]
            if len(cycle_known) == 0:
                continue

            first_in_cycle = cycle_idx[0]
            first_known_in_cycle = cycle_known[0]

            cycle_series = pd.Series(np.nan, index=cycle_idx, dtype="float64")
            for i in cycle_known:
                cycle_series[i] = adjusted[i]

            if first_known_in_cycle > first_in_cycle:
                cycle_series.iloc[0] = 0.0

            cycle_series = cycle_series.interpolate(method="linear").ffill()
            hours_filled[cycle_idx] = cycle_series.values

        group["componentHours_filled"] = hours_filled
        group["ciclo"] = ciclos_filled
        result.append(group)

    if not result:
        return df.assign(componentHours_filled=np.nan, ciclo=1)

    return pd.concat(result, ignore_index=True)


# =============================================================================
# 2. PREPARACION DE DATOS  (notebook celdas 6, 8, 9, 11)
# =============================================================================

def build_accumulated_data(df, df_component_hours, component="motor"):
    """
    Cruza el ranking diario con las horas del componente y calcula el
    ranking acumulado por ciclo de vida.

    Devuelve un DataFrame con: Unit, Fecha, ranking, componentHours_filled,
    ciclo, ranking_acumulado, curva.  DataFrame vacio si faltan datos.
    """
    if df is None or df.empty or "ranking" not in df.columns:
        return pd.DataFrame()
    if df_component_hours is None or df_component_hours.empty:
        return pd.DataFrame()

    base = df.loc[:, ["Unit", "Fecha", "ranking"]].copy()
    base["Fecha"] = pd.to_datetime(base["Fecha"])

    # ── PARCHE TEMPORAL (solo para la curva) ──
    # El CSV de ranking puede traer valores no finitos (-inf / +inf / NaN) que
    # envenenan el cálculo de la banda de referencia (media/σ), aplastando las
    # zonas contra el eje. Se descartan aquí, sin tocar el CSV ni el resto del
    # dashboard. TODO: investigar el origen de los -inf en el pipeline de ranking.
    base["ranking"] = pd.to_numeric(base["ranking"], errors="coerce")
    base = base[np.isfinite(base["ranking"])]
    if base.empty:
        return pd.DataFrame()

    base["_unit_norm"] = base["Unit"].apply(_normalize_unit)

    hours = df_component_hours[
        df_component_hours["componentName"] == component
    ].copy()

    if hours.empty:
        return pd.DataFrame()

    hours["Fecha"] = pd.to_datetime(hours["sampleDate"])
    hours["_unit_norm"] = hours["unitId"].apply(_normalize_unit)
    hours = (
        hours.loc[:, ["_unit_norm", "Fecha", "componentHours_cleaned"]]
        .dropna(subset=["componentHours_cleaned"])
        .drop_duplicates(subset=["_unit_norm", "Fecha"], keep="last")
    )

    merged = base.merge(hours, on=["_unit_norm", "Fecha"], how="left")

    merged = fill_hours_progressive(merged)
    merged = merged.dropna(subset=["componentHours_filled"])

    if merged.empty:
        return pd.DataFrame()

    merged = merged.sort_values(["Unit", "ciclo", "Fecha"])
    merged["ranking_acumulado"] = (
        merged.groupby(["Unit", "ciclo"])["ranking"].cumsum()
    )
    merged["curva"] = (
        merged["Unit"].astype(str) + " · ciclo " + merged["ciclo"].astype(str)
    )

    return merged.drop(columns=["_unit_norm"])


# =============================================================================
# 3. BANDA DE REFERENCIA DE FLOTA  (notebook celda 11, bloque 2)
# =============================================================================

def build_reference_band(df_acum, component="motor", k=K_SIGMA, n_grid=N_GRID):
    """
    Media de flota +- K*sigma calculada sobre la TASA de acumulacion por hora
    y luego integrada.  Excluye las unidades de fallas conocidas para no
    inflar sigma.

    Devuelve (grid_v, media_v, lo_v, hi_v) o None si no hay soporte suficiente.
    """
    excluded = EXCLUDE_FROM_REFERENCE.get(component, [])
    df_ref = df_acum[~df_acum["Unit"].isin(excluded)]

    if df_ref.empty or df_ref["curva"].nunique() < MIN_SUPPORT:
        df_ref = df_acum  # sin soporte: usar la flota completa

    if df_ref.empty:
        return None

    h_max = df_ref.groupby("curva")["componentHours_filled"].max().quantile(0.95)
    if not np.isfinite(h_max) or h_max <= 0:
        return None

    # Redondear hacia arriba al millar mas cercano para que el fondo de
    # zonas (Normal/Alerta/Anormal) termine en un numero limpio en vez de
    # cortar en un percentil arbitrario (p.ej. 23500 -> 24000).
    h_max = float(np.ceil(h_max / 1000.0) * 1000.0)

    grid = np.linspace(0, h_max, n_grid)
    paso = grid[1] - grid[0]

    # Tasa de acumulacion por hora de cada curva, interpolada sobre la grilla
    curvas_rate = []
    for _, g in df_ref.groupby("curva"):
        g = g.dropna(subset=["componentHours_filled", "ranking"])
        g = g.sort_values("componentHours_filled")
        if len(g) < 2:
            continue

        h = g["componentHours_filled"].to_numpy(dtype=float)
        r = g["ranking"].to_numpy(dtype=float)
        dh = np.diff(h)
        ok = dh > 0                                # evitar division por cero
        if not ok.any():
            continue

        rate = r[1:][ok] / dh[ok]                  # incremento por hora
        h_mid = ((h[1:] + h[:-1]) / 2)[ok]         # punto medio del intervalo
        if len(h_mid) < 2:
            continue

        y = np.interp(grid, h_mid, rate)
        y[(grid < h_mid.min()) | (grid > h_mid.max())] = np.nan
        curvas_rate.append(y)

    if not curvas_rate:
        return None

    M = np.vstack(curvas_rate)

    # Media y sigma de la tasa por punto (con soporte minimo de curvas)
    n_curvas = np.sum(~np.isnan(M), axis=0)
    mask = n_curvas >= min(MIN_SUPPORT, M.shape[0])
    if not mask.any():
        return None

    rate_center = np.full(grid.shape, np.nan)
    rate_std = np.full(grid.shape, np.nan)

    rate_center[mask] = np.nanmean(M[:, mask], axis=0)
    if M.shape[0] > 1:
        rate_std[mask] = np.nanstd(M[:, mask], axis=0, ddof=1)
    else:
        rate_std[mask] = 0.0

    rate_center_full = pd.Series(rate_center).interpolate().fillna(0).to_numpy()
    rate_std_full = pd.Series(rate_std).interpolate().fillna(0).to_numpy()

    # Centro acumulado (media de flota, integrada)
    acum_center = np.cumsum(rate_center_full) * paso

    # Propagacion de sigma al acumular, con incrementos independientes (~raiz t)
    banda = paso * np.sqrt(np.cumsum(rate_std_full ** 2))

    acum_lo = np.maximum(acum_center - k * banda, 0)   # el acumulado no baja de 0
    acum_hi = acum_center + k * banda

    return grid[mask], acum_center[mask], acum_lo[mask], acum_hi[mask]


# =============================================================================
# 4. CLASIFICACION POR ZONA  (notebook celda 12)
# =============================================================================

def classify_curves(df_plot, grid_v, media_v, hi_v):
    """
    Clasifica cada curva segun donde termina y la peor zona que alcanzo.
    Devuelve un DataFrame con Unit, curva, zona_final, peor_zona, horas_max.
    """
    orden = {"Normal": 0, "Alerta": 1, "Anormal": 2}
    inv_orden = {v: k for k, v in orden.items()}

    def zona_de(h, y):
        media = np.interp(h, grid_v, media_v, left=np.nan, right=np.nan)
        umbral = np.interp(h, grid_v, hi_v, left=np.nan, right=np.nan)
        if np.isnan(media) or np.isnan(umbral):
            return None                     # fuera del rango con soporte
        if y > umbral:
            return "Anormal"
        if y > media:
            return "Alerta"
        return "Normal"

    filas = []
    for curva, g in df_plot.groupby("curva"):
        g = g.sort_values("componentHours_filled")
        h = g["componentHours_filled"].to_numpy(dtype=float)
        y = g["ranking_acumulado"].to_numpy(dtype=float)

        zonas_puntos = [z for z in (zona_de(hi, yi) for hi, yi in zip(h, y)) if z]
        if not zonas_puntos:
            continue

        filas.append({
            "Unit": g["Unit"].iloc[0],
            "curva": curva,
            "zona_final": zona_de(h[-1], y[-1]),
            "peor_zona": inv_orden[max(orden[z] for z in zonas_puntos)],
            "horas_max": h[-1],
        })

    if not filas:
        return pd.DataFrame(columns=["Unit", "curva", "zona_final", "peor_zona", "horas_max"])

    return pd.DataFrame(filas)


# =============================================================================
# 5. FIGURA  (notebook celda 11, bloques 3-7)
# =============================================================================

def build_accumulated_figure(df_acum, component="motor", k=K_SIGMA):
    """
    Construye la figura de curva acumulada con zonas de salud.
    Devuelve (figura, resumen_de_zonas) o (None, DataFrame vacio).
    """
    if df_acum is None or df_acum.empty:
        return None, pd.DataFrame()

    band = build_reference_band(df_acum, component=component, k=k)
    if band is None:
        return None, pd.DataFrame()

    grid_v, media_v, _lo_v, hi_v = band

    # ── Ultima curva (ciclo mas reciente) de cada unidad ──
    curvas_recientes = (
        df_acum.groupby(["Unit", "curva"])["Fecha"].max()
        .reset_index()
        .sort_values("Fecha")
        .groupby("Unit")
        .tail(1)["curva"]
        .tolist()
    )

    df_plot = (
        df_acum[df_acum["curva"].isin(curvas_recientes)]
        .dropna(subset=["ranking_acumulado"])
        .copy()
    )

    if df_plot.empty:
        return None, pd.DataFrame()

    # ── Prefijos sinteticos para curvas que arrancan despues del origen ──
    umbral_h0 = grid_v[0] + 1e-9
    prefijos = {}

    for curva, g in df_plot.groupby("curva"):
        h0 = g["componentHours_filled"].min()
        if h0 <= umbral_h0:
            continue

        # Valor de la media en el punto de partida de la curva
        offset = float(np.interp(h0, grid_v, media_v))

        sel = grid_v < h0
        xs = np.append(grid_v[sel], h0)
        ys = np.append(media_v[sel], offset)

        prefijos[curva] = pd.DataFrame({
            "Unit": g["Unit"].iloc[0],
            "componentHours_filled": xs,
            "ranking_acumulado": ys,
        })

        # Desplazar la curva real para que continue desde la media
        df_plot.loc[df_plot["curva"] == curva, "ranking_acumulado"] += offset

    units = sorted(df_plot["Unit"].unique())
    color_map = {u: PALETTE[i % len(PALETTE)] for i, u in enumerate(units)}

    fig = go.Figure()

    # ── Zonas de salud (al fondo) ──
    y_top = max(float(df_plot["ranking_acumulado"].max()), float(hi_v.max())) * 1.05
    y_bottom = np.zeros_like(grid_v)
    x_ida_vuelta = np.concatenate([grid_v, grid_v[::-1]])

    fig.add_trace(go.Scatter(
        x=x_ida_vuelta,
        y=np.concatenate([media_v, y_bottom[::-1]]),
        fill="toself", fillcolor=ZONE_COLORS["Normal"],
        line=dict(width=0), hoverinfo="skip",
        name="Zona normal", legendgroup="zonas",
    ))
    fig.add_trace(go.Scatter(
        x=x_ida_vuelta,
        y=np.concatenate([hi_v, media_v[::-1]]),
        fill="toself", fillcolor=ZONE_COLORS["Alerta"],
        line=dict(width=0), hoverinfo="skip",
        name=f"Zona de alerta (hasta media + {k}σ)", legendgroup="zonas",
    ))
    fig.add_trace(go.Scatter(
        x=x_ida_vuelta,
        y=np.concatenate([np.full_like(grid_v, y_top), hi_v[::-1]]),
        fill="toself", fillcolor=ZONE_COLORS["Anormal"],
        line=dict(width=0), hoverinfo="skip",
        name=f"Zona anormal (> media + {k}σ)", legendgroup="zonas",
    ))

    # ── Prefijos sinteticos (punteados, mismo color, sin leyenda propia) ──
    for curva, pref in prefijos.items():
        unit = pref["Unit"].iloc[0]
        fig.add_trace(go.Scatter(
            x=pref["componentHours_filled"],
            y=pref["ranking_acumulado"],
            mode="lines",
            line=dict(color=color_map.get(unit, "gray"), width=1.4, dash="dot"),
            opacity=0.55,
            hoverinfo="skip",
            showlegend=False,
            legendgroup=unit,
        ))

    # ── Curvas reales, una traza por unidad ──
    for unit in units:
        g_unit = df_plot[df_plot["Unit"] == unit].sort_values("componentHours_filled")
        fig.add_trace(go.Scatter(
            x=g_unit["componentHours_filled"],
            y=g_unit["ranking_acumulado"],
            mode="lines",
            name=unit,
            legendgroup=unit,
            line=dict(color=color_map[unit], width=2.2),
            opacity=0.85,
            customdata=np.stack([
                g_unit["ciclo"].to_numpy(),
                g_unit["Fecha"].dt.strftime("%d %b %Y").to_numpy(),
            ], axis=-1),
            hovertemplate=(
                f"<b>{unit}</b><br>"
                "Horas: %{x:,.0f}<br>"
                "Ranking acum: %{y:,.0f}<br>"
                "Ciclo: %{customdata[0]}<br>"
                "Fecha: %{customdata[1]}<extra></extra>"
            ),
        ))

    # ── Linea de la media de flota (encima de todo) ──
    fig.add_trace(go.Scatter(
        x=grid_v, y=media_v,
        mode="lines",
        line=dict(color="#111827", width=2.4, dash="dash"),
        name="Media de flota",
        hovertemplate="Horas: %{x:,.0f}<br>Media: %{y:,.0f}<extra></extra>",
    ))

    # ── Umbral media + K sigma ──
    fig.add_trace(go.Scatter(
        x=grid_v, y=hi_v,
        mode="lines",
        line=dict(color="rgba(200,60,40,0.7)", width=1.4, dash="dot"),
        name=f"Umbral media + {k}σ",
        hovertemplate="Horas: %{x:,.0f}<br>Umbral: %{y:,.0f}<extra></extra>",
    ))

    # ── Etiqueta permanente al final de cada curva (con anti-solape) ──
    finales = []
    for unit in units:
        g_unit = df_plot[df_plot["Unit"] == unit].sort_values("componentHours_filled")
        if g_unit.empty:
            continue
        finales.append({
            "unit": unit,
            "x": float(g_unit["componentHours_filled"].iloc[-1]),
            "y": float(g_unit["ranking_acumulado"].iloc[-1]),
        })

    if finales:
        # Separacion vertical minima entre rotulos
        y_rango = float(df_plot["ranking_acumulado"].max()) or 1.0
        gap = y_rango * LABEL_MIN_GAP

        finales.sort(key=lambda d: d["y"])
        y_prev = -np.inf
        for f in finales:
            f["y_label"] = max(f["y"], y_prev + gap)
            y_prev = f["y_label"]

        # Puntos en su posicion real
        fig.add_trace(go.Scatter(
            x=[f["x"] for f in finales],
            y=[f["y"] for f in finales],
            mode="markers",
            marker=dict(
                size=7,
                color=[color_map[f["unit"]] for f in finales],
                line=dict(color="white", width=1.5),
            ),
            cliponaxis=False, showlegend=False, hoverinfo="skip",
        ))

        # Rotulos, desplazados verticalmente solo lo necesario
        fig.add_trace(go.Scatter(
            x=[f["x"] for f in finales],
            y=[f["y_label"] for f in finales],
            mode="text",
            text=[f"  {f['unit']}" for f in finales],
            textposition="middle right",
            textfont=dict(
                size=10,
                color=[color_map[f["unit"]] for f in finales],
                family="DM Sans, Inter, sans-serif",
            ),
            cliponaxis=False, showlegend=False, hoverinfo="skip",
        ))

    # ── Entrada de leyenda para explicar los tramos punteados ──
    if prefijos:
        fig.add_trace(go.Scatter(
            x=[None], y=[None], mode="lines",
            line=dict(color="gray", width=1.4, dash="dot"),
            name="Inicio asignado (media)",
        ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, Inter, sans-serif", size=11, color="#6C7280"),
        height=460,
        margin=dict(l=64, r=56, t=16, b=52),
        hovermode="closest",
        legend=dict(
            title=dict(text="Máquina", font=dict(size=11)),
            orientation="v",
            yanchor="top", y=1,
            xanchor="left", x=1.01,
            font=dict(size=10),
            bgcolor="rgba(0,0,0,0)",
        ),
        xaxis=dict(
            title=dict(text="Horas de componente", font=dict(size=11)),
            showgrid=True, gridcolor="rgba(0,0,0,0.05)",
            zeroline=False, tickfont=dict(size=10),
            rangemode="tozero",
            range=[0, float(df_plot["componentHours_filled"].max()) * LABEL_X_PAD],
        ),
        yaxis=dict(
            title=dict(text="Ranking acumulado", font=dict(size=11)),
            showgrid=True, gridcolor="rgba(0,0,0,0.05)",
            zeroline=False, tickfont=dict(size=10),
            rangemode="tozero",
        ),
    )

    resumen = classify_curves(df_plot, grid_v, media_v, hi_v)
    return fig, resumen


# =============================================================================
# 6. SECCION LISTA PARA EL OVERVIEW
# =============================================================================

_ZONE_BADGE = {
    "Anormal":   {"bg": "#fcebeb", "text": "#a32d2d"},
    "Alerta":    {"bg": "#faeeda", "text": "#854f0b"},
    "Normal":    {"bg": "#eaf3de", "text": "#3b6d11"},
}


def _zone_summary_row(resumen):
    """Chips con el conteo de unidades por zona final."""
    if resumen.empty or "zona_final" not in resumen.columns:
        return None

    counts = resumen["zona_final"].value_counts()
    chips = []
    for zona in ("Anormal", "Alerta", "Normal"):
        n = int(counts.get(zona, 0))
        style = _ZONE_BADGE[zona]
        chips.append(html.Div([
            html.Span(str(n), style={
                "fontSize": "15px", "fontWeight": "700", "marginRight": "6px",
            }),
            html.Span(zona, style={"fontSize": "11px"}),
        ], style={
            "background": style["bg"],
            "color": style["text"],
            "padding": "5px 12px",
            "borderRadius": "99px",
            "display": "inline-flex",
            "alignItems": "baseline",
        }))

    return html.Div(chips, style={
        "display": "flex", "gap": "8px", "flexWrap": "wrap",
        "marginBottom": "12px",
    })


def _empty_state(message):
    return html.Div([
        html.Div([
            html.I(className="fas fa-chart-line me-2"),
            "Curva Acumulada de Riesgo",
        ], className="page-title", style={
            "display": "flex", "alignItems": "center", "fontSize": "16px",
        }),
        html.P(message, className="text-muted mb-0",
               style={"fontSize": "13px", "padding": "24px 0"}),
    ], className="card", style={"marginTop": "16px", "marginBottom": "16px"})


def render_accumulated_section(df, df_component_hours, component="motor"):
    """
    Tarjeta completa con la curva acumulada, lista para insertar en el overview.

    Args:
        df: historico completo del componente (Unit, Fecha, ranking, ...)
        df_component_hours: parquet de horas de componente
        component: nombre del componente ("motor", "transmision", ...)
    """
    try:
        df_acum = build_accumulated_data(df, df_component_hours, component)
    except Exception as exc:  # noqa: BLE001 - no romper el overview completo
        return _empty_state(f"No se pudo calcular la curva acumulada: {exc}")

    if df_acum.empty:
        return _empty_state(
            "No hay horas de componente cruzables con el ranking para este componente."
        )

    fig, resumen = build_accumulated_figure(df_acum, component=component)

    if fig is None:
        return _empty_state(
            "No hay suficientes curvas con soporte para construir la banda de referencia."
        )

    excluded = EXCLUDE_FROM_REFERENCE.get(component, [])
    nota_excluidas = (
        f""
        if excluded else ""
    )

    return html.Div([
        html.Div([
            html.H4([
                html.I(className="fas fa-chart-line me-2"),
                "Curva Acumulada de Riesgo",
            ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
            html.P(
                "Ranking acumulado por ciclo de vida frente a las horas del componente. "
                f"La banda de referencia es la media de flota ± {K_SIGMA}σ."
                + nota_excluidas,
                className="text-muted mb-3",
            ),
        ]),
        _zone_summary_row(resumen),
        dcc.Graph(
            figure=fig,
            config={"displayModeBar": False, "responsive": True},
        ),
    ], className="card", style={"marginTop": "16px"})