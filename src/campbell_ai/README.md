# Campbell AI

Esta carpeta contiene la API FastAPI y la lógica multiagente de Campbell AI. Reutiliza
`config/users.py` para identidad y permisos, y lee directamente la estructura `data/` del
dashboard; no descarga ni copia datos.

Los prompts versionados viven en `src/campbell_ai/prompts/`. Incluyen Gatekeeper, Head
Maintenance, Planner, Data Analyst Query, Data Analyst Visualization, Technical Expert y la
metodología de 5 porqués. La construcción de agentes los carga mediante `prompts.py`.

## Arranque local

Instalar las dependencias de `requirements.txt`. Después, desde la raíz del dashboard, iniciar la
API en una terminal:

```powershell
$env:OPENAI_API_KEY="..."
$env:CAMPBELL_AI_INTERNAL_TOKEN="..."
$env:CAMPBELL_AI_DATA_ROOT="C:\ruta\tds_alerts_dashboard\data"
uvicorn src.campbell_ai.api:app --host 0.0.0.0 --port 8000
```

El dashboard debe usar el mismo `CAMPBELL_AI_INTERNAL_TOKEN`. En otra terminal:

```powershell
$env:CAMPBELL_AI_ENABLED="true"
$env:CAMPBELL_AI_API_URL="http://127.0.0.1:8000"
$env:CAMPBELL_AI_INTERNAL_TOKEN="..."
python dashboard/app.py
```

`SECRET_KEY` debe ser robusto y compartido por todas las réplicas Dash. En HTTPS también debe
configurarse `SESSION_COOKIE_SECURE=true`.

Como alternativa, `docker compose up --build` levanta ambos procesos. Compose exige
`CAMPBELL_AI_INTERNAL_TOKEN` y monta `data/` en `/app/data` como solo lectura. El feedback se
guarda, sin copiar pregunta ni respuesta, en `logs/campbell_ai_feedback.jsonl`.

## Endpoints

- `GET /api/v1/campbell-ai/health`
- `GET /api/v1/campbell-ai/capabilities`
- `POST /api/v1/campbell-ai/initialize`
- `POST /api/v1/campbell-ai/message`
- `POST /api/v1/campbell-ai/history`
- `POST /api/v1/campbell-ai/feedback`
- `DELETE /api/v1/campbell-ai/clear`

Todos salvo health requieren `X-Campbell-Token`. El usuario y cliente de cada request vuelven a
validarse contra los permisos del dashboard.

### Por qué existe el token interno

El token autentica al servicio consumidor (Dash) frente a FastAPI; no reemplaza el login del
usuario. Sin esta credencial, cualquier proceso con acceso a la red interna podría enviar un
nombre de usuario en el JSON e intentar suplantarlo. Debe ser un secreto aleatorio independiente
de `OPENAI_API_KEY`, compartido solo por Dash y FastAPI y administrado mediante variables o el
gestor de secretos del entorno.

La memoria conversacional es local al proceso FastAPI y expira por defecto tras 30 minutos. Una
ejecución con múltiples workers debe reemplazarla por un store compartido antes de escalar
horizontalmente.

## Alcance

El perfil permite consultas de datos, análisis técnico, gráficos Plotly dentro del chat, feedback
y 5 porqués. Las figuras se construyen mediante datasets, dimensiones y tipos permitidos; el LLM
no ejecuta código arbitrario. No se registran funciones de reportes, PDF, tablas capturadas,
exportaciones, descargas o archivos.

Las visualizaciones soportan barras, líneas temporales, pie, Pareto, mapas de calor y barras
apiladas. Las consultas de alertas y mantenimiento aceptan ventanas relativas (`days`) o fechas
ISO explícitas (`start_date`, `end_date`). El agente dispone de ejemplos ejecutables en
`prompts/data_analyst_query.md` y `prompts/data_analyst_visualization.md`.
