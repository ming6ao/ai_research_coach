#!/usr/bin/env bash
# Run the custom UI (FastAPI backend + Vite frontend dev server)
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

VENV="$DIR/.venv"
UVICORN="$VENV/bin/uvicorn"

echo "Starting FastAPI backend on port 8001..."
"$UVICORN" backend.main:app --reload --port 8001 &
BACKEND_PID=$!

echo "Starting Vite dev server on port 5173..."
cd "$DIR/frontend"
npx vite --host &
FRONTEND_PID=$!

cleanup() {
  kill $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
  wait $BACKEND_PID $FRONTEND_PID 2>/dev/null || true
}
trap cleanup EXIT

echo ""
echo "  Backend:  http://localhost:8001"
echo "  Frontend: http://localhost:5173"
echo ""

wait
