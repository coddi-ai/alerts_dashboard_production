# Plan de implementación para Claude — mejoras Dashboard W34

**Fecha de preparación:** 2026-08-19  
**Repositorio:** `CDA/Dashboard/tds_alerts_dashboard`  
**Worktree de trabajo:** `C:\Users\panch\Desktop\Coddi\.worktrees\tds-alerts-dashboard\claude-dashboard-w34`  
**Rama:** `ai/claude/dashboard-w34`  
**Base:** `dev@506ad72f765198b32effa261f04e5319730c34bf`  
**Tarea Coddi:** `tds-alerts-dashboard--claude--dashboard-w34`

## 1. Objetivo y alcance

Implementar y validar las 13 mejoras P0, P1 y P2 del dashboard asignadas a Francisco Vilches en W34. La fuente funcional es `seguimiento_semanal/2026-W34/objetivos.md` del meta-repo.

Queda fuera de alcance:

- mejoras P3;
- mejoras asignadas a Pato o Matías Sepúlveda;
- crear o modificar tickets Jira;
- volver a implementar `Arreglar Análisis Inteligente`: el ZIP la marca `Listo`. Solo se debe comprobar que no haya regresión;
- cambios de ETL, contratos upstream, infraestructura, despliegue productivo o credenciales.

## 2. Definición de terminado

La tarea está terminada cuando:

- cada una de las 13 mejoras tiene estado `Implementada`, `Bloqueada` o `No reproducible`, con evidencia y siguiente acción;
- las mejoras implementadas tienen pruebas unitarias o de callback que cubren el comportamiento nuevo;
- las etiquetas solo cambian la presentación y no rompen claves, joins ni filtros internos;
- las tablas conservan la capacidad de seleccionar una alerta, unidad o variable aunque se oculten columnas visuales;
- se verifica que las rutas principales y callbacks de General, Estado de Datos, Alertas, Telemetría y Predictivo siguen registrándose;
- pasan `python -m compileall -q dashboard src config` y `python -m pytest -q tests` en un entorno funcional;
- el handoff registra commits, archivos, validaciones, riesgos, bloqueos y siguiente acción. No se hace push ni integración automática.

## 3. Matriz de mejoras

| ID | Prioridad | Mejora | Resultado esperado | Áreas a inspeccionar primero | Aceptación mínima |
|---|---:|---|---|---|---|
| W34-01 | P0 | Unificar Componentes | Capstone Copper muestra una nomenclatura única y consistente para componentes en General y vistas relacionadas. | `src/data/component_normalizer.py`, `dashboard/components/labels.py`, `dashboard/tabs/tab_overview_general.py`, `dashboard/callbacks/overview_general_callbacks.py`, configuración de cliente Capstone. | Mismo componente se presenta igual en tabla, filtros, gráficos y detalle; los valores crudos usados para joins permanecen intactos; prueba con alias representativos. |
| W34-02 | P2 | Mejorar Look&Feel Estado de Datos | La tabla de Estado de Datos comparte jerarquía visual, estados, espaciado y encabezados con General. | `dashboard/tabs/tab_data_freshness.py`, `dashboard/callbacks/data_freshness_callbacks.py`, `dashboard/assets/custom_layout.css`, `dashboard/assets/custom_tabs.css`. | Comparación visual coherente; estados Ok/Atención/Preocupante siguen diferenciados; no cambia el cálculo de frescura; prueba de estructura/estilos. |
| W34-03 | P1 | Acortar Tabla de Alertas | La vista general no muestra ID, Fuente ni Evidencia como columnas visibles. | `dashboard/tabs/tab_alerts_general.py`, `dashboard/components/alerts_tables.py`, `dashboard/callbacks/alerts_callbacks.py`. | Las tres columnas no aparecen en la tabla; selección, navegación al detalle y datos necesarios para callbacks siguen funcionando. |
| W34-04 | P1 | Cambio de Nomenclatura Alertas Mixtas | Se incorpora una leyenda de color y se actualiza la nomenclatura/color de las alertas mixtas. | `src/charts/signals.py`, `dashboard/components/labels.py`, `dashboard/components/alerts_charts.py`, `dashboard/components/alerts_tables.py`, CSS de alertas. | La misma etiqueta y color aparecen en tabla, leyenda, gráfico y detalle; no se confunden alertas de aceite, telemetría o mixtas; prueba de mapeo. |
| W34-05 | P1 | Modificar Filtros | Alertas Detalle elimina el filtro de telemetría e incorpora un filtro de fecha desde. | `dashboard/tabs/tab_alerts_detail.py`, `dashboard/callbacks/alerts_callbacks.py`, `dashboard/components/filters.py`. | El filtro retirado no se renderiza ni participa en callbacks; fecha desde filtra de forma inclusiva y con zona horaria consistente; prueba de límites y valor vacío. |
| W34-06 | P0 | Cuadrar Instante de Alertas | El instante mostrado para una alerta coincide con el tiempo usado por el dashboard y sus evidencias. | `dashboard/tabs/tab_alerts_detail.py`, `dashboard/callbacks/alerts_callbacks.py`, `dashboard/components/alerts_charts.py`, `src/data/loaders.py`, `src/utils/date_utils.py`. | Un fixture con zona horaria/formatos mixtos produce el mismo instante en tabla, encabezado, gráfico y selección; no se desplaza por conversión doble. |
| W34-07 | P0 | Arreglar Análisis Inteligente | No duplicar implementación; verificar que los mensajes por defecto existentes sigan presentándose correctamente. | `dashboard/components/ai_analysis_panel.py`, callbacks de Alertas Detalle y pruebas Campbell/AI existentes. | Smoke test de alerta sin análisis disponible: mensaje por defecto correcto, sin excepción ni llamada externa. Registrar como `Validada/no duplicar`. |
| W34-08 | P2 | Renombrar percentil X por Límite | Telemetría usa “límite marginal”/“límite condenatorio” donde hoy expone percentiles al usuario. | `dashboard/tabs/tab_telemetry_unit_detail.py`, `dashboard/components/telemetry_charts.py`, `dashboard/components/telemetry_tables.py`, `src/charts/builders.py`. | Se actualizan títulos, leyendas, tooltips y tablas sin cambiar valores ni cálculos; búsqueda de regresión sin textos `Percentil` en la UI objetivo. |
| W34-09 | P2 | Simplificar análisis de una señal | La vista parte con un día, omite eventos y ofrece botones claros para ampliar días. | `dashboard/tabs/tab_telemetry_unit_detail.py`, `dashboard/callbacks/telemetry_callbacks.py`, `dashboard/components/telemetry_charts.py`. | Valor por defecto de 1 día; eventos no se muestran en la vista simplificada; botones cambian la ventana sin perder unidad/señal; pruebas de 1/7/30 días. |
| W34-10 | P1 | Mejorar Tabla Predictivo | La tabla del Predictivo mejora legibilidad, orden, nombres y estados sin cambiar el ranking. | `dashboard/components/predictive_tables.py`, `dashboard/tabs/tab_predictive_overview.py`, `dashboard/callbacks/predictive_callbacks.py`, CSS predictivo. | Columnas y etiquetas son comprensibles, ordenamiento sigue estable y valores `ranking`/modos de falla no se alteran; fixture con nulos y empates. |
| W34-11 | P0 | Ajustar Variables en Serie de Tiempo | El diccionario de variables mostrado en Alertas Detalle coincide con las variables permitidas/disponibles en la fuente. | `dashboard/components/alerts_charts.py`, `dashboard/components/telemetry_charts.py`, `src/charts/signals.py`, `dashboard/callbacks/alerts_callbacks.py`, `src/data/loaders.py`. | No aparecen variables inexistentes; las variables disponibles conservan su código interno y etiqueta; prueba de señal conocida, desconocida y mixta. |
| W34-12 | P2 | Unificar Nomenclatura de Nombres de Variables | Alertas, Telemetría y Predictivo muestran traducciones consistentes. | `src/charts/signals.py`, `dashboard/components/labels.py`, `dashboard/components/telemetry_charts.py`, `dashboard/components/predictive_config.py`, componentes de alertas. | Cada variable tiene una fuente de verdad; no hay traducciones divergentes entre módulos; prueba parametrizada de catálogo. |
| W34-13 | P2 | Corregir Fuentes disponibles en Estado x Unidad | General/Estado x Unidad solo muestra columnas respaldadas por la data disponible del cliente. | `dashboard/tabs/tab_overview_general.py`, `dashboard/callbacks/overview_general_callbacks.py`, `dashboard/tabs/tab_data_freshness.py`, `src/data/loaders.py`, contratos en `documentation/general` y `documentation/alerts`. | Las columnas se derivan de disponibilidad real; fuente ausente se comunica como no disponible y no como cero/sano; prueba por cliente con fuente presente y ausente. |

## 4. Orden de ejecución recomendado

### Fase 0 — Baseline y mapa de callbacks

1. Confirmar worktree, rama y estado limpio.
2. Ejecutar `python -m compileall -q dashboard src config`.
3. Ejecutar `python -m pytest -q tests` y registrar el resultado antes de tocar código.
4. Leer los contratos de Alertas, Telemetría, Predictivo y Estado de Datos.
5. Construir una tabla interna de IDs de componentes, tablas, filtros, stores y callbacks afectados. Evitar cambios hasta saber qué `id` alimenta cada callback.

### Fase 1 — P0 y contratos de datos/presentación

Implementar en este orden: W34-01, W34-06, W34-11. Son cambios transversales y deben estabilizar primero los nombres y tiempos que consumen las vistas.

- Centralizar normalización/traducción en helpers reutilizables.
- Separar siempre valor crudo de etiqueta visible.
- Normalizar timestamps una sola vez en el borde de carga y usar el mismo valor en la UI.
- Mantener un diccionario de variables con códigos permitidos por fuente/cliente; no inventar unidades ni señales.
- Tras cada mejora, agregar pruebas pequeñas antes de pasar a la siguiente.

W34-07 se valida al final de esta fase como regresión, sin modificar el trabajo ya marcado como listo salvo evidencia reproducible de una falla.

### Fase 2 — P1 de interacción y tablas

Implementar W34-03, W34-04, W34-05 y W34-10.

- Primero ajustar funciones puras que producen columnas/opciones.
- Después ajustar layouts y callbacks.
- Al ocultar columnas, conservar IDs en `data`, `dcc.Store` o el mecanismo que use el detalle; no eliminar campos requeridos para navegación.
- Asegurar que el filtro de fecha tenga una semántica explícita: fecha desde inclusiva, sin fecha significa sin límite y fechas inválidas producen estado visible, no excepción.
- Mantener el ranking predictivo numérico y separar el orden visual de la etiqueta.

### Fase 3 — P2 visuales y consistencia

Implementar W34-02, W34-08, W34-09, W34-12 y W34-13.

- Reutilizar clases CSS y componentes existentes cuando sea posible.
- No cambiar cálculos de frescura, límites o clasificación para resolver un ajuste de nomenclatura.
- Para Telemetría, conservar unidad, señal y rango seleccionado al cambiar los botones de días.
- Para fuentes faltantes, distinguir `sin fuente`, `sin registros` y `estado desconocido`.

### Fase 4 — Validación integral y handoff

1. Ejecutar las validaciones offline.
2. Ejecutar pruebas de importación/registro de callbacks.
3. Hacer una revisión visual local solo con datos locales/sintéticos disponibles; no usar S3 ni despliegue productivo.
4. Actualizar la matriz de trazabilidad con archivos, pruebas y estado de cada W34-ID.
5. Revisar `git diff --check`, `git status` y el diff completo.
6. Crear commits locales pequeños, preferentemente uno por fase o por grupo coherente.
7. Generar el handoff Coddi; dejar como siguiente acción la revisión/integración humana.

## 5. Estrategia de pruebas

Crear o ampliar pruebas bajo `tests/`, sin depender de credenciales ni servicios externos.

- **Catálogos y etiquetas:** pruebas parametrizadas para componentes, señales, alertas mixtas y variables predictivas.
- **Timestamps:** casos naive, UTC, offset de Chile y formatos ISO con/sin milisegundos; verificar un único instante esperado.
- **Filtros:** fecha desde inclusiva, vacío, fecha posterior al máximo y datos con timestamps inválidos.
- **Tablas:** columnas visibles, orden, nulos, empates y conservación de campos internos para navegación.
- **Telemetría:** ventana por defecto de 1 día, botones de ampliación y ausencia de eventos en la vista simplificada.
- **Estado de Datos:** estados visuales y ausencia de fuentes; nunca confundir falta de datos con estado saludable.
- **Callback smoke:** importación de módulos y registro de callbacks sin levantar servicios externos.

Comandos mínimos al terminar:

```powershell
python -m compileall -q dashboard src config
python -m pytest -q tests
git diff --check
```

Si el entorno no tiene dependencias, no instalar desde internet silenciosamente: documentar el bloqueo y pedir una preparación de entorno. Las pruebas Docker, AWS/S3, túneles, bases reales y despliegues son integración y requieren aprobación explícita.

## 6. Evidencia y handoff

Mantener una tabla de seguimiento en el PR/commit o en el handoff con estas columnas:

`W34-ID | estado | archivos | prueba | evidencia | riesgo/bloqueo | siguiente acción`.

Usar solo estados verificables:

- `Implementada`: comportamiento y prueba confirmados.
- `Validada/no duplicar`: aplica únicamente a W34-07.
- `Bloqueada`: falta dato, dependencia o decisión; incluir acción concreta.
- `No reproducible`: incluir fixture/flujo intentado y por qué no pudo observarse.

El handoff debe declarar explícitamente que no se modificó la copia productiva local, no se tocaron secretos, no se hizo push y no se integró la rama.

## 7. Riesgos conocidos

- Los nombres de variables y componentes pueden variar por cliente; la etiqueta visible no debe convertirse en clave de join.
- El flujo actual mezcla vistas Dash, callbacks y loaders; cambiar un `id` sin revisar todos sus consumidores puede romper el arranque.
- La evidencia de Alertas depende de timestamps y puede sufrir conversiones dobles de zona horaria.
- El entorno virtual ignorado no se copia al worktree; la validación debe ejecutarse con un intérprete preparado para esta copia.
- La mejora visual no debe ocultar datos necesarios para el detalle ni convertir fuentes ausentes en ceros.
