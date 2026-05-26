# Production Deployment Guide

> **Audience:** operators standing up AOE in a real environment (single-host
> Docker host, small VM, or as a stepping stone before Kubernetes). This guide
> covers the contracts the application makes with the surrounding stack:
> ports, health checks, metrics, alerts, log rotation, resource limits, and
> the optional observability sidecars.

---

## Table of contents

- [Topology](#topology)
- [Bring-up](#bring-up)
- [Resource limits & logging](#resource-limits--logging)
- [Observability](#observability)
  - [Metrics endpoint](#metrics-endpoint)
  - [Prometheus + Alertmanager profile](#prometheus--alertmanager-profile)
  - [OpenTelemetry tracing](#opentelemetry-tracing)
- [Alert reference & runbooks](#alert-reference--runbooks)
  - [ExtractionFailureRateHigh](#alert-extractionfailureratehigh)
  - [APILatencyP95High](#alert-apilatencyp95high)
  - [ExtractionQueueBacklog](#alert-extractionqueuebacklog)
  - [ArangoDBConnectionFailures](#alert-arangodbconnectionfailures)
- [Customising Alertmanager routing](#customising-alertmanager-routing)
- [Backup & recovery](#backup--recovery)

---

## Topology

`docker-compose.prod.yml` ships seven services on the `aoe-prod-network`:

| Service        | Role                              | Profile          | Exposed |
| -------------- | --------------------------------- | ---------------- | ------- |
| `caddy`        | Reverse proxy + TLS               | default          | 80, 443 |
| `backend`      | FastAPI + LangGraph extraction    | default          | (internal) 8000 |
| `frontend`     | Next.js static + SPA              | default          | (internal) 3000 |
| `arangodb`     | ArangoDB 3.12 with vector index   | default          | (internal) 8529 |
| `redis`        | Cache + queue                     | default          | (internal) 6379 |
| `mcp-server`   | MCP stdio server                  | `mcp`            | n/a (stdio) |
| `prometheus`   | Scrape + alert rule evaluator     | `monitoring`     | 127.0.0.1:9090 |
| `alertmanager` | Alert routing / dedup / silencing | `monitoring`     | 127.0.0.1:9093 |

Caddy is the only service with a public-port binding. Prometheus and
Alertmanager are bound to the loopback interface only -- expose them through
Caddy with auth if you need remote access.

---

## Bring-up

```bash
# Core production stack
docker compose -f docker-compose.prod.yml up -d

# Optional MCP server (stdio over docker exec; usually only needed for
# integration with Claude Desktop / similar tools)
docker compose -f docker-compose.prod.yml --profile mcp up -d

# Optional monitoring stack (Prometheus + Alertmanager)
docker compose -f docker-compose.prod.yml --profile monitoring up -d
```

Health probe order: `arangodb` + `redis` must become healthy before
`backend`; `backend` must become healthy before `frontend` and `caddy`.
The `condition: service_healthy` `depends_on` rules enforce this.

---

## Resource limits & logging

Every service ships with `deploy.resources.limits` + `reservations` and a
shared `json-file` log driver capped at 10MB × 5 files. The limits are
defaults tuned for a small-to-mid host; bump them per your traffic.

| Service        | CPU limit | Memory limit | CPU reservation | Memory reservation |
| -------------- | --------- | ------------ | --------------- | ------------------ |
| `caddy`        | 0.5       | 256M         | 0.1             | 64M                |
| `backend`      | 2.0       | 2G           | 0.5             | 512M               |
| `frontend`     | 0.5       | 512M         | 0.1             | 128M               |
| `arangodb`     | 4.0       | 4G           | 1.0             | 1G                 |
| `redis`        | 0.5       | 384M         | 0.1             | 128M               |
| `mcp-server`   | 1.0       | 512M         | 0.1             | 128M               |
| `prometheus`   | 1.0       | 1G           | 0.2             | 256M               |
| `alertmanager` | 0.5       | 256M         | 0.1             | 64M                |

> **Note:** `deploy.resources` is honoured by `docker compose up` since
> Compose v1.28; you do not need swarm mode. Verify with
> `docker inspect <container> | grep -E 'Memory|NanoCpus'`.

Logs live in `/var/lib/docker/containers/<id>/<id>-json.log` on the host;
the 10MB × 5 file cap is the floor that stops disk exhaustion. Production
deployments forward these to a real aggregator (Loki / CloudWatch /
Datadog) with the node-level log driver or a sidecar collector.

---

## Observability

### Metrics endpoint

`backend` exposes Prometheus-format metrics at
**`GET /api/v1/metrics`** (no auth required from inside the compose
network; gate via Caddy if you publish it externally).

Series the application writes (defined in `app/api/metrics.py`):

| Series                                      | Type      | Labels                          | Written by |
| ------------------------------------------- | --------- | ------------------------------- | ---------- |
| `aoe_http_request_duration_seconds_*`       | Histogram | method, path, status            | `PrometheusMiddleware` |
| `aoe_http_requests_total`                   | Counter   | method, path, status            | `PrometheusMiddleware` |
| `aoe_http_errors_total`                     | Counter   | method, path, status            | `PrometheusMiddleware` |
| `aoe_extraction_runs_total`                 | Counter   | status (completed / completed_with_errors / failed) | `services.extraction.execute_run` |
| `aoe_extraction_duration_seconds_*`         | Histogram | (none)                          | `services.extraction.execute_run` |
| `aoe_queue_depth`                           | Gauge     | queue (ingest / extraction)     | `api.documents._track_ingest_task`, `services.extraction.execute_run` |
| `aoe_db_connection_errors_total`            | Counter   | reason (timeout / auth / unknown) | `api.health.ready` |
| `aoe_active_websocket_connections`          | Gauge     | endpoint                        | (reserved -- set by WS handlers) |

Path labels use the matched route pattern, not raw URLs, to keep
cardinality bounded.

### Prometheus + Alertmanager profile

```bash
docker compose -f docker-compose.prod.yml --profile monitoring up -d
```

Configs are bind-mounted read-only from `infra/monitoring/`:

- `prometheus.yml` -- scrape config + alert-rule loader + Alertmanager wiring
- `alerts.yml`     -- alert rules (see [Alert reference](#alert-reference--runbooks))
- `alertmanager.yml` -- routing + receivers + inhibit rules

Reload Prometheus rules without a restart:

```bash
# alerts.yml is bind-mounted; edit the file, then:
curl -X POST http://127.0.0.1:9090/-/reload
```

### OpenTelemetry tracing

Default OFF. Flip on with env overrides at compose-up time:

```bash
OTEL_ENABLED=true \
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317 \
docker compose -f docker-compose.prod.yml up -d backend
```

When `OTEL_EXPORTER_OTLP_ENDPOINT` is unset the backend falls back to a
console exporter -- handy for smoke-testing instrumentation locally
without standing up a collector. See
[`backend/app/observability/tracing.py`](../../backend/app/observability/tracing.py)
for the full sampler / instrumentor wiring.

---

## Alert reference & runbooks

All four PRD-required alerts live in `infra/monitoring/alerts.yml`. Each
has an embedded `runbook_url` annotation pointing at the matching section
below.

### Alert: `ExtractionFailureRateHigh`

- **Severity:** critical (pages)
- **Fires when:** `>20%` of `aoe_extraction_runs_total` are `status="failed"`
  over a 5-minute window, sustained for 5 minutes.
- **What to check:**
  1. `GET /api/v1/runs?status=failed` -- list the failing run IDs.
  2. For each, pull `step_logs` from `/api/v1/runs/{id}` -- look for common
     patterns (LLM provider 5xx, consistency-check crash, materialization
     write errors).
  3. Recent deploys -- a regression in `extraction.execute_run` is the most
     common cause if the failures are clustered around a release time.
- **Common remediations:**
  - LLM provider outage -- ratchet `extraction_max_retries` up or fall
    back to the secondary provider via `LLM_PROVIDER=openai|anthropic`.
  - Materialization write timeout -- check ArangoDB headroom + the
    `ArangoDBConnectionFailures` alert.

### Alert: `APILatencyP95High`

- **Severity:** warning
- **Fires when:** p95 of `aoe_http_request_duration_seconds_bucket` exceeds
  2.0s for any (method, path) pair, sustained for 5 minutes.
- **What to check:**
  1. Note the offending `{method, path}` labels in the alert.
  2. If tracing is on, search Jaeger / Tempo by route -- the per-request
     trace shows whether the latency is in HTTP middleware, an AQL query,
     or an outbound LLM call.
  3. Recent ontology size growth -- workspace `/classes` and `/edges`
     endpoints scale with class count; consider adding `?include=summary`
     projections at call sites that don't need full payloads.

### Alert: `ExtractionQueueBacklog`

- **Severity:** warning
- **Fires when:** `aoe_queue_depth{queue=...} > 10` for 5 minutes on
  either `queue=ingest` or `queue=extraction`.
- **What to check:**
  1. Which queue? `ingest` backlog means uploads are queueing for parse /
     chunk / embed; `extraction` backlog means LLM-bound work is queueing.
  2. `aoe_extraction_duration_seconds` -- a creep upward here explains a
     `queue=extraction` backlog without a change in upload rate.
  3. Horizontal capacity -- the simplest remediation is more `backend`
     replicas behind Caddy; the second-simplest is moving to a real
     queue (Celery / ARQ) if backlog is chronic.

### Alert: `ArangoDBConnectionFailures`

- **Severity:** critical (pages)
- **Fires when:** any non-zero rate on `aoe_db_connection_errors_total`
  over 5 minutes, sustained for 2 minutes.
- **What to check:**
  1. The `reason` label buckets the failure:
     - `timeout` -- network partition, Arango hung, or the container is
       OOM-killed (check `docker stats arangodb`).
     - `auth` -- credentials drift, `ARANGO_PASSWORD` mismatch between
       backend and Arango, or the target DB was dropped.
     - `unknown` -- novel failure mode; check the backend container
       logs for the `/ready` exception trace.
  2. Arango container health: `docker inspect arangodb --format '{{.State.Health.Status}}'`.
  3. Disk space on the `arangodb_prod_data` volume -- Arango refuses
     writes (and ultimately reads) when out of disk.

---

## Customising Alertmanager routing

The shipped `alertmanager.yml` has a stdout-only `default` receiver --
alerts will appear in `docker logs alertmanager` and that's it. To wire
real channels:

1. Add a receiver block under `receivers:`:
   ```yaml
   - name: critical
     slack_configs:
       - api_url: ${SLACK_CRITICAL_WEBHOOK}
         channel: "#alerts-critical"
         send_resolved: true
   ```
2. Either put the webhook in a `.env` referenced by the compose file,
   or pass it through docker-compose `environment:` so the file stays
   secret-free.
3. Reload:
   ```bash
   docker compose -f docker-compose.prod.yml --profile monitoring \
     restart alertmanager
   ```

Keep `severity: critical` and `severity: warning` routes separate -- the
defaults already inhibit warnings while a related critical is firing.

---

## Backup & recovery

ArangoDB lives in the named volume `arangodb_prod_data`. Before any
risky operation (major version bump, schema migration with `make migrate`),
take a snapshot:

```bash
docker run --rm \
  -v arangodb_prod_data:/data:ro \
  -v "$PWD/backups":/backup \
  alpine \
  tar czf /backup/arango-$(date +%Y%m%d-%H%M%S).tgz -C / data
```

Restore:

```bash
docker compose -f docker-compose.prod.yml stop arangodb
docker run --rm \
  -v arangodb_prod_data:/data \
  -v "$PWD/backups":/backup \
  alpine \
  sh -c "rm -rf /data/* && tar xzf /backup/arango-YYYYMMDD-HHMMSS.tgz -C /"
docker compose -f docker-compose.prod.yml start arangodb
```

Redis is configured with `--appendonly yes` so the AOF survives restarts;
no separate backup procedure is required unless you depend on Redis for
durable state (we don't -- it's cache + queue).
