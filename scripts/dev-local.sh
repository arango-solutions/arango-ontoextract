#!/usr/bin/env bash
# Start ArangoDB + Redis + FastAPI + Next.js in one terminal. Ctrl+C stops both app processes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT="${BACKEND_PORT:-8010}"
export BACKEND_PROXY_URL="${BACKEND_PROXY_URL:-http://127.0.0.1:${PORT}}"

UV="${ROOT}/backend/.venv/bin/uvicorn"
if [[ ! -x "$UV" ]]; then
  echo "error: missing $UV — run: make setup" >&2
  exit 1
fi

cleanup() {
  if [[ -n "${API_PID:-}" ]] && kill -0 "$API_PID" 2>/dev/null; then
    echo ""
    echo "==> Stopping API (pid $API_PID)"
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup INT TERM EXIT

# ---- Infrastructure (ArangoDB + Redis) ----
# Read ARANGO_ENDPOINT from .env to decide whether DB is local or remote.
ARANGO_ENDPOINT=""
if [[ -f "$ROOT/.env" ]]; then
  ARANGO_ENDPOINT=$(grep -E '^ARANGO_ENDPOINT=' "$ROOT/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true)
fi

if [[ -n "$ARANGO_ENDPOINT" ]] && [[ "$ARANGO_ENDPOINT" != *"localhost"* ]] && [[ "$ARANGO_ENDPOINT" != *"127.0.0.1"* ]]; then
  echo "==> Remote ArangoDB detected (${ARANGO_ENDPOINT}) — skipping local Docker"
else
  echo "==> Ensuring local ArangoDB + Redis are running…"
  (cd "$ROOT" && docker compose up -d --wait 2>/dev/null) || {
    echo "warn: 'docker compose up -d --wait' failed — trying without --wait" >&2
    (cd "$ROOT" && docker compose up -d 2>/dev/null) || {
      echo "error: docker compose failed — is Docker running?" >&2
      exit 1
    }
    arango_ok=0
    echo "==> Waiting for ArangoDB to be healthy…"
    for _ in $(seq 1 30); do
      if curl -sf "http://127.0.0.1:8530/_api/version" >/dev/null 2>&1; then
        arango_ok=1
        break
      fi
      sleep 1
    done
    if [[ "$arango_ok" -ne 1 ]]; then
      echo "error: ArangoDB did not become healthy on port 8530" >&2
      exit 1
    fi
  }
fi
echo "==> Infrastructure ready"
echo ""

echo "==> API  http://127.0.0.1:${PORT}   (proxy ${BACKEND_PROXY_URL})"
echo "==> UI   http://localhost:3000"
echo ""

(cd "$ROOT/backend" && exec "$UV" app.main:app --reload --host 127.0.0.1 --port "$PORT") &
API_PID=$!

ok=0
for _ in $(seq 1 60); do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    echo "error: API process exited — check backend logs above" >&2
    exit 1
  fi
  if curl -sf "http://127.0.0.1:${PORT}/health" >/dev/null 2>&1; then
    ok=1
    break
  fi
  sleep 0.2
done

if [[ "$ok" -ne 1 ]]; then
  echo "error: API did not become ready on port ${PORT}" >&2
  exit 1
fi

echo "==> API is up — starting Next.js"
cd "$ROOT/frontend"
npm run dev
