#!/usr/bin/env bash
# Docker smoke test — mirrors .github/workflows/ci.yml unified-image job.
# Requires a running Docker daemon. Containers are named with $$ to reduce collisions.
# Binds HOST :8000; stop anything else listening there first (e.g. unified compose).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT}"

if ! command -v docker >/dev/null 2>&1; then
	echo "smoke-test: docker not on PATH" >&2
	exit 1
fi
if ! docker info >/dev/null 2>&1; then
	echo "smoke-test: Docker daemon not reachable (start Docker and retry)" >&2
	exit 1
fi

NET="aoe-smoke-$$"
ARANGO_C="aoe-smoke-arango-$$"
AOE_C="aoe-smoke-aoe-$$"
IMG_TAG="aoe:smoke-$$"

cleanup() {
	docker rm -f "${AOE_C}" "${ARANGO_C}" >/dev/null 2>&1 || true
	docker network rm "${NET}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> smoke-test: building unified image (${IMG_TAG})..."
docker build -t "${IMG_TAG}" -f Dockerfile .

docker network create "${NET}"

echo "==> smoke-test: starting ArangoDB..."
docker run -d --name "${ARANGO_C}" --network "${NET}" \
	-e ARANGO_ROOT_PASSWORD=changeme \
	arangodb:3.12 \
	arangod --server.endpoint tcp://0.0.0.0:8529

_arangodb_ready() {
	docker exec "${ARANGO_C}" arangosh \
		--server.endpoint tcp://127.0.0.1:8529 \
		--server.authentication true \
		--server.username root \
		--server.password changeme \
		--javascript.execute-string "db._version();" \
		>/dev/null 2>&1
}

for _ in $(seq 1 60); do
	if _arangodb_ready; then
		echo "smoke-test: ArangoDB ready"
		break
	fi
	sleep 2
done
if ! _arangodb_ready; then
	echo "smoke-test: ArangoDB did not become ready in time" >&2
	exit 1
fi

echo "==> smoke-test: starting unified AOE container..."
docker run -d --name "${AOE_C}" --network "${NET}" -p 8000:8000 \
	-e ARANGO_HOST="http://${ARANGO_C}:8529" \
	-e ARANGO_DB=OntoExtract \
	-e ARANGO_USER=root \
	-e ARANGO_PASSWORD=changeme \
	-e APP_SECRET_KEY="smoke-test-$(openssl rand -hex 16)" \
	-e APP_ENV=development \
	-e APP_LOG_LEVEL=DEBUG \
	-e RATE_LIMIT_ENABLED=false \
	-e ANTHROPIC_API_KEY=smoke-stub \
	-e OPENAI_API_KEY=smoke-stub \
	"${IMG_TAG}"

for _ in $(seq 1 90); do
	if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then
		echo "smoke-test: AOE healthy"
		break
	fi
	sleep 2
done

body="$(curl -fsS http://localhost:8000/health)"
echo "${body}"
echo "${body}" | grep -q '"status":"ok"'

echo "==> smoke-test: GET / ..."
code="$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/)"
echo "GET / -> ${code}"
# Login redirect / HTML acceptable; reject 404 and 5xx.
if [[ "${code}" == "404" ]] || [[ "${code}" =~ ^5 ]]; then
	echo "smoke-test: unexpected / status ${code}" >&2
	exit 1
fi

echo "==> smoke-test: WebSocket upgrade handshake..."
response="$(
	curl -s -i -m 5 \
		-H 'Connection: Upgrade' \
		-H 'Upgrade: websocket' \
		-H 'Sec-WebSocket-Version: 13' \
		-H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
		"http://localhost:8000/ws/extraction/ci-smoke" || true
)"
echo "${response}" | head -20
status="$(echo "${response}" | head -1)"
echo "Status: ${status}"
echo "${status}" | grep -q '101' ||
	(echo "smoke-test: expected 101 Switching Protocols, got: ${status}" >&2 && exit 1)

echo "==> smoke-test: OK"
