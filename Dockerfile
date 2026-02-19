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

EXPOSE 7860

# WSGI server for production platforms (Coolify, Cloud Run, etc.)
CMD ["sh", "-c", "gunicorn -w ${WEB_CONCURRENCY:-1} -k gthread --threads ${WEB_THREADS:-4} -b 0.0.0.0:${PORT:-7860} --timeout ${WEB_TIMEOUT:-300} src.web_app:app"]
