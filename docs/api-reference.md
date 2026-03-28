# AOE API Reference

Complete endpoint catalog for the Arango-OntoExtract REST API. All endpoints are prefixed with `/api/v1/` unless otherwise noted.

Interactive documentation (Swagger UI) is available at `http://localhost:8000/docs` when the backend is running.

---

## Table of Contents

1. [System](#system)
2. [Documents](#documents)
3. [Extraction](#extraction)
4. [Ontology Library](#ontology-library)
5. [Ontology — Domain and Local](#ontology--domain-and-local)
6. [Ontology — Temporal](#ontology--temporal)
7. [Ontology — Import and Export](#ontology--import-and-export)
8. [Curation](#curation)
9. [Entity Resolution](#entity-resolution)
10. [WebSocket](#websocket)
11. [Error Format](#error-format)
12. [Pagination](#pagination)

---

## System

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/health` | Health check — returns `{"status": "ok"}` | No |
| `GET` | `/ready` | Readiness probe — verifies ArangoDB connection | No |

---

## Documents

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `POST` | `/api/v1/documents/upload` | Upload a document (PDF, DOCX, Markdown) | Yes |
| `GET` | `/api/v1/documents` | List all documents (paginated, filterable) | Yes |
| `GET` | `/api/v1/documents/{doc_id}` | Get document metadata and processing status | Yes |
| `GET` | `/api/v1/documents/{doc_id}/chunks` | List document chunks (paginated) | Yes |
| `DELETE` | `/api/v1/documents/{doc_id}` | Soft-delete a document | Yes |

### POST /api/v1/documents/upload

Upload a file for processing. The file is parsed, chunked, and embedded asynchronously.

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `file` | File | Yes | PDF, DOCX, or Markdown file |
| `org_id` | string | No | Organization ID for tenant scoping |

**Response:** `200 OK`

```json
{
  "doc_id": "abc123",
  "filename": "document.pdf",
  "status": "uploading"
}
```

**Errors:**
- `409 Conflict` — duplicate file (identical SHA-256 hash)
- `400 Validation Error` — unsupported file type

### GET /api/v1/documents

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `limit` | int | 25 | Page size (1–100) |
| `cursor` | string | null | Pagination cursor |
| `sort` | string | `upload_date` | Sort field |
| `order` | string | `desc` | Sort order (`asc` or `desc`) |
| `org_id` | string | null | Filter by organization |
| `status` | string | null | Filter by status |

**Response:** Paginated envelope (see [Pagination](#pagination)).

### GET /api/v1/documents/{doc_id}

**Response:** `200 OK`

```json
{
  "_key": "abc123",
  "filename": "document.pdf",
  "mime_type": "application/pdf",
  "org_id": "org_001",
  "status": "ready",
  "upload_date": "2026-03-15T10:30:00Z",
  "chunk_count": 42,
  "file_hash": "sha256:...",
  "metadata": null,
  "error_message": null
}
```

---

## Extraction

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `POST` | `/api/v1/extraction/run` | Trigger ontology extraction on a document | Yes |
| `GET` | `/api/v1/extraction/runs` | List extraction runs (paginated) | Yes |
| `GET` | `/api/v1/extraction/runs/{run_id}` | Get extraction run status and stats | Yes |
| `GET` | `/api/v1/extraction/runs/{run_id}/steps` | Get per-agent step details | Yes |
| `GET` | `/api/v1/extraction/runs/{run_id}/results` | Get extracted entities | Yes |
| `POST` | `/api/v1/extraction/runs/{run_id}/retry` | Retry a failed extraction run | Yes |
| `GET` | `/api/v1/extraction/runs/{run_id}/cost` | Get LLM cost breakdown | Yes |

### POST /api/v1/extraction/run

**Request Body:**

```json
{
  "document_id": "abc123",
  "config": {
    "num_passes": 3,
    "consistency_threshold": 2
  }
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `document_id` | string | Yes | Document to extract from |
| `config` | object | No | Pipeline config overrides |

**Response:** `200 OK`

```json
{
  "run_id": "run_456",
  "doc_id": "abc123",
  "status": "running"
}
```

### GET /api/v1/extraction/runs/{run_id}/steps

**Response:** `200 OK`

```json
{
  "run_id": "run_456",
  "steps": [
    {
      "name": "strategy_selector",
      "status": "completed",
      "started_at": 1711500000.0,
      "completed_at": 1711500002.5,
      "duration_seconds": 2.5,
      "tokens": {"input": 500, "output": 100}
    }
  ]
}
```

### GET /api/v1/extraction/runs/{run_id}/cost

**Response:** `200 OK`

```json
{
  "run_id": "run_456",
  "total_tokens": 12450,
  "estimated_cost_usd": 0.037,
  "breakdown": [
    {"model": "claude-sonnet-4-20250514", "tokens": 10000, "cost_usd": 0.030},
    {"model": "text-embedding-3-small", "tokens": 2450, "cost_usd": 0.007}
  ]
}
```

---

## Ontology Library

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/v1/ontology/library` | List registered ontologies (paginated) | Yes |
| `GET` | `/api/v1/ontology/library/{ontology_id}` | Get ontology detail with stats | Yes |
| `PUT` | `/api/v1/ontology/orgs/{org_id}/ontologies` | Set base ontologies for an organization | Yes |
| `GET` | `/api/v1/ontology/orgs/{org_id}/ontologies` | Get selected base ontologies | Yes |

### GET /api/v1/ontology/library/{ontology_id}

**Response:** `200 OK`

```json
{
  "_key": "financial_services",
  "label": "Financial Services Ontology",
  "ontology_uri": "http://example.org/ontology/financial",
  "ontology_type": "owl",
  "source_type": "import",
  "status": "active",
  "stats": {
    "class_count": 142,
    "property_count": 387
  }
}
```

### PUT /api/v1/ontology/orgs/{org_id}/ontologies

**Request Body:**

```json
{
  "ontology_ids": ["financial_services", "compliance"]
}
```

**Response:** `200 OK`

```json
{
  "org_id": "org_acme",
  "selected_ontologies": ["financial_services", "compliance"]
}
```

---

## Ontology — Domain and Local

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/v1/ontology/domain` | Get domain ontology graph (paginated) | Yes |
| `GET` | `/api/v1/ontology/domain/classes` | List domain ontology classes | Yes |
| `GET` | `/api/v1/ontology/local/{org_id}` | Get organization's local ontology | Yes |
| `GET` | `/api/v1/ontology/staging/{run_id}` | Get staging graph for curation | Yes |
| `POST` | `/api/v1/ontology/staging/{run_id}/promote` | Promote staging to production | Yes |

---

## Ontology — Temporal

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/v1/ontology/{ontology_id}/snapshot` | Point-in-time graph snapshot | Yes |
| `GET` | `/api/v1/ontology/class/{class_key}/history` | All versions of a class | Yes |
| `GET` | `/api/v1/ontology/{ontology_id}/diff` | Temporal diff between two timestamps | Yes |
| `GET` | `/api/v1/ontology/{ontology_id}/timeline` | Discrete change events for VCR slider | Yes |
| `POST` | `/api/v1/ontology/class/{class_key}/revert` | Revert class to a historical version | Yes |

### GET /api/v1/ontology/{ontology_id}/snapshot

**Query Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `at` | float | Yes | Unix timestamp for the snapshot |

**Response:** `200 OK`

```json
{
  "ontology_id": "financial_services",
  "timestamp": 1711500000.0,
  "class_count": 140,
  "property_count": 380,
  "classes": [...],
  "properties": [...],
  "edges": [...]
}
```

### GET /api/v1/ontology/{ontology_id}/diff

**Query Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `t1` | float | Yes | Start timestamp |
| `t2` | float | Yes | End timestamp (must be > t1) |

**Response:** `200 OK`

```json
{
  "ontology_id": "financial_services",
  "t1": 1711500000.0,
  "t2": 1711600000.0,
  "added": [{"key": "cls_new", "label": "Transaction"}],
  "removed": [{"key": "cls_old", "label": "Deprecated"}],
  "changed": [{"key": "cls_mod", "label": "Account", "before_version": 2, "after_version": 3}],
  "added_count": 1,
  "removed_count": 1,
  "changed_count": 1
}
```

### POST /api/v1/ontology/class/{class_key}/revert

**Query Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `to_version` | float | Yes | Timestamp of the version to revert to |

---

## Ontology — Import and Export

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `POST` | `/api/v1/ontology/import` | Import an OWL/TTL ontology file | Yes |
| `GET` | `/api/v1/ontology/export` | Export ontology (TTL, JSON-LD, CSV) | Yes |
| `POST` | `/api/v1/ontology/schema/extract` | Extract ontology from ArangoDB schema | Yes |
| `GET` | `/api/v1/ontology/schema/extract/{run_id}` | Get schema extraction status | Yes |

### GET /api/v1/ontology/export

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `format` | string | `ttl` | Export format: `ttl`, `json-ld`, `csv` |

---

## Curation

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `POST` | `/api/v1/curation/decide` | Record a single curation decision | Yes |
| `POST` | `/api/v1/curation/batch` | Batch approve/reject/edit multiple entities | Yes |
| `GET` | `/api/v1/curation/decisions` | List curation decisions (paginated) | Yes |
| `GET` | `/api/v1/curation/decisions/{decision_id}` | Get a single decision | Yes |
| `POST` | `/api/v1/curation/merge` | Merge entities into a target | Yes |
| `POST` | `/api/v1/curation/promote/{run_id}` | Promote approved entities to production | Yes |
| `GET` | `/api/v1/curation/promote/{run_id}/status` | Get promotion status | Yes |

### POST /api/v1/curation/decide

**Request Body:**

```json
{
  "run_id": "run_456",
  "entity_key": "cls_001",
  "entity_type": "class",
  "action": "approve",
  "curator_id": "user_jane",
  "notes": "Confirmed by SME",
  "edited_data": null
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `run_id` | string | Yes | Extraction run ID |
| `entity_key` | string | Yes | Entity document key |
| `entity_type` | enum | Yes | `class`, `property`, `constraint` |
| `action` | enum | Yes | `approve`, `reject`, `edit`, `merge` |
| `curator_id` | string | Yes | User who made the decision |
| `notes` | string | No | Optional notes |
| `edited_data` | object | No | Modified fields (for `edit` action) |

### POST /api/v1/curation/merge

**Request Body:**

```json
{
  "source_keys": ["cls_dup_1", "cls_dup_2"],
  "target_key": "cls_canonical",
  "merged_data": {"label": "Canonical Label"},
  "curator_id": "user_jane",
  "notes": "Merged duplicates"
}
```

### POST /api/v1/curation/promote/{run_id}

**Request Body (optional):**

```json
{
  "ontology_id": "my_ontology"
}
```

**Response:** `200 OK`

```json
{
  "run_id": "run_456",
  "status": "completed",
  "promoted_classes": 12,
  "promoted_properties": 8,
  "promoted_edges": 15,
  "skipped": 3,
  "errors": []
}
```

---

## Entity Resolution

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `POST` | `/api/v1/er/run` | Trigger ER pipeline | Yes |
| `GET` | `/api/v1/er/runs/{run_id}` | Get ER run status | Yes |
| `GET` | `/api/v1/er/runs/{run_id}/candidates` | List merge candidates (paginated) | Yes |
| `GET` | `/api/v1/er/runs/{run_id}/clusters` | List entity clusters | Yes |
| `POST` | `/api/v1/er/explain` | Explain match between two entities | Yes |
| `POST` | `/api/v1/er/merge` | Execute merge for a candidate pair | Yes |
| `POST` | `/api/v1/er/cross-tier` | Cross-tier duplicate candidates | Yes |
| `GET` | `/api/v1/er/config` | Get ER pipeline configuration | Yes |
| `PUT` | `/api/v1/er/config` | Update ER pipeline configuration | Yes |

### POST /api/v1/er/run

**Request Body:**

```json
{
  "ontology_id": "my_ontology",
  "config": {
    "similarity_threshold": 0.8,
    "blocking_strategies": ["bm25", "vector"]
  }
}
```

**Response:** `200 OK`

```json
{
  "run_id": "er_001",
  "status": "completed",
  "candidate_count": 15,
  "cluster_count": 5,
  "duration_seconds": 12.3,
  "error": null
}
```

### POST /api/v1/er/explain

**Request Body:**

```json
{
  "key1": "cls_001",
  "key2": "cls_002"
}
```

**Response:** `200 OK`

```json
{
  "key1": "cls_001",
  "key2": "cls_002",
  "overall_score": 0.87,
  "field_scores": {
    "label": {"score": 0.92, "method": "jaro_winkler"},
    "description": {"score": 0.78, "method": "cosine"},
    "uri": {"score": 0.85, "method": "levenshtein"},
    "topology": {"score": 0.91, "method": "neighbor_overlap"}
  }
}
```

### POST /api/v1/er/cross-tier

**Request Body:**

```json
{
  "local_ontology_id": "org_acme_local",
  "domain_ontology_id": "financial_services",
  "min_score": 0.6
}
```

---

## WebSocket

| Path | Description |
|------|-------------|
| `ws://host/ws/extraction/{run_id}` | Real-time extraction pipeline progress |

### Event Format

```json
{
  "event": "step_completed",
  "step": "extraction_agent",
  "data": {"classes_found": 15, "tokens_used": 3200},
  "timestamp": 1711500042.5,
  "run_id": "run_456"
}
```

### Event Types

| Event | Description |
|-------|-------------|
| `connected` | WebSocket connection established |
| `step_started` | Pipeline agent step began |
| `step_completed` | Pipeline agent step finished successfully |
| `step_failed` | Pipeline agent step failed |
| `pipeline_paused` | Pipeline paused for human-in-the-loop |
| `completed` | Pipeline finished |
| `failed` | Pipeline failed |
| `heartbeat` | Keep-alive (every 30s if no events) |

---

## Error Format

All error responses follow this envelope:

```json
{
  "error": {
    "code": "ENTITY_NOT_FOUND",
    "message": "Document 'abc123' not found",
    "details": {"doc_id": "abc123"},
    "request_id": "req_a1b2c3d4e5f6"
  }
}
```

### Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `VALIDATION_ERROR` | 400 | Request body or parameter validation failed |
| `UNAUTHORIZED` | 401 | Missing or invalid authentication |
| `FORBIDDEN` | 403 | Insufficient permissions for the requested action |
| `ENTITY_NOT_FOUND` | 404 | Requested resource does not exist |
| `CONFLICT` | 409 | Duplicate resource (e.g., duplicate document upload) |
| `RATE_LIMITED` | 429 | Per-organization rate limit exceeded |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

---

## Pagination

All list endpoints use cursor-based pagination with a standard envelope:

```json
{
  "data": [...],
  "cursor": "eyJzb3J0IjoiLi4uIn0=",
  "has_more": true,
  "total_count": 142
}
```

| Field | Type | Description |
|-------|------|-------------|
| `data` | array | Page of results |
| `cursor` | string or null | Opaque cursor for the next page; null if no more pages |
| `has_more` | boolean | Whether additional pages exist |
| `total_count` | integer | Total number of matching records |

**Usage:**

```bash
# First page
curl "http://localhost:8000/api/v1/documents?limit=25"

# Next page (use cursor from previous response)
curl "http://localhost:8000/api/v1/documents?limit=25&cursor=eyJzb3J0IjoiLi4uIn0="
```
