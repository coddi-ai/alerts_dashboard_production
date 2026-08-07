FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

RUN mkdir -p logs

EXPOSE 8050
EXPOSE 8000

ENV PYTHONUNBUFFERED=1
ENV DASHBOARD_HOST=0.0.0.0
ENV DASHBOARD_PORT=8050

# Campbell AI — operational defaults, not secrets. Real credentials (OPENAI_API_KEY,
# the shared AWS keys, CAMPBELL_AI_INTERNAL_TOKEN's deploy-specific override) still
# come from .env / the compose environment and are never baked in here. Everything
# below is safe to keep in version control; changing one of these means rebuilding
# the image, so frequently-tuned values can also be overridden per-deployment via
# docker-compose.yml's `environment:` block without touching this file.
ENV CAMPBELL_AI_ENABLED=true
ENV CAMPBELL_AI_API_TIMEOUT_SECONDS=90
# Shared secret between the dashboard and the internal API, both built from this
# same image — baking one default in keeps the two containers automatically in
# sync. The API is only reachable from other containers on the compose network
# (never published to the host), so the exposure here is low; override it via
# docker-compose's `environment:` for a deployment-specific value instead.
ENV CAMPBELL_AI_INTERNAL_TOKEN=campbell-internal-service-token
ENV CAMPBELL_AI_SESSION_TTL_SECONDS=1800
ENV CAMPBELL_AI_MAX_HISTORY_MESSAGES=20
ENV CAMPBELL_AI_MAX_MESSAGE_CHARS=4000
# Agent turn budgets: the data analyst chains several detail tools for cross-source answers.
ENV CAMPBELL_AI_MAX_TURNS_DATA_ANALYST=10
ENV CAMPBELL_AI_MAX_TURNS_HEAD=10
# `memory` is process-local and only valid for a single worker; any deployment
# with more than one worker or replica must use `redis` (CAMPBELL_AI_REDIS_URL).
ENV CAMPBELL_AI_SESSION_BACKEND=memory
# Progressive answers over SSE. Requires the same value in the Dash process.
ENV CAMPBELL_AI_STREAMING=false
# Durable backup of conversations and feedback, to the S3 bucket configured via
# BUCKET_NAME/ACCESS_KEY/SECRET_KEY. With no bucket configured it mirrors to disk.
ENV CAMPBELL_AI_PERSISTENCE=true
ENV CAMPBELL_AI_S3_PREFIX=campbellAI
ENV CAMPBELL_AI_HISTORY_LIMIT=50
ENV CAMPBELL_AI_SUMMARY=true
ENV CAMPBELL_AI_MODEL_SUMMARY=gpt-4.1-mini
# Admission control. One answer holds a worker for tens of seconds, so the useful
# global bound is low; the per-user bound keeps one person with several tabs from
# filling it.
ENV CAMPBELL_AI_MAX_CONCURRENT_REQUESTS=10
ENV CAMPBELL_AI_MAX_CONCURRENT_PER_USER=2
ENV CAMPBELL_AI_MAX_REQUESTS_PER_MINUTE=200
ENV CAMPBELL_AI_QUEUE_TIMEOUT_SECONDS=20
ENV CAMPBELL_AI_RETRY_ATTEMPTS=3
ENV CAMPBELL_AI_RETRY_INITIAL_DELAY=1
ENV CAMPBELL_AI_RETRY_MAX_DELAY=30
ENV CAMPBELL_AI_MODEL_GATEKEEPER=gpt-4.1-mini
ENV CAMPBELL_AI_MODEL_HEAD=gpt-4.1-mini
ENV CAMPBELL_AI_MODEL_PLANNER=gpt-4.1-mini
ENV CAMPBELL_AI_MODEL_DATA_ANALYST=gpt-4.1
ENV CAMPBELL_AI_MODEL_TECHNICAL_EXPERT=gpt-4.1-mini
ENV CAMPBELL_AI_MODEL_DASHBOARD_GUIDE=gpt-4.1-mini

CMD ["python", "dashboard/app.py"]
