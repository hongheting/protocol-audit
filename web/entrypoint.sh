#!/bin/sh
# Optional entrypoint (refcheck-style). Prefer Dockerfile CMD; this mirrors it.
set -e
PORT="${PORT:-8080}"
if [ -n "${PROTOCOL_AUDIT_DEMO_PASSWORD:-}" ]; then
  mkdir -p /run/secrets
  printf '%s' "$PROTOCOL_AUDIT_DEMO_PASSWORD" > /run/secrets/demo_password
  chmod 600 /run/secrets/demo_password
  export PROTOCOL_AUDIT_DEMO_PASSWORD_FILE=/run/secrets/demo_password
  unset PROTOCOL_AUDIT_DEMO_PASSWORD
fi
# gthread: long LLM /upload must not block /health on a single sync worker.
exec gunicorn -b "0.0.0.0:${PORT}" -w 2 -k gthread --threads 4 --timeout 300 --keep-alive 5 "web.app:app"
