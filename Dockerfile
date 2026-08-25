FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

RUN mkdir -p logs

EXPOSE 8050
EXPOSE 8000

# Image-level only: things that describe how the container runs, not how Campbell AI
# behaves.
ENV PYTHONUNBUFFERED=1
ENV DASHBOARD_HOST=0.0.0.0
ENV DASHBOARD_PORT=8050
# Speed profile: Polars is used for large CSV/Parquet reads and automatically
# uses the CPUs assigned to the container unless POLARS_MAX_THREADS is set.
ENV DASHBOARD_FRAME_ENGINE=polars

# Keep the default thread pool bounded on small containers. Deployments with
# more CPU can override this without rebuilding the image.
ENV POLARS_MAX_THREADS=4

CMD ["gunicorn", "--bind", "0.0.0.0:8050", "--workers", "1", "--threads", "8", "--timeout", "120", "dashboard.app:server"]
