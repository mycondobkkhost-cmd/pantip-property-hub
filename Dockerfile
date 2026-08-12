FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    HUB_STARTUP_SHEET_SYNC=0 \
    HUB_ALLOW_SHEET_PULL=0 \
    HUB_AUTO_SYNC_TO_SHEET=1 \
    HUB_QUEUE_SHEET_SYNC=0 \
    HUB_ALLOW_QUEUE_SHEET_PULL=0 \
    HUB_FOCUS_SHEET_SYNC=1 \
    HUB_CUSTOMERS_SHEET_SYNC=1 \
    LINE_MENU_WEBHOOK=1 \
    DATA_DIR=/app/data \
    DATA_SEED_DIR=/app/data_seed

COPY requirements-hub.txt .
RUN pip install --no-cache-dir -r requirements-hub.txt

COPY scripts/ scripts/
COPY src/hub/ src/hub/
COPY src/__init__.py src/__init__.py
COPY hub/ hub/
# Seed copy — Fly volume mounts over /app/data; entrypoint copies missing files.
COPY data/ /app/data_seed/
RUN mkdir -p /app/data && cp -a /app/data_seed/. /app/data/ \
    && chmod +x scripts/docker_entrypoint.sh

EXPOSE 8080

CMD ["scripts/docker_entrypoint.sh"]
