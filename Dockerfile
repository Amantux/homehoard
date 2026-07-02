# --- Stage 1: build the Vue frontend ---
FROM node:20-alpine AS frontend
WORKDIR /build
COPY frontend/package*.json ./
RUN npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Stage 2: python runtime ---
FROM python:3.11-slim
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    HBOX_DATA_DIR=/data \
    HBOX_FRONTEND_DIST=/app/frontend/dist \
    HBOX_PORT=7745

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend/dist
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

VOLUME ["/data"]
EXPOSE 7745

# The entrypoint works both standalone and as a Home Assistant add-on
# (it reads /data/options.json and registers Supervisor discovery when present).
CMD ["/app/docker-entrypoint.sh"]
