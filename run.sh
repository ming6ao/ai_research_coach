#!/usr/bin/env bash
# Run the custom UI (FastAPI backend + Vite frontend dev server)
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

BACKEND_PID=""
FRONTEND_PID=""

free_port() {
  local pids
  pids=$(lsof -ti ":$1" || true)
  if [ -n "$pids" ]; then
    echo "Freeing port $1..."
    # shellcheck disable=SC2086  # word-split so every PID reaches kill
    kill -9 $pids 2>/dev/null || true
  fi
}

cleanup() {
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null || true
  # `uvicorn --reload` (and vite) spawn children that outlive a parent-only kill
  free_port 8001
  free_port 5173
}
trap cleanup EXIT HUP INT TERM

free_port 8001
free_port 5173

echo "Starting FastAPI backend on port 8001..."
.venv/bin/uvicorn backend.main:app --reload --port 8001 &
BACKEND_PID=$!

echo "Starting Vite dev server on port 5173..."
(cd frontend && npx vite --host) &
FRONTEND_PID=$!

echo ""
echo "  Backend:  http://localhost:8001"
echo "  Frontend: http://localhost:5173"
echo ""

wait
