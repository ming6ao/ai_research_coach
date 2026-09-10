#!/usr/bin/env bash
# Run the custom UI (FastAPI backend + Vite frontend dev server)
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

BACKEND_PID=""
FRONTEND_PID=""

cleanup() {
  [ -n "$BACKEND_PID" ] && kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "$FRONTEND_PID" ] && kill "$FRONTEND_PID" 2>/dev/null || true
}
trap cleanup EXIT

free_port() {
  if lsof -i ":$1" >/dev/null 2>&1; then
    echo "Freeing port $1..."
    kill -9 "$(lsof -ti ":$1")" 2>/dev/null || true
  fi
}
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
