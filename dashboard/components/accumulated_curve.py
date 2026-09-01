"""
Curva acumulada de riesgo (ERS) — modulo del dashboard.

El NUCLEO DE PROCESAMIENTO (limpieza de horometro, relleno y ciclos,
extrapolacion/truncado de colas, cruce ranking x horas, banda de referencia,
gold) es copia VERBATIM de curva_acumulada.py, que es la fuente de verdad.
No editar esa logica aqui: cambiarla alla y re-sincronizar.

Lo propio del dashboard es:
  - _normalize_unit + build_accumulated_data (wrapper): el modulo canonico
    exige (precondicion 3 de su docstring) unidades normalizadas y horas ya
    limpias; el wrapper garantiza ambas cosas UNA sola vez por llamada, porque
    los consumidores del dashboard pasan el parquet crudo.
  - Las funciones de UI: classify_curves, build_accumulated_figure,
    _zone_summary_row, _empty_state, render_accumulated_section, que conservan
    sus firmas para el resto del dashboard.
"""

import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import dcc, html

from src.utils.logger import get_logger

logger = get_logger(__name__)


# =========================================================================
# CONFIGURACION (verbatim de curva_acumulada.py, salvo DEBUG_TAIL)
# =========================================================================

# Unidades excluidas del CALCULO de la banda de referencia (siguen apareciendo
# en df_gold y se grafican; solo no contaminan la referencia de flota).
# Motivo: horas de componente demasiado sucias como para ser representativas.
# OJO: la comparacion es por igualdad exacta contra la columna Unit.
EXCLUDE_FROM_REFERENCE = {
    "motor": ["T_11"],
    "transmision": ["T_9"],
}

K_SIGMA = 2        # ancho de la banda: media + K_SIGMA * sigma = umbral Anormal
N_GRID = 200       # resolucion de la grilla de horas de la banda
MIN_SUPPORT = 3    # curvas minimas que deben cubrir un punto de la grilla
                   # para que ese punto tenga banda; con menos no hay
                   # estadistica de flota que valga

# -- Extrapolacion de la cola de cada ciclo --
# "Cola" = los dias posteriores a la ultima lectura real de horas. La
# interpolacion no los cubre (solo rellena huecos INTERNOS), asi que se
# proyectan al ritmo reciente de horas/dia.
TAIL_RATE_WINDOW = 60   # dias hacia atras para estimar el ritmo. Debe ser
                        # MAYOR que el intervalo tipico entre muestras (20-30
                        # dias), si no la ventana queda vacia y siempre cae al
                        # fallback de pendiente del ciclo completo.
TAIL_RATE_MIN_PTS = 2   # puntos reales minimos dentro de la ventana
TAIL_RATE_CAP = 20.0    # h/dia maximo. Es un tope de PLAUSIBILIDAD para un
                        # haul truck en operacion continua, no el limite
                        # fisico de 24. Si el ritmo estimado se pega a este
                        # valor en muchas unidades, algo esta mal aguas arriba.

# Tope de dias que se extrapolan despues de la ultima lectura conocida.
# Mas alla de esto no hay un hueco de datos sino AUSENCIA de datos: la curva
# se trunca (los dias quedan en NaN) y build_accumulated_data los descarta.
# Subirlo infla las curvas de las unidades mal muestreadas; bajarlo acorta las
# curvas de las unidades con muestreo espaciado.
MAX_TAIL_DAYS = 45

# -- Lecturas rancias (horometro congelado) --
# DESACTIVADO a proposito (ver el punto 1 de ANTECEDENTES).
# Reactivar (1-3) SOLO si la fuente pasa a ser un horometro con lectura
# diaria real, donde un valor repetido si significa "no tengo dato nuevo".
FLAT_RUN_MAX_DAYS = 999

# Traza detallada del tratamiento de colas, por unidad y ciclo.
DEBUG_TAIL = False   # en el dashboard: sin traza por stdout


# =========================================================================
# CONFIGURACION DE UI (solo dashboard)
# =========================================================================

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


# =========================================================================
# HELPERS
# =========================================================================

def _normalize_unit(unit_id):
    """T_09 -> T_9 (mismo criterio que app.py / overview.py)."""
    if pd.isna(unit_id):
        return unit_id
    unit_str = str(unit_id)
    match = re.match(r"^([A-Za-z]+)_(0+)(\d+)$", unit_str)
    if match:
        return f"{match.group(1)}_{match.group(3)}"
    return unit_str


def _mask_stale_runs(serie, max_run=FLAT_RUN_MAX_DAYS):
    """Anula rachas del mismo valor, conservando solo la primera aparicion.

    Con el default actual (FLAT_RUN_MAX_DAYS = 999) esta funcion es un no-op.
    Se conserva para poder reactivarla si cambia la fuente de horas.

    La logica opera sobre los valores NO nulos compactados, ignorando los NaN
    intermedios. Con muestreo mensual eso significa que dos muestras separadas
    30 dias con el mismo valor cuentan como "racha", que es justamente el
    comportamiento que rompia el pipeline.

    Args:
        serie: Series de horas del ciclo, con NaN en los dias sin lectura.
        max_run: largo maximo tolerado de una racha de valores identicos.

    Returns:
        Copia de la serie con las repeticiones excedentes en NaN.

    OJO: `max_run` se captura como valor por defecto AL DEFINIR la funcion.
    Cambiar FLAT_RUN_MAX_DAYS en una celda posterior de un notebook no afecta
    a esta firma; hay que reejecutar el `def`.
    """
    s = serie.copy()
    validos = s.dropna()
    if len(validos) < 2:
        return s

    # cumsum sobre "el valor cambio" -> un id de grupo por racha
    grupo = (validos != validos.shift()).cumsum()
    for _g, idx in validos.groupby(grupo).groups.items():
        if len(idx) > max_run:
            s.loc[list(idx)[1:]] = np.nan
    return s


def _tail_rate(fechas, valores, window=TAIL_RATE_WINDOW, min_pts=TAIL_RATE_MIN_PTS):
    """Estima el ritmo de acumulacion de horas (h/dia) al final de un ciclo.

    Usa la PENDIENTE AGREGADA de la ventana — (horas_fin - horas_inicio) /
    (dias transcurridos) — y no la mediana de los incrementos diarios. Con
    lecturas espaciadas la mayoria de los incrementos diarios valen 0, y la
    mediana daba 0 h/dia: la cola quedaba plana y la curva subia en vertical.

    Estrategia en dos niveles:
      1. Pendiente de los ultimos `window` dias, si hay al menos `min_pts`.
      2. Fallback: pendiente de todo el ciclo.

    Args:
        fechas: iterable de fechas de las lecturas conocidas.
        valores: horas correspondientes a esas fechas.
        window: dias hacia atras desde la ultima lectura.
        min_pts: puntos minimos dentro de la ventana.

    Returns:
        float en [0, TAIL_RATE_CAP]. Devuelve 0.0 si no se puede estimar, lo
        que dejaria la cola plana — el llamador tiene su propia cadena de
        respaldo para ese caso.

    Mismo detalle que en _mask_stale_runs: `window` y `min_pts` se capturan
    al definir la funcion.
    """
    if len(valores) < 2:
        return 0.0

    t = pd.to_datetime(pd.Series(fechas)).to_numpy()
    v = np.asarray(valores, dtype=float)

    def _slope(t_sub, v_sub):
        """Pendiente h/dia entre el primer y ultimo punto del subconjunto."""
        if len(v_sub) < 2:
            return None
        dias = (t_sub[-1] - t_sub[0]) / np.timedelta64(1, "D")
        if dias <= 0:
            return None
        return (v_sub[-1] - v_sub[0]) / dias

    corte = t[-1] - np.timedelta64(int(window), "D")
    sel = t >= corte

    rate = _slope(t[sel], v[sel]) if sel.sum() >= min_pts else None
    if rate is None or rate <= 0:
        rate = _slope(t, v)          # fallback: pendiente del ciclo completo
    if rate is None or rate <= 0:
        return 0.0

    return float(np.clip(rate, 0.0, TAIL_RATE_CAP))


# =========================================================================
# NUCLEO CANONICO (verbatim de curva_acumulada.py)
# =========================================================================

def clean_component_hours(df, hours_col='componentHours_cleaned', unit_col='unitId',
                          component_col='componentName', date_col='sampleDate'):
    """Limpia el horometro crudo, por unidad y componente.

    Un horometro deberia ser monotono creciente y reiniciarse solo cuando se
    cambia el componente. En la practica trae duplicados por fecha, digitos de
    mas, y bajadas pequenas que son errores de transcripcion.

    Pasos:
        1. Duplicados por fecha: se conserva el valor mas coherente con la
           tendencia (el mas cercano al promedio de sus vecinos).
        2. Picos: valores muy por encima de ambos vecinos, reemplazados por
           interpolacion. NOTA: el bucle va de 1 a n-2, asi que un pico en la
           PRIMERA o ULTIMA muestra de una unidad no se corrige. La ultima es
           especialmente sensible porque ancla la extrapolacion de cola.
        3. Resets reales: bajada a menos del 30% del valor previo. Se marcan
           pero no se corrigen — son cambios de componente legitimos.
        4. Bajadas que NO son reset: se aplanan hacia arriba.
        5. NaN originales que caen justo antes de un reset: se invalidan,
           porque interpolar a traves de un cambio de componente no tiene
           sentido fisico.

    Args:
        df: DataFrame de horas de la capa de plata.
        hours_col: columna de horas a limpiar.
        unit_col, component_col, date_col: columnas de agrupacion y orden.

    Returns:
        DataFrame con `hours_col` limpio, ordenado por unidad/componente/fecha
        y con el indice reseteado.

    ADVERTENCIA — NO ES IDEMPOTENTE. El paso 4 fuerza monotonicidad; correrla
    dos veces sobre el mismo DataFrame aplica el trinquete dos veces y las
    horas suben en cada pasada. No hacer `df = clean_component_hours(df)` en
    una celda de notebook que se reejecuta; usar un nombre distinto:
        df_hours_clean = clean_component_hours(df_hours)

    Los umbrales de reset de esta funcion (0.3) y de fill_hours_progressive
    (0.5) NO coinciden a proposito, pero interactuan: el paso 4 de aqui aplana
    toda bajada menor al 70%, asi que fill_hours_progressive nunca llega a ver
    bajadas en el rango 30-50%. Si se cambia uno, revisar el otro.
    """
    df = df.copy()
    # El orden cronologico es un supuesto de TODO lo que sigue. Si date_col
    # llega como string, sort_values ordena alfabeticamente y la deteccion de
    # resets y bajadas opera sobre una serie barajada, sin error visible.
    df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
    df = df.sort_values([unit_col, component_col, date_col])
    result = []

    for (unit, comp), group in df.groupby([unit_col, component_col]):
        group = group.reset_index(drop=True)

        # -- 1. Eliminar duplicados por fecha --
        # De cada grupo de filas con la misma fecha se conserva la que mejor
        # encaja con la tendencia local (promedio del vecino anterior y el
        # siguiente); las demas se descartan.
        dup_dates = group[date_col][group.duplicated(subset=[date_col], keep=False)].unique()
        if len(dup_dates) > 0:
            to_drop = []
            for date in dup_dates:
                mask = group[date_col] == date
                dup_idx = group.index[mask].tolist()
                first_dup, last_dup = dup_idx[0], dup_idx[-1]
                prev_val = group.loc[:first_dup - 1, hours_col].dropna().values[-1] if first_dup > 0 else None
                nxt_val = group.loc[last_dup + 1:, hours_col].dropna().values[0] if last_dup < len(group) - 1 else None

                if prev_val is not None and nxt_val is not None:
                    expected = (prev_val + nxt_val) / 2
                elif prev_val is not None:
                    expected = prev_val
                elif nxt_val is not None:
                    expected = nxt_val
                else:
                    expected = np.nanmedian(group.loc[dup_idx, hours_col].values)

                best = min(dup_idx, key=lambda i: abs(group.loc[i, hours_col] - expected) if not pd.isna(group.loc[i, hours_col]) else float('inf'))
                to_drop.extend([i for i in dup_idx if i != best])
            group = group.drop(to_drop).reset_index(drop=True)

        vals = group[hours_col].values.copy()
        raw_vals = group['componentHours'].values if 'componentHours' in group.columns else None
        n = len(vals)

        # -- 2. Corregir outliers (picos) --
        # Dos criterios: 5x ambos vecinos (digito de mas), o 2x ambos vecinos
        # con una diferencia absoluta grande (salto no explicable por uso).
        for i in range(1, n - 1):
            prev, curr, nxt = vals[i-1], vals[i], vals[i+1]
            if pd.isna(curr) or pd.isna(prev) or pd.isna(nxt):
                continue
            if prev == 0 and nxt == 0:
                continue
            is_spike = (
                (curr > prev * 5 and curr > nxt * 5) or
                (curr > prev * 2 and curr > nxt * 2 and (curr - max(prev, nxt)) > 2000)
            )
            if is_spike:
                vals[i] = (prev + nxt) / 2 if nxt >= prev else nxt / 2

        # -- 3. Detectar resets reales (bajada > 70%) --
        # Solo se MARCAN. Un reset es un cambio de componente y debe
        # preservarse: es lo que separa un ciclo del siguiente.
        reset_threshold = 0.3
        is_reset = [False] * n
        for i in range(1, n):
            if pd.isna(vals[i]) or pd.isna(vals[i-1]) or vals[i-1] == 0:
                continue
            if vals[i] < vals[i-1] * reset_threshold:
                is_reset[i] = True

        # -- 4. Corregir pequenas bajadas (no-resets) --
        # Un horometro no puede retroceder. Si la proxima lectura valida
        # confirma el nivel previo, se interpola; si no, se aplana al valor
        # anterior. Esto es un trinquete: de aqui viene la no-idempotencia.
        for i in range(1, n):
            if pd.isna(vals[i]) or pd.isna(vals[i-1]):
                continue
            if vals[i] < vals[i-1] and not is_reset[i]:
                nxt_val = None
                for j in range(i+1, n):
                    if not pd.isna(vals[j]) and not is_reset[j]:
                        nxt_val = vals[j]
                        break
                if nxt_val is not None and nxt_val >= vals[i-1]:
                    vals[i] = (vals[i-1] + nxt_val) / 2
                else:
                    vals[i] = vals[i-1]

        # -- 5. Invalidar NaNs originales antes de un reset --
        # Si el valor venia NaN en el crudo y hay un reset dentro de las 2
        # filas siguientes, cualquier relleno cruzaria el cambio de componente.
        # Mejor dejarlo desconocido.
        if raw_vals is not None:
            for i in range(n):
                if pd.isna(raw_vals[i]):
                    for j in range(i+1, min(i+3, n)):
                        if is_reset[j]:
                            vals[i] = np.nan
                            break

        group[hours_col] = vals
        result.append(group)

    return pd.concat(result, ignore_index=True)


def fill_hours_progressive(df, hours_col="componentHours_cleaned", unit_col="Unit"):
    """Rellena horas faltantes por unidad y detecta los ciclos de vida.

    Entra un DataFrame diario (una fila por unidad y dia, resultado del merge
    contra el ranking) donde `hours_col` solo tiene valor en los dias con
    muestra de aceite. Sale el mismo DataFrame con dos columnas nuevas:
    `componentHours_filled` y `ciclo`.

    Cada dia del ciclo se resuelve por una de tres vias:
      - Lectura real: se usa tal cual.
      - Hueco INTERNO (entre dos lecturas): interpolacion lineal.
      - Cola (posterior a la ultima lectura): extrapolacion al ritmo estimado
        por _tail_rate, hasta un maximo de MAX_TAIL_DAYS dias. Mas alla, NaN.

    Deteccion de ciclos: una bajada a menos del 50% del valor previo se
    interpreta como cambio de componente e incrementa el contador de ciclo.
    Una bajada menor se considera error y se aplana al valor anterior.

    Args:
        df: DataFrame con unit_col, "Fecha" y hours_col.
        hours_col: columna de horas (con NaN en los dias sin muestra).
        unit_col: columna de unidad.

    Returns:
        DataFrame con `componentHours_filled` (float, con NaN en los dias
        truncados) y `ciclo` (int, desde 1).

    Efectos de borde: imprime un aviso por cada ciclo truncado y por cada
    ciclo donde no se pudo estimar el ritmo. Esos avisos son la senal de que
    una unidad dejo de muestrearse.

    DETALLES FRAGILES
    -----------------
    - `interpolate(limit_area="inside")` es deliberado. Sin ese argumento
      pandas tambien rellena los NaN finales propagando el ultimo valor
      valido (equivale a un ffill), lo que deja la cola plana y ademas hace
      que el bloque de extrapolacion nunca se ejecute: al consultar isna() ya
      no queda ningun NaN que procesar.
    - El truncado se aplica DESPUES del bfill/ffill de seguridad. Si se
      moviera antes, esas dos lineas volverian a rellenar los dias que se
      acaban de descartar y el tope no tendria efecto.
    """
    df = df.sort_values([unit_col, "Fecha"]).copy()
    result = []

    for _unit, group in df.groupby(unit_col):
        group = group.reset_index(drop=True)
        raw = group[hours_col].copy()
        known_idx = raw.dropna().index.tolist()

        # Unidad sin ninguna lectura: no hay nada que reconstruir.
        if len(known_idx) == 0:
            group["componentHours_filled"] = np.nan
            group["ciclo"] = 1
            result.append(group)
            continue

        # -- Pasada de deteccion de ciclos sobre las lecturas conocidas --
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

        # El ciclo de los dias SIN lectura se hereda del dia anterior con
        # lectura (ffill). Los dias previos a la primera lectura toman el
        # primer ciclo conocido (bfill).
        ciclos_filled = pd.Series(np.nan, index=group.index, dtype="float64")
        for i in known_idx:
            ciclos_filled[i] = ciclos[i]
        ciclos_filled = ciclos_filled.ffill().bfill().fillna(1).astype(int)

        # -- Relleno de horas, ciclo por ciclo --
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

            # Si el ciclo empieza antes de la primera lectura, se ancla en 0:
            # un componente nuevo arranca con cero horas.
            if first_known_in_cycle > first_in_cycle:
                cycle_series.iloc[0] = 0.0

            # No-op con el default actual (ver FLAT_RUN_MAX_DAYS).
            cycle_series = _mask_stale_runs(cycle_series)

            # Solo huecos internos; la cola queda en NaN a proposito.
            cycle_series = cycle_series.interpolate(method="linear", limit_area="inside")

            # -- Cola: extrapolar hasta MAX_TAIL_DAYS, truncar el resto --
            faltan_cola = cycle_series.index[cycle_series.isna()]
            idx_truncados = []
            if DEBUG_TAIL:
                print(f"[cola] {_unit} ciclo {cycle}: {len(cycle_idx)} dias, "
                      f"{len(faltan_cola)} NaN tras interpolar")
            if len(faltan_cola):
                conocidos = cycle_series.dropna()
                ultimo_idx = conocidos.index[-1]
                ultimo_val = float(conocidos.iloc[-1])

                fechas_ciclo = group.loc[conocidos.index, "Fecha"]
                rate = _tail_rate(fechas_ciclo.to_numpy(), conocidos.to_numpy())

                # Cadena de respaldo: sin un ritmo > 0 la cola queda plana, que
                # es el defecto que se quiere evitar. Se prueban ventanas cada
                # vez mas amplias antes de rendirse.
                if rate <= 0:                     # pendiente del ciclo completo
                    rate = _tail_rate(fechas_ciclo.to_numpy(), conocidos.to_numpy(),
                                      window=10 ** 6)
                if rate <= 0:                     # ritmo medio de la unidad
                    v_all = adjusted.dropna()
                    if len(v_all) >= 2:
                        t_all = pd.to_datetime(group.loc[v_all.index, "Fecha"])
                        dias_all = (t_all.iloc[-1] - t_all.iloc[0]).total_seconds() / 86400.0
                        if dias_all > 0:
                            rate = max((v_all.iloc[-1] - v_all.iloc[0]) / dias_all, 0.0)
                if rate <= 0:
                    print(f"  ! {_unit} ciclo {cycle}: no se pudo estimar ritmo de "
                          f"horas; la cola quedara plana ({len(faltan_cola)} dias).")

                t_ref = pd.to_datetime(group.at[ultimo_idx, "Fecha"])
                dias = (
                    pd.to_datetime(group.loc[faltan_cola, "Fecha"]) - t_ref
                ).dt.total_seconds() / 86400.0

                dentro = (dias <= MAX_TAIL_DAYS).to_numpy()
                idx_ok = faltan_cola[dentro]
                idx_truncados = list(faltan_cola[~dentro])

                cycle_series.loc[idx_ok] = (
                    ultimo_val + rate * dias[dentro].clip(lower=0).to_numpy()
                )

                # Este aviso es diagnostico, no cosmetico: indica que la unidad
                # dejo de muestrearse en esa fecha.
                if idx_truncados:
                    print(f"  ! {_unit} ciclo {cycle}: {len(idx_truncados)} dias "
                          f"truncados (ultima lectura {t_ref:%d/%m/%Y}, "
                          f"tope {MAX_TAIL_DAYS} dias).")

                if DEBUG_TAIL:
                    print(f"[cola] {_unit} ciclo {cycle}: ultima lectura "
                          f"{t_ref:%d/%m/%Y} = {ultimo_val:.1f} h - "
                          f"ritmo {rate:.2f} h/dia - {len(idx_ok)} dias "
                          f"extrapolados, {len(idx_truncados)} truncados")

            # NaN al inicio del ciclo (sin ancla en 0): se cubren hacia atras.
            if cycle_series.isna().any():
                cycle_series = cycle_series.bfill()
            cycle_series = cycle_series.ffill()   # red de seguridad

            # El truncado va DESPUES del bfill/ffill: si no, esas dos lineas
            # vuelven a rellenar los dias que acabamos de descartar.
            if idx_truncados:
                cycle_series.loc[idx_truncados] = np.nan

            hours_filled[cycle_idx] = cycle_series.values

        group["componentHours_filled"] = hours_filled
        group["ciclo"] = ciclos_filled
        result.append(group)

    if not result:
        return df.assign(componentHours_filled=np.nan, ciclo=1)
    return pd.concat(result, ignore_index=True)


def _build_accumulated_core(df, df_component_hours, component="motor"):
    """Cruza el ranking diario con las horas y acumula el riesgo por ciclo.

    Args:
        df: ranking diario (Unit, Fecha, ranking).
        df_component_hours: horas ya limpias (unitId, componentName,
            sampleDate, componentHours_cleaned).
        component: "motor" o "transmision".

    Returns:
        DataFrame con una fila por unidad y dia con horas resueltas, mas:
        componentHours_filled, ciclo, ranking_acumulado, curva.
        DataFrame VACIO si falta alguna de las entradas o si el cruce no deja
        ninguna fila util — el llamador decide si eso es un error.

    El merge es LEFT desde el ranking: manda el calendario del ranking y las
    horas se pegan donde hay muestra. Los dias sin horas resueltas (truncados
    por MAX_TAIL_DAYS) se descartan aqui.

    Los valores no finitos del ranking se filtran antes de acumular: un -inf
    envenena la media y la sigma de la banda de referencia y hace que todas
    las curvas se rendericen apelotonadas cerca del origen.
    """
    if df is None or df.empty or "ranking" not in df.columns:
        return pd.DataFrame()
    if df_component_hours is None or df_component_hours.empty:
        return pd.DataFrame()

    base = df.loc[:, ["Unit", "Fecha", "ranking"]].copy()
    base["Fecha"] = pd.to_datetime(base["Fecha"])

    # Descarta -inf/+inf/NaN del ranking (envenenan media/sigma de la banda).
    base["ranking"] = pd.to_numeric(base["ranking"], errors="coerce")
    base = base[np.isfinite(base["ranking"])]
    if base.empty:
        return pd.DataFrame()

    hours = df_component_hours[df_component_hours["componentName"] == component].copy()
    if hours.empty:
        return pd.DataFrame()

    hours["Fecha"] = pd.to_datetime(hours["sampleDate"])
    hours = (
        hours.loc[:, ["unitId", "Fecha", "componentHours_cleaned"]]
        .rename(columns={"unitId": "Unit"})
        .dropna(subset=["componentHours_cleaned"])
        # Si un dia tiene mas de una muestra, se queda la ultima del archivo.
        .drop_duplicates(subset=["Unit", "Fecha"], keep="last")
    )

    # OJO: el merge es por igualdad exacta de Unit. Formatos distintos entre
    # las dos fuentes ("T_9" vs "T_09") producen un resultado todo-NaN sin
    # ningun error visible.
    merged = base.merge(hours, on=["Unit", "Fecha"], how="left")
    merged = fill_hours_progressive(merged)
    # Aqui caen los dias truncados por MAX_TAIL_DAYS.
    merged = merged.dropna(subset=["componentHours_filled"])
    if merged.empty:
        return pd.DataFrame()

    merged = merged.sort_values(["Unit", "ciclo", "Fecha"])
    merged["ranking_acumulado"] = merged.groupby(["Unit", "ciclo"])["ranking"].cumsum()
    merged["curva"] = merged["Unit"].astype(str) + " \u00b7 ciclo " + merged["ciclo"].astype(str)
    return merged


def build_reference_band(df_acum, component="motor", k=K_SIGMA, n_grid=N_GRID):
    """Media de flota +- k sigma sobre la TASA de riesgo por hora, integrada.

    POR QUE SOBRE LA TASA Y NO SOBRE EL ACUMULADO
    ---------------------------------------------
    Promediar directamente las curvas acumuladas seria incorrecto: cada curva
    empieza a observarse en un punto distinto de la vida del componente, asi
    que a una misma hora unas llevan mucho acumulado y otras poco, por razones
    de observacion y no de riesgo.

    En cambio la TASA (ranking por hora de componente) es una propiedad local:
    "cuanto riesgo se acumula por cada hora operada alrededor de las N horas".
    Eso si es comparable entre curvas. Se promedia la tasa en cada punto de la
    grilla y despues se integra (cumsum * paso) para volver al espacio
    acumulado.

    La banda de incertidumbre se propaga como suma en cuadratura de las sigmas
    de la tasa — se asume independencia entre intervalos —, por eso crece con
    la raiz del numero de pasos y no linealmente.

    Args:
        df_acum: salida de build_accumulated_data.
        component: clave para EXCLUDE_FROM_REFERENCE.
        k: multiplos de sigma para el umbral superior.
        n_grid: puntos de la grilla de horas.

    Returns:
        Tupla (grid, acum_center, acum_lo, acum_hi) recortada a los puntos con
        soporte suficiente, o None si no hay estadistica utilizable. Los
        cuatro arrays tienen el mismo largo.

    El dominio llega hasta el percentil 95 de las horas maximas por curva, no
    hasta el maximo absoluto: una sola curva larga no debe estirar la grilla
    hacia una zona donde ninguna otra aporta datos.

    Si tras excluir las unidades sucias quedan menos de MIN_SUPPORT curvas, se
    revierte a usar TODAS — es preferible una banda con datos sucios que
    ninguna banda.
    """
    excluded = EXCLUDE_FROM_REFERENCE.get(component, [])
    df_ref = df_acum[~df_acum["Unit"].isin(excluded)]
    if df_ref.empty or df_ref["curva"].nunique() < MIN_SUPPORT:
        df_ref = df_acum
    if df_ref.empty:
        return None

    h_max = df_ref.groupby("curva")["componentHours_filled"].max().quantile(0.95)
    if not np.isfinite(h_max) or h_max <= 0:
        return None

    grid = np.linspace(0, float(h_max), n_grid)
    paso = grid[1] - grid[0]

    # -- Tasa por hora de cada curva, remuestreada sobre la grilla comun --
    curvas_rate = []
    for _, g in df_ref.groupby("curva"):
        g = g.dropna(subset=["componentHours_filled", "ranking"]).sort_values("Fecha")
        if len(g) < 2:
            continue
        h = g["componentHours_filled"].to_numpy(dtype=float)
        r = g["ranking"].to_numpy(dtype=float)
        dh = np.diff(h)
        ok = dh > 0                      # intervalos sin avance de horas no
        if not ok.any():                 # aportan tasa (division por cero)
            continue
        rate = r[1:][ok] / dh[ok]
        h_mid = ((h[1:] + h[:-1]) / 2)[ok]   # la tasa vive en el punto medio
        if len(h_mid) < 2:
            continue
        y = np.interp(grid, h_mid, rate)
        # Fuera del rango observado de la curva no se extrapola: NaN.
        y[(grid < h_mid.min()) | (grid > h_mid.max())] = np.nan
        curvas_rate.append(y)

    if not curvas_rate:
        return None

    # -- Estadistica por punto de grilla --
    M = np.vstack(curvas_rate)           # (n_curvas, n_grid)
    # Un punto solo tiene banda si suficientes curvas lo cubren.
    mask = np.sum(~np.isnan(M), axis=0) >= min(MIN_SUPPORT, M.shape[0])
    if not mask.any():
        return None

    rate_center = np.full(grid.shape, np.nan)
    rate_std = np.full(grid.shape, np.nan)
    rate_center[mask] = np.nanmean(M[:, mask], axis=0)
    rate_std[mask] = np.nanstd(M[:, mask], axis=0, ddof=1) if M.shape[0] > 1 else 0.0

    # La integracion necesita la serie completa; los puntos sin soporte se
    # rellenan por interpolacion (y con 0 en los extremos) solo para poder
    # acumular. El recorte final por `mask` los deja fuera del resultado.
    rate_center_full = pd.Series(rate_center).interpolate().fillna(0).to_numpy()
    rate_std_full = pd.Series(rate_std).interpolate().fillna(0).to_numpy()

    # -- Integracion: de tasa por hora a riesgo acumulado --
    acum_center = np.cumsum(rate_center_full) * paso
    # Suma en cuadratura: la incertidumbre crece con sqrt(n_pasos).
    banda = paso * np.sqrt(np.cumsum(rate_std_full ** 2))
    acum_lo = np.maximum(acum_center - k * banda, 0)   # el riesgo no es negativo
    acum_hi = acum_center + k * banda

    return grid[mask], acum_center[mask], acum_lo[mask], acum_hi[mask]


def build_gold_curve(df, df_component_hours, component="motor", k=K_SIGMA):
    """Construye df_gold: todo lo necesario para graficar y clasificar.

    Una fila por punto de curva (Unit x ciclo x Fecha). Ver el glosario de
    columnas en el docstring del modulo.

    Decisiones de diseno:
      - La banda de referencia se calcula con TODAS las curvas, incluidos los
        ciclos historicos. Filtrar por vigencia es una decision de
        VISUALIZACION, no de estadistica: mientras mas vidas de componente
        aporten, mejor la referencia.
      - Cada curva que no arranca en h~0 se desplaza al valor de la media de
        flota en su hora de inicio (offset). Ver la nota OFFSET del modulo.
      - El estado punto a punto se evalua sobre el acumulado AJUSTADO, no
        sobre el crudo. Se conservan ambas columnas para poder auditar si un
        salto viene del offset o de los datos.
      - zona_final clasifica cada unidad segun el ULTIMO punto observado de su
        ciclo vigente. Es constante dentro de la curva y NaN en las
        historicas, para que el boletin la lea directo sin recalcular.

    Args:
        df: ranking diario (Unit, Fecha, ranking).
        df_component_hours: horas ya pasadas por clean_component_hours.
        component: "motor" o "transmision".
        k: multiplos de sigma para el umbral Anormal.

    Returns:
        DataFrame df_gold ordenado por Unit, ciclo, Fecha.

    Raises:
        ValueError: si no hay horas cruzables con el ranking, o si no hay
            soporte suficiente para la banda de referencia.

    Falla RUIDOSO a proposito. En un Lambda agendado, devolver un gold con
    estado en blanco terminaria con exit code 0 y el boletin saldria vacio sin
    que nadie se entere; una excepcion queda en CloudWatch y falla la
    invocacion, que es el comportamiento deseado.
    """
    gold_cols = ["Unit", "Fecha", "ciclo", "curva", "componentHours_filled",
                 "ranking", "ranking_acumulado", "offset_curva",
                 "ranking_acumulado_ajustado", "banda_media", "banda_umbral",
                 "estado", "es_vigente", "zona_final", "componente"]

    df_gold = build_accumulated_data(df, df_component_hours, component)
    if df_gold is None or df_gold.empty:
        raise ValueError(
            f"[{component}] no hay horas de componente cruzables con el ranking."
        )

    df_gold["Fecha"] = pd.to_datetime(df_gold["Fecha"])
    df_gold["componente"] = component

    band = build_reference_band(df_gold, component=component, k=k)
    if band is None:
        raise ValueError(
            f"[{component}] sin soporte suficiente para la banda de referencia "
            f"({df_gold['curva'].nunique()} curvas, minimo {MIN_SUPPORT})."
        )
    grid_v, media_v, _lo_v, hi_v = band

    # -- Offset por curva: arrancar desde la media de flota en h0 --
    # Las curvas que ya arrancan en el origen (h0 ~ 0) no se tocan.
    # np.interp clampa fuera de la grilla: una curva con h0 > grid_v[-1]
    # recibe media_v[-1]. Con las horas acotadas eso deberia ser raro; si
    # aparece, es senal de que quedan curvas infladas.
    umbral_h0 = grid_v[0] + 1e-9
    h0 = df_gold.groupby("curva")["componentHours_filled"].transform("min").to_numpy(dtype=float)
    offset = np.where(h0 > umbral_h0, np.interp(h0, grid_v, media_v), 0.0)

    df_gold["offset_curva"] = offset
    df_gold["ranking_acumulado_ajustado"] = df_gold["ranking_acumulado"] + offset

    # -- Estado punto a punto sobre el acumulado ajustado --
    # Fuera del dominio de la banda el estado queda en None: no se clasifica
    # lo que no se puede comparar.
    h = df_gold["componentHours_filled"].to_numpy(dtype=float)
    y = df_gold["ranking_acumulado_ajustado"].to_numpy(dtype=float)

    media = np.interp(h, grid_v, media_v, left=np.nan, right=np.nan)
    umbral = np.interp(h, grid_v, hi_v, left=np.nan, right=np.nan)

    fuera_banda = np.isnan(media) | np.isnan(umbral)
    df_gold["banda_media"] = media
    df_gold["banda_umbral"] = umbral
    # np.select evalua en orden: la primera condicion verdadera gana.
    df_gold["estado"] = np.select(
        [fuera_banda, y > umbral, y > media],
        [None, "Anormal", "Alerta"],
        default="Normal",
    )

    # -- Ciclo vigente: la curva con la Fecha mas reciente de cada unidad --
    vigentes = (
        df_gold.groupby(["Unit", "curva"], sort=False)["Fecha"].max()
        .reset_index()
        .sort_values("Fecha")
        .groupby("Unit")
        .tail(1)["curva"]
    )
    df_gold["es_vigente"] = df_gold["curva"].isin(set(vigentes))

    # -- zona_final: estado del ultimo punto (por Fecha) de la curva vigente --
    # Se ordena por Fecha y no por horas: con horas repetidas el orden entre
    # empates es arbitrario y el "ultimo" punto seria cualquiera.
    ultimos = (
        df_gold[df_gold["es_vigente"]]
        .sort_values("Fecha")
        .groupby("curva", sort=False)
        .tail(1)
        .set_index("curva")["estado"]
    )
    df_gold["zona_final"] = df_gold["curva"].map(ultimos).where(df_gold["es_vigente"])

    df_gold = df_gold.loc[:, gold_cols].sort_values(["Unit", "ciclo", "Fecha"])

    return df_gold


# =========================================================================
# ADAPTADOR DASHBOARD
# =========================================================================

def build_accumulated_data(df, df_component_hours, component="motor"):
    """Adaptador del dashboard sobre el nucleo canonico (_build_accumulated_core).

    El nucleo exige (precondiciones de curva_acumulada.py):
      3. unidades identicas entre ambas fuentes  -> aqui se normalizan (T_09 -> T_9)
      -  horas ya pasadas por clean_component_hours -> aqui se limpian UNA vez

    Los consumidores del dashboard pasan el parquet crudo, por eso este wrapper
    hace ambas cosas antes de delegar. clean_component_hours NO es idempotente:
    nunca limpiar antes de llamar a esta funcion.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    if df_component_hours is None or df_component_hours.empty:
        return pd.DataFrame()

    df = df.copy()
    df["Unit"] = df["Unit"].apply(_normalize_unit)

    hours = df_component_hours.copy()
    if "unitId" in hours.columns:
        hours["unitId"] = hours["unitId"].apply(_normalize_unit)

    hours = clean_component_hours(hours)

    return _build_accumulated_core(df, hours, component)


# =========================================================================
# UI (solo dashboard; firmas estables para los consumidores)
# =========================================================================

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


# =========================================================================
# Data Contract v2.0 (Change 6) — build the curve from the precomputed
# `cumulative_risk_curve` table instead of the client-side pipeline above.
# Only used when predictive_v2.read_cumulative_risk_curve() returns data for
# a client/component; callers fall back to render_accumulated_section (the
# Oil-join pipeline above) otherwise. Only the 8 confirmed columns are used
# - see CURVE_TABLE_COLUMNS in src/data/predictive_v2.py.
# =========================================================================

from src.data.predictive_v2 import CUMULATIVE_CURVE_COLUMNS  # noqa: E402


def build_accumulated_figure_from_curve(df_curve, component="motor"):
    """
    Build the cumulative-curve figure directly from the precomputed
    `cumulative_risk_curve` table. Zone boundaries come from the table's own
    per-point `banda_media`/`banda_umbral` (a single function of component
    hours, shared across curves), not from build_reference_band/K_SIGMA.

    Returns (figure, resumen) or (None, empty DataFrame) - same contract as
    build_accumulated_figure, so render_accumulated_section_from_curve can
    reuse _zone_summary_row/_empty_state unchanged.
    """
    if df_curve is None or df_curve.empty:
        return None, pd.DataFrame()

    missing = [c for c in CUMULATIVE_CURVE_COLUMNS if c not in df_curve.columns]
    if missing:
        return None, pd.DataFrame()

    df = df_curve.loc[:, CUMULATIVE_CURVE_COLUMNS].copy()
    df = df.dropna(subset=["componentHours_filled", "ranking_acumulado_ajustado"])
    if df.empty:
        return None, pd.DataFrame()

    # ── Curva vigente de cada unidad (la actual, una por unidad) ──
    df_plot = df[df["es_vigente"] == True].copy()  # noqa: E712 - bool compare, column may be object dtype
    if df_plot.empty:
        return None, pd.DataFrame()

    # ── Banda de referencia: puntos únicos (hora, media, umbral) ya
    # calculados upstream - una sola función de horas, compartida entre
    # curvas, así que basta con deduplicar sobre todo el histórico. ──
    band_points = (
        df.loc[:, ["componentHours_filled", "banda_media", "banda_umbral"]]
        .dropna()
        .drop_duplicates(subset=["componentHours_filled"])
        .sort_values("componentHours_filled")
    )
    if band_points.empty:
        return None, pd.DataFrame()
    grid_v = band_points["componentHours_filled"].to_numpy(dtype=float)
    media_v = band_points["banda_media"].to_numpy(dtype=float)
    hi_v = band_points["banda_umbral"].to_numpy(dtype=float)

    units = sorted(df_plot["Unit"].unique())
    color_map = {u: PALETTE[i % len(PALETTE)] for i, u in enumerate(units)}

    fig = go.Figure()

    y_top = max(float(df_plot["ranking_acumulado_ajustado"].max()), float(hi_v.max())) * 1.05
    y_bottom = np.zeros_like(grid_v)
    x_ida_vuelta = np.concatenate([grid_v, grid_v[::-1]])

    fig.add_trace(go.Scatter(
        x=x_ida_vuelta, y=np.concatenate([media_v, y_bottom[::-1]]),
        fill="toself", fillcolor=ZONE_COLORS["Normal"],
        line=dict(width=0), hoverinfo="skip", name="Zona normal", legendgroup="zonas",
    ))
    fig.add_trace(go.Scatter(
        x=x_ida_vuelta, y=np.concatenate([hi_v, media_v[::-1]]),
        fill="toself", fillcolor=ZONE_COLORS["Alerta"],
        line=dict(width=0), hoverinfo="skip", name="Zona de alerta", legendgroup="zonas",
    ))
    fig.add_trace(go.Scatter(
        x=x_ida_vuelta, y=np.concatenate([np.full_like(grid_v, y_top), hi_v[::-1]]),
        fill="toself", fillcolor=ZONE_COLORS["Anormal"],
        line=dict(width=0), hoverinfo="skip", name="Zona anormal", legendgroup="zonas",
    ))

    for unit in units:
        g_unit = df_plot[df_plot["Unit"] == unit].sort_values("componentHours_filled")
        fig.add_trace(go.Scatter(
            x=g_unit["componentHours_filled"], y=g_unit["ranking_acumulado_ajustado"],
            mode="lines", name=unit, legendgroup=unit,
            line=dict(color=color_map[unit], width=2.2), opacity=0.85,
            hovertemplate=(
                f"<b>{unit}</b><br>Horas: %{{x:,.0f}}<br>"
                "Ranking acum.: %{y:,.0f}<extra></extra>"
            ),
        ))

    fig.add_trace(go.Scatter(
        x=grid_v, y=media_v, mode="lines",
        line=dict(color="#111827", width=2.4, dash="dash"), name="Media de flota",
    ))
    fig.add_trace(go.Scatter(
        x=grid_v, y=hi_v, mode="lines",
        line=dict(color="rgba(200,60,40,0.7)", width=1.4, dash="dot"), name="Umbral",
    ))

    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="DM Sans, Inter, sans-serif", size=11, color="#6C7280"),
        height=460, margin=dict(l=64, r=56, t=16, b=52), hovermode="closest",
        legend=dict(
            title=dict(text="Máquina", font=dict(size=11)), orientation="v",
            yanchor="top", y=1, xanchor="left", x=1.01, font=dict(size=10),
            bgcolor="rgba(0,0,0,0)",
        ),
        xaxis=dict(
            title=dict(text="Horas de componente", font=dict(size=11)),
            showgrid=True, gridcolor="rgba(0,0,0,0.05)", zeroline=False,
            tickfont=dict(size=10), rangemode="tozero",
            range=[0, float(df_plot["componentHours_filled"].max()) * LABEL_X_PAD],
        ),
        yaxis=dict(
            title=dict(text="Ranking acumulado", font=dict(size=11)),
            showgrid=True, gridcolor="rgba(0,0,0,0.05)", zeroline=False,
            tickfont=dict(size=10), rangemode="tozero",
        ),
    )

    resumen = (
        df_plot.dropna(subset=["zona_final"])
        .drop_duplicates(subset=["Unit"])
        .loc[:, ["Unit", "zona_final"]]
    )
    return fig, resumen


def render_accumulated_section_from_curve(df_curve, component="motor"):
    """
    Change 6: card for the cumulative-curve section built from the
    precomputed `cumulative_risk_curve` table, when it exists for this
    client/component. Same card shell as render_accumulated_section (title +
    zone chips + graph) so the rest of the page doesn't need to know which
    source produced it. Returns None (not an empty-state div) on any
    failure, so the caller can fall back to the Oil-join pipeline instead of
    showing a dead end.
    """
    try:
        fig, resumen = build_accumulated_figure_from_curve(df_curve, component=component)
    except Exception as exc:  # noqa: BLE001 - nunca romper el overview
        logger.warning(f"No se pudo construir la curva desde cumulative_risk_curve: {exc}")
        return None

    if fig is None:
        return None

    config = df_curve.attrs.get("config", {}) if hasattr(df_curve, "attrs") else {}
    k_sigma = config.get("K_SIGMA")
    banda_txt = f" La banda de referencia es la media de flota + {k_sigma}σ." if k_sigma else ""

    return html.Div([
        html.Div([
            html.H4([
                html.I(className="fas fa-chart-line me-2"),
                "Curva Acumulada de Riesgo",
            ], className="text-primary mb-3 mt-4 pb-2 border-bottom"),
            html.P(
                "Ranking acumulado por ciclo de vida frente a las horas del componente."
                + banda_txt,
                className="text-muted mb-3",
            ),
        ]),
        _zone_summary_row(resumen),
        dcc.Graph(figure=fig, config={"displayModeBar": False, "responsive": True}),
    ], className="card", style={"marginTop": "16px"})