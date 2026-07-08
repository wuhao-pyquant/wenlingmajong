FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    WENLING_DATA_DIR=/data \
    WENLING_STATIC_DIR=/app/static

WORKDIR /app

RUN addgroup --system wenling \
    && adduser --system --ingroup wenling --home /nonexistent --no-create-home wenling

COPY pyproject.toml requirements.txt README.md ./
COPY src ./src
COPY packages ./packages
COPY static ./static

RUN python -m pip install --no-cache-dir --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && mkdir -p /data \
    && chown -R wenling:wenling /data

USER wenling

EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import json, urllib.request; payload = json.load(urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)); raise SystemExit(0 if payload.get('ok') else 1)"

CMD ["python", "-m", "wenling_lan_host", "--host", "0.0.0.0", "--port", "8765", "--data-dir", "/data"]
