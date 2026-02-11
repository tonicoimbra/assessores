FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

COPY . /app

RUN useradd -m appuser \
    && mkdir -p /app/outputs \
    && chown -R appuser:appuser /app

USER appuser

# Rodar o servidor WEB como módulo para corrigir imports
CMD ["python", "-m", "src.web_app"]
