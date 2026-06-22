"""
Componentes de tablas para la página de evidencia.
"""
from dash import html
import pandas as pd


def create_oil_variables_table(df_unit, variables, oil_labels, oil_thresholds=None):
    """
    Crear tabla de variables de aceite con valores actuales, anteriores,
    variación, velocidad de desgaste y estado.
    
    IMPORTANTE: El "valor anterior" es el último valor DIFERENTE al valor actual,
    no el registro inmediatamente anterior (para evitar comparar con valores replicados).
    """
    if not variables:
        return html.P(
            "No hay variables de aceite asociadas a este modo de falla.",
            style={"color": "var(--text-muted)", "fontSize": "13px"}
        )

    # Obtener serie ordenada por fecha de muestra
    df_sorted = df_unit.sort_values("sampleDate")
    
    if len(df_sorted) < 1:
        return html.P(
            "No hay datos de aceite disponibles.",
            style={"color": "var(--text-muted)", "fontSize": "13px"}
        )

    last_sample = df_sorted.iloc[-1]
    last_date = last_sample.get("sampleDate")

    rows = []

    for var in variables:
        if var not in df_sorted.columns:
            continue

        # Valor actual
        current_val = last_sample.get(var)
        if pd.isna(current_val):
            continue

        current_val = float(current_val)

        # CAMBIO CLAVE: Buscar último valor anterior DIFERENTE al valor actual
        prev_val = None
        prev_date = None
        
        # Recorrer hacia atrás hasta encontrar un valor diferente
        for i in range(len(df_sorted) - 2, -1, -1):
            sample = df_sorted.iloc[i]
            val = sample.get(var)
            if pd.notna(val):
                val = float(val)
                # Comparar con tolerancia para evitar diferencias mínimas por redondeo
                if abs(val - current_val) > 0.001:
                    prev_val = val
                    prev_date = sample.get("sampleDate")
                    break

        # Variación
        if prev_val is not None:
            variation = current_val - prev_val
            variation_pct = (variation / prev_val * 100) if prev_val != 0 else 0
            
            # Calcular días entre muestras efectivamente diferentes
            if prev_date is not None and pd.notna(last_date) and pd.notna(prev_date):
                days_diff = (pd.to_datetime(last_date) - pd.to_datetime(prev_date)).days
                if days_diff > 0:
                    # Velocidad = variación / días
                    velocity = variation / days_diff
                else:
                    velocity = None
            else:
                velocity = None
        else:
            variation = None
            variation_pct = None
            velocity = None

        # Estado (basado en umbrales si están disponibles)
        oil_range = last_sample.get("oilHourRange", "LT_1000")
        status = _get_status(var, current_val, oil_range, oil_thresholds)

        # Construir fila
        rows.append(html.Tr([
            # Variable
            html.Td(
                oil_labels.get(var, var),
                className="fm-td",
                style={"fontWeight": "500", "color": "var(--text-default)"}
            ),
            # Valor actual
            html.Td(
                f"{current_val:.2f}",
                className="fm-td",
                style={"textAlign": "right", "fontFamily": "DM Mono, monospace"}
            ),
            # Valor anterior (último diferente)
            html.Td(
                f"{prev_val:.2f}" if prev_val is not None else "Sin muestra previa",
                className="fm-td",
                style={"textAlign": "right", "fontFamily": "DM Mono, monospace", "color": "var(--text-light)"}
            ),
            # Variación
            html.Td(
                _render_variation(variation, variation_pct),
                className="fm-td",
                style={"textAlign": "center"}
            ),
            # Velocidad de desgaste
            html.Td(
                _render_velocity(velocity),
                className="fm-td",
                style={"textAlign": "center"}
            ),
            # Estado
            html.Td(
                _render_status_badge(status),
                className="fm-td",
                style={"textAlign": "center"}
            ),
        ]))

    if not rows:
        return html.P(
            "No hay datos suficientes para las variables seleccionadas.",
            style={"color": "var(--text-muted)", "fontSize": "13px"}
        )

    table = html.Table([
        html.Thead(html.Tr([
            html.Th("Variable", className="fm-th"),
            html.Th("Valor actual", className="fm-th", style={"textAlign": "right"}),
            html.Th("Valor anterior", className="fm-th", style={"textAlign": "right"}),
            html.Th("Variación", className="fm-th", style={"textAlign": "center"}),
            html.Th("Vel. Desgaste", className="fm-th", style={"textAlign": "center"}),
            html.Th("Estado", className="fm-th", style={"textAlign": "center"}),
        ])),
        html.Tbody(rows),
    ], className="fm-table")

    return html.Div(table, className="fm-table-wrapper")


def _get_status(var, value, oil_range, thresholds):
    """Determinar estado basado en umbrales."""
    if thresholds is None or var not in thresholds:
        return None

    ranges = thresholds[var].get(oil_range)
    if ranges is None:
        return None

    normal, alert, critic = ranges

    if value <= normal:
        return "Normal"
    elif value <= alert:
        return "Alerta"
    else:
        return "Crítico"


def _render_variation(variation, variation_pct):
    """Renderizar celda de variación."""
    if variation is None:
        return html.Span("—", style={"color": "var(--text-light)"})

    if abs(variation) < 0.01:
        color, symbol = "#6C7280", "→"
    elif variation > 0:
        color, symbol = "#e24b4a", "↑"
    else:
        color, symbol = "#1d9e75", "↓"

    return html.Span(
        f"{symbol} {abs(variation):.2f} ({abs(variation_pct):.1f}%)",
        style={
            "color": color,
            "fontFamily": "DM Mono, monospace",
            "fontSize": "11px"
        }
    )


def _render_velocity(velocity):
    """Renderizar celda de velocidad de desgaste calculada entre muestras diferentes."""
    if velocity is None:
        return html.Span("—", style={"color": "var(--text-light)"})

    STABLE = 0.02

    if velocity > STABLE:
        arrow, color, bg = "↑", "#a32d2d", "#fcebeb"
    elif velocity < -STABLE:
        arrow, color, bg = "↓", "#3b6d11", "#eaf3de"
    else:
        arrow, color, bg = "→", "#854f0b", "#faeeda"

    return html.Span(
        f"{arrow} {velocity:+.3f}/d",
        className="status-badge",
        style={
            "background": bg,
            "color": color,
            "fontFamily": "DM Mono, monospace",
            "fontSize": "10px"
        }
    )


def _render_slope(slope):
    """Renderizar celda de velocidad de desgaste (slope) - función legacy mantenida por compatibilidad."""
    if slope is None:
        return html.Span("—", style={"color": "var(--text-light)"})

    STABLE = 0.02

    if slope > STABLE:
        arrow, color, bg = "↑", "#a32d2d", "#fcebeb"
    elif slope < -STABLE:
        arrow, color, bg = "↓", "#3b6d11", "#eaf3de"
    else:
        arrow, color, bg = "→", "#854f0b", "#faeeda"

    return html.Span(
        f"{arrow} {slope:+.3f}/d",
        className="status-badge",
        style={
            "background": bg,
            "color": color,
            "fontFamily": "DM Mono, monospace",
            "fontSize": "10px"
        }
    )


def _render_status_badge(status):
    """Renderizar badge de estado."""
    if status is None:
        return html.Span("—", style={"color": "var(--text-light)"})

    colors = {
        "Normal": {"bg": "#eaf3de", "text": "#3b6d11"},
        "Alerta": {"bg": "#faeeda", "text": "#854f0b"},
        "Crítico": {"bg": "#fcebeb", "text": "#a32d2d"},
    }

    c = colors.get(status, {"bg": "#f0f0f0", "text": "#444"})

    return html.Span(
        status,
        className="status-badge",
        style={
            "background": c["bg"],
            "color": c["text"],
            "fontSize": "11px",
            "fontWeight": "600"
        }
    )
