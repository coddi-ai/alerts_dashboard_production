# Resumen del Procesamiento Predictivo

> **Nota**: Este documento es una nota informal de implementación y puede quedar desactualizado.
> La documentación formal y mantenida vive en [project_overview.md](project_overview.md) (qué
> hace el módulo y cómo se arma el modelo) y [data_contracts.md](data_contracts.md) (esquema de
> columnas de los CSV). En particular, la sección 3.2 de este documento (clasificación de estado
> por percentil P80) ya no refleja el código actual — ver
> [project_overview.md](project_overview.md#processing-pipeline-in-the-dashboard) para la lógica
> de umbrales fijos vigente.

## 1. Fuente de Datos

Los datos predictivos se almacenan en la capa **Golden** del pipeline de datos:

```
data/predictive/golden/{client}/{component}.csv
```

### Archivos disponibles (Cliente: CDA)

| Archivo | Componente | Descripción |
|---------|-----------|-------------|
| `motor.csv` | Motor | Datos de riesgo predictivo del motor |
| `transmision.csv` | Transmisión | Datos de riesgo predictivo de la transmisión |

> **Auto-discovery**: El sistema descubre automáticamente los componentes disponibles escaneando archivos `.csv` en la carpeta del cliente.

---

## 2. Estructura de los Datos (Columnas del CSV)

Cada CSV contiene un registro **diario por unidad** con las siguientes categorías de columnas:

### 2.1 Identificadores

| Columna | Tipo | Descripción |
|---------|------|-------------|
| `Unit` | string | Identificador de la unidad (ej: `T_09`) |
| `Fecha` | datetime | Fecha del registro diario |
| `unitId` | string | ID de unidad normalizado |

### 2.2 Tasas de Telemetría (por señal y modo operacional)

Formato: `{ModoOperacional}_{Señal}_{tipo_tasa}`

**Modos operacionales:**
- `ND` (No Definido)
- `Operacional Alto`
- `Operacional Bajo`
- `Ralenti`
- `Ralenti Alto`
- `Ralenti Bajo`

**Tipos de tasa:**
- `alert_rate` — Proporción del tiempo en zona de alerta
- `critic_rate` — Proporción del tiempo en zona crítica
- `normal_rate` — Proporción del tiempo en zona normal

**Señales de telemetría por componente:**

| Componente | Señales |
|-----------|---------|
| **Motor** | `CnkcasePres`, `DeltaExh`, `EngOilPres`, `LtExhTemp`, `RtExhTemp` |
| **Transmisión** | `LckupSlip`, `TCOutTemp`, `TrnLubeTemp`, `TrnSlip`, `gear_mismatch` |

**Ejemplo de columnas (Motor):**
```
Operacional Alto_CnkcasePres_alert_rate
Ralenti_DeltaExh_critic_rate
ND_EngOilPres_normal_rate
```

### 2.3 Variables de Aceite (Tribología)

| Columna | Motor | Transmisión | Unidad |
|---------|:-----:|:-----------:|--------|
| `Hierro` | ✅ | ✅ | ppm |
| `Silicio` | ✅ | ✅ | ppm |
| `Plomo` | ✅ | ✅ | ppm |
| `Cromo` | ✅ | ❌ | ppm |
| `Cobre` | ✅ | ✅ | ppm |
| `Sodio` | ✅ | ✅ | ppm |
| `Hollín` | ✅ | ❌ | % |
| `Viscocidad` | ✅ | ✅ | cSt |
| `Estaño` | ❌ | ✅ | ppm |
| `Aluminio` | ❌ | ✅ | ppm |
| `Agua` | ❌ | ✅ | % |
| `Potasio` | ❌ | ✅ | ppm |
| `Boro` | ❌ | ✅ | ppm |

### 2.4 Derivados de Aceite

| Columna | Descripción |
|---------|-------------|
| `sampleDate` | Fecha de toma de muestra |
| `oilMeter` | Horas del aceite |
| `oilHourRange` | Rango de horas (`LT_1000` o `GE_1000`) — usado para seleccionar umbrales |
| `{variable}_slope` | Pendiente (velocidad de cambio) de cada variable de aceite |
| `{variable}_ratio` | Ratio respecto a umbrales de cada variable |

### 2.5 Scores de Modos de Falla

Cada fila contiene un score de 0-100 por modo de falla:

**Motor (7 modos):**

| Columna | Etiqueta | Variables Aceite | Variables Telemetría |
|---------|----------|------------------|---------------------|
| `abrasive_wear_risk` | Desgaste Abrasivo | Hierro, Silicio, Cromo | — |
| `combustion_risk` | Combustión | Hollín, Viscosidad | LtExhTemp, RtExhTemp, DeltaExh |
| `thermal_imbalance_risk` | Δ T° Escape | — | LtExhTemp, RtExhTemp, DeltaExh |
| `oil_degradation_risk` | Degradación de Aceite | Viscosidad, Hollín | — |
| `lubrication_failure_risk` | Falla de Lubricación | Plomo, Cobre | EngOilPres |
| `bearing_wear_risk` | Desgaste de Cojinetes | Plomo, Cobre | EngOilPres |
| `blowby_risk` | Blow-by | Hollín | CnkcasePres |

**Transmisión (7 modos):**

| Columna | Etiqueta | Variables Aceite | Variables Telemetría |
|---------|----------|------------------|---------------------|
| `clutch_pack_risk` | Desgaste de Clutch Pack | Hierro, Cobre, Aluminio | LckupSlip, TrnSlip |
| `thermal_degradation_risk` | Degradación Térmica | Viscosidad, Agua | TCOutTemp, TrnLubeTemp |
| `planetary_gear_risk` | Desgaste Engranajes Planetarios | Hierro, Silicio, Cobre | gear_mismatch, TrnSlip |
| `bearing_risk` | Desgaste de Rodamientos | Hierro, Cobre, Plomo, Estaño | TrnLubeTemp |
| `contamination_risk` | Contaminación | Silicio, Agua, Sodio, Potasio | — |
| `torque_converter_risk` | Convertidor de Torque | Aluminio, Cobre, Hierro | LckupSlip, TCOutTemp |
| `shift_quality_risk` | Calidad de Cambio | Viscosidad, Hierro | TrnSlip, gear_mismatch, LckupSlip |

### 2.6 Ranking General

| Columna | Descripción |
|---------|-------------|
| `ranking` | Score consolidado de riesgo de la unidad (0-100). Combina todos los modos de falla. |

---

## 3. Pipeline de Procesamiento en el Dashboard

### 3.1 Carga de Datos (`_load_component_data`)

```
CSV → DataFrame → Parsing de Fecha → Rolling Averages → Snapshot más reciente
```

**Pasos:**
1. Lee el CSV con `pd.read_csv(filepath)`
2. Convierte `Fecha` a datetime
3. Calcula promedios móviles por unidad:
   - `ranking_30d` — Rolling 30 días
   - `ranking_60d` — Rolling 60 días
   - `ranking_90d` — Rolling 90 días
   - Se calculan también por cada score de modo de falla
4. Genera `df_latest`: último registro por unidad (snapshot actual)
5. Calcula `prev_ranking`: ranking de la fecha anterior (para deltas)

### 3.2 Clasificación de Estado

El estado de cada unidad se determina con la siguiente lógica:

```python
p80_30d = df_latest["avg_ranking_30d"].quantile(0.80)

Estado = "Saludable"     # Por defecto
Estado = "Alerta"        # Si avg_ranking_30d >= P80
Estado = "Crítica"       # Si ranking > 80 AND avg_ranking_30d >= P80
```

| Estado | Condición | Color |
|--------|-----------|-------|
| 🟢 Saludable | Bajo el umbral P80 | `#1d9e75` |
| 🟡 Alerta | `avg_ranking_30d >= P80` | `#ef9f27` |
| 🔴 Crítica | `ranking > 80` AND `avg_ranking_30d >= P80` | `#e24b4a` |

### 3.3 Umbrales de Aceite

Los umbrales dependen del rango de horas del aceite (`oilHourRange`):

| Variable | Normal (LT_1000) | Alerta (LT_1000) | Crítico (LT_1000) | Normal (GE_1000) | Alerta (GE_1000) | Crítico (GE_1000) |
|----------|:-:|:-:|:-:|:-:|:-:|:-:|
| Hierro | 48 | 57 | 65 | 71 | 84 | 93 |
| Cobre | 5 | 8 | 17 | 7 | 12 | 51 |
| Plomo | 3 | 5 | 8 | 4 | 5 | 6 |
| Silicio | 5 | 6 | 8 | 5 | 6 | 7 |
| Sodio | 7 | 9 | 18 | 8 | 9 | 10 |
| Viscosidad | 16 | 17 | 18 | 16 | 17 | 18 |
| Hollín | 64 | 73 | 84 | 91 | 106 | 120 |
| Cromo | 0 | 0.5 | 1.0 | 0 | 0.5 | 1.0 |

---

## 4. Visualizaciones y Páginas

### 4.1 Arquitectura de Páginas

```
Predictivo → {Componente} → [Resumen | Evidencia]
```

- **`tab_predictive_component.py`** — Página unificada por componente con tabs internos
- **`tab_predictive_overview.py`** — Vista de resumen/flota
- **`tab_predictive_evidence.py`** — Evidencia detallada por unidad

### 4.2 Tab: Resumen (Overview)

Contenido renderizado:

| Elemento | Descripción |
|----------|-------------|
| **KPIs Hero** | Ranking promedio flota, unidades críticas/alerta/saludables |
| **Priority Cards** | Tarjetas por unidad ordenadas por avg_ranking_30d, con top 3 drivers |
| **Tabla de Modos de Falla** | Ranking hoy, 30d, 60d, 90d + score por cada modo de falla, ordenable |

**KPIs calculados:**
- `Ranking Flota`: Promedio de ranking actual de todas las unidades
- `Unidades Críticas`: Count de unidades con estado "Crítica"
- `Unidades en Alerta`: Count de unidades con estado "Alerta"
- `Unidades Saludables`: Count de unidades con estado "Saludable"

### 4.3 Tab: Evidencia (Evidence)

Contenido renderizado por unidad seleccionada:

| Elemento | Descripción |
|----------|-------------|
| **Banner de Unidad** | Nombre, componente, ranking actual, estado con color |
| **KPIs de Condición** | Ranking actual, riesgo acum. 90d, modo dominante, última fecha |
| **Fleet Scatter** | Gráfico de dispersión: ranking actual vs ranking acumulado 90d |
| **Barras Comparativas** | Score por modo de falla: unidad vs promedio de flota |
| **Panel de Insight AI** | Análisis inteligente con metodología, resultado y observaciones |
| **Evidencia Tribológica** | Serie temporal de aceite 90d + tabla de variables |
| **Evidencia de Telemetría** | Gráficos de barras apiladas de alert/critic rate por señal |

---

## 5. Análisis Inteligente (AI Insight Engine)

El módulo genera observaciones automáticas basadas en datos:

### 5.1 Observaciones de Aceite

| Tipo | Condición |
|------|-----------|
| 🔴 Crítica | Valor actual > umbral crítico |
| 🟡 Alerta | Valor actual > umbral de alerta |
| 🟢 Normal | Valor actual ≤ umbral normal |
| ⬆️ Tendencia | Cambio > 25% en últimas 5 muestras |
| 👥 Flota | Valor > 40% por encima del promedio de flota |

### 5.2 Observaciones de Telemetría

| Tipo | Condición |
|------|-----------|
| 🔴 Tasa crítica alta | `avg_critic_rate > 15%` en últimos 90 días |
| 🟡 Tasa crítica moderada | `avg_critic_rate > 5%` en últimos 90 días |
| ⚡ Spike reciente | Tasa últimos 7 días > 2x promedio previo |
| 🔔 Tasa alerta alta | `avg_alert_rate > 20%` en últimos 90 días |
| ✅ Sin alertas | Tasa total < 2% |

### 5.3 Metodología por Modo de Falla

Cada modo de falla tiene una descripción de **qué se analiza y por qué**:

**Motor:**
- **Desgaste Abrasivo**: Fe, Cr (desgaste interno) + Si (contaminantes externos)
- **Combustión**: Hollín + Viscosidad + Temperaturas de escape
- **Δ T° Escape**: Diferencial entre temperaturas izq/der → inyectores, válvulas, turbo
- **Degradación de Aceite**: Viscosidad + Hollín fuera de rango
- **Falla de Lubricación**: Pb + Cu + Presión de Aceite baja
- **Desgaste de Cojinetes**: Pb + Cu sostenidos + Presión de Aceite
- **Blow-by**: Presión Cárter + Hollín → fuga de gases al cárter

**Transmisión:**
- **Clutch Pack**: Fe + Cu + Al + Deslizamientos lock-up/transmisión
- **Degradación Térmica**: Viscosidad + Agua + Temperaturas del convertidor/aceite
- **Engranajes Planetarios**: Fe + Si + Cu + desajustes de marcha
- **Rodamientos**: Fe + Cu + Pb + Sn + Temperatura aceite
- **Contaminación**: Si + Agua + Na + K (no generados por desgaste)
- **Convertidor de Torque**: Al + Cu + Fe + deslizamiento lock-up
- **Calidad de Cambio**: Viscosidad + Fe + deslizamientos + desajustes

---

## 6. Gráficos Disponibles

### 6.1 Fleet Scatter (`create_fleet_scatter`)
- **Ejes**: Ranking actual (X) vs Ranking acumulado 90d (Y)
- **Cuadrantes**: Crítica sostenida | Empeoró de golpe | Mejoró recientemente | Zona saludable
- **Destaca**: La unidad seleccionada en azul

### 6.2 Barras Comparativas (`create_comparative_bars`)
- **Barras horizontales**: Score por modo de falla
- **Comparación**: Unidad seleccionada vs Promedio de flota
- **Ordenado**: De mayor a menor score

### 6.3 Serie Temporal de Aceite (`create_oil_timeseries_90d`)
- **Ventana**: Máximo(90 días, últimas 3 muestras reales)
- **Líneas de límite**: Normal/Alerta/Crítico (cuando hay 1 sola variable)
- **Datos**: Valores reales de muestra deduplicados por `sampleDate`

### 6.4 Gráfico de Telemetría (`create_telemetry_signal_chart`)
- **Barras apiladas**: `alert_rate` (amarillo) + `critic_rate` (rojo) por fecha
- **Normalización**: Promedio de tasas entre modos operacionales
- **Individual**: Un gráfico por señal de telemetría

---

## 7. Tabla de Variables de Aceite (`create_oil_variables_table`)

Muestra por cada variable asociada al modo de falla:

| Campo | Descripción |
|-------|-------------|
| Variable | Nombre de la variable |
| Valor actual | Último valor de muestra |
| Valor anterior | Último valor **diferente** al actual (evita replicados) |
| Variación | Diferencia entre actual y anterior |
| Velocidad | Variación / días entre muestras |
| Estado | Normal / Alerta / Crítico (basado en umbrales) |

---

## 8. Flujo de Callbacks

```
┌─────────────────────────────────────────────────────────────┐
│                    predictive_callbacks.py                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  switch_internal_tab ←── Tab Resumen/Evidencia              │
│       │                                                      │
│       ├── Resumen → _render_component_overview()             │
│       └── Evidencia → Render shell interactivo               │
│                                                              │
│  sort_failure_mode_table ←── Dropdown de ordenamiento        │
│       └── Re-renderiza tabla con nuevo orden                 │
│                                                              │
│  update_unit_banner ←── Dropdown de unidad                   │
│       └── Banner con ranking y estado de la unidad           │
│                                                              │
│  update_initial_content ←── Dropdown de unidad               │
│       └── KPIs + Fleet scatter + Barras comparativas         │
│                                                              │
│  set_default_failure_mode ←── Dropdown de unidad             │
│       └── Selecciona el modo de falla con mayor score        │
│                                                              │
│  update_detailed_evidence ←── Unidad + Modo de falla         │
│       └── AI Insight + Aceite (gráfico+tabla) + Telemetría   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 9. Archivos Relevantes

| Archivo | Responsabilidad |
|---------|----------------|
| `dashboard/components/predictive_config.py` | Configuración de modos de falla, variables, umbrales, metodología |
| `dashboard/components/predictive_charts.py` | Gráficos Plotly (scatter, barras, series temporales, telemetría) |
| `dashboard/components/predictive_tables.py` | Tablas HTML de variables de aceite |
| `dashboard/components/predictive_kpis.py` | Componentes de tarjetas KPI |
| `dashboard/tabs/tab_predictive_component.py` | Layout unificado por componente con tabs internos |
| `dashboard/tabs/tab_predictive_overview.py` | Tab de resumen: carga, clasificación, rendering de flota |
| `dashboard/tabs/tab_predictive_evidence.py` | Tab de evidencia: insights AI, aceite, telemetría |
| `dashboard/callbacks/predictive_callbacks.py` | Callbacks Dash para interactividad |
| `data/predictive/golden/cda/motor.csv` | Datos golden de motor |
| `data/predictive/golden/cda/transmision.csv` | Datos golden de transmisión |

---

## 10. Resumen del Flujo Completo

```
┌──────────────────┐     ┌──────────────────┐     ┌──────────────────────┐
│   Datos Crudos   │     │   Procesamiento  │     │   Dashboard Golden   │
│                  │     │   (Upstream)     │     │                      │
│ • Telemetría     │────▶│ • Clasificación  │────▶│ • motor.csv          │
│   (VIMS/PLM)    │     │   operacional    │     │ • transmision.csv    │
│ • Muestras de   │     │ • Cálculo de     │     │                      │
│   aceite (CDA/  │     │   alert/critic   │     │ Contiene:            │
│   ALS labs)     │     │   rates          │     │ • Tasas telemetría   │
│                  │     │ • Scores de      │     │ • Variables aceite   │
│                  │     │   riesgo por     │     │ • Scores de falla    │
│                  │     │   modo de falla  │     │ • Ranking general    │
│                  │     │ • Slopes/ratios  │     │                      │
└──────────────────┘     └──────────────────┘     └──────────────────────┘
                                                           │
                                                           ▼
                                                  ┌──────────────────────┐
                                                  │   Dashboard App      │
                                                  │                      │
                                                  │ • Rolling averages   │
                                                  │ • Status classify    │
                                                  │ • AI observations    │
                                                  │ • Visualizaciones    │
                                                  └──────────────────────┘
```

---

## 11. Señales de Telemetría — Detalle

| Señal | Etiqueta | Componente | Descripción |
|-------|----------|-----------|-------------|
| `CnkcasePres` | Presión Cárter | Motor | Presión en el cárter del motor |
| `DeltaExh` | Delta Escape | Motor | Diferencia entre temperaturas de escape L/R |
| `EngOilPres` | Presión Aceite Motor | Motor | Presión del sistema de lubricación |
| `LtExhTemp` | Temp. Escape Izq. | Motor | Temperatura de gases de escape izquierdo |
| `RtExhTemp` | Temp. Escape Der. | Motor | Temperatura de gases de escape derecho |
| `LckupSlip` | Deslizamiento Lock-up | Transmisión | Deslizamiento del embrague lock-up |
| `TCOutTemp` | Temp. Salida Convertidor | Transmisión | Temperatura de salida del convertidor de torque |
| `TrnLubeTemp` | Temp. Aceite Transmisión | Transmisión | Temperatura del aceite de la transmisión |
| `TrnSlip` | Deslizamiento Transmisión | Transmisión | Deslizamiento general de la transmisión |
| `gear_mismatch` | Desajuste de Marcha | Transmisión | Tasa de desajuste entre marcha comandada y actual |

---

*Documento generado el 2025-06-24 — Dashboard TDS Alerts v2.0*
