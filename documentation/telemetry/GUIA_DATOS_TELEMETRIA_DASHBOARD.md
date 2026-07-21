# Analisis y Roadmap de Reportabilidad en Telemetria

## Implementacion de reportabilidad v1

La experiencia activa de Telemetria mantiene dos pestanas y esta optimizada para
la revision semanal de mantenimiento:

- **Vista de Flota**: filtros por modelo, estado y sistema; KPIs sincronizados;
  heatmap de riesgo; tabla de prioridades y acciones; resumen IA de la unidad
  seleccionada.
- **Detalle de Unidad**: encabezado sticky con unidad, sistema y señal; bloque
  "Por que esta en alerta"; tabla de sistemas con estado y hallazgos; evaluación
  IA del sistema seleccionado; tabla de señales con evidencia de desviación,
  eventos y tendencia; una tarjeta de evidencia por señal seleccionada.

La navegación desde una celda del heatmap o una fila de prioridades conserva la
unidad y el sistema seleccionados. La vista muestra la semana, fecha de
ejecucion y baseline del manifiesto `latest.json` para que el lector pueda
evaluar la vigencia de la evidencia.

Esta versión no modifica los resultados golden/silver ni crea nuevos scores,
reglas, análisis, exportables o integraciones. Las agregaciones de la interfaz
solo ordenan y unen resultados ya calculados por el pipeline. El estado
`InsufficientData` se muestra separado de `Normal` y los comentarios IA nuevos
y legacy son compatibles. Los puntajes internos (`risk_score`, `priority_score`
y `confidence`) se conservan para ordenar y seleccionar evidencia, pero no se
exponen como números en la interfaz cliente.

## Resumen ejecutivo

La vista de telemetria actual ya tiene una base solida para monitoreo de salud:
usa resultados agregados por unidad y sistema, analisis por senal, episodios,
tendencias, limites percentilares, comentarios IA y series recientes de la capa
silver. Hoy responde bien a dos preguntas: como esta la flota ahora y que
evidencia respalda el diagnostico de una unidad.

La principal oportunidad no es agregar mas graficos aislados, sino convertir la
telemetria en reportabilidad accionable para mantenimiento: ranking de deterioro,
explicacion de cambios, senales contributivas, persistencia de eventos,
confiabilidad del dato y exportables para reunion operacional.

Este roadmap separa dos tipos de mejoras:

- **Quick wins con datos actuales**: se pueden construir con parquet/csv/configs
  que ya existen en el repo.
- **Mejoras con pipeline nuevo**: requieren generar nuevas tablas o enriquecer
  la capa golden antes de mostrarlas en el dashboard.

## Estado actual de las vistas

### Vista de Flota

La pestana `Vista de Flota` muestra:

- KPIs de unidades totales, normales, en alerta y anormales.
- Heatmap de estado por unidad y sistema.
- Indicadores sobre unidad más prioritaria, sistema más crítico y su estado.
- Evaluaciones IA por unidad con descripcion, explicacion, urgencia y accion
  recomendada cuando estan disponibles.

Fuentes principales:

- `data/telemetry/golden/{client}/unit_health`
- `data/telemetry/golden/{client}/system_health`
- `data/telemetry/golden/{client}/ai_comments`
- `data/telemetry/golden/{client}/latest.json`

### Detalle de Unidad

La pestana `Detalle de Unidad` muestra:

- Selector de unidad, ordenado por prioridad.
- Comentario IA ejecutivo de la unidad.
- Tabla de sistemas ordenados por la prioridad interna existente.
- Evaluación IA del sistema seleccionado, antes de sus señales.
- Selector de sistema.
- Tabla de senales del sistema seleccionado.
- Tarjetas por senal con serie temporal, limites percentilares y tendencia. Las
  bandas de **Anomalía** y **Evento** usan los intervalos ya materializados en
  `events`; la ventana inicial comienza en el inicio del episodio de mayor
  duración y termina en la última fecha silver observada.

Fuentes principales:

- `data/telemetry/golden/{client}/technique_results/deviation`
- `data/telemetry/golden/{client}/technique_results/events`
- `data/telemetry/golden/{client}/technique_results/trend`
- `data/telemetry/silver/{client}/Telemetry_Wide_With_States`
- `data/telemetry/silver/{client}/baselines`
- `data/telemetry/silver/{client}/limits`
- `data/telemetry/config/{client}/signal_registry.yaml`

### Datos relacionados que hoy estan desacoplados

Hay dos capacidades relacionadas que pueden aportar contexto, pero no estan
integradas de forma fuerte en la vista de telemetria:

- **Health Index**: contiene evolucion temporal de salud por unidad, sistema y
  componente. Puede servir como vista historica o validacion cruzada del riesgo
  telemetrico.
- **Alertas con evidencia de telemetria**: contienen detalle de alertas y
  senales alrededor del evento. Pueden servir para conectar diagnostico,
  evidencia y accion.

## Brechas detectadas

### Reportabilidad ejecutiva

- Falta una vista que responda rapidamente: que unidades empeoraron, que sistemas
  concentran riesgo y que accion tomar primero.
- El heatmap muestra estado actual, pero no muestra variacion respecto de la
  semana anterior.
- Las evaluaciones IA existen, pero no quedan consolidadas en una tabla
  descargable para gestion semanal.
- No hay una salida lista para reunion de mantenimiento con unidad, sistema,
  senal, evidencia, urgencia y accion.

### Trazabilidad del diagnostico

- El usuario puede ver senales individuales, pero no hay una explicacion compacta
  tipo "por que esta unidad esta en alerta".
- Falta separar los drivers del riesgo: desviacion, evento persistente, tendencia
  significativa, criticidad del sistema o baja confiabilidad del dato.
- Las senales contributivas aparecen en detalle, pero no se agregan como ranking
  por unidad o por sistema.

### Analitica temporal

- La vista esta orientada al ultimo snapshot disponible.
- El repo ya filtra ultima semana en varios loaders, pero la reportabilidad
  necesita comparar estado actual contra semanas previas.
- No hay tendencia de estado por unidad/sistema dentro de la vista de telemetria,
  aunque existen datos de tendencia por senal y Health Index historico.

### Calidad y confiabilidad del dato

- La vista informa la semana de referencia, pero no muestra cobertura por unidad,
  gaps de semanas o senales con datos insuficientes.
- `latest.json` expone semanas silver disponibles; ese dato se puede convertir
  en una alerta operacional de frescura/cobertura.
- No hay un indicador claro para diferenciar "unidad sana" de "unidad sin data
  suficiente".

## Quick wins con datos actuales

### 1. Resumen Ejecutivo Telemetria

Agregar una seccion o pestana ejecutiva con cinco bloques:

| Bloque | Objetivo | Datos actuales |
|---|---|---|
| Flota en riesgo | Cantidad y porcentaje de unidades en `Alerta` o `Anormal` | `unit_health.overall_status` |
| Unidades prioritarias | Ranking de unidades por prioridad operacional | `unit_health.priority_score` |
| Sistemas criticos | Sistemas con mayor `system_score` agregado | `system_health.system_score` |
| Senales causales | Top senales por `risk_score`, estado y comentario IA | `deviation`, `signal_comments` |
| Acciones sugeridas | Consolidado de urgencia y accion recomendada | `unit_comments`, `signal_comments` |

Valor esperado: una pantalla lista para revision semanal sin entrar unidad por
unidad.

### 2. Ranking de deterioro semanal

Construir un ranking con comparacion contra la semana anterior:

- Unidad.
- Sistema principal afectado.
- Estado actual y estado anterior.
- `priority_score` actual y delta semanal.
- Senales nuevas en `Alerta` o `Anormal`.
- Accion recomendada.

Datos actuales requeridos:

- `unit_health` y `system_health` particionados por `year/week`.
- `deviation` particionado por `year/week`.
- `ai_comments` para explicar acciones.

Nota: hoy algunos loaders filtran automaticamente la ultima semana. Para esta
vista se debe agregar un loader historico o un parametro opcional `latest_only`.

### 3. Top senales contributivas por unidad

Agregar una tabla compacta por unidad:

| Campo | Descripcion |
|---|---|
| Unidad | Equipo evaluado |
| Sistema | Sistema asociado a la senal |
| Senal | Nombre amigable desde `signal_registry.yaml` |
| Estado | `Normal`, `Alerta`, `Anormal` o `InsufficientData` |
| Risk Score | Puntaje de riesgo de la senal |
| Evidencia | `abnormal_pct`, eventos, episodio maximo y tendencia |
| Recomendacion | Comentario IA o accion sugerida |

Valor esperado: convertir el detalle tecnico en una lista priorizada de causas.

### 4. Reporte de persistencia de eventos

Agregar una vista o bloque que priorice eventos recurrentes y largos:

- Total de episodios por senal.
- Episodio maximo en minutos.
- Minutos acumulados en estado no normal.
- Numero de warnings.
- Senales con eventos persistentes aunque el promedio semanal no sea extremo.

Datos actuales:

- `technique_results/events`
- `technique_results/deviation`

Valor esperado: detectar fallas intermitentes o persistentes que el heatmap puede
ocultar.

### 5. Vista de confiabilidad de datos

Agregar un indicador de cobertura:

- Semana evaluada y fecha de ejecucion desde `latest.json`.
- Semanas silver disponibles.
- Unidades sin datos recientes.
- Senales sin muestras suficientes o con `InsufficientData`.
- Diferencia entre "sin riesgo" y "sin evidencia suficiente".

Datos actuales:

- `latest.json`
- `Telemetry_Wide_With_States`
- `unit_health`, `system_health`, `deviation`

Valor esperado: evitar conclusiones falsas cuando falta data.

### 6. Exportable para mantenimiento

Agregar descarga CSV/Excel con una fila por combinacion relevante
unidad-sistema-senal:

| Campo minimo | Fuente |
|---|---|
| Semana, anio | particiones o `latest.json` |
| Unidad | `unit_health`, `deviation` |
| Sistema | `system_health`, `signal_registry.yaml` |
| Senal | `deviation.signal` |
| Estado | `deviation.status` |
| Risk Score | `deviation.risk_score` |
| Eventos | `events` |
| Episodio maximo | `events.duration_minutes` |
| Tendencia | `trend.trend_interpretation`, `slope_per_day`, `r2` |
| Diagnostico IA | `signal_comments.description` |
| Accion recomendada | `signal_comments.recommended_action` o `unit_comments.recommended_action` |

Valor esperado: soporte directo para reuniones, seguimiento y trazabilidad.

## Mejoras que requieren pipeline nuevo

### 1. Patrones multi-senal desde reglas diagnosticas

El archivo `data/telemetry/config/{client}/diagnostic_rules.yaml` define reglas
por sistema, senales, duracion, severidad y acciones. Para explotarlas en
dashboard se recomienda generar una tabla golden:

`data/telemetry/golden/{client}/technique_results/rules/year={YYYY}/week={WW}/rule_matches.parquet`

Campos minimos:

- `unit`
- `system`
- `rule_id`
- `rule_name`
- `severity`
- `status`
- `confidence`
- `start_time`
- `end_time`
- `duration_minutes`
- `triggered_signals`
- `evidence_summary`
- `recommended_actions`

Uso en dashboard:

- Mostrar patrones activos por unidad.
- Priorizar casos donde varias senales confirman un mismo modo de falla.
- Explicar riesgo con reglas operacionales, no solo con percentiles.

### 2. Correlacion telemetria + tribologia + mantenciones

Crear una tabla de correlacion por unidad, sistema y ventana temporal:

`data/alerts/golden/{client}/cross_technique_evidence.parquet`

Campos minimos:

- `unit`
- `system`
- `component`
- `window_start`
- `window_end`
- `has_telemetry_evidence`
- `has_oil_evidence`
- `has_maintenance_context`
- `telemetry_risk_score`
- `oil_severity`
- `maintenance_status`
- `combined_priority`
- `recommended_action`

Uso en dashboard:

- Subir prioridad cuando telemetria y tribologia coinciden.
- Mostrar alertas mixtas como casos de mayor confianza.
- Separar anomalia aislada de problema confirmado por multiples fuentes.

### 3. Severidad operacional ponderada por contexto

Enriquecer eventos con contexto operacional:

- Estado de maquina.
- Carga o ciclo operativo si existe.
- GPS, pendiente o elevacion cuando este disponible.
- Duracion y recurrencia bajo condiciones equivalentes.

Salida sugerida:

`data/telemetry/golden/{client}/technique_results/contextual_events/year={YYYY}/week={WW}/contextual_events.parquet`

Uso en dashboard:

- Diferenciar evento esperable por condicion operacional de evento anomalo.
- Reducir falsos positivos.
- Priorizar eventos que ocurren bajo condiciones normales de operacion.

### 4. Prediccion de ventana de intervencion

Generar una tabla forecast por senal/sistema:

`data/telemetry/golden/{client}/forecast/year={YYYY}/week={WW}/intervention_windows.parquet`

Campos minimos:

- `unit`
- `system`
- `signal`
- `current_value`
- `current_risk_score`
- `slope_per_day`
- `projected_days_to_limit`
- `confidence`
- `recommended_window`
- `assumptions`

Uso en dashboard:

- Traducir tendencias en ventana de inspeccion.
- Ordenar backlog por urgencia temporal.
- Convertir telemetria en planificacion preventiva.

## Cambios recomendados en el dashboard

### Nueva pestana: Resumen Ejecutivo

Agregar una pestana interna antes de `Vista de Flota`:

1. KPIs ejecutivos.
2. Ranking de unidades prioritarias.
3. Ranking de sistemas criticos.
4. Top senales causales.
5. Acciones sugeridas.
6. Boton de descarga.

La pestana debe cargar rapido usando solo golden layer. Las series silver deben
quedar para drill-down, no para la primera pantalla.

### Mejoras en Detalle de Unidad

Agregar un bloque "Por que esta en alerta" con:

- Estado actual de la unidad.
- Variacion semanal de prioridad.
- Sistema principal afectado.
- Top 3 senales causales.
- Eventos persistentes relevantes.
- Tendencias significativas.
- Recomendacion IA consolidada.

Este bloque debe aparecer antes de la tabla de sistemas para orientar al usuario
antes del detalle tecnico.

### Filtros recomendados

Agregar filtros globales o por pestana:

- Semana/anio.
- Sistema.
- Estado/severidad.
- Urgencia IA.
- Solo unidades con deterioro semanal.
- Solo senales con datos suficientes.

### Exportables

Implementar descarga con dos niveles:

- **Resumen ejecutivo**: una fila por unidad/sistema prioritario.
- **Evidencia tecnica**: una fila por unidad/sistema/senal.

Formato recomendado:

- CSV primero por simplicidad y compatibilidad.
- Excel en una segunda etapa si se necesita separar hojas por resumen,
  evidencia, eventos y tendencias.

## Roadmap priorizado

### Fase 1: Reportabilidad con datos actuales

Objetivo: mejorar decisiones semanales sin tocar el pipeline.

Entregables:

- Pestana `Resumen Ejecutivo`.
- Tabla de top unidades/sistemas/senales.
- Bloque "Por que esta en alerta" en detalle de unidad.
- Exportable CSV.
- Loader historico opcional para comparar semanas.

Criterio de exito:

- Un usuario puede identificar en menos de 2 minutos las unidades a revisar,
  las causas principales y las acciones sugeridas.

### Fase 2: Confiabilidad y explicabilidad

Objetivo: evitar decisiones con datos incompletos o poco trazables.

Entregables:

- Vista de cobertura y freshness de telemetria.
- Indicador de `InsufficientData`.
- Explicacion de drivers del riesgo.
- Diferenciacion visual entre riesgo bajo y evidencia insuficiente.

Criterio de exito:

- Cada estado critico o normal queda respaldado por cobertura, semana evaluada y
  evidencia disponible.

### Fase 3: Nuevas salidas analiticas del pipeline

Objetivo: pasar de anomalias individuales a diagnostico operacional.

Entregables:

- Tabla golden de reglas multi-senal.
- Tabla de correlacion telemetria/tribologia/mantenciones.
- Eventos contextualizados por estado operacional y GPS.
- Forecast de ventana de intervencion.

Criterio de exito:

- Las prioridades reflejan confirmacion multi-fuente, severidad contextual y
  urgencia temporal.

## Validacion recomendada

### Validacion funcional

- Verificar que CDA cargue la vista de telemetria sin errores.
- Probar estados vacios para cada loader.
- Confirmar que `latest.json` se muestre coherentemente con semana/anio.
- Validar que el ranking ejecutivo coincida con `priority_score` y
  `system_score`.
- Validar que el exportable tenga columnas completas aunque falten comentarios
  IA.

### Validacion de datos

- Comparar conteos por estado entre `unit_health` y KPIs de la vista.
- Comparar top sistema del heatmap contra maximo `system_score`.
- Comparar top senales contra `deviation.risk_score`.
- Confirmar que eventos se agrupen por `feature` o `signal` segun el esquema
  disponible.
- Confirmar que tendencias usen solo `is_significant == True` y
  `is_good_fit == True`.

### Validacion de UX

- La pantalla ejecutiva debe poder leerse sin abrir el detalle.
- El detalle debe explicar el diagnostico antes de mostrar graficos.
- Los colores deben distinguir estado critico, alerta, normal e insuficiencia de
  datos.
- El exportable debe ser legible para mantenimiento sin conocer el esquema
  tecnico.

## Supuestos

- El alcance inicial es CDA, porque la vista declara disponibilidad solo para ese
  cliente.
- No se requieren instalaciones nuevas para producir este analisis.
- Las mejoras de fase 1 deben reutilizar loaders existentes y agregar parametros
  historicos solo cuando sea necesario.
- Las mejoras de pipeline deben escribirse en golden layer antes de conectarlas
  al dashboard.
- La prioridad de implementacion debe favorecer reportabilidad accionable por
  sobre agregar visualizaciones tecnicas aisladas.
