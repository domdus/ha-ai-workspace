#!/bin/bash
set -euo pipefail
cd /app
export DATA_DIR="${DATA_DIR:-/data}"
export HOST="${HOST:-0.0.0.0}"
export PORT="${PORT:-8090}"
mkdir -p "${DATA_DIR}"
exec python -m uvicorn app.main:app --host "${HOST}" --port "${PORT}" --log-level info
