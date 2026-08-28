# Auditoría productiva por cliente y pestaña

## Alcance aplicado

La implementación agrega una capa de lectura y diagnóstico. Los CSV, Parquet,
Excel, manifiestos y sus esquemas no se modifican. Las normalizaciones se
realizan únicamente en DataFrames defensivos, metadatos del catálogo y
componentes de Dash.

El comando reproducible es:

```powershell
python scripts/audit_dashboard.py --json > audit_dashboard.json
```

Para comparar el lector rápido con pandas en el snapshot local:

```powershell
python scripts/benchmark_dashboard.py --client CAPSTONE
```

También acepta `--root <ruta>` para inspeccionar el volumen montado en
producción. El comando solo lee y emite metadatos: estado, tamaño, filas,
columnas, unidades y rango temporal cuando el formato permite calcularlo.

## Estados de contrato

| Estado | Significado operativo |
|---|---|
| Disponible | La fuente esperada existe y puede ser localizada por el adaptador. |
| Parcial | Existe una fuente compatible, pero falta parte del contrato (por ejemplo, CSV semanales donde General espera Parquet). |
| Sin fuente | No se encontró una ruta compatible para esa técnica. |
| Desactualizado | La fuente existe, pero su fecha máxima no cumple el umbral acordado; se determina en la auditoría de fechas y en Estado de Datos. |
| Contrato incompatible | Hay archivos, pero no cumplen las columnas mínimas de la vista; debe aparecer como error de lectura, no como “Normal”. |

## Matriz de cobertura esperada

La matriz se deriva de `config/client_services.json` y del catálogo. Las
fuentes mostradas en cada página se calculan en tiempo de ejecución, por lo
que la UI deja de afirmar que una pestaña está disponible solo porque el
servicio fue habilitado en configuración.

| Cliente | General | Estado de Datos | Alertas | Telemetría | Aceite | Predictivo | Campbell / Integraciones |
|---|---|---|---|---|---|---|---|
| CDA | Parcial si falta mantenimiento o telemetría | Fuente auxiliar compatible | Alertas + evidencia | Validar `unit_health/system_health` | Disponible según límites | Componentes CSV + IA | No auditados como fuentes técnicas |
| EMIN | Parcial por mantenimiento y/o telemetría | Validar fecha y ruta | Alertas; sin evidencia de telemetría local | Parcial/sin salida health | Aceite sin archivo four-limit | No habilitado | No auditados como fuentes técnicas |
| ENEX | Aceite y servicios dummy | No habilitado | No habilitado | No habilitado | Disponible | No habilitado | Dummy/protegidos por configuración |
| CAPSTONE | Parcial si falta mantenimiento o telemetría | Fuente auxiliar compatible | Alertas + evidencia grande | Validar `unit_health/system_health` | Disponible según límites | Componentes CSV + IA | No auditados como fuentes técnicas |

La auditoría offline debe ser la fuente de números exactos del snapshot; esta
tabla no sustituye la medición del volumen productivo.

## Cambios implementados

- `src/data/catalog.py`: catálogo central de rutas, tamaños, `mtime`, estados y
  fallback de `auxiliar/golden/{cliente}`.
- `dashboard/components/source_status.py`: banda de procedencia por página.
- General, Estado de Datos, Alertas, Telemetría y Aceite: muestran cobertura
  real; Telemetría explicita cuando faltan salidas health.
- General: `dcc.Store` conserva metadatos derivados de disponibilidad junto con
  el snapshot de la vista.
- Predictivo: Resumen y Evidencia reutilizan la misma preparación de CSV y la
  invalidan por `mtime`/tamaño; la detección de componentes también respeta el
  raíz de datos configurable. El lector usa Polars cuando está instalado y
  conserva pandas como fallback compatible.
- Lecturas repetidas de mapping Excel y límites four-limit usan caché con
  invalidación por generación de archivo.
- Loaders de Telemetría y metadatos de registro usan
  `DASHBOARD_DATA_ROOT`, evitando que una ruta relativa ignore el volumen
  montado.
- Docker usa Gunicorn con un worker y threads para mantener el caché local
  coherente; el número de workers/replicas debe decidirse junto con una caché
  distribuida si se escala horizontalmente.
- El perfil productivo prioriza velocidad: Polars es el motor predeterminado,
  la evidencia de Alertas se cachea por alerta/unidad y el contenedor mantiene
  un solo worker para evitar recalentar cachés duplicados.

## Ranking de trabajo pendiente

### P0 — evitar decisiones incorrectas

1. Contrastar en AWS que cada cliente tenga los archivos que declara la
   configuración y que las columnas mínimas sean compatibles.
2. Acordar un único calendario de frescura y separar fecha de evaluación,
   fecha máxima de observación y fecha de publicación del snapshot.
3. Mantener “Sin datos”, “Sin fuente”, “Parcial” y “Desactualizado” como estados
   distintos en KPIs, tablas y exportaciones.

### P1 — tiempo y cobertura

1. Medir y optimizar Alertas Detallada con proyección de columnas y carga por
   alerta/unidad; CAPSTONE requiere prioridad por su archivo ancho.
2. Sustituir serialización de datos no consumidos en General por agregados
   derivados cuando se confirme qué callbacks heredados siguen navegables.
3. Completar el contrato de mantenimiento o implementar un adaptador de
   lectura para sus CSV semanales sin inventar KPIs no disponibles.
4. Evitar escaneos de particiones repetidos con un manifest de lectura derivado
   y cacheado por `mtime`.

### P2 — operación y trazabilidad

1. Eliminar callbacks heredados no navegables después de validar el registro de
   rutas y pruebas de regresión.
2. Centralizar etiquetas, umbrales y mensajes de calidad de fuente.
3. Registrar por cliente/pestaña: latencia, filas leídas, bytes, cache hit/miss,
   error de contrato y fecha máxima mostrada.
4. Revisar credenciales embebidas, secretos por entorno y autenticación antes
   de ampliar el despliegue.

## Criterios de aceptación

- Ningún archivo de entrada cambia su hash después de ejecutar la auditoría.
- Cada cliente y servicio habilitado tiene estado visible y procedencia.
- Una fuente ausente no produce un estado “Normal” por defecto.
- Cambiar `mtime` o tamaño de una fuente invalida el resultado cacheado.
- El lector Polars devuelve pandas en la frontera de Dash y permite forzar
  `DASHBOARD_FRAME_ENGINE=pandas` para comparar o diagnosticar.
- Predictivo Resumen/Evidencia no parsea dos veces el mismo CSV en una misma
  generación.
- Las rutas de Telemetría funcionan con `DASHBOARD_DATA_ROOT` tanto en local
  como en el volumen montado.
- La auditoría continúa si una fuente es incompatible y reporta el error sin
  ocultar el estado de las demás fuentes.

## Validación AWS requerida

Contrastar por cliente y pestaña: p50/p95/p99 de callbacks, tiempo de primera
carga, CPU, memoria, concurrencia, errores 4xx/5xx, lecturas EFS, throughput,
IOPS, burst credits, latencia de CloudWatch, número de procesos/replicas y
cache hit/miss. Estas mediciones no se pueden inferir con seguridad desde el
snapshot local y no se ejecutan en la validación offline.
