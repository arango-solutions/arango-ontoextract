# AOE Performance Benchmarks

Performance targets and measurement methodology for the AOE platform. Derived from PRD Section 8.1.

---

## Performance Targets

### API Response Times

| Metric | Target | Measurement |
|--------|--------|-------------|
| Read endpoints (p95) | < 200ms | Prometheus histogram on all `GET` API routes |
| Write endpoints (p95) | < 500ms | Prometheus histogram on all `POST`/`PUT`/`DELETE` routes |
| Health check | < 10ms | Lightweight endpoint with no DB query |
| Readiness probe | < 50ms | Single `db.version()` call |

### Graph Rendering

| Metric | Target | Measurement |
|--------|--------|-------------|
| Curation UI render (500 nodes) | < 2 seconds | Time from data fetch to interactive React Flow canvas |
| Initial page load | < 3 seconds | Lighthouse Performance score, Time to Interactive |
| Graph layout computation | < 500ms | Dagre layout for 500-node hierarchical graph |

### Extraction Pipeline

| Metric | Target | Measurement |
|--------|--------|-------------|
| Per-document extraction | < 5 minutes | Wall clock from `POST /extraction/run` to `status: completed` for a 50-chunk document |
| Document upload + chunking | < 60 seconds | End-to-end for a 100-page PDF |
| Concurrent extraction runs | ≥ 5 parallel | Celery worker concurrency |

### Temporal Queries

| Metric | Target | Measurement |
|--------|--------|-------------|
| Point-in-time snapshot | < 500ms | `GET /ontology/{id}/snapshot?at={ts}` for an ontology with 500 classes |
| Version history lookup | < 100ms | `GET /ontology/class/{key}/history` for a class with 10 versions |
| Temporal diff | < 500ms | `GET /ontology/{id}/diff?t1=&t2=` across 500 classes |
| Timeline events | < 200ms | `GET /ontology/{id}/timeline` returning up to 100 events |

### Entity Resolution

| Metric | Target | Measurement |
|--------|--------|-------------|
| ER pipeline (1000 entities) | < 30 seconds | Full blocking → scoring → clustering cycle |
| BM25 blocking query | < 200ms | ArangoSearch query for candidate retrieval |
| Vector similarity blocking | < 500ms | FAISS IVF approximate nearest neighbor search (cosine, `nLists` ≈ `15·√N`) |
| Explain match | < 100ms | Field-by-field similarity computation for a single pair |
| WCC clustering | < 5 seconds | Weakly connected components on `similarTo` edges (1000 entities) |

---

## Scalability Targets

| Dimension | Target |
|-----------|--------|
| Documents per organization | ≥ 10,000 |
| Ontology classes (domain-wide) | ≥ 50,000 |
| Concurrent users (curation UI) | ≥ 20 |
| Organizations (multi-tenant) | ≥ 100 |
| Concurrent extraction pipelines | ≥ 5 |

---

## Infrastructure Sizing

### Local Development

| Component | Resources |
|-----------|-----------|
| ArangoDB | 2 GB RAM, 10 GB disk |
| Redis | 256 MB RAM |
| Backend | 1 GB RAM |
| Frontend | 512 MB RAM (dev server) |

### Production (Recommended)

| Component | Resources |
|-----------|-----------|
| ArangoDB cluster | 8 GB RAM per node, 100 GB SSD, replication factor ≥ 2 |
| Redis | 1 GB RAM; use HA/Sentinel where required by the deployment platform |
| Backend (per replica) | 2 GB RAM, 2 vCPU |
| Frontend (Next.js standalone) | 256 MB RAM |
| MCP server | 1 GB RAM |

---

## Index Strategy

Performance targets are achieved through careful indexing:

### MDI-Prefixed Indexes (Temporal)

Multi-dimensional indexes on `[created, expired]` for all versioned collections:

- `ontology_classes`
- `ontology_properties`
- `ontology_constraints`
- `subclass_of`, `has_property`, `extends_domain`, `equivalent_class`, `related_to`

These indexes enable sub-millisecond range queries for point-in-time snapshots.

### ArangoSearch Views

BM25 full-text search on `ontology_classes` (label, description) for:
- ER blocking queries
- Class search endpoint
- MCP `search_similar_classes` tool

### Vector Indexes

HNSW approximate nearest neighbor index on `chunks.embedding` for:
- RAG context retrieval during extraction
- Vector-based ER blocking

### TTL Indexes

Sparse TTL indexes on `ttlExpireAt` for automatic historical version cleanup:
- Production: 90-day retention
- Demo: 5-minute retention

---

## Monitoring and Alerting

### Prometheus Metrics

These are the series the backend actually emits (defined in
`backend/app/api/metrics.py`). The alert rules that consume them
live in `infra/monitoring/alerts.yml`; see
[docs/operations/production-deployment.md](operations/production-deployment.md#alert-reference--runbooks)
for the per-alert remediation runbook.

| Metric | Type | Labels | Alert rule (`alerts.yml`) |
|--------|------|--------|---------------------------|
| `aoe_http_request_duration_seconds_*` | Histogram | method, path, status | `APILatencyP95High` (p95 > 2s / 5m) |
| `aoe_http_requests_total` | Counter | method, path, status | — (used for ad-hoc dashboards) |
| `aoe_http_errors_total` | Counter | method, path, status | — (rate spikes surface on dashboards) |
| `aoe_extraction_runs_total` | Counter | status (`completed` / `completed_with_errors` / `failed`) | `ExtractionFailureRateHigh` (failed/total > 20% / 5m) |
| `aoe_extraction_duration_seconds_*` | Histogram | (none) | — (referenced by runbooks for triage) |
| `aoe_queue_depth` | Gauge | queue (`ingest` / `extraction`) | `ExtractionQueueBacklog` (> 10 / 5m) |
| `aoe_db_connection_errors_total` | Counter | reason (`timeout` / `auth` / `unknown`) | `ArangoDBConnectionFailures` (any rate / 2m) |
| `aoe_active_websocket_connections` | Gauge | endpoint | — (reserved, not yet wired) |

Path labels use the matched route pattern (`/api/v1/ontology/{id}`),
not raw URLs, to keep Prometheus cardinality bounded under load.

### Health Checks

| Endpoint | Checks |
|----------|--------|
| `GET /health` | Application is running |
| `GET /ready` | ArangoDB connection is active |

---

## Benchmark Methodology

### How to Run Benchmarks

**Ops benchmarks** (Stream 7 PR 4 — E.5). Latency / throughput of
the application code paths with DB and HTTP I/O mocked. Stable
floor independent of host hardware; catches regressions in
middleware, serialization, materialization, and temporal
aggregation. Committed baseline lives at
[`benchmarks/operations/baseline.md`](../benchmarks/operations/baseline.md).

```bash
# Run all ops benchmarks, print results (safe for CI smoke checks)
make bench

# Run + overwrite baseline.md with the new numbers
make bench-update

# Run a single benchmark in isolation
python -m benchmarks.operations.bench_api_latency
python -m benchmarks.operations.bench_materialize
python -m benchmarks.operations.bench_temporal_snapshot
```

See [`benchmarks/operations/README.md`](../benchmarks/operations/README.md)
for the per-benchmark interpretation guide.

**Ontology-extraction quality benchmarks**. Precision / recall
against Re-DocRED and WebNLG; orthogonal to ops latency. Lives in
[`benchmarks/ontology_extraction/`](../benchmarks/ontology_extraction/).

```bash
python -m benchmarks.ontology_extraction.run_benchmark --help
```

**Real-DB end-to-end benchmarks** (manual). For latency numbers
that include Arango RTT + LLM provider latency, run against a
real backend with a real ArangoDB. Use a load-testing tool like
[`k6`](https://k6.io/) or [`locust`](https://locust.io/) and
script representative workflows (upload → extract → curate).
This is not part of the committed harness — those numbers depend
on hardware, network, and Arango configuration in ways that make
a committed baseline misleading.

### What to Measure

1. **Cold start** — first request after server startup. The ops
   harness includes 5 warmup invocations to amortize Python lazy
   imports; without that, the first sample can be 2-10× the
   steady-state value.
2. **Warm steady-state** — p50, p95, p99 under sustained load.
   This is what `make bench` records.
3. **Concurrent load** — response times at 10 / 20 / 50
   concurrent users. Requires a real backend and `k6` / `locust`.
4. **Data scale** — response times as data volume grows
   (100, 1K, 10K, 50K entities). `bench_materialize` and
   `bench_temporal_snapshot` already sweep three sizes;
   real-DB sweep requires fixture data.

### Reporting

Ops benchmark baseline (`benchmarks/operations/baseline.md`)
auto-records:

- Date (UTC)
- OS / machine / Python version / processor
- Per-scenario p50 / p95 / p99 / min / max / mean

For real-DB benchmarks, record additionally:

- Commit hash
- ArangoDB version and deployment mode
- Hardware specs (CPU, RAM, disk type)
- Data volume (number of entities, documents, chunks)
- Concurrency level
