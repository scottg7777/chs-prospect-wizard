#!/usr/bin/env bash
# Starts the wizard locally on http://127.0.0.1:8090 using secrets from .secrets/admin.env (never printed).
cd "$(dirname "$0")"
set -a; . ./.secrets/admin.env; set +a
exec .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "${PORT:-8090}" --no-access-log
