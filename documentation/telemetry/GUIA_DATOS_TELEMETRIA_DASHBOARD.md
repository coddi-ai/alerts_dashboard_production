# Guía de reportabilidad de Telemetría

## Propósito

La sección de Telemetría mantiene dos pestañas para la reunión semanal de
mantenimiento y confiabilidad. La interfaz reutiliza exclusivamente resultados
materializados en golden, silver, YAML y comentarios IA. No crea scores,
diagnósticos ni reglas nuevas.

Los campos internos `priority_score`, `system_score`, `risk_score` y
`confidence` se utilizan para ordenar o seleccionar evidencia, pero no se
muestran como números al cliente.

## Flujo recomendado

1. En **Vista de Flota**, revise las filas superiores de la matriz. El orden
   combina severidad (`Anormal`, `Alerta`, `Normal`, `Sin evidencia`) y, dentro
   de cada estado, el score interno descendente.
2. Seleccione un sistema de la unidad. La celda muestra su estado y el tooltip
   contiene la acción recomendada IA del sistema.
3. Abra la fila o celda para ir a **Detalle de Unidad** con unidad y sistema
   precargados.
4. En el detalle, lea primero el resumen único de la unidad, luego la
   evaluación IA del sistema y finalmente seleccione la señal de mayor riesgo.
5. Use la serie temporal para confirmar la evidencia, límites, eventos,
   anomalías y tendencia. La vista inicial parte en el episodio máximo y llega
   hasta la última observación disponible.

## Vista de Flota

La tabla única contiene:

- `Unidad`: identificador de equipo.
- `Modelo`: modelo materializado en el manifiesto de equipos.
- Columnas de sistema: estado materializado por sistema.
- `Estado`: estado general de `unit_health`.

El selector **Sistemas visibles** inicia con todos los sistemas seleccionados y
solo controla las columnas visibles. No recalcula el estado de la unidad.
Pasar el cursor sobre una celda de sistema muestra estado y acción IA. Cuando
no existe comentario de sistema, se informa que no hay acción registrada.

## Detalle de Unidad

La información sigue la jerarquía:

### Unidad

El bloque inicial muestra unidad, modelo, semana de evaluación y fecha de
ejecución. Incluye estado general, cantidad de sistemas afectados, sistema y
señal principales, urgencia, diagnóstico IA y acción IA de la unidad. Este
mensaje permanece estable aunque se cambie el sistema seleccionado.

### Sistema

La tabla muestra todos los sistemas con estado, cantidad de señales afectadas
y señal principal. Se ordena por `system_score` descendente y el primer sistema
es el predeterminado, salvo que la navegación desde Flota haya enviado otro.
La tarjeta inmediatamente inferior contiene la descripción, explicación y
acción IA del sistema elegido.

### Señal

La tabla muestra nombre legible, estado, porcentaje fuera de rango, eventos,
episodio máximo y tendencia. El nombre técnico y la unidad se obtienen de
`signal_registry.yaml`; por ejemplo, `LckupSlip` y `TrnSlip` se muestran en
segundos.

Solo se renderiza la evidencia de la señal seleccionada. Si no hay comentario
IA, datos silver, serie o evidencia suficiente, la interfaz lo indica
explícitamente y no inventa una explicación.

## Serie temporal

- Media móvil temporal de 120 minutos.
- Percentiles en orden ascendente: P2, P5, P95 y P98.
- Rango vertical inicial entre P1 y P99 de los valores observados.
- Fondos y marcadores distintos para Anomalía y Evento.
- Range slider y accesos: Última semana, Últimas 2 semanas, Último mes y
  Episodio crítico.
- Los conteos permanecen en la tabla KPI de la señal, no en la leyenda.

Los fondos y marcadores utilizan únicamente intervalos existentes en
`technique_results/events`. El snapshot CDA actual contiene eventos hasta el
24/05/2026 mientras que la serie llega posteriormente; en ese caso aparece un
aviso de cobertura y los datos posteriores se muestran sin clasificación de
eventos.

## Trazabilidad de campos

| Campo mostrado | Fuente | Transformación de presentación |
|---|---|---|
| Estado de unidad | `unit_health.overall_status` | Traducción de estado y ordenamiento |
| Orden de unidades | `unit_health.priority_score` | Solo orden, oculto |
| Estado de sistema | `system_health.system_status` | Traducción y color |
| Orden de sistema | `system_health.system_score` | Solo orden, oculto |
| Señales afectadas | `deviation.status` | Conteo de estados Alerta/Anormal |
| Porcentaje fuera de rango | `deviation.abnormal_pct` | Formato porcentual |
| Eventos y episodio máximo | `technique_results/events` | Unión por `signal` o alias legacy `feature` |
| Tendencia | `technique_results/trend` | Se muestra solo si ya está marcada como significativa |
| Límites | `limits` / baseline materializado | Líneas P2/P5/P95/P98 |
| Nombre y unidad | `signal_registry.yaml` | Traducción de nombre técnico |
| Diagnóstico y acción | comentarios IA unit/system | Compatibilidad con campos nuevos y legacy |

## Estados de datos

`InsufficientData` se representa en gris y no se interpreta como `Normal`.
Cuando no existe comentario IA, serie silver, evento asociado o evidencia
suficiente, se muestra un estado explícito para mantener trazabilidad durante
la reunión.
