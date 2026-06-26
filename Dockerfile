FROM public.ecr.aws/docker/library/python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y gcc curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./

RUN mkdir -p logs

EXPOSE 8050

ENV PYTHONUNBUFFERED=1
ENV DASHBOARD_HOST=0.0.0.0
ENV DASHBOARD_PORT=8050

CMD ["python", "dashboard/app.py"]
