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
8. [Quality metrics](#quality-metrics)
9. [Curation](#curation)
10. [Entity Resolution](#entity-resolution)
11. [Belief Revision](#belief-revision)
12. [WebSocket](#websocket)
13. [Error Format](#error-format)
14. [Pagination](#pagination)

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
| `GET` | `/api/v1/ontology/library/{ontology_id}/deletion-impact` | Cascade-on-delete dependency analysis (Stream 1 H.4) | Yes |
| `PUT` | `/api/v1/ontology/library/{ontology_id}` | Update registry metadata: `name`, `description`, `tags`, `tier`, `status` (also syncs `label` with `name`) | Yes |
| `DELETE` | `/api/v1/ontology/library/{ontology_id}` | Deprecate (or, with `?hard_delete=true`, remove) an ontology. Without `?confirm=true`, returns the same `deletion_impact` payload as a dry-run. | Yes |
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

### GET /api/v1/ontology/library/{ontology_id}/deletion-impact

Read-only dependency analysis used by the workspace's "Delete ontology"
dialog (Stream 1 H.4) to surface the full blast radius of a deprecation
or hard-delete **before** the user is asked to confirm.

The same payload is returned by `DELETE /library/{ontology_id}` (without
`?confirm=true`) under the `deletion_impact` key.

**Response:** `200 OK`

```json
{
  "ontology_id": "financial_services",
  "ontology_name": "Financial Services Ontology",
  "status": "active",
  "direct_dependents": [
    {"_key": "compliance", "name": "Compliance Ontology", "status": "active"}
  ],
  "transitive_dependents": [
    {"_key": "compliance", "name": "Compliance Ontology", "status": "active", "depth": 1},
    {"_key": "trade_surveillance", "name": "Trade Surveillance", "status": "active", "depth": 2}
  ],
  "imports_outgoing": [
    {"_key": "fibo_core", "name": "FIBO Core", "status": "active"}
  ],
  "cross_ontology_extends_edges": 5,
  "expire_counts": {
    "ontology_classes": 142,
    "ontology_properties": 387,
    "subclass_of": 96,
    "has_property": 387
  },
  "extraction_runs": {"as_target": 12, "as_domain": 4, "total": 14},
  "quality_history_snapshots": 28,
  "released_versions": 2,
  "open_revisions": 0,
  "has_dependents": true,
  "safe_to_delete": false,
  "warnings": [
    "2 ontology(ies) depend on this one via imports; they will keep their import edges expired but lose live access to imported axioms.",
    "5 cross-ontology extends_domain edge(s) point into this ontology's classes; they will be expired so dependent extractions lose their domain anchors.",
    "2 released version(s) exist for this ontology; deletion forfeits the published artifact."
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `direct_dependents` | array | Ontologies importing this one in **one hop** |
| `transitive_dependents` | array | Full upstream closure with `depth` (1 = direct), sorted by depth then name |
| `imports_outgoing` | array | Ontologies this one imports (informational; not affected by deletion) |
| `cross_ontology_extends_edges` | int | Live `extends_domain` edges from another ontology's classes pointing into this one |
| `expire_counts` | object | Per-collection counts of live entities/edges that the cascade will soft-expire (one row per known collection, zero when empty) |
| `extraction_runs.as_target` | int | Runs whose `target_ontology_id == ontology_id` |
| `extraction_runs.as_domain` | int | Runs that include this ontology in `domain_ontology_ids` |
| `extraction_runs.total` | int | Deduped union of the two |
| `quality_history_snapshots` | int | Quality history entries referencing the ontology |
| `released_versions` | int | Release records for the ontology |
| `open_revisions` | int | `revision_meta` documents in `proposed` status |
| `has_dependents` | bool | True iff any transitive dependent exists |
| `safe_to_delete` | bool | True iff there are no upstream dependents AND no cross-ontology edges AND no released versions |
| `warnings` | array | Human-readable strings, one per concern — render as a list above the typed-name confirmation input |

**Errors:** `404 ENTITY_NOT_FOUND` if the ontology does not exist.

### DELETE /api/v1/ontology/library/{ontology_id}

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `confirm` | bool | `false` | Without this, the call is a **dry-run** that returns the deletion-impact preview |
| `hard_delete` | bool | `false` | When `true`, removes the registry entry after expiring its contents. Default: marks the registry entry `deprecated` instead |

**Dry-run response (`confirm=false`):** `200 OK`

```json
{
  "ontology_id": "financial_services",
  "status": "pending_confirmation",
  "dependent_ontologies": [
    {"_key": "compliance", "name": "Compliance Ontology", "status": "active"}
  ],
  "deletion_impact": { /* same shape as GET .../deletion-impact */ },
  "message": "Pass ?confirm=true to proceed with deprecation."
}
```

`dependent_ontologies` is retained for backward compatibility with older
clients that only consume direct dependents; new clients should read
`deletion_impact.transitive_dependents` instead.

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
| `POST` | `/api/v1/ontology/import` | Import OWL/TTL/RDF-XML/JSON-LD (multipart file) | Yes |
| `GET` | `/api/v1/ontology/{ontology_id}/export` | Export one ontology (Turtle, JSON-LD, CSV) | Yes |
| `POST` | `/api/v1/ontology/schema/extract` | Extract ontology from ArangoDB schema | Yes |
| `GET` | `/api/v1/ontology/schema/extract/{run_id}` | Get schema extraction status | Yes |

### POST /api/v1/ontology/import

**Query parameters (required / optional):**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `ontology_id` | string | Yes | Registry `_key` for the imported ontology |
| `ontology_label` | string | No | Display name override |
| `ontology_uri_prefix` | string | No | URI prefix filter for entity import |

**Request:** `multipart/form-data` with field `file` (the ontology file).

### GET /api/v1/ontology/{ontology_id}/export

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `format` | string | `turtle` | `turtle`, `jsonld`, or `csv` |

---

## Quality metrics

| Method | Path | Description | Auth |
|--------|------|-------------|------|
| `GET` | `/api/v1/quality/dashboard` | Full dashboard: `summary`, `ontologies[]`, `alerts` | Yes |
| `GET` | `/api/v1/quality/{ontology_id}` | Structural + extraction quality merge for one ontology | Yes |
| `GET` | `/api/v1/quality/{ontology_id}/evaluation` | Qualitative strengths / weaknesses | Yes |
| `GET` | `/api/v1/quality/{ontology_id}/class-scores` | Per-class faithfulness and semantic validity | Yes |
| `GET` | `/api/v1/quality/{ontology_id}/history?limit=50` | Timestamped quality snapshots for trend views (Q.2) | Yes |
| `GET` | `/api/v1/quality/{ontology_id}/revisions?recent_limit=20` | Belief-revision metrics tile: verdict/action/status distribution, decay state, pending inbox count, recent timeline (§7.7a, FR-13.26) | Yes |
| `POST` | `/api/v1/quality/recall` | Compare an ontology to a gold-standard OWL/TTL document (Q.4) | Yes |

**Note:** `GET /api/v1/quality/summary` was removed; use `GET /api/v1/quality/dashboard` and read the `summary` field.

### POST /api/v1/quality/recall

Compute precision / recall / F1 of an extracted ontology against a
user-supplied reference document, using fuzzy label matching so
superficial differences (case, plural, punctuation, camelCase vs
snake_case) don't artificially lower recall.

**Request Body:**

```json
{
  "ontology_id": "onto_banking",
  "reference_content": "@prefix : <http://x#> . :Person a <owl#Class> .",
  "rdf_format": "turtle",
  "match_threshold": 0.85,
  "include_object_properties": true
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `ontology_id` | string | Yes | Extracted ontology to score. |
| `reference_content` | string | Yes | Raw OWL / TTL / RDF body. Sent inline (not multipart). |
| `rdf_format` | enum | No | `turtle` (default), `xml` (RDF/XML), `nt`, `json-ld`. |
| `match_threshold` | float | No | 0.0–1.0; default 0.85. 1.0 = exact post-normalisation match. |
| `include_object_properties` | bool | No | Default `true`. Set `false` for class-only comparison. |

**Response (abridged):**

```json
{
  "ontology_id": "onto_banking",
  "match_threshold": 0.85,
  "rdf_format": "turtle",
  "summary": {
    "reference_count": 3, "extracted_count": 3, "matched_count": 2,
    "recall": 0.6667, "precision": 0.6667, "f1": 0.6667
  },
  "classes": {
    "summary": {"reference_count": 3, "extracted_count": 3, "matched_count": 2},
    "matched": [{"reference_label": "Person", "extracted_label": "Person", "similarity": 1.0, ...}],
    "missed": [{"reference_label": "Checking Account", ...}],
    "false_positives": [{"extracted_label": "Vehicle", ...}]
  },
  "object_properties": { ... }
}
```

A `400` is returned when `reference_content` cannot be parsed under the
chosen `rdf_format` (this is user input, not a server bug). `500` is
returned for unexpected backend failures.

### GET /api/v1/curation/throughput

Q.5 — curator throughput for a window:

| Query param | Type | Description |
|-------------|------|-------------|
| `run_id` | string | Optional — restrict to one extraction run. |
| `ontology_id` | string | Optional — restrict via the `extraction_runs.ontology_id` join. |
| `window_seconds` | int (60–86_400) | Trailing window. Default 3600 (1 h). |

Response includes `decisions_in_window`, `decisions_per_hour`,
`active_time_seconds`, `wall_clock_seconds`, and a `source` flag of
`"active_time"` / `"wall_clock"` / `"none"` describing which strategy
produced the rate.

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

## Belief Revision

Curator-facing endpoints for the Incremental Belief Revision (IBR) inbox.
Every row in `revision_meta` records an agent's verdict on an existing
ontology belief in light of new evidence; these endpoints let a curator (or
an MCP agent) accept, reject, or modify those proposals. See
[ADR-008](./adr/008-belief-revision-substrate.md) for the architectural
context.

| Method | Path                                       | Description                                          | Auth |
|--------|--------------------------------------------|------------------------------------------------------|------|
| `GET`  | `/api/v1/revisions/inbox`                  | List pending `FLAG_FOR_CURATION` revisions           | Yes  |
| `GET`  | `/api/v1/revisions/`                       | Filterable list (status, agent_type, ontology)       | Yes  |
| `GET`  | `/api/v1/revisions/{key}`                  | Single revision document                             | Yes  |
| `GET`  | `/api/v1/revisions/entity/{entity_id}`     | All revisions touching one entity                    | Yes  |
| `POST` | `/api/v1/revisions/{key}/accept`           | Apply the proposed action via temporal supersede     | Yes  |
| `POST` | `/api/v1/revisions/{key}/reject`           | Mark rejected; no graph change                       | Yes  |
| `POST` | `/api/v1/revisions/{key}/modify`           | Override action / payload, then apply                | Yes  |

### GET /api/v1/revisions/inbox

**Query Parameters:** `ontology_id` (required), `limit` (default 50, max 500).

**Response:** `200 OK`

```json
{
  "ontology_id": "onto_xyz",
  "count": 2,
  "data": [
    {
      "_key": "rev_abc",
      "ontology_id": "onto_xyz",
      "verdict": "REFINED",
      "action": "FLAG_FOR_CURATION",
      "status": "pending",
      "agent_type": "belief_revision_llm",
      "agent_version": "v1",
      "triggering_doc_id": "doc_001",
      "existing_entity_id": "ontology_classes/onto_xyz__VirtualCare",
      "existing_version": "v1",
      "evidence_quotes": ["...telehealth..."],
      "reasoning": "Description should mention telehealth.",
      "confidence_before": 0.6,
      "confidence_after": 0.8,
      "created": 1715000000
    }
  ]
}
```

### POST /api/v1/revisions/{key}/accept

**Request Body:**

```json
{ "decided_by": "curator_alice", "note": "Looks right." }
```

**Response:** `200 OK`

```json
{
  "revision_key": "rev_abc",
  "decision": "accept",
  "status": "applied",
  "already_decided": false,
  "supersede_result": {
    "entity_id": "ontology_classes/onto_xyz__VirtualCare",
    "old_version": "v1",
    "new_version": "v2"
  },
  "revision": { "...": "updated revision_meta doc" }
}
```

When `already_decided` is `true`, the response status echoes the prior
decision and no graph mutation occurs (idempotent).

### POST /api/v1/revisions/{key}/reject

Same envelope as `/accept` but `decision = "reject"` and no
`supersede_result`. The graph is not modified.

### POST /api/v1/revisions/{key}/modify

**Request Body:**

```json
{
  "decided_by": "curator_alice",
  "note": "Promote to RETRACT — duplicate of existing class.",
  "override_action": "RETRACT"
}
```

`override_action` is one of `REINFORCE | REVISE | RETRACT | GAP_FILL |
FLAG_FOR_CURATION`. The `agent_version` field on the persisted revision
gets a `+modified-by:<curator_id>` suffix so the audit trail makes the
human override unambiguous.

### Admin-only

Background consolidation and circuit breaker visibility live under the
`/admin` router (admin scope required):

| Method | Path                                                      | Description                                  |
|--------|-----------------------------------------------------------|----------------------------------------------|
| `POST` | `/api/v1/admin/ontology/{ontology_id}/consolidate`        | Run rules + decay + stale-belief scan        |
| `GET`  | `/api/v1/admin/consolidation-jobs`                        | List recent consolidation jobs               |
| `GET`  | `/api/v1/admin/consolidation-jobs/{job_key}`              | Inspect cursor for one job                   |
| `GET`  | `/api/v1/admin/belief-revision/circuit-breaker`           | Snapshot of the LLM agent's rate limiter     |

`/consolidate` query parameters: `dry_run` (default `false`), `job_key`
(resume an interrupted job), `stale_age_days`, `stale_min_confidence`.

---

## WebSocket

| Path | Description |
|------|-------------|
| `ws://host/ws/extraction/{run_id}?token=JWT` | Real-time extraction pipeline progress |
| `ws://host/ws/curation/{session_id}?token=JWT` | Real-time curation collaboration events |

**Authentication:** Pass a valid JWT as the `token` query parameter. In dev mode (APP_ENV != production), the token is optional and a mock admin user is used.

### Extraction Event Format

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

### Curation Event Format

```json
{
  "event": "decision_made",
  "data": {"entity_key": "cls_123", "decision": "approve"},
  "user_id": "user_abc",
  "session_id": "session_456",
  "timestamp": 1711500042.5
}
```

### Curation Event Types

| Event | Description |
|-------|-------------|
| `connected` | WebSocket connection established |
| `decision_made` | A curation decision was recorded |
| `entity_merged` | Two entities were merged |
| `staging_promoted` | Staging entities promoted to production |
| `heartbeat` | Keep-alive (every 30s if no events) |

---

## Rate Limiting

All authenticated endpoints include rate-limit headers in the response:

| Header | Description |
|--------|-------------|
| `X-RateLimit-Limit` | Maximum requests per window |
| `X-RateLimit-Remaining` | Requests remaining in current window |
| `X-RateLimit-Reset` | Unix timestamp when the window resets |

When the limit is exceeded, the API returns HTTP 429 with error code `RATE_LIMITED`.

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
