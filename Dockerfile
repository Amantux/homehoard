# --- Stage 1: build the Vue frontend ---
# Base images are pinned by multi-arch index digest so a rebuild of the same
# commit is reproducible; the tag kept alongside lets Dependabot (docker
# ecosystem) keep proposing digest bumps. Keep the tag INSIDE the reference
# (name:tag@sha256:...): Docker resolves by digest, Dependabot reads the tag.
# Never put a trailing comment on a FROM line — Dockerfiles only allow
# full-line comments, so it would become an extra FROM argument.
FROM node:26-alpine@sha256:143494b1da2945f061539253adc65e4f1569ddf07da2d384c022c791a9d90a4a AS frontend
WORKDIR /build
COPY frontend/package*.json ./
# npm ci installs exactly what package-lock.json records (and fails if the lock
# and package.json disagree) instead of re-resolving ranges on every build.
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# --- Stage 2: python runtime ---
FROM python:3.14-slim@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170
WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    HBOX_DATA_DIR=/data \
    HBOX_FRONTEND_DIST=/app/frontend/dist \
    HBOX_PORT=7745

# gosu lets the entrypoint do its privileged setup (read the HA add-on's
# options.json, fix /data ownership) as root, then drop to a non-root user for
# the actual server processes. A non-root app user is the CIS-hardening default.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r app && useradd -r -g app -u 1000 -m -d /home/app app

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend/dist
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh \
    && mkdir -p /data \
    && chown -R app:app /app /data

VOLUME ["/data"]
EXPOSE 7745

# Readiness-based healthcheck (not just "process alive"): probes /api/v1/ready,
# which verifies DB connectivity + data-dir writability. urlopen raises on 503,
# so a degraded dependency marks the container unhealthy. The port follows
# HBOX_PORT the way settings.py reads it (PORT has no add-on option, so the env
# is its only source; blank = unset = 7745).
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD python3 -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%d/api/v1/ready' % int((os.environ.get('HBOX_PORT') or '').strip() or 7745), timeout=3)" || exit 1

# The entrypoint works both standalone and as a Home Assistant add-on
# (it reads /data/options.json and registers Supervisor discovery when present).
CMD ["/app/docker-entrypoint.sh"]
