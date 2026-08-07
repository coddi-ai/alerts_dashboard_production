# Campbell AI

**Versión 1.1.3** — arquitectura de páginas de Dash, historial de conversaciones en un
panel lateral, streaming de respuestas sin condición de carrera y configuración
reorganizada (solo secretos reales en `.env`). El detalle está en
[Novedades de la versión 1.1.1–1.1.3](#novedades-de-la-versión-111–113) y
[Novedades de la versión 1.1.0](#novedades-de-la-versión-110).

Campbell AI está integrado en `tds_alerts_dashboard` mediante dos componentes:

- `src/campbell_ai/`: API FastAPI, agentes, prompts, seguridad, sesiones y adaptación de datos.
- `dashboard/campbell_ai/`: cliente interno, layout y callbacks Dash.

La API reutiliza los usuarios y permisos de `config/users.py` y lee los datos desde
`CAMPBELL_AI_DATA_ROOT`. No crea otro login, no copia datos y no depende de Streamlit ni de
`mining_chatbot` durante la ejecución.

## Requisitos

- Python 3.9 o superior.
- Dependencias de `requirements.txt` instaladas.
- Un usuario válido del dashboard y una empresa incluida en sus `clients`.
- `OPENAI_API_KEY` para consultas reales al modelo.
- El mismo `CAMPBELL_AI_INTERNAL_TOKEN` en Dash y FastAPI.

## Configuración local

Desde la raíz de `tds_alerts_dashboard`:

```powershell
Copy-Item .env.example .env
```

Configurar `OPENAI_API_KEY` en `.env` — es el único secreto de Campbell AI que vive ahí. El
archivo `.env` está ignorado por Git y no debe compartirse.

**Todo lo demás de Campbell AI (feature flags, timeouts, nombres de modelo, el token interno)
son valores por defecto declarados como `ENV` en el `Dockerfile`** — no son secretos, así que
viven en el repositorio para que un despliegue sea reproducible sin depender de un `.env`
completo. Para overridear cualquiera de ellos sin reconstruir la imagen, agrega la variable en
el bloque `environment:` del servicio correspondiente en `docker-compose.yml`, o localmente
(fuera de Docker) agrega la variable de vuelta a tu `.env` — sigue ganando sobre el default de
la imagen. Ver el `Dockerfile` para la lista completa y sus valores documentados.

Variables que sí siguen viviendo en `.env` (secretos reales, compartidos con el resto del
dashboard):

| Variable | Uso |
|---|---|
| `OPENAI_API_KEY` | Acceso del runtime de agentes a OpenAI. |
| `SECRET_KEY` | Firma la sesión autenticada de Dash; en este repositorio cumple además el rol de secret access key de AWS. |
| `BUCKET_NAME`, `ACCESS_KEY` | Bucket y credencial del respaldo en S3; ya configurados para el dashboard. |
| `DASHBOARD_IDENTITY_MAX_AGE_SECONDS` | Vigencia de la prueba firmada de identidad; 12 horas por defecto. |

Variables de Campbell AI con valor por defecto en el `Dockerfile` (documentadas ahí, resumen
aquí para referencia rápida):

| Variable | Defecto | Uso |
|---|---|---|
| `CAMPBELL_AI_ENABLED` | `true` | Habilita u oculta Campbell AI. |
| `CAMPBELL_AI_INTERNAL_TOKEN` | valor de imagen | Autentica a Dash frente a FastAPI; ambos contenedores comparten la misma imagen, así que quedan en sincronía automáticamente. |
| `CAMPBELL_AI_STREAMING` | `false` | Respuestas progresivas por SSE. |
| `CAMPBELL_AI_PERSISTENCE` | `true` | Habilita el respaldo de conversaciones y feedback. |
| `CAMPBELL_AI_S3_PREFIX` | `campbellAI` | Carpeta propia dentro del bucket ya configurado. |
| `CAMPBELL_AI_HISTORY_LIMIT` | `50` | Conversaciones que devuelve el listado por usuario. |
| `CAMPBELL_AI_SUMMARY` | `true` | Genera un título con IA para las conversaciones largas. |
| `CAMPBELL_AI_MODEL_SUMMARY` | `gpt-4.1-mini` | Modelo del titulador. |
| `CAMPBELL_AI_MAX_CONCURRENT_REQUESTS` | `10` | Respuestas simultáneas admitidas en total. |
| `CAMPBELL_AI_MAX_CONCURRENT_PER_USER` | `2` | Respuestas simultáneas por usuario. |
| `CAMPBELL_AI_MAX_REQUESTS_PER_MINUTE` | `200` | Cuota por minuto. |
| `CAMPBELL_AI_QUEUE_TIMEOUT_SECONDS` | `20` | Espera máxima antes de responder "ocupado". |
| `CAMPBELL_AI_RETRY_ATTEMPTS` | `3` | Reintentos ante fallos transitorios del modelo. |
| `CAMPBELL_AI_API_URL` | `http://127.0.0.1:8000` | URL que Dash usa para llamar a FastAPI; Docker Compose la overridea a `http://campbell-api:8000` en su `environment:`. |
| `CAMPBELL_AI_DATA_ROOT` | ruta del proyecto + `/data` | Directorio existente con los datos del dashboard; no se importan. |

## Lanzar solo la API en local

Crear y preparar el entorno una vez:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Iniciar FastAPI desde la raíz del repositorio:

```powershell
python -m uvicorn src.campbell_ai.api:app `
  --host 127.0.0.1 `
  --port 8000 `
  --reload `
  --env-file .env
```

`--reload` es solo para desarrollo. La API queda disponible en:

- Health: `http://127.0.0.1:8000/api/v1/campbell-ai/health`
- OpenAPI/Swagger: `http://127.0.0.1:8000/docs`
- Esquema OpenAPI: `http://127.0.0.1:8000/openapi.json`

### Smoke test de la API

`CAMPBELL_AI_INTERNAL_TOKEN` solo tiene un valor por defecto dentro de la imagen Docker (ver
Dockerfile); para correr la API fuera de Docker hay que declararlo explícitamente en `.env`:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(32))"
# pega el valor en CAMPBELL_AI_INTERNAL_TOKEN dentro de .env
```

En otra terminal, desde la misma carpeta:

```powershell
$token = (python -m dotenv get CAMPBELL_AI_INTERNAL_TOKEN).Trim()
$headers = @{ "X-Campbell-Token" = $token }

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/v1/campbell-ai/health"

Invoke-RestMethod `
  -Uri "http://127.0.0.1:8000/api/v1/campbell-ai/capabilities" `
  -Headers $headers
```

Para probar una conversación real, reemplazar los valores por un usuario y una empresa que ese
usuario tenga autorizada en `config/users.py`:

```powershell
$username = "USUARIO_DASHBOARD"
$company = "CDA"
$initializeBody = @{
  username = $username
  company_id = $company
} | ConvertTo-Json

$session = Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/campbell-ai/initialize" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $initializeBody

$messageBody = @{
  username = $username
  company_id = $company
  session_id = $session.session_id
  message = "Genera un Pareto de alertas para los últimos 30 días"
} | ConvertTo-Json

Invoke-RestMethod `
  -Method Post `
  -Uri "http://127.0.0.1:8000/api/v1/campbell-ai/message" `
  -Headers $headers `
  -ContentType "application/json" `
  -Body $messageBody
```

Un `401` indica que el token interno no coincide; un `403`, que el usuario no tiene acceso a la
empresa; y un `503`, que falta configuración, acceso a datos o disponibilidad de una dependencia.

## Lanzar API y Dash en local

1. Mantener la API ejecutándose en la primera terminal.
2. Abrir una segunda terminal en la raíz del repositorio y activar el mismo entorno.
3. Iniciar Dash cargando `.env` en el proceso:

```powershell
.\.venv\Scripts\Activate.ps1
python -m dotenv run -- python -m dashboard.app
```

Abrir `http://127.0.0.1:8050`, iniciar sesión y seleccionar **Campbell AI**. En `.env`, Dash debe
usar `CAMPBELL_AI_API_URL=http://127.0.0.1:8000` y exactamente el mismo token que la API.

No basta con que algunas configuraciones de Pydantic lean `.env`: el cliente Campbell y su feature
flag usan variables del proceso. Por eso el comando local de Dash se ejecuta mediante
`python -m dotenv run`.

## Lanzar con Docker Compose

```powershell
docker compose up --build -d
docker compose ps
docker compose logs -f campbell-api dashboard
```

El dashboard queda publicado en `http://127.0.0.1:8050`. En Compose, FastAPI escucha en el puerto
8000 de la red interna y Dash la consume mediante `http://campbell-api:8000`; el puerto 8000 no se
publica en el host por diseño.

Verificación del health desde el contenedor:

```powershell
docker exec campbell-ai-api curl -f `
  http://127.0.0.1:8000/api/v1/campbell-ai/health
```

Para detener ambos servicios:

```powershell
docker compose down
```

## Endpoints

| Método | Ruta | Propósito |
|---|---|---|
| `GET` | `/api/v1/campbell-ai/health` | Salud básica; no requiere token. |
| `GET` | `/api/v1/campbell-ai/capabilities` | Capacidades habilitadas. |
| `POST` | `/api/v1/campbell-ai/initialize` | Inicializa o recupera una sesión. |
| `POST` | `/api/v1/campbell-ai/message` | Procesa una pregunta y devuelve texto, figuras y el historial actualizado. |
| `POST` | `/api/v1/campbell-ai/history` | Recupera el historial vigente. |
| `POST` | `/api/v1/campbell-ai/conversations` | Lista las conversaciones respaldadas del usuario para la empresa activa. |
| `POST` | `/api/v1/campbell-ai/conversations/open` | Reabre una conversación respaldada y la deja activa. |
| `POST` | `/api/v1/campbell-ai/feedback` | Registra valoración positiva o negativa y, opcionalmente, un comentario escrito. |
| `DELETE` | `/api/v1/campbell-ai/clear` | Limpia la conversación. |

Todos salvo `health` requieren `X-Campbell-Token`. Cada operación de sesión vuelve a validar el
usuario y `company_id` contra los permisos del dashboard.

Códigos de estado que el consumidor debe distinguir: `401` credencial interna o usuario inexistente,
`403` empresa no autorizada, `422` sesión inválida, `429` **servicio ocupado** (trae `Retry-After`; no
es una falla, la misma consulta funciona al reintentar) y `503` falta configuración o datos.

`message` devuelve el historial completo en `messages`, por lo que un consumidor no necesita
encadenar `history` tras cada envío. Dash solo llama a `initialize` cuando aún no tiene sesión, de
modo que un mensaje en una conversación en curso cuesta una sola llamada.

El login genera una prueba de identidad firmada y temporal que la navegación entrega a Campbell
mediante su store en memoria. Esto permite validar al usuario aunque una solicitud dinámica de Dash
no incluya la cookie Flask, sin confiar en un nombre de usuario manipulable. La prueba no contiene
contraseñas ni claves de OpenAI, y FastAPI vuelve a comprobar los permisos de empresa.

### Por qué existe el token interno

El token autentica al servicio consumidor —actualmente Dash— frente a FastAPI; no reemplaza el
login del usuario. Evita que otro proceso de la red invoque la API declarando arbitrariamente un
usuario en el JSON. Debe ser aleatorio, independiente de `OPENAI_API_KEY` y administrarse como
secreto en producción.

## Alcance funcional actual

El perfil incluye Gatekeeper, Head Maintenance, Planner, Data Analyst Query, Data Visualization
Analyst, Technical Expert y Dashboard Navigation Guide. También incluye feedback y análisis de 5
porqués.

El agente Dashboard Navigation Guide orienta al usuario sobre en qué sección del menú lateral
encontrar algo (Resumen, Monitoreo, Predictivo, Campbell AI, Integración, Reportes,
Administración). Su prompt (`prompts/dashboard_guide.md`) solo describe el mapa de navegación
visible en la interfaz; no incluye rutas de archivos, esquemas de datos ni secretos.

### Herramientas de datos

El analista consulta las fuentes del dashboard mediante herramientas explícitas; no ejecuta Python
arbitrario. La cobertura va del nivel flota al detalle, que es lo que permite responder "qué
componente", "qué señal" y "cuánto valió".

| Herramienta | Fuente | Entrega |
|---|---|---|
| `inspect_available_data` | catálogo | Fuentes disponibles, columnas y qué herramienta lee cada una. |
| `inspect_dataset` | catálogo | Esquema de una fuente y **los valores reales que admite cada filtro**. Es la herramienta de recuperación tras un error. |
| `describe_signals` | catálogo | Nombre oficial de una señal de telemetría; declara que no hay unidad de medida. |
| `query_alerts` | `consolidated_alerts.csv` | Totales, ventana, distribuciones por equipo, sistema, subsistema, componente, tipo y variable disparadora, desglose mensual. |
| `query_alert_detail` | `alerts_detail_wide_with_gps.csv` | Por alerta y señal: valor pico, mínimo, promedio, umbral aplicable, muestras fuera de límite y estados de máquina. |
| `query_maintenance` | `query_3_actions_all_equipment.parquet` | Acciones con filtros por equipo, sistema, componente, tipo y ventana. |
| `query_maintenance_summary` | `Resumen_Semanal_Completo.csv` | Resumen semanal redactado por equipo. |
| `query_oil_status` | `oil/machine_status.parquet` | Una fila por equipo con su muestra más reciente y distribución por estado. |
| `query_oil_components` | `oil/classified.parquet` | Condición por componente con ensayos fuera de límite, valor, umbral y severidad. |
| `query_telemetry_health` | `telemetry/machine_status.parquet` | Condición por equipo, solo la última semana evaluada salvo que se pida historial. |
| `query_telemetry_components` | `telemetry/classified.parquet` | Condición por componente y las señales que la disparan. |
| `query_predictive_risk` | `predictive/motor.csv`, `transmision.csv` | Ranking, banda de salud y modos de riesgo dominantes. |

### Cuando el servicio no está disponible

Un fallo de la API mostraba una sola línea sin salida ("No fue posible conectar con la API de
Campbell AI") con el compositor habilitado, así que la única opción del usuario era repetir la acción
que falla y perder la consulta que había escrito.

Ahora el cliente clasifica la causa y la vista actúa según ella:

| Causa | Badge | Reintento | Compositor |
|---|---|---|---|
| `unreachable` — servicio caído | Servicio caído | Sí | Bloqueado |
| `timeout` — tardó demasiado | Tiempo excedido | Sí | Habilitado |
| `busy` — servicio saturado (429) | Servicio ocupado | Sí | Habilitado |
| `unavailable` — datos faltantes (503) | Datos no disponibles | Sí | Habilitado |
| `server_error` — error interno (5xx) | Error del servicio | Sí | Bloqueado |
| `credentials` / `not_configured` — token | Mal configurado / Sin configurar | No | Bloqueado |
| `forbidden` — sin permisos (403) | Sin acceso | No | Habilitado |
| `invalid_request` — 422 | Solicitud inválida | No | Habilitado |

Cada caso trae una guía distinta, porque el usuario no puede arreglar un problema de despliegue pero
sí necesita saber si esperar sirve o hay que avisar a alguien. Las causas que no pueden responderse
bloquean el compositor en lugar de invitar a repetir la acción, y el área de conversación explica la
situación aclarando que **el resto del dashboard sigue funcionando**, en vez de quedar en blanco como
si la página estuviera rota.

La consulta que falló se conserva y el botón de reintento la reenvía, así que no hay que reescribirla.
Todo esto pasa por un único `campbell-ai-failure-store`: antes el texto de error se construía en seis
lugares distintos.

### Errores accionables y autocorrección

Un fallo de herramienta antes devolvía `"Fuente no disponible para el cliente activo"` sin importar
qué había pasado. Ese mensaje suele ser **falso** —la fuente existe y el argumento estaba mal— y no
deja salida: el agente abandona la pregunta o inventa la respuesta. Ambas cosas son peores que el
error real.

Ahora un fallo devuelve el motivo exacto más la vía de recuperación:

```json
{
  "ok": false,
  "tool": "query_alerts",
  "error": "CampbellDataError",
  "detail": "start_date no tiene un formato de fecha válido",
  "recovery": {
    "retry_allowed": true,
    "inspect_with": "inspect_dataset(dataset=\"alerts\")",
    "hint": "Revisa columnas y valores permitidos, corrige y reintenta una sola vez…"
  }
}
```

Tres clases de fallo, con tratamiento distinto:

| Clase | `retry_allowed` | Comportamiento esperado |
|---|---|---|
| Argumento inválido (fecha, dimensión, dominio, valor de filtro) | `true` | Inspeccionar el esquema, corregir y reintentar **una** vez. |
| Fuente inexistente o módulo no habilitado para el cliente | `false` | Informar la limitación; reintentar sería inútil e invita a inventar. |
| Error interno inesperado | `false` | Se registra con traza en el log; al agente se le da un mensaje genérico sin filtrar rutas ni detalles de implementación. |

Los mensajes de dominio están escritos para el agente y se pasan tal cual —normalmente ya nombran
las opciones válidas ("Dimensión 'x' no disponible. Disponibles: component, system, unit")— después
de pasar por un sanitizador que elimina cualquier fragmento con forma de ruta, porque estos textos
ahora llegan al modelo.

`inspect_dataset(dataset="alerts")` devuelve, por cada parámetro de filtro, los valores que la
columna realmente contiene. Ese es el paso de "consultar los nombres antes de reintentar": el agente
lee el vocabulario real en lugar de adivinar otra vez. `DATASET_FILTERS` declara esa correspondencia
una sola vez, y un test verifica que ninguna fuente con herramienta de consulta se quede sin filtros
declarados.

Comportamiento observado en vivo:

| Pregunta | Resultado |
|---|---|
| "alertas del **sistema** de Refrigeración" | Cero como sistema → consultó el esquema → la resolvió como **subsistema**: 10 alertas en T_18. |
| "alertas del sistema de Neumáticos" | Informó que no existe y listó los sistemas reales (Motor, Frenos, Tren de Fuerza, Dirección). |
| "alertas del equipo T_99" | Informó que el identificador no existe y listó los equipos con alertas. |
| "gráfico de alertas por marca de neumático" | Rechazó la dimensión y ofreció las válidas. |

### Cobertura de datos por empresa

Las empresas no tienen las mismas técnicas. En los datos actuales:

| Cliente | Alertas | Detalle de señal | Mantenimiento | Aceite | Telemetría | Predictivo |
|---|---|---|---|---|---|---|
| CDA | sí | sí | sí | sí | sí | motor y transmisión |
| EMIN | sí | — | sí | sí | — | — |
| ENEX | — | — | — | sí | — | — |
| CAPSTONE | sí | sí | — | sí | — | solo motor |

Asumir el catálogo de CDA lleva a prometer análisis que no pueden ejecutarse, así que
`ANALYSIS_CAPABILITIES` declara qué fuentes necesita cada tipo de análisis y
`client_capabilities()` resuelve, por cliente, qué es posible y **por qué** el resto no:
falta una fuente, o el módulo no está habilitado — son motivos distintos y se informan distinto.

Se expone por tres vías: el campo `capabilities` de `initialize`, la herramienta
`client_capabilities` del agente, y el filtro que ya aplicaba `list_charts`. Los prompts instruyen
consultarla antes de un análisis multi-fuente y, ante una técnica ausente, informar la limitación
con su motivo y ofrecer la alternativa más cercana, sin sustituirla por otra fuente.

Comportamiento observado en vivo:

| Cliente | Pregunta | Respuesta |
|---|---|---|
| EMIN | "¿qué componentes están anormales en telemetría?" | Informa que la empresa no tiene telemetría por componentes y ofrece alertas, mantenimiento y aceite. |
| EMIN | "ranking de riesgo predictivo" | Informa que el módulo predictivo no está habilitado para el cliente. |
| ENEX | "panorama con todo lo que tengas" | Declara que solo hay aceite y entrega los **208 equipos** evaluados por esa técnica. |

### Trazabilidad de cifras (requisito duro)

Toda cifra que el agente escribe debe provenir de una consulta a los datos, nunca del modelo. Los
prompts solos no lo garantizan: una cifra fluida y verosímil es exactamente lo que produce un LLM
cuando no tiene el dato. Por eso `grounding.py` cierra el ciclo: guarda la salida de **cada**
herramienta ejecutada en el turno y, al terminar, extrae los números de la respuesta y verifica que
cada uno aparezca en esa evidencia.

Es un **detector, no un filtro**. Reporta, no reescribe: borrar en silencio una cifra de un
diagnóstico de mantenimiento es peor que exponer que no está verificada.

`message` (y el evento `done` del streaming) devuelven un campo `grounding`:

| Campo | Significado |
|---|---|
| `verified` | Cifras que se rastrearon hasta un resultado de herramienta. |
| `unverified_numbers` | Cifras sin origen en los datos. **Falla la puerta de calidad.** |
| `invented_units` | Unidades de medida escritas por el modelo. **Falla la puerta.** |
| `derived_without_basis` | Derivables de cifras reales mediante aritmética que la respuesta no mostró. Aviso, no falla. |
| `is_grounded` | Falso si hubo cifras sin origen o unidades inventadas. |

Se aceptan derivaciones cuyas entradas están en los datos, porque calcular no es inventar:
redondeos (`100.917` → `100.92`), separadores de miles, porcentajes sobre un par real
(`20` de `21` → `95%`), diferencias, sumas y componentes de fecha (`2026-07-09` → `9 de julio`).
La notación `1.247` es ambigua entre decimal y separador de miles, así que se conservan ambas
lecturas y basta que una coincida: un auditor con falsos positivos es un auditor que se ignora.

**Sobre unidades de medida:** ningún dataset de este repositorio publica la unidad de una señal, así
que no hay nada que leer. Un agente que escribe "°C" o "kPa" está afirmando conocimiento del modelo
como si fuera una medición, y una unidad equivocada convierte una lectura correcta en un diagnóstico
incorrecto. La regla es absoluta y el auditor reporta cualquier ocurrencia. Si las unidades llegan
desde el pipeline de datos, se agregan a `src/charts/signals.py` y los agentes podrán citarlas.

Para el **nombre** de una señal existe `describe_signals`, que lee el catálogo de
`src/charts/signals.py` (el mismo que rotula los gráficos del dashboard) y declara explícitamente
`unit: null`. El agente no traduce códigos por su cuenta.

Medición sobre la suite completa (29 casos, versión 1.1.0): **485 cifras verificadas contra los
datos, 0 sin origen, 0 unidades inventadas**. Un control negativo con preguntas que invitan a inventar confirmó el
comportamiento: preguntado "¿a cuántos grados centígrados llegó…?" el agente respondió el valor sin
unidad; una pregunta por costos fue bloqueada por estar fuera de dominio; y al interpretar la
categoría `oil_hour_range: LT_1000` como "1000 horas" el auditor marcó la cifra, porque el código
existe en los datos pero su equivalencia en horas la puso el modelo.

Notas de contrato que evitan conclusiones incorrectas:

- Las ventanas relativas se anclan en la fecha máxima de **cada** fuente, no en hoy, y la respuesta
  incluye `window.source_coverage` para advertir cuando dos fuentes terminan en fechas distintas.
- Los filtros de texto ignoran mayúsculas y acentos; cuando un filtro deja el resultado vacío, la
  respuesta incluye `filter_hints` con los valores que sí existen.
- Los identificadores de equipo se normalizan entre técnicas (`T_9`, `T_09`, `T9`).
- El identificador de unión con el detalle de alertas es `TelemetryID` y solo es único dentro de un
  equipo; `FusionID` también se acepta y se traduce.
- Si un modelo predictivo no publica ranking, la respuesta lo declara (`ranking_available: false`)
  en lugar de dejar que el agente sustituya la fuente.

### Visualizaciones

Las figuras Plotly se construyen desde una gramática segura de datasets, dimensiones y operaciones;
el modelo no ejecuta Python arbitrario. Las fuentes son `alerts`, `maintenance_actions`,
`maintenance_summary`, `oil_machine_status`, `oil_components`, `telemetry_machine_status` y
`telemetry_components`, con ventanas relativas o fechas ISO explícitas. Los ejemplos para los
agentes están en `prompts/data_analyst_query.md` y `prompts/data_analyst_visualization.md`.

El vocabulario de tipos se declara una sola vez en `src/charts/__init__.py`, para que la gramática,
el modelo de respuesta y el endpoint de capacidades no puedan discrepar:

| Familia | Tipos | Cómo se usan |
|---|---|---|
| Agregados por categoría | `bar`, `horizontal_bar`, `line`, `area`, `pie`, `pareto`, `treemap`, `heatmap`, `stacked_bar` | `dimension` agrupa; `metric` + `aggregation` opcionales |
| A nivel de registro | `histogram`, `box`, `scatter` | Grafican valores individuales; exigen una `metric` numérica, no `count` |
| Solo catálogo | `radar`, `gauge` | Requieren una forma de datos curada |

Los de nivel de registro no agregan, así que su etiqueta de eje **no** dice "Promedio de…": decirlo
sería describir una operación que no ocurrió. El histograma no acepta `dimension` (bina la métrica) y
el scatter reutiliza `secondary_dimension` para nombrar su segunda métrica; ambos rechazan la llamada
con el motivo exacto en lugar de ignorar el argumento en silencio.

Una respuesta puede incluir **más de una figura** cuando la pregunta realmente pide varias
distintas ("muéstrame el estado de la flota y también el ranking de alertas"): los prompts del
Head y del Data Visualization Analyst instruyen llamar a la herramienta de construcción una vez
por figura en lugar de comprimir varias peticiones en una sola llamada, y el presupuesto de
turnos del analista de visualización se amplió de 5 a 8 para dar espacio a esas llamadas
adicionales.

Además de esa gramática existe un **catálogo de gráficos con nombre** en `chart_registry.py`, que
reproduce vistas concretas del dashboard. El agente lo consulta con `list_dashboard_charts()` y lo
renderiza con `render_dashboard_chart(chart_id, ...)`, de modo que "muéstrame el estado de la flota"
entrega la misma figura que el usuario ve en su pestaña en lugar de una aproximación.

| `chart_id` | Tipo | Dominio | Parámetros |
|---|---|---|---|
| `oil_fleet_status` | donut | aceite | — |
| `oil_component_status` | barras apiladas | aceite | — |
| `oil_essay_radar` | radar | aceite | `unit_id`, `component` |
| `oil_severity_histogram` | histograma | aceite | — |
| `telemetry_fleet_status` | donut | telemetría | — |
| `telemetry_component_status` | barras apiladas | telemetría | — |
| `telemetry_component_heatmap` | mapa de calor | telemetría | — |
| `unit_health_gauge` | indicador | telemetría | `unit_id` |
| `alert_ranking` | barras | alertas | `days`, `top_n` |
| `alert_trend` | serie temporal | alertas | `days` |
| `alert_trigger_treemap` | treemap | alertas | `days` |
| `alert_sensor_trend` | series por señal | alertas | `unit_id`, `alert_id`, `signal` |
| `predictive_motor_ranking` | barras | predictivo | `top_n` |
| `predictive_risk_radar` | radar | predictivo | `unit_id`, `domain` |

**Radar e indicador solo existen en el catálogo.** Requieren una forma de datos curada —ensayos
contra sus umbrales, modos de falla contra la mediana de la flota— que la gramática libre no puede
armar a partir de dataset × dimensión.

El radar de aceite normaliza cada eje como valor ÷ umbral de alerta, porque los ensayos viven en
escalas incomparables (hierro en decenas, zinc en miles) y un radar con ejes crudos es ilegible. El
resumen conserva los valores absolutos y sus umbrales, así que el agente cita mediciones, no
proporciones. Si no se indica `component`, elige el **de peor condición** y lo declara en
`component_selected_by`, en lugar de tomar una muestra arbitraria y describirla como otra.

`alert_sensor_trend` reemplaza el gráfico de sensores por alerta del dashboard anterior: un panel por
señal, con su banda de límites y el eje temporal compartido. La pregunta abierta era cómo elige el
agente qué señales graficar; la respuesta es que **por defecto usa la señal disparadora** —la que
originó la alerta— y `query_alert_signals` reporta qué otras tienen valores capturados para que la
elección sea informada. Una columna con límites pero sin lecturas no genera panel, y pedir una señal
inexistente falla indicando las disponibles en vez de graficar otra. Los códigos se resuelven sin
distinguir mayúsculas, porque un desliz de transcripción abortaba el gráfico completo.

**El umbral depende del estado de máquina.** Un equipo en ralentí tiene un techo menor que uno en
operación, así que `query_alert_detail` compara **cada muestra contra su propio umbral** y reporta
`upper_limit_values`, `upper_limit_at_peak` y `state_at_peak`. Colapsar la columna a su máximo
reportaba cero excedencias en alertas que sí superaron su límite de ralentí: la diferencia entre
"no pasó nada" y "excedió el umbral 10 veces".

`chart_id` y parámetros se validan contra listas explícitas: un id desconocido, un parámetro no
declarado o un módulo no habilitado para el cliente se rechazan, y los valores numéricos se acotan a
un rango usable. Nunca se evalúa un nombre de función, una expresión ni código generado por el
modelo. El catálogo solo ofrece gráficos cuyos datasets existen y están válidos para el cliente
activo, así que EMIN no ve entradas de telemetría ni predictivo.

### Capa de gráficos compartida

`src/charts/` es la fuente única del aspecto visual y vive fuera de `dashboard/` para que FastAPI no
dependa de Dash:

- `theme.py`: paleta, tipografía, ejes y el lenguaje de estados (`Normal`, `Alerta`, `Anormal`,
  `Insuficiente`). `dashboard/components/charts.py` reexporta `STATUS_COLORS` desde aquí, así que
  las pestañas y el chat coinciden en qué color es cada estado.
- `builders.py`: funciones puras que reciben datos y devuelven `plotly.graph_objects.Figure`. Tanto
  la gramática libre como el catálogo construyen sus figuras con estos builders, así que un cambio
  de estilo se aplica en un solo lugar.

Las fuentes que se reevalúan periódicamente se reducen a su última evaluación por equipo, para no
acumular semanas históricas en un gráfico de condición actual.

Pendiente: `telemetry_charts.py` y `tab_predictive_evidence.py` todavía definen su propia paleta de
estados, distinta de la compartida. Unificarlas cambia el aspecto de esas pestañas, por lo que es
una decisión visual separada de esta migración.

Siguen deshabilitados reportes, PDF, tablas capturadas, exportaciones, descargas y archivos.

### Sesiones y escalamiento horizontal

La memoria conversacional vive detrás de `sessions.py`, que ofrece dos backends con el mismo
contrato: escrituras atómicas por sesión y expiración por inactividad.

| `CAMPBELL_AI_SESSION_BACKEND` | Uso |
|---|---|
| `memory` (por defecto) | Estado local al proceso. Válido **solo con un worker**. |
| `redis` | Estado compartido; cualquier worker o réplica atiende la misma conversación. |

Con `redis` hay que definir `CAMPBELL_AI_REDIS_URL` e instalar el paquete `redis`. Si el backend es
`redis` sin URL, el servicio falla al arrancar en lugar de degradar silenciosamente a memoria: ese
fallback reintroduciría justamente el problema que el store resuelve.

El candado de sesión se mantiene durante toda la ejecución de los agentes, así que
`CAMPBELL_AI_SESSION_LOCK_TIMEOUT_SECONDS` debe superar la respuesta más lenta esperada. Una
segunda consulta sobre la misma sesión espera su turno; si el candado no se libera dentro del
plazo, la solicitud recibe un error explícito en vez de intercalarse.

`health` y `capabilities` publican `session_backend`, de modo que un despliegue puede verificar que
no está corriendo varios workers sobre el store local.

### Persistencia e historial por usuario

El store de sesiones expira las conversaciones y, con el backend `memory`, vive en un solo proceso.
Eso es correcto para la memoria conversacional y **no sirve como respaldo**: un reinicio, un TTL
vencido o un cambio de pestaña se llevaban la conversación. `persistence.py` mantiene la copia
durable en el bucket que el dashboard ya usa, bajo una carpeta propia:

```
campbellAI/
  conversations/<empresa>/<usuario>/index.json
  conversations/<empresa>/<usuario>/<sesion>/conversation.json
  conversations/<empresa>/<usuario>/<sesion>/batches/<n_mensajes>.json
  logs/feedback/<empresa>/<usuario>/<fecha>/<sesion>__<mensaje>__<tipo>.json
```

Tres decisiones que no son las obvias:

- **Los mensajes se escriben por lote, no un objeto por mensaje.** Cada interacción escribe un
  objeto pequeño con lo nuevo desde el último respaldo, más el snapshot completo. Si falla el
  snapshot, el intercambio sobrevive en su lote; y como la clave del lote se deriva del número de
  mensajes —que solo crece— un reintento **sobrescribe** en vez de duplicar la conversación.
- **El índice por usuario es un objeto real.** Listar leyendo cada `conversation.json` cuesta un GET
  por sesión y la barra lateral se degradaría con cada conversación nueva. Un índice responde el
  listado con un solo GET, y si se pierde se reconstruye recorriendo el prefijo.
- **Nada de esto puede romper una conversación.** El respaldo es un efecto secundario de responder:
  cada llamada al almacenamiento está contenida, los fallos se registran y cuentan, el espejo local
  sigue escribiendo y el usuario recibe su respuesta igual. Las escrituras van a un hilo para no
  bloquear el event loop y, en el camino bloqueante, ocurren **fuera del candado de sesión**, así que
  un respaldo lento no retrasa la siguiente pregunta de esa conversación.

Las claves se derivan siempre del principal autenticado, nunca de la entrada del cliente, así que la
carpeta de un usuario es inalcanzable desde la sesión de otro. Los segmentos se normalizan: un
`../` en un nombre no produce una clave que se salga del prefijo. Las **figuras Plotly se
respaldan diezmadas**: cada traza se reduce a un máximo de 300 puntos (`_downsample_figure`),
así que la figura que se reabre sigue siendo interactiva y conserva la forma de la serie, sin
guardar los cientos de miles de puntos originales — probar renderizarlas como imagen (kaleido)
resultó frágil en el entorno de despliegue, y el diezmado no depende de ningún binario externo.

**Recuperación.** `initialize` comprueba si la sesión viva está vacía y, en ese caso, restaura la
conversación archivada de ese mismo `session_id`, informando cuántos mensajes recuperó en
`restored_messages`. Verificado en vivo: tras matar y relanzar la API, `initialize` devolvió
`restored: 8` y `history` los ocho mensajes. Restaurar nunca sobrescribe un hilo vivo, porque la
sesión activa siempre es más reciente que el archivo.

**Título de la conversación.** El listado necesita una etiqueta reconocible; un `session_id` no dice
nada. Por defecto es el **primer mensaje del usuario** recortado —determinista y sin invención—. A
partir del segundo intercambio se genera además un **resumen con IA** (`summary.py`) que pasa a ser
la etiqueta visible, conservando el título original. El resumen se somete a la misma regla de
trazabilidad que cualquier respuesta: si contiene una cifra que no aparece en la conversación, se
descarta y queda el título. Un fallo del titulador no es un error; solo significa que manda el primer
mensaje.

**En la vista.** Un panel lateral (`dbc.Offcanvas`, desliza desde el borde de la pantalla en lugar
de empujar el chat hacia abajo) "Conversaciones anteriores" lista las conversaciones respaldadas
con su etiqueta, fecha y cantidad de mensajes; abrir una la deja activa, cierra el panel — elegir
una conversación es la intención de leerla, no de seguir explorando la lista — y se puede seguir
conversando en ella. La ventana de mensajes hace scroll automático al último mensaje tanto al
enviar uno como al cargar una conversación. "Nueva" abre un hilo vacío sin tocar el respaldo, y
"Limpiar" vacía el hilo visible **sin borrar** lo ya respaldado: vaciar la pantalla no es una
orden de eliminación.

**Al volver a la pestaña.** La conversación ya no desaparece. `campbell-ai-session-company` guarda,
junto al `session_id` en almacenamiento de sesión, a qué empresa pertenece el hilo. Antes el store de
empresa vivía en memoria y se vaciaba en cada montaje, así que volver a la pestaña se interpretaba
como un cambio de empresa y descartaba el hilo. Ahora un montaje sin empresa almacenada reutiliza la
sesión, y si el servicio no la tiene en memoria, la restaura desde el respaldo.

### Feedback: valoración y comentario

Las flechas registran dos eventos distintos —la valoración y, opcionalmente, el comentario escrito—
para que quien vota primero y explica después no vea su explicación descartada como duplicada. Cada
evento se escribe en el log local JSONL y se respalda en S3 como su propio objeto; una clave derivada
del evento hace que un reenvío se sobrescriba, en lugar de perder votos en un lectura-modificación-
escritura sobre un archivo compartido.

El cuadro de comentario aparece **solo después de votar**: preguntar el motivo antes de saber si la
respuesta sirvió es una pregunta sin contexto, y un campo de texto permanente en cada respuesta se
lee como una obligación.

Lo que deliberadamente **no** se guarda es la pregunta ni la respuesta. Una valoración es una opinión
sobre una respuesta; copiar la conversación a un log aparte duplicaría datos del cliente en una
segunda ruta de retención sin ganar nada.

### Concurrencia y usuarios en paralelo

Una respuesta ocupa un worker durante decenas de segundos y encadena varias llamadas al modelo, así
que bastan unos pocos usuarios simultáneos para agotar el event loop o la cuota. Sin un límite, el
modo de fallo es el peor: todas las consultas se degradan juntas hasta expirar, y nadie sabe si
esperar sirve.

`concurrency.py` acota la admisión en tres ejes, en el borde del servicio (los caminos bloqueante y
de streaming comparten los contadores):

| Eje | Defecto | Qué evita |
|---|---|---|
| Global | 10 simultáneas | Saturar el proceso y la cuota del modelo. |
| Por usuario | 2 simultáneas | Que una persona con varias pestañas ocupe todo el servicio. |
| Por minuto | 200 | Superar la cuota upstream en ráfagas. |

Una solicitud que no puede admitirse espera poco y luego falla rápido con `429` y `Retry-After`.
Fallar rápido es el punto: una cola sin límite convierte una sobrecarga en un timeout, y el usuario
no sabe si esperar. El límite por usuario **no espera**, porque encolarlo solo retrasaría una consulta
que ese usuario no está mirando mientras ocupa un cupo que otro sí necesita.

Dos consultas sobre la **misma** conversación siguen serializadas por el candado de sesión, ahora con
dos presupuestos distintos: la expiración de la llave supera la respuesta más lenta —para que nada se
intercale— mientras la **espera** es corta, de modo que la segunda pestaña recibe "la sesión está
ocupada" en vez de retener un worker durante minutos.

Del lado del modelo, `execute_with_retry` reintenta con backoff exponencial **solo** los fallos
transitorios (429, 5xx, timeouts, conexiones cortadas). Un error permanente —una columna inexistente—
se propaga en el primer intento: gastar tres llamadas al modelo en un error que no puede cambiar es
puro costo.

En el dashboard, `429` se clasifica como `busy`: badge "Servicio ocupado", guía que dice esperar unos
segundos, consulta conservada, botón de reintento y **compositor habilitado**, porque la misma
pregunta va a funcionar. `capabilities` publica la carga actual (`in_flight`, `peak_in_flight`,
`admitted`, `rejected`) sin identificar a nadie.

Comportamiento observado en vivo con tres consultas simultáneas del mismo usuario sobre una sesión:
dos respondieron `200` una tras otra y la tercera recibió `429` con `Retry-After: 5` y el mensaje
"Ya tienes una consulta de Campbell AI en curso; espera su respuesta antes de enviar otra".

### Streaming de respuestas

Con `CAMPBELL_AI_STREAMING=true` la API expone `POST /api/v1/campbell-ai/message/stream` como SSE.
Los eventos son:

| Evento | Contenido |
|---|---|
| `status` | Etapa en curso; incluye `detail` con la herramienta que está corriendo. |
| `delta` | Fragmento incremental del texto de la respuesta. |
| `done` | Respuesta final, `message_id`, figuras e historial actualizado. |
| `error` | Fallo posterior a la apertura del stream; el consumidor debe reintentar sin streaming. |

Un error anterior al primer evento se devuelve como estado HTTP normal (por ejemplo `503`), no como
un `200` con un evento de error dentro.

En el dashboard, `dashboard/campbell_ai/stream.py` publica un proxy same-origin en
`/campbell-ai/stream`. El navegador nunca conoce la URL ni el token interno de la API, y la
identidad se toma de la sesión firmada de Dash, no del cuerpo de la solicitud.
`dashboard/assets/campbell_ai_stream.js` va escribiendo el texto en una burbuja provisional y, al
recibir `done`, devuelve el control a Dash para el render definitivo con gráficos y controles de
feedback. Si el stream falla, el mensaje vuelve al camino bloqueante: la pregunta no se pierde.

**Qué mejora y qué no.** La mayor parte del tiempo se consume llamando herramientas antes de que
exista texto, así que los eventos `status` con el nombre del paso ("Consultando datos",
"Construyendo el gráfico") son los que realmente reducen la sensación de espera; el primer `delta`
puede tardar decenas de segundos. El primer mensaje de una conversación no usa streaming, porque el
navegador no puede crear la sesión.

**Compositor bloqueado durante toda la solicitud, en ambos caminos.** El compositor (input, botón
Enviar, Limpiar) se deshabilita mientras `campbell-ai-pending-message-store` tiene un mensaje en
curso, sin importar si termina por streaming o por el camino bloqueante — es la única fuente de
verdad para ese estado. Antes existían dos mecanismos separados escribiendo la misma propiedad
(el `running=[...]` de la llamada bloqueante y el gate de streaming), y podían competir: la
reactivación de uno llegaba al navegador después de la deshabilitación del otro, dejando el
compositor operable durante una respuesta todavía en curso — lo que permitía enviar un segundo
mensaje antes de que el primero terminara, y la respuesta tardía del primero (con su gráfico)
podía aparecer después de que el segundo ya estuviera en pantalla. Consolidar el bloqueo en un
único callback elimina la carrera.

## Pruebas

Las pruebas rápidas no consumen la API de OpenAI ni requieren secretos:

```powershell
python -m pytest tests/ -q
```

| Archivo | Cubre |
|---|---|
| `tests/test_campbell_ai.py` | Identidad, aislamiento, herramientas de datos, prompts y gráficos. |
| `tests/test_campbell_ai_api.py` | Contrato HTTP, token interno y streaming SSE. |
| `tests/test_campbell_ai_sessions.py` | Store de sesiones, serialización, TTL y candados. Los casos del backend Redis se omiten si el paquete `redis` no está instalado. |
| `tests/test_campbell_ai_charts.py` | Tema compartido, builders puros y catálogo con nombre. |
| `tests/test_campbell_ai_grounding.py` | Auditoría de trazabilidad numérica y catálogo de señales. |
| `tests/test_campbell_ai_recovery.py` | Esquema con vocabulario de filtros y errores accionables. |
| `tests/test_campbell_ai_chart_types.py` | Tipos de gráfico recuperados y formas curadas del catálogo. |
| `tests/test_campbell_ai_unavailable.py` | Clasificación de fallos de la API y degradación de la vista. |
| `tests/test_campbell_ai_coverage.py` | Capacidades por cliente y gráfico de señales por alerta. |
| `tests/test_campbell_ai_persistence.py` | Layout de claves, escritura por lotes, índice, aislamiento entre usuarios, restauración y respaldo de feedback. |
| `tests/test_campbell_ai_concurrency.py` | Límites global, por usuario y por minuto; reintentos transitorios; candado de sesión; `429` con `Retry-After`. |
| `tests/test_campbell_ai_ui.py` | Layout y callbacks de la vista Dash. |
| `tests/test_response_quality.py` | Lógica del evaluador de calidad (siempre) y la suite completa (opt-in). |

### Suite de calidad de respuesta

Las pruebas anteriores verifican que la capa de datos devuelva las filas correctas. Esa garantía no
dice nada sobre la **respuesta que lee el usuario**, y editar un prompt es la forma más fácil de
degradarla sin que nada falle. `tests/quality/` cubre justamente eso: 29 casos que ejecutan los
agentes reales y evalúan si la respuesta está fundamentada, completa y con el formato acordado.

Es opt-in porque consume la API de OpenAI (~10 minutos y costo real):

```powershell
python -m dotenv run -- python -m tests.quality.runner --client cda --report quality.json
```

Filtros útiles: `--case latest_alert`, `--tag graficos`, `--tag seguridad`, `--concurrency 4`.
Bajo pytest se habilita con `CAMPBELL_AI_QUALITY_SUITE=1`.

Conviene ejecutarla con `CAMPBELL_AI_PERSISTENCE=false`, para no dejar 29 conversaciones de prueba
en el respaldo del usuario con el que corre. El runner además ensancha el límite de admisión por
usuario al ancho del lote: todos los casos corren como el mismo usuario y, con el tope de dos,
`--concurrency 4` habría reportado como fallos consultas que solo estaban en cola.

Cada caso declara en `expectations.py` qué protege y qué debe cumplirse: tipo de respuesta,
menciones obligatorias, menciones prohibidas, negrita en los datos, declaración del periodo,
figuras esperadas por `chart_id` y, con `expect_grounded`, que **toda cifra de la respuesta sea
trazable a los datos y no aparezca ninguna unidad de medida**. Los valores factuales **se resuelven desde los datos vivos** (el
equipo con más alertas, la señal que dispara un componente anormal, el ensayo fuera de límite), de
modo que un refresco de datos no vuelve roja la suite por el motivo equivocado. Solo se fijan de
forma literal los comportamientos que deben cumplirse siempre: rechazos de alcance, aislamiento
multiempresa y bloqueo de prompt injection.

Ejecútala antes de integrar cualquier cambio de prompts. Tres regresiones reales se detectaron así:
un análisis de 5 porqués sin sección de causa raíz, negrita aplicada de forma intermitente, y una
cifra derivada de un código de categoría sin respaldo en los datos.

Los tests del evaluador (`test_response_quality.py`) sí corren siempre, así que un error en la
lógica de puntuación se detecta sin gastar tokens.

## Novedades de la versión 1.1.1–1.1.3

| Cambio | Dónde |
|---|---|
| Migración a la arquitectura de páginas de Dash (`dash.register_page`) | `dashboard/campbell_ai/` |
| Corrección de códigos de señal sin traducir en las respuestas del chat (`EngCoolTemp`, `AirFltr`, etc.) | `src/charts/signals.py`, `data.py`, `visualization.py` |
| Respaldo de figuras Plotly por diezmado (300 puntos por traza) en vez de omitirlas; se descartó una prueba con render a PNG (kaleido) por resultar frágil en el entorno de despliegue | `persistence._downsample_figure` |
| Panel "Conversaciones anteriores" es ahora exclusivamente un drawer lateral (`dbc.Offcanvas`); se retiró la variante inline (`dbc.Collapse`) que existía como alternativa | `dashboard/campbell_ai/layout.py` |
| Abrir una conversación cierra el panel lateral | `open_archived_conversation` |
| Scroll automático al último mensaje, tanto al enviar uno como al cargar una conversación | `campbell-ai-scroll-container`, callback clientside |
| Indicador de "Pensando…" visible por defecto en la burbuja de streaming (antes quedaba vacía hasta el primer delta o status) | `_streaming_placeholder` |
| El compositor se bloquea de forma confiable durante **toda** la solicitud, tanto en el camino de streaming como en el bloqueante, eliminando una condición de carrera que permitía enviar un segundo mensaje mientras el primero seguía en curso | `gate_composer` |
| Mayor flexibilidad para generar varias figuras en una misma respuesta cuando la pregunta lo pide | prompts del Head y del Data Visualization Analyst, presupuesto de turnos del analista de visualización (5 → 8) |
| Configuración reorganizada: solo `OPENAI_API_KEY` (y los secretos ya existentes del dashboard) siguen en `.env`; el resto de las variables de Campbell AI son valores por defecto declarados en el `Dockerfile`, no secretos | `Dockerfile`, `.env.example`, `docker-compose.yml` |
| Limpieza previa al primer despliegue a producción: código muerto, imports sin usar y tests redundantes retirados | ver commit de limpieza |

## Novedades de la versión 1.1.0

| Cambio | Dónde |
|---|---|
| Respaldo de cada interacción en S3 bajo `campbellAI/`, por empresa y usuario, con escritura por lotes | `persistence.py` |
| Restauración de la conversación tras expirar la sesión o reiniciar el servicio | `service.initialize`, `runtime.restore` |
| Historial navegable por usuario, con título del primer mensaje o resumen generado por IA | `persistence.py`, `summary.py`, panel "Conversaciones anteriores" |
| La conversación ya no desaparece al salir y volver a la pestaña | `campbell-ai-session-company` |
| Valoración y comentario escrito como eventos separados, ambos respaldados | `feedback.py`, `_feedback_comment_box` |
| Control de admisión global, por usuario y por minuto, con `429` + `Retry-After` | `concurrency.py`, `api._translate_error` |
| Reintento con backoff de fallos transitorios del modelo | `concurrency.execute_with_retry` |
| Candado de sesión con espera acotada: la segunda pestaña recibe "ocupada" en vez de retener un worker | `sessions.py` |
| Corrección: `synchronize_chat` declaraba un parámetro sin su `State`, por lo que el reintento fallaba | `dashboard/campbell_ai/callbacks.py` |

Verificado en vivo contra el bucket configurado y la API en ejecución: escritura y lectura de los
objetos bajo `campbellAI/`, listado y reapertura de una conversación, valoración más comentario,
restauración de ocho mensajes tras reiniciar el proceso, y `429` con `Retry-After` en la tercera
consulta simultánea de un mismo usuario. Los objetos de esa verificación se eliminaron del bucket.

Sin cambios en el alcance excluido: siguen deshabilitados reportes, PDF, tablas capturadas,
exportaciones, descargas y archivos.
