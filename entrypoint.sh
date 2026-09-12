#!/bin/sh
# Container entrypoint: take a safety backup BEFORE the app starts (and thus
# before any schema migration runs on the first request), then launch the
# server. The backup is best-effort — a transient offsite outage must not
# block startup — but it alerts loudly on failure (see app/backup.py).
set -e

python -m app.backup run --if-configured || echo "pre-start backup skipped/failed (see logs)"

exec gunicorn app.main:app \
  -k uvicorn.workers.UvicornWorker \
  --workers "${WORKERS:-${WEB_CONCURRENCY:-2}}" \
  --bind "0.0.0.0:${PORT:-8000}" \
  --timeout 180
