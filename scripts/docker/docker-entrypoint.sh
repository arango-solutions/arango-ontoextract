#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# Arango-OntoExtract Docker Entrypoint
# ============================================================================
# Orchestrates startup of:
#   1. Database migrations
#   2. FastAPI backend (port 8001)
#   3. Nginx reverse proxy (port 8000)
#   4. Next.js frontend (served via nginx)
# ============================================================================

# --- Configuration (all from env with defaults) ---
ARANGO_HOST="${ARANGO_HOST:-http://localhost:8529}"
ARANGO_DB="${ARANGO_DB:-OntoExtract}"
ARANGO_USER="${ARANGO_USER:-root}"
ARANGO_PASSWORD="${ARANGO_PASSWORD:-changeme}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
OPENAI_API_KEY="${OPENAI_API_KEY:-}"
APP_SECRET_KEY="${APP_SECRET_KEY:-change-this}"
APP_ENV="${APP_ENV:-production}"
APP_LOG_LEVEL="${APP_LOG_LEVEL:-INFO}"

BACKEND_PORT="${BACKEND_PORT:-8001}"
FRONTEND_PORT="${FRONTEND_PORT:-8000}"

NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-/api/v1}"
FRONTEND_URL="${FRONTEND_URL:-http://localhost:8000}"

export ARANGO_HOST ARANGO_DB ARANGO_USER ARANGO_PASSWORD
export ANTHROPIC_API_KEY OPENAI_API_KEY APP_SECRET_KEY
export APP_ENV APP_LOG_LEVEL
export BACKEND_PORT FRONTEND_PORT
export NEXT_PUBLIC_API_URL

echo "==> AOE starting, connecting to ArangoDB at ${ARANGO_HOST}"
echo "==> Database: ${ARANGO_DB}"
echo "==> App environment: ${APP_ENV}"

# --- Signal handling for graceful shutdown ---
shutdown() {
    echo "==> Shutting down..."
    if [ -n "${NGINX_PID:-}" ] && kill -0 "$NGINX_PID" 2>/dev/null; then
        nginx -s quit 2>/dev/null || true
    fi
    if [ -n "${FRONTEND_PID:-}" ] && kill -0 "$FRONTEND_PID" 2>/dev/null; then
        kill "$FRONTEND_PID" 2>/dev/null || true
    fi
    if [ -n "$BACKEND_PID" ] && kill -0 "$BACKEND_PID" 2>/dev/null; then
        kill "$BACKEND_PID" 2>/dev/null || true
    fi
    wait "$BACKEND_PID" 2>/dev/null || true
    wait "${FRONTEND_PID:-}" 2>/dev/null || true
    echo "==> Shutdown complete."
    exit 0
}

trap 'shutdown' SIGTERM SIGINT

# --- Run database migrations ---
echo "==> Running database migrations..."
cd /app
python -m migrations.runner
echo "==> Migrations complete."

# --- Start frontend (Next.js) in background ---
echo "==> Starting frontend (Next.js) on port 3000..."
export PORT=3000
export HOSTNAME="0.0.0.0"
node frontend/server.js &
FRONTEND_PID=$!

# --- Start nginx first (for health checks) ---
echo "==> Starting nginx on port ${FRONTEND_PORT}..."
sed -i "s/server 127.0.0.1:8010/server 127.0.0.1:${BACKEND_PORT}/g" /etc/nginx/nginx.conf
nginx -g 'daemon off;' &
NGINX_PID=$!

# --- Start backend in background ---
echo "==> Starting backend on port ${BACKEND_PORT}..."
BACKEND_CMD="uvicorn app.main:app \
    --host 0.0.0.0 \
    --port \"${BACKEND_PORT}\" \
    --workers 2"
eval $BACKEND_CMD &
BACKEND_PID=$!

# --- Wait for backend and frontend health ---
echo "==> Waiting for backend and frontend to be ready..."
RETRIES=60
INTERVAL=1
while true; do
    BACKEND_READY=false
    FRONTEND_READY=false
    
    if curl -sf "http://127.0.0.1:${BACKEND_PORT}/health" > /dev/null 2>&1; then
        BACKEND_READY=true
    fi
    
    if curl -sf "http://127.0.0.1:3000/" > /dev/null 2>&1; then
        FRONTEND_READY=true
    fi
    
    if [ "$BACKEND_READY" = true ] && [ "$FRONTEND_READY" = true ]; then
        echo "==> Backend and frontend are ready."
        break
    fi
    
    RETRIES=$((RETRIES - 1))
    if [ "$RETRIES" -le 0 ]; then
        echo "ERROR: Services did not become healthy in time" >&2
        [ "$BACKEND_READY" = false ] && echo "  - Backend is NOT ready"
        [ "$FRONTEND_READY" = false ] && echo "  - Frontend is NOT ready"
        shutdown
    fi
    sleep "$INTERVAL"
done

# --- Verify nginx is running ---
echo "==> Verifying nginx is running..."
for i in $(seq 1 10); do
    if kill -0 "$NGINX_PID" 2>/dev/null; then
        echo "==> Nginx is running (PID: ${NGINX_PID})."
        break
    fi
    if [ "$i" -eq 10 ]; then
        echo "ERROR: Nginx failed to start" >&2
        shutdown
    fi
    sleep 1
done

echo "=============================================="
echo "  Arango-OntoExtract is ready!"
echo "  Frontend: http://localhost:${FRONTEND_PORT}"
echo "  Backend:  http://localhost:${BACKEND_PORT}"
echo "  API Docs: http://localhost:${FRONTEND_PORT}/docs"
echo "=============================================="

# --- Wait for backend to exit ---
wait "$BACKEND_PID"
