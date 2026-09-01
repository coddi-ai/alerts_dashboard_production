# Cómo leer los datos del ERS desde el dashboard

Guía rápida de dónde están los datos, cómo se leen y por qué están organizados así.

---

## 1. Qué hay disponible

Cuatro tablas, todas en parquet sobre S3.

| Tabla | Qué contiene | Grano |
|---|---|---|
| `telemetry / signal_daily_status` | % del tiempo diario que cada señal del motor pasó en alerta y en crítico | unidad × día × señal |
| `predictive / risk_scores` | puntaje de riesgo de cada modo de falla, más el ranking sintético | unidad × día × modo |
| `predictive / unit_status_summary` | foto del estado de cada unidad al cierre de la corrida | unidad |
| `predictive / cumulative_risk_curve` | curva de riesgo acumulado por ciclo de vida, con su banda de flota | unidad × día |

Las cuatro se regeneran una vez por semana.

`failure_mode_diagnosis` — el detalle textual por modo alterado — todavía se está definiendo y no está disponible.

---

## 2. Dónde están

```
s3://{bucket}/MultiTechnique Alerts/{tecnica}/golden/{cliente}/{componente}/{tabla}/year=2026/week=33/part-0.parquet
```

Hoy `cliente = capstone` y `componente = motor`. Un ejemplo real:

```
.../MultiTechnique Alerts/predictive/golden/capstone/motor/risk_scores/year=2026/week=33/part-0.parquet
```

Las carpetas `year=` y `week=` son **particiones**: no hace falta abrirlas a mano, las funciones de abajo las usan para leer solo lo necesario.

La semana es ISO (lunes a domingo) y `year` es el año ISO, no el calendario. Por eso el 29 de diciembre de 2025 aparece en `year=2026/week=1`.

---

## 3. Cómo leerlas

Copiar este bloque tal cual:

```python
import os
import re
import pandas as pd
import pyarrow as pa
import pyarrow.dataset as pads
import s3fs

BUCKET = os.getenv("ERS_S3_BUCKET")
RAIZ = "MultiTechnique Alerts"
CLIENTE, COMPONENTE = "capstone", "motor"

fs = s3fs.S3FileSystem()
PARTICION = pads.partitioning(pa.schema([("year", pa.int32()), ("week", pa.int32())]),
                              flavor="hive")


def ruta_tabla(tecnica, nombre, cliente=CLIENTE, componente=COMPONENTE):
    return f"{BUCKET}/{RAIZ}/{tecnica}/golden/{cliente}/{componente}/{nombre}"


def semanas_disponibles(ruta, filesystem=fs):
    """Lista los pares (year, week) que existen. Solo lista rutas, no abre archivos."""
    dset = pads.dataset(ruta, format="parquet", partitioning=PARTICION, filesystem=filesystem)
    return sorted({(int(y.group(1)), int(w.group(1)))
                   for r in dset.files
                   if (y := re.search(r"year=(\d+)", r)) and (w := re.search(r"week=(\d+)", r))})


def leer_ultimas_semanas(ruta, n=13, filesystem=fs):
    """Lee las últimas n semanas con datos. n=13 ≈ 3 meses."""
    pares = semanas_disponibles(ruta, filesystem)[-n:]
    return pd.read_parquet(ruta,
                           filters=[[("year", "==", y), ("week", "==", w)] for y, w in pares],
                           filesystem=filesystem)


def leer_ultima_semana(ruta, filesystem=fs):
    return leer_ultimas_semanas(ruta, n=1, filesystem=filesystem)
```

### Uso

```python
# Tarjetas de estado de la flota — una sola partición, 30 filas
resumen = leer_ultima_semana(ruta_tabla("predictive", "unit_status_summary"))

# Curva de riesgo por unidad — 3 meses
riesgos = leer_ultimas_semanas(ruta_tabla("predictive", "risk_scores"), n=13)

# Evidencia de señales — 3 meses
señales = leer_ultimas_semanas(ruta_tabla("telemetry", "signal_daily_status"), n=13)

# Curva acumulada — ver la sección 5, necesita su propio lector
```

`leer_ultimas_semanas` devuelve un DataFrame ya concatenado. Trae además las columnas `year` y `week`, que salen de la ruta.

---

## 4. Las tablas por dentro

### `unit_status_summary`

Una fila por unidad. Es lo que alimenta las tarjetas de crítico / alerta / saludable.

| Columna | Qué es |
|---|---|
| `Unit` | identificador de la unidad |
| `Fecha` | fecha del último dato **de esa unidad** |
| `estado` | `anormal` / `alerta` / `normal` |
| `estado_previo`, `cambio_estado` | estado hace 7 días y si cambió (`sí` / `no`) |
| `ranking` | riesgo sintético del día |
| `delta_ranking` | cuánto cambió el ranking en 7 días |
| `media_30d` | promedio móvil de 30 días del ranking |
| `dias_media_30d` | sobre cuántos días reales se calculó esa media |
| `peor_modo`, `peor_valor` | el modo con el puntaje más alto y su valor |
| `modes_over_threshold_count` | cuántos modos superan 35 |
| `modos_ordenados` | JSON con los 9 modos y su puntaje, de mayor a menor |
| `dias_sin_datos` | qué tan vieja es la foto de esa unidad |

**Ojo con `Fecha`**: cada unidad trae la suya. Todas las unidades están siempre en la partición de la corrida, pero una que dejó de reportar tendrá una fecha más vieja y `dias_sin_datos > 0`.

**`modos_ordenados` es texto**, hay que parsearlo:

```python
import json
modos = json.loads(fila["modos_ordenados"])
# {'lubrication_failure_risk': 85.3, 'blowby_risk': 70.0, ...}
```

Viene ordenado de mayor a menor y `json.loads` respeta ese orden, así que sirve directo para una lista o un gráfico de barras.

**La regla de estado**:

- `anormal` — `media_30d ≥ 60` **o** algún modo `≥ 80`
- `alerta` — `media_30d ≥ 30` **o** algún modo `≥ 50`
- `normal` — el resto

Se evalúa en ese orden: anormal gana sobre alerta.

### `risk_scores`

| Columna | Qué es |
|---|---|
| `Unit`, `Fecha` | unidad y día |
| `failure_mode` | uno de los 9 modos, **o** el valor `ranking` |
| `risk_value` | puntaje 0–100 |

Formato largo: 10 filas por unidad y día. `ranking` viene como una fila más, no como columna aparte.

Para separarlos:

```python
modos = riesgos[riesgos["failure_mode"] != "ranking"]
curva = riesgos[riesgos["failure_mode"] == "ranking"]
```

Los nombres de modo terminan todos en `_risk`, así que `str.endswith("_risk")` también funciona como filtro.

Si un modo no tiene fila para una unidad y día, es que **no había datos** — distinto de un 0.0, que significa sin riesgo.

### `telemetry / signal_daily_status`

| Columna | Qué es |
|---|---|
| `Unit`, `Fecha` | unidad y día |
| `signal_name` | nombre de la señal (`oil_diff_pressure_psi`, `egt_avg_c`, …) |
| `pct_time_alert` | % del día en banda de alerta (0–100) |
| `pct_time_critical` | % del día en banda crítica (0–100) |

Mismo criterio: sin fila = sin datos ese día para esa señal.

---

## 5. La curva acumulada

Es la única tabla que **no** se lee con las funciones de arriba, por dos motivos: cada partición contiene el historial completo (no solo esa semana), y trae metadata que `pd.read_parquet` descarta.

Se lee con su propia función:

```python
import json

def leer_curva(ruta, filesystem=fs, semana=None):
    """Lee una partición de la curva y restituye attrs para plot_curva_acumulada."""
    dset = pads.dataset(ruta, format="parquet", partitioning=PARTICION, filesystem=filesystem)
    pares = sorted({(int(y.group(1)), int(w.group(1))) for r in dset.files
                    if (y := re.search(r"year=(\d+)", r)) and (w := re.search(r"week=(\d+)", r))})
    y, w = semana or pares[-1]

    tabla = dset.to_table(filter=(pads.field("year") == y) & (pads.field("week") == w))
    df = tabla.to_pandas()
    for k, v in (tabla.schema.metadata or {}).items():
        if (nombre := k.decode()) in ("config", "banda"):
            df.attrs[nombre] = json.loads(v.decode())
    df["Fecha"] = pd.to_datetime(df["Fecha"])
    return df
```

### Graficarla

El módulo de figura viene aparte (archivo adjunto). Se usa tal cual:

```python
from curva_figura import plot_curva_acumulada

df_curva = leer_curva(ruta_tabla("predictive", "cumulative_risk_curve"))
fig = plot_curva_acumulada(df_curva)
fig.show()
```

Opciones útiles: `units=["CA-44"]` para filtrar máquinas, `solo_vigentes=False` para incluir ciclos históricos, `height=` para el alto.

**Hay que usar `leer_curva`, no `pd.read_parquet`.** La función de graficado lee `df.attrs["config"]` (los parámetros `K_SIGMA` y `K_ALERTA` con los que se generó la curva) y `df.attrs["banda"]` (la banda de flota desde hora cero, que permite dibujar el tramo punteado inicial). Esa información viaja en la metadata del parquet y `pd.read_parquet` la descarta. Si se pierde, el gráfico **no falla**: cae a valores por defecto y pinta las zonas de color en fronteras distintas a las que usó la clasificación. El error es silencioso.

### Columnas

| Columna | Qué es |
|---|---|
| `Unit`, `Fecha` | unidad y día |
| `ciclo` | número de vida del componente; sube en cada cambio |
| `curva` | clave de una vida completa, `"CA-44 - ciclo 2"` |
| `componentHours_filled` | horas del componente ese día (eje X del gráfico) |
| `ranking` | riesgo del día, sin acumular |
| `ranking_acumulado` | suma acumulada dentro del ciclo; arranca en ~0 |
| `offset_curva` | desplazamiento vertical para que arranque en la media de flota |
| `ranking_acumulado_ajustado` | **la columna que se grafica y sobre la que se clasifica** |
| `banda_media`, `banda_umbral` | media de flota y umbral en las horas de ese punto |
| `estado` | zona del punto: `Normal` / `Alerta` / `Anormal`, o nulo si cae fuera del dominio de la banda |
| `es_vigente` | `True` si es el ciclo actual de la unidad |
| `zona_final` | estado del último punto de la curva vigente, repetido en todas sus filas; nulo en las históricas |
| `componente` | `motor` o `transmision` |

**Los dos nulos significan cosas distintas**: `estado` nulo es "fuera del dominio de la banda", `zona_final` nulo es "curva histórica, no vigente".

**El eje X son horas, no fechas.** La curva se grafica contra `componentHours_filled` porque el desgaste depende de las horas del componente, no del calendario.

---

## 6. Qué señales mostrar por modo de falla

Esto **no** está en un parquet: vive en `FAILURE_MODE_CONFIG`, un diccionario de Python que se importa en el dashboard.

```python
FAILURE_MODE_CONFIG["capstone"]["components"]["motor"]["blowby_risk"]
# {'label': 'Blow-by / Desgaste de Anillos',
#  'signals': ['Cromo', 'Hierro', 'Hollín', 'crankcase_pressure_inh2o', 'oil_level_pct']}
```

Y el catálogo dice de dónde sale cada señal y cómo mostrarla:

```python
FAILURE_MODE_CONFIG["capstone"]["signals"]["crankcase_pressure_inh2o"]
# {'technique': 'telemetry', 'label': 'Presión Cárter', 'unit': 'inH2O'}
```

Con eso se arma el desplegable: al seleccionar un modo, se filtran sus señales, y `technique` indica de qué tabla leer cada una.

```python
cfg = FAILURE_MODE_CONFIG["capstone"]
modo = cfg["components"]["motor"]["blowby_risk"]

for nombre in modo["signals"]:
    s = cfg["signals"][nombre]
    ruta = ruta_tabla(s["technique"], "signal_daily_status")
    serie = leer_ultimas_semanas(ruta, n=13).query("signal_name == @nombre")
    # graficar con s["label"] en la leyenda y s["unit"] en el eje
```

---

## 7. Por qué está organizado así

**Formato largo en vez de una columna por señal.** Antes había ~250 columnas con el nombre codificado (`OPERACIONAL_CON_CARGA_oil_diff_pressure_psi_alert_rate`). Ahora agregar una señal o un modo de falla es una fila más, no un cambio de esquema — el dashboard no se rompe cuando eso pasa.

**Particiones `year=` / `week=` en formato Hive.** Es lo que permite que `pyarrow` lea solo las semanas pedidas. En una prueba con 38 semanas cargadas, pedir las últimas 13 abrió 13 archivos y salteó los otros 25. Sin esto habría que leer todo y filtrar después.

**Año y semana como enteros separados, no como un texto `Week33Year2026`.** Con dos enteros funcionan los rangos (`week >= 30`) y no se rompe al cruzar de año. Con un texto solo se puede preguntar por igualdad exacta.

**"Últimas N semanas disponibles", no "últimos 90 días de calendario".** `semanas_disponibles` lista las particiones que existen de verdad y toma las últimas. Si la corrida se atrasó, el dashboard igual muestra el último dato disponible en vez de quedar vacío.

**La curva guarda el historial completo en cada partición.** Pesa menos de 1 MB, así que en vez de acumular incrementos se recalcula entera cada semana. Eso mantiene la banda de flota consistente en todos los puntos y deja reproducible exactamente qué curva se mostró cada semana.

**`unit_status_summary` toda en una partición.** Las series temporales parten por la fecha del dato; el resumen parte por la semana de la corrida. Así una sola lectura trae siempre la flota completa, incluidas las unidades que dejaron de reportar.

**Ausencia de fila = sin datos.** El formato largo distingue naturalmente "no hay medición" de "medición en cero", cosa que con columnas y NaN se prestaba a confusión.

---

## 8. Recomendaciones prácticas

**Cachear `semanas_disponibles`.** Hace un listado sobre S3 cada vez que se llama. Es rápido, pero si se llama en cada interacción del usuario conviene guardarlo y refrescarlo una vez por corrida.

**13 semanas son 91 días, no 3 meses exactos.** Si falta una semana por una caída de ingesta, las 13 últimas *con datos* pueden abarcar más tiempo de calendario. Si eso importa, filtrar por `Fecha` después de leer.

**Los dos `estado` no son lo mismo.** El de `unit_status_summary` compara el ranking contra umbrales fijos (30/50/60/80) y usa minúsculas: `anormal` / `alerta` / `normal`. El de `cumulative_risk_curve` compara el acumulado contra la banda de flota y usa mayúscula inicial: `Normal` / `Alerta` / `Anormal`. Son criterios distintos y **pueden no coincidir** para la misma unidad. Conviene etiquetarlos distinto en la interfaz.

**`Fecha` vuelve como objeto `date`**, no como texto ni como `datetime64`. Si se necesita operar con fechas, convertir con `pd.to_datetime`.
