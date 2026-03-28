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
| Vector similarity blocking | < 500ms | HNSW approximate nearest neighbor search |
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
| Redis Sentinel | 1 GB RAM, 3-node sentinel |
| Backend (per replica) | 2 GB RAM, 2 vCPU |
| Frontend (nginx) | 256 MB RAM |
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

| Metric | Type | Alert Threshold |
|--------|------|-----------------|
| `aoe_api_request_duration_seconds` | Histogram | p95 > 500ms |
| `aoe_extraction_duration_seconds` | Histogram | p95 > 300s |
| `aoe_extraction_errors_total` | Counter | Rate > 10% |
| `aoe_api_errors_total` | Counter | Rate > 1% |
| `aoe_queue_depth` | Gauge | > 100 pending tasks |
| `aoe_temporal_snapshot_duration_seconds` | Histogram | p95 > 1s |
| `aoe_er_pipeline_duration_seconds` | Histogram | p95 > 60s |

### Health Checks

| Endpoint | Checks |
|----------|--------|
| `GET /health` | Application is running |
| `GET /ready` | ArangoDB connection is active |

---

## Benchmark Methodology

### How to Run Benchmarks

```bash
# API latency benchmarks (requires running backend)
cd backend
pytest tests/benchmarks/ -v --benchmark-only

# Load testing (requires k6 or locust)
k6 run scripts/benchmarks/api_load_test.js

# Graph rendering benchmark (frontend)
cd frontend
npx playwright test e2e/benchmarks/graph-render.spec.ts
```

### What to Measure

1. **Cold start** — first request after server startup
2. **Warm steady-state** — p50, p95, p99 under sustained load
3. **Concurrent load** — response times at 10, 20, 50 concurrent users
4. **Data scale** — response times as data volume grows (100, 1K, 10K, 50K entities)

### Reporting

Benchmark results should be recorded with:
- Date and commit hash
- ArangoDB version and deployment mode
- Hardware specs (CPU, RAM, disk type)
- Data volume (number of entities, documents, chunks)
- Concurrency level
