# Deletion, Referential Integrity & Curation Actions

**Document Version:** 1.0
**Date:** March 31, 2026
**PRD Reference:** Sections 5.3, 6.1 (FR-1.9), 6.4 (FR-4.2–4.6), 6.7, 6.8 (FR-8.12–8.14), 7.2.1

---

## 1. Overview

AOE manages three fundamentally different types of data mutation, each with distinct referential integrity rules:

| Category | Mechanism | History Preserved? | When Used |
|----------|-----------|-------------------|-----------|
| **Temporal soft-delete** | Set `expired = now` | Yes — VCR timeline shows historical state | Normal ontology lifecycle: deprecation, rejection, supersession |
| **Hard delete** | `REMOVE` / `truncate()` | No — data permanently destroyed | System reset (dev/demo), document chunk replacement |
| **Status transition** | Update `status` field | Yes — entity still exists with new status | Curation approval, ontology deprecation |

These three mechanisms interact with ArangoDB's multi-collection graph model, where a single class may be referenced by edges in 10+ collections. This document maps every mutation scenario to its required cascade behavior.

---

## 2. Data Model & Reference Paths

### 2.1 Collections and Relationships

```
ontology_registry ──(produced_by)──→ extraction_runs
       │
       ├──(imports)──→ ontology_registry  (owl:imports dependencies)
       │
       └── scoped by ontology_id ──→ ontology_classes
                                          │
                                          ├──(subclass_of)──→ ontology_classes
                                          ├──(has_property)──→ ontology_properties
                                          ├──(has_constraint)──→ ontology_constraints
                                          ├──(extends_domain)──→ ontology_classes (cross-ontology)
                                          ├──(related_to)──→ ontology_classes
                                          ├──(equivalent_class)──→ ontology_classes
                                          └──(extracted_from)──→ documents
                                                                    │
                                                                    └──(has_chunk)──→ chunks
```

### 2.2 Cross-Ontology References

These edge types can reference entities in OTHER ontologies:

| Edge Collection | Cross-Ontology? | Example |
|----------------|-----------------|---------|
| `imports` | **Yes** — between registry entries | Ontology A imports Ontology B |
| `extends_domain` | **Yes** — local class extends domain class | Local class → Domain class in different ontology |
| `equivalent_class` | **Yes** — classes across ontologies | Class in Ontology A ≡ Class in Ontology B |
| `merge_candidate` | **Yes** — ER similarity links | Class in Ontology A ~ Class in Ontology B |
| `subclass_of` | Typically no (same ontology) | Child class → Parent class |
| `has_property` | No (same ontology) | Class → Property |
| `extracted_from` | Cross-domain (ontology → document) | Class → Source document |

**Referential integrity rule:** When an entity is expired or deleted, ALL edges pointing to or from it must also be expired — including edges from OTHER ontologies.

### 2.3 Temporal Fields

Every versioned entity carries (PRD §5.3):

| Field | Current Entity | Historical Entity |
|-------|---------------|-------------------|
| `created` | Unix timestamp of creation | Unix timestamp of creation |
| `expired` | `9223372036854775807` (NEVER_EXPIRES) | Unix timestamp when superseded |
| `version` | Monotonically increasing integer | Previous version number |
| `status` | `draft` / `approved` / `deprecated` | Status at time of expiration |
| `change_type` | `initial` / `edit` / `approve` / etc. | What created this version |
| `ttlExpireAt` | `null` | Unix timestamp for garbage collection |

---

## 3. Mutation Scenarios

### 3.1 Curation: Approve Entity

**PRD Reference:** FR-4.2 (Node actions: approve)

**What happens:**
1. Current version of the entity is expired (`expired = now`)
2. New version created with `status: "approved"`, `change_type: "approve"`
3. All edges connected to the old version are expired
4. Identical edges re-created pointing to the new version
5. Decision recorded in `curation_decisions`

**Implementation:** `curation.py → _apply_approve() → temporal.update_entity()`

**Cascade:**

| Affected | Action | Why |
|----------|--------|-----|
| Old class version | `expired = now` | Superseded by approved version |
| New class version | Created with `status: "approved"` | New current version |
| All `subclass_of` edges FROM/TO this class | Expire old, create new | Edges reference specific document versions |
| All `has_property` edges FROM this class | Expire old, create new | Properties linked to class version |
| All `extends_domain` edges FROM/TO this class | Expire old, create new | Cross-ontology edges updated |
| All `related_to` edges FROM/TO this class | Expire old, create new | Lateral relationships updated |

**Referential integrity:** Preserved — no dangling references. New edges point to new version. Old edges are expired alongside old version. Timeline shows both versions.

---

### 3.2 Curation: Reject Entity

**PRD Reference:** FR-4.2 (Node actions: reject)

**What happens:**
1. Entity is expired (`expired = now`)
2. NO new version created — the entity is effectively removed from the current graph
3. Connected edges are NOT automatically expired by the reject action

**Implementation:** `curation.py → _apply_reject() → temporal.expire_entity()`

**Cascade:**

| Affected | Action | Why |
|----------|--------|-----|
| Class | `expired = now` | Rejected — no longer current |
| Connected edges | **NOT expired** | ⚠️ Gap — see Issue below |

**⚠️ Referential Integrity Issue:**
`expire_entity()` only expires the class itself. Edges connected to the rejected class remain active, creating dangling references. Queries filtering by `expired == NEVER_EXPIRES` on edges will return edges pointing to an expired class.

**Correct behavior (per PRD §5.3 FR-5.2):** "old vertex gets `expired = now`; edges to/from old vertex are expired." The reject action should call `expire_class_cascade()` (which expires connected edges) instead of `expire_entity()`.

---

### 3.3 Curation: Edit Entity

**PRD Reference:** FR-4.2 (Node actions: edit properties)

**What happens:**
1. Current version expired
2. New version created with edited fields, `change_type: "edit"`
3. All connected edges expired and re-created for new version
4. Decision recorded with `before` and `after` state

**Implementation:** `curation.py → _apply_edit() → temporal.update_entity()`

**Cascade:** Same as Approve (§3.1) — full edge re-creation. Correctly preserves referential integrity.

---

### 3.4 Curation: Merge Entities (Entity Resolution)

**PRD Reference:** FR-4.2 (Node actions: merge), §6.7 (Entity Resolution)

**What happens:**
1. "Losing" entity is expired
2. "Winning" entity may be updated with merged fields (golden record)
3. All edges from the losing entity should be transferred to the winning entity
4. `merge_candidate` edge is resolved
5. Decision recorded as `action: "merge"`

**Implementation:** `er.py → execute_merge()`

**Cascade:**

| Affected | Action | Why |
|----------|--------|-----|
| Losing class | `expired = now` | Merged into winner |
| Winning class | Updated with merged fields (new version) | Golden record |
| Edges FROM losing class | Expire, re-create pointing FROM winner | Transfer relationships |
| Edges TO losing class | Expire, re-create pointing TO winner | Transfer incoming references |
| `merge_candidate` edge | Expired (resolved) | No longer a candidate |
| Cross-ontology `extends_domain` TO losing class | Must be redirected TO winner | External references preserved |

**Referential integrity:** Must handle cross-ontology edges carefully — other ontologies' classes that `extends_domain` or `equivalent_class` to the losing class need their edges redirected to the winner.

---

### 3.5 Curation: Promote Staging to Production

**PRD Reference:** FR-4.6 (Promote staging → production)

**What happens:**
1. All staging entities (from an extraction run) with `status: "approved"` are confirmed
2. Entities already in the ontology graph remain as-is
3. New entities materialized during extraction are already in the graph — promotion is primarily a status confirmation
4. Per-ontology named graph is ensured

**Implementation:** `promotion.py → promote_staging()`

**Cascade:** Minimal — promotion doesn't expire or delete anything. It confirms what the extraction pipeline already materialized.

---

### 3.6 Ontology Editor: Update Class

**PRD Reference:** FR-4.11 (Direct class creation/editing in editor)

**What happens:**
1. Current version expired
2. New version created with updated fields, `source_type: "manual"`, `change_type: "edit"`
3. All connected edges expired and re-created

**Implementation:** `ontology.py → PUT /ontology/{id}/classes/{key} → ontology_repo.update_class()`

**Cascade:** Same as Approve/Edit (§3.1/§3.3) — uses `temporal.update_entity()` with full edge re-creation.

---

### 3.7 Ontology Editor: Delete Class

**PRD Reference:** FR-4.11 (implied — editor supports delete)

**What happens:**
1. Class is expired (`expired = now`)
2. ALL connected edges in ALL ontology edge collections are expired
3. Properties owned by this class are NOT automatically expired (they become orphan properties)

**Implementation:** `ontology.py → DELETE /ontology/{id}/classes/{key} → ontology_repo.expire_class_cascade()`

**Cascade:**

| Affected | Action | Why |
|----------|--------|-----|
| Class | `expired = now` | Soft-deleted |
| `subclass_of` edges (in and out) | `expired = now` | No dangling hierarchy |
| `has_property` edges (out) | `expired = now` | Property links removed |
| `extends_domain` edges (in and out) | `expired = now` | Cross-ontology refs cleaned |
| `related_to` edges (in and out) | `expired = now` | Lateral refs cleaned |
| `equivalent_class` edges (in and out) | `expired = now` | Cross-ontology equivalences cleaned |
| Properties themselves | **NOT expired** | ⚠️ Properties become orphans |
| `extracted_from` edges | **NOT expired** | Provenance preserved |

**Note:** Properties are intentionally not cascade-deleted because they may be shared or reassigned. The quality metrics system flags orphan properties for curator attention.

---

### 3.8 Ontology Lifecycle: Deprecate Ontology

**PRD Reference:** FR-8.13 (Ontology deletion with cascade analysis)

**What happens:**
1. Cascade analysis: check `imports` graph for dependent ontologies → warn user
2. On confirmation: expire ALL current entities scoped to this `ontology_id`
3. Expire cross-ontology edges pointing to/from this ontology's entities
4. Mark registry entry as `status: "deprecated"` (NOT hard-deleted)
5. Remove per-ontology named graph (queries filter by `expired` anyway)

**Implementation:** `ontology.py → DELETE /library/{ontology_id} → temporal soft-delete`

**Cascade:**

| Affected | Action | Why |
|----------|--------|-----|
| All `ontology_classes` with `ontology_id` | `expired = now` | No longer current |
| All `ontology_properties` with `ontology_id` | `expired = now` | No longer current |
| All `ontology_constraints` with `ontology_id` | `expired = now` | No longer current |
| All scoped edges (`subclass_of`, `has_property`, etc.) | `expired = now` | No dangling edges |
| `imports` edges where this ontology is source OR target | `expired = now` | Cross-ontology: other ontologies' import declarations cleaned |
| `extends_domain` edges where target is a class in this ontology | `expired = now` | Cross-ontology: local classes extending this domain cleaned |
| `ontology_registry` entry | `status = "deprecated"` | Audit trail preserved |
| Per-ontology named graph | Deleted | Graph definition removed; data remains in shared collections |

**Referential integrity:** Fully preserved. No dangling references. VCR timeline shows the ontology's complete history before deprecation.

---

### 3.9 Document: Hard Delete

**PRD Reference:** FR-1.9 (Full CRUD on documents), FR-8.14 (Document deletion does not cascade to ontology)

**What happens:**
1. Document is hard-deleted from `documents` collection
2. All chunks for this document are hard-deleted from `chunks` collection
3. `extracted_from` provenance edges are expired (NOT hard-deleted — preserves ontology-side history)
4. `has_chunk` edges are expired
5. Ontology classes are NOT deleted — they may have been curated and enriched beyond the original extraction
6. UI warns which ontologies were sourced from this document

**Implementation:** `documents.py → DELETE /documents/{doc_id}`

**Cascade:**

| Affected | Action | Why |
|----------|--------|-----|
| Document | **Hard delete** | Permanent removal of source |
| Chunks | **Hard delete** | No longer needed |
| `extracted_from` edges | `expired = now` | Provenance trail expired (not destroyed) |
| `has_chunk` edges | `expired = now` | Link to deleted chunks expired |
| Ontology classes | **NOT affected** | May be curated/promoted independently |
| Per-ontology graphs | **NOT affected** | Classes still valid |

**Design rationale (PRD FR-8.14):** Ontology classes extracted from a document may have been reviewed, approved, edited, merged with other classes, or enriched from additional documents. Deleting the source document should not destroy curated ontology knowledge.

---

### 3.10 System Reset: Hard Delete All

**PRD Reference:** §7.2.1 (System Administration Endpoints)

**What happens:**
1. All ontology collections truncated (hard-deleted)
2. Optionally: documents and chunks also truncated (full reset)
3. All per-ontology named graphs removed
4. Visualizer configuration assets (themes, queries, actions) preserved

**Implementation:** `admin.py → POST /admin/reset` (soft) or `POST /admin/reset/full` (full)

**Cascade:** Everything is wiped — no referential integrity needed because all data is gone.

| Reset Type | Documents | Chunks | Classes | Properties | Edges | Registry | Named Graphs | Visualizer Assets |
|-----------|-----------|--------|---------|------------|-------|----------|-------------|------------------|
| Soft reset | **Preserved** | **Preserved** | Truncated | Truncated | Truncated | Truncated | Removed | **Preserved** |
| Full reset | Truncated | Truncated | Truncated | Truncated | Truncated | Truncated | Removed | **Preserved** |

**Guard:** Requires `ALLOW_SYSTEM_RESET=true` environment variable. Should never be enabled in production.

---

## 4. Edge Re-creation on Versioned Updates

When an entity is updated via `temporal.update_entity()`, the following happens atomically:

```
1. Load current entity (version N)
2. Set entity.expired = now  (expire version N)
3. Create new entity (version N+1) with updated fields, created = now, expired = NEVER_EXPIRES
4. For each edge collection:
   a. Find all active edges where _from or _to == entity._id
   b. For each edge:
      i.  Set edge.expired = now  (expire old edge)
      ii. Create new edge with same data but pointing to version N+1's _id
          new_edge.created = now
          new_edge.expired = NEVER_EXPIRES
```

**Why re-create edges?** In ArangoDB, edge `_from` and `_to` fields are immutable after creation. When a vertex document is updated (new `_key` suffix or same `_key` with different `_rev`), edges must be re-created to maintain valid references. The edge-interval pattern treats every edge as a temporal fact: "this relationship was active from time T1 to time T2."

**Performance implication:** Updating a class with 10 connected edges requires 10 edge expirations + 10 edge creations = 20 write operations. For batch updates, this can be significant. The MDI-prefixed indexes on `[ontology_id, created, expired]` ensure that point-in-time queries remain fast despite the growing number of historical edges.

---

## 5. Referential Integrity Rules Summary

| Rule | Scope | Enforcement | PRD Ref |
|------|-------|-------------|---------|
| Expiring an entity MUST expire all connected edges | Within ontology | `expire_class_cascade()`, `update_entity()` | §5.3 FR-5.2 |
| Expiring an entity MUST expire cross-ontology edges pointing to it | Across ontologies | `DELETE /library/{id}` cascade logic | FR-8.13 |
| Document deletion MUST NOT cascade to ontology classes | Cross-domain | `DELETE /documents/{id}` only expires provenance edges | FR-8.14 |
| Ontology deprecation MUST check imports graph for dependents | Across ontologies | `DELETE /library/{id}` dry-run mode | FR-15.4 |
| Curation reject MUST expire connected edges | Within ontology | ⚠️ Currently calls `expire_entity()` which does NOT cascade — should call `expire_class_cascade()` | FR-4.2, §5.3 |
| Curation merge MUST redirect cross-ontology edges | Across ontologies | `execute_merge()` handles edge transfer | §6.7 |
| System reset MAY hard-delete everything | System-wide | `truncate()` on all collections | §7.2.1 |
| Registry entries are NEVER hard-deleted during normal operations | System-wide | Use `deprecate_registry_entry()`, not `delete_registry_entry()` | FR-8.13 |

---

## 6. Known Issues & Gaps

| # | Issue | Severity | Status | Description |
|---|-------|----------|--------|-------------|
| 1 | Curation reject doesn't cascade to edges | Medium | **Open** | `_apply_reject()` calls `expire_entity()` which only expires the class, leaving connected edges as dangling references. Should call `expire_class_cascade()` instead. |
| 2 | Properties not expired on class delete | Low | **By Design** | When a class is deleted, its `has_property` edges are expired but the property documents themselves remain. This is intentional — properties may be reassigned — but can lead to orphan property accumulation. Quality metrics flag this. |
| 3 | `extracted_from` edge direction semantics | Low | **Documented** | `_from = ontology_classes/{key}`, `_to = documents/{doc_id}`. This means "class was extracted from document." When traversing from document to classes, use `INBOUND` traversal. |
| 4 | `equivalent_class` edges on merge not always created | Low | **Open** | After a merge, the system should create an `equivalent_class` edge between the winning and losing entities for OWL completeness. Currently only edge transfer happens. |
| 5 | TTL garbage collection not verified | Low | **Open** | `ttlExpireAt` is set on expired entities per PRD, but the TTL index configuration and actual garbage collection have not been verified in production. |

---

## 7. Decision Tree: Which Deletion Method?

```
Is this a system reset (dev/demo fresh start)?
├── YES → Hard delete (truncate) — POST /admin/reset or /admin/reset/full
│         All data destroyed. No history. Requires ALLOW_SYSTEM_RESET=true.
│
└── NO → Is this a document being removed?
    ├── YES → Hard delete document + chunks. Expire provenance edges.
    │         Leave ontology classes intact. — DELETE /documents/{id}
    │
    └── NO → Is this an ontology being retired?
        ├── YES → Temporal soft-delete with cascade analysis.
        │         Expire all entities + edges. Deprecate registry.
        │         Check imports graph for dependents first.
        │         — DELETE /library/{ontology_id}?confirm=true
        │
        └── NO → Is this a single class/property being removed?
            ├── YES → Temporal soft-delete with edge cascade.
            │         Expire entity + all connected edges.
            │         — DELETE /ontology/{id}/classes/{key}
            │
            └── NO → Is this a curation rejection?
                ├── YES → Temporal soft-delete with edge cascade.
                │         Same as class delete — expire entity + edges.
                │         Record decision in curation_decisions.
                │
                └── NO → Is this a curation edit/approve?
                    └── YES → Temporal version update.
                              Old version expired. New version created.
                              All edges expired and re-created for new version.
                              Record decision in curation_decisions.
```
