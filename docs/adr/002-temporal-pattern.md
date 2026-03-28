# ADR 002: Temporal Versioning Pattern

**Status:** Accepted
**Date:** 2026-02-20
**Decision Makers:** AOE Core Team

---

## Context

AOE requires full version history for every ontology concept and relationship. Domain experts need to:

- View the ontology as it existed at any point in time (point-in-time snapshots)
- Compare two points in time (temporal diffs)
- Navigate history via a VCR timeline slider
- Revert to previous versions

Two established patterns for temporal graph versioning in ArangoDB were evaluated:

1. **Edge-interval time travel** — vertices and edges carry `created`/`expired` timestamp intervals; changes create new documents and expire old ones
2. **Immutable-proxy pattern** — stable ProxyIn/ProxyOut anchors with `hasVersion` edges pointing to immutable Entity snapshots; topology routes through proxies

Both patterns are production-proven in ArangoDB (the immutable-proxy pattern is used in the `network-asset-management-demo` reference implementation).

## Decision

We chose **edge-interval time travel** as the initial temporal versioning pattern, with the immutable-proxy pattern reserved as a Phase 6 optimization if edge re-creation costs become a bottleneck.

## Rationale

### Edge-Interval Pattern

Every versioned vertex and edge carries two fields:

| Field | Meaning |
|-------|---------|
| `created` | Unix timestamp when this version became active |
| `expired` | Unix timestamp when superseded, or `NEVER_EXPIRES` (sentinel: `sys.maxsize`) for current |

When an entity changes:
1. Current vertex gets `expired = now`
2. New vertex inserted with `created = now`, `expired = NEVER_EXPIRES`
3. All edges to/from old vertex are expired
4. New edges re-created pointing to/from new vertex

### Immutable-Proxy Pattern

Stable ProxyIn/ProxyOut anchors are never modified. Version changes only insert new Entity documents and `hasVersion` edges. Topology edges connect proxies (stable), not entities (versioned).

### Comparison

| Factor | Edge-Interval | Immutable-Proxy |
|--------|--------------|-----------------|
| Schema complexity | 2 extra fields per doc | 3 extra collections (ProxyIn, Entity, ProxyOut) + hasVersion edges |
| Query complexity | Simple `FILTER created <= @t AND expired > @t` | Requires multi-hop traversals through proxy → hasVersion → entity |
| Write cost on vertex change | Must expire and re-create all edges (O(edges)) | Only insert new entity + hasVersion edge (O(1)) |
| Read performance | Direct — entities are the graph nodes | Indirect — must resolve proxy → entity for each node |
| AQL simplicity | Standard range filters | Subqueries for version resolution at each traversal step |
| Collection count | No extra collections | 3 extra collections per versioned type |

### Why Edge-Interval Wins for AOE

1. **Ontologies change infrequently.** Unlike network asset management (where topology changes frequently), ontology edits happen during curation sessions — typically a few changes per session, not continuous streams.

2. **Edge counts per class are moderate.** A typical ontology class has 5–20 edges (subClassOf, hasProperty, related_to). Re-creating these on edit is sub-millisecond.

3. **Simpler AQL.** Point-in-time queries are a single `FILTER` clause rather than multi-hop proxy resolution. This makes the temporal API implementation straightforward and performant.

4. **Fewer collections.** No need for ProxyIn, ProxyOut, hasVersion collections — the existing ontology collections just gain two fields.

5. **MDI-prefixed indexes.** ArangoDB's multi-dimensional indexes on `[created, expired]` make interval range queries highly efficient, eliminating the performance concern.

## Consequences

### Positive

- Simpler schema: just add `created`/`expired` to existing collections
- Simpler queries: standard AQL range filters for temporal operations
- MDI-prefixed indexes ensure sub-500ms snapshot queries
- TTL indexes automatically garbage-collect historical versions
- Lower learning curve for developers

### Negative

- Edge re-creation cost on vertex changes — all edges to/from a changed vertex must be expired and re-created
- Storage growth — each change creates new vertex + new copies of all edges (mitigated by TTL aging)
- If edit frequency increases significantly (e.g., automated bulk edits), edge re-creation could become a bottleneck

### Mitigations

- TTL aging (90-day default retention) limits historical storage growth
- If edge re-creation becomes a bottleneck, migrate to the immutable-proxy pattern in Phase 6
- Edge re-creation is batched in a single AQL transaction for atomicity
- Monitoring: track edge re-creation counts and duration per edit to detect degradation early
