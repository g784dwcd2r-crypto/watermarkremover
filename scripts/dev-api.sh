#!/usr/bin/env bash
# Run the API against SQLite, filesystem storage and in-process job execution.
#
# This is the zero-infrastructure path: no Postgres, no Redis, no MinIO. It is
# meant for a first run and for end-to-end tests, not for anything real.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${ARS_DEV_STATE_DIR:-$ROOT/.dev-state}"
mkdir -p "$STATE_DIR"

export ARS_ENVIRONMENT="${ARS_ENVIRONMENT:-development}"
export ARS_DEBUG="${ARS_DEBUG:-true}"
export ARS_SECRET_KEY="${ARS_SECRET_KEY:-dev-only-insecure-secret-key-change-me-please-0123456789}"
export ARS_DATABASE_URL="${ARS_DATABASE_URL:-sqlite:///$STATE_DIR/artrestore.db}"
export ARS_STORAGE_BACKEND="${ARS_STORAGE_BACKEND:-local}"
export ARS_LOCAL_STORAGE_DIR="${ARS_LOCAL_STORAGE_DIR:-$STATE_DIR/storage}"
export ARS_CELERY_TASK_ALWAYS_EAGER="${ARS_CELERY_TASK_ALWAYS_EAGER:-true}"
export ARS_RATE_LIMIT_ENABLED="${ARS_RATE_LIMIT_ENABLED:-false}"
export ARS_PUBLIC_API_URL="${ARS_PUBLIC_API_URL:-http://localhost:8000}"
export ARS_PUBLIC_WEB_URL="${ARS_PUBLIC_WEB_URL:-http://localhost:3000}"
export ARS_CORS_ORIGINS="${ARS_CORS_ORIGINS:-http://localhost:3000,http://127.0.0.1:3000}"
export ARS_REDIS_URL="${ARS_REDIS_URL:-}"
export ARS_LOG_LEVEL="${ARS_LOG_LEVEL:-INFO}"

PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"

"$PYTHON" - <<'PYEOF'
"""Create the schema on first run so the dev API starts with no extra steps."""
from artrestore_api import models  # noqa: F401  (registers tables)
from artrestore_api.db import Base, get_engine

Base.metadata.create_all(get_engine())
print("database ready")
PYEOF

# Registering the worker tasks lets eager mode run jobs inside the API process.
exec "$PYTHON" -c "
import artrestore_worker.tasks  # noqa: F401
import uvicorn
uvicorn.run('artrestore_api.main:app', host='0.0.0.0', port=${PORT:-8000}, log_level='info')
"
