#!/usr/bin/env bash
# One-command launcher for the Property Intel demo portal.
# Usage: scripts/start_portal.sh [--port 8012] [--no-open]
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ -x .venv/Scripts/python ]]; then
  PY=.venv/Scripts/python
elif [[ -x .venv/bin/python ]]; then
  PY=.venv/bin/python
else
  PY=python
fi

if ! "$PY" -c "import fastapi, uvicorn" 2>/dev/null; then
  echo "Dependencies not found. Run:"
  echo "  $PY -m pip install -e \".[dev]\""
  exit 1
fi

exec "$PY" scripts/dev_seed.py "$@"
