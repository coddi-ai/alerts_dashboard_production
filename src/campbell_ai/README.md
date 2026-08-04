# Campbell AI

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
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copiar el valor generado en `CAMPBELL_AI_INTERNAL_TOKEN` dentro de `.env`. Configurar también
`OPENAI_API_KEY`, una `SECRET_KEY` distinta y, si los datos están fuera del repositorio, su ruta
real en `CAMPBELL_AI_DATA_ROOT`. El archivo `.env` está ignorado por Git y no debe compartirse.

Variables esenciales:

| Variable | Uso |
|---|---|
| `OPENAI_API_KEY` | Acceso del runtime de agentes a OpenAI. |
| `CAMPBELL_AI_INTERNAL_TOKEN` | Autentica a Dash u otro servicio frente a FastAPI. |
| `CAMPBELL_AI_DATA_ROOT` | Directorio existente con los datos del dashboard; no se importan. |
| `CAMPBELL_AI_API_URL` | URL que Dash usa para llamar a FastAPI. |
| `CAMPBELL_AI_ENABLED` | Habilita u oculta Campbell AI. |
| `SECRET_KEY` | Firma la sesión autenticada de Dash. |
| `DASHBOARD_IDENTITY_MAX_AGE_SECONDS` | Vigencia de la prueba firmada de identidad; 12 horas por defecto. |

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
| `POST` | `/api/v1/campbell-ai/feedback` | Registra valoración positiva o negativa. |
| `DELETE` | `/api/v1/campbell-ai/clear` | Limpia la conversación. |

Todos salvo `health` requieren `X-Campbell-Token`. Cada operación de sesión vuelve a validar el
usuario y `company_id` contra los permisos del dashboard.

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

Medición sobre la suite completa: **257 cifras verificadas contra los datos, 0 sin origen, 0
unidades inventadas**. Un control negativo con preguntas que invitan a inventar confirmó el
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
el modelo no ejecuta Python arbitrario. Se admiten barras, líneas, pie, Pareto, mapas de calor y
barras apiladas sobre `alerts`, `maintenance_actions`, `maintenance_summary`, `oil_machine_status`,
`oil_components`, `telemetry_machine_status` y `telemetry_components`, junto con ventanas relativas
o fechas ISO explícitas. Los ejemplos para los agentes están en `prompts/data_analyst_query.md` y
`prompts/data_analyst_visualization.md`.

Además de esa gramática existe un **catálogo de gráficos con nombre** en `chart_registry.py`, que
reproduce vistas concretas del dashboard. El agente lo consulta con `list_dashboard_charts()` y lo
renderiza con `render_dashboard_chart(chart_id, ...)`, de modo que "muéstrame el estado de la flota"
entrega la misma figura que el usuario ve en su pestaña en lugar de una aproximación.

| `chart_id` | Dominio | Fuente |
|---|---|---|
| `oil_fleet_status` | aceite | `oil/machine_status` |
| `oil_component_status` | aceite | `oil/classified` |
| `telemetry_fleet_status` | telemetría | `telemetry/machine_status` |
| `telemetry_component_status` | telemetría | `telemetry/classified` |
| `alert_ranking` | alertas | `consolidated_alerts` |
| `predictive_motor_ranking` | predictivo | `predictive/motor` |

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
| `tests/test_campbell_ai_ui.py` | Layout y callbacks de la vista Dash. |
| `tests/test_response_quality.py` | Lógica del evaluador de calidad (siempre) y la suite completa (opt-in). |

### Suite de calidad de respuesta

Las pruebas anteriores verifican que la capa de datos devuelva las filas correctas. Esa garantía no
dice nada sobre la **respuesta que lee el usuario**, y editar un prompt es la forma más fácil de
degradarla sin que nada falle. `tests/quality/` cubre justamente eso: 22 casos que ejecutan los
agentes reales y evalúan si la respuesta está fundamentada, completa y con el formato acordado.

Es opt-in porque consume la API de OpenAI (~10 minutos y costo real):

```powershell
python -m dotenv run -- python -m tests.quality.runner --client cda --report quality.json
```

Filtros útiles: `--case latest_alert`, `--tag graficos`, `--tag seguridad`, `--concurrency 4`.
Bajo pytest se habilita con `CAMPBELL_AI_QUALITY_SUITE=1`.

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
