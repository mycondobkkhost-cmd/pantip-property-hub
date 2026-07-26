FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8080 \
    HUB_STARTUP_SHEET_SYNC=1 \
    HUB_AUTO_SYNC_TO_SHEET=1

COPY requirements-hub.txt .
RUN pip install --no-cache-dir -r requirements-hub.txt

COPY scripts/ scripts/
COPY src/hub/ src/hub/
COPY src/__init__.py src/__init__.py
COPY hub/ hub/
COPY data/ data/

EXPOSE 8080

CMD ["python3", "scripts/hub_server.py"]
