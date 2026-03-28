# ADR 003: Entity Resolution Integration Strategy

**Status:** Accepted
**Date:** 2026-03-01
**Decision Makers:** AOE Core Team

---

## Context

AOE needs entity resolution (ER) to detect and merge duplicate or overlapping ontology concepts — both within a single ontology and across tiers (local vs. domain). Duplicates arise from:

- LLM extraction producing similar but non-identical concepts across passes
- Multiple ontologies defining the same real-world concept with different labels or URIs
- Tier 2 local extensions that overlap with Tier 1 domain ontologies

Two approaches were evaluated:

1. **Custom ER implementation** — build blocking, scoring, and clustering from scratch using AQL and Python
2. **`arango-entity-resolution` library** — use the existing ArangoDB-native ER library that provides configurable blocking strategies, field-level scoring, WCC clustering, and a MCP server interface

## Decision

We chose to integrate the **`arango-entity-resolution` library** rather than building custom ER logic.

## Rationale

### Library Capabilities

The `arango-entity-resolution` library provides:

| Feature | Description |
|---------|-------------|
| Blocking strategies | ArangoSearch BM25, vector similarity, exact match, phonetic |
| Field-level scoring | Configurable similarity functions per field (Jaro-Winkler, Levenshtein, cosine, exact) |
| WCC clustering | Weakly connected component analysis with GAE backend support |
| Golden records | Merge strategies (most_complete, most_recent, source_priority) |
| MCP server | Pre-built MCP tools for ER operations |
| Explain match | Field-by-field similarity breakdown for transparency |

### Custom ER Would Require

| Component | Estimated Effort |
|-----------|-----------------|
| Blocking strategy framework | 2–3 weeks |
| Field-level similarity scoring | 1–2 weeks |
| WCC clustering (Python + GAE backends) | 1–2 weeks |
| Golden record merging | 1 week |
| Configuration management | 1 week |
| MCP tool exposure | 1 week |
| **Total** | **7–10 weeks** |

### Why the Library Wins

1. **Time savings.** The library provides 7–10 weeks of functionality out of the box. AOE's ER needs (label matching, description similarity, URI comparison) are well within the library's capabilities.

2. **ArangoDB-native.** The library stores candidates in `similarTo` edges, clusters in `entity_clusters`, and golden records in `golden_records` — all standard ArangoDB collections using AQL. No external service needed.

3. **GAE integration.** On ArangoDB Enterprise (self-managed or AMP), the library's WCC clustering automatically uses the Graph Analytics Engine for distributed graph algorithms. On local Docker, it falls back to in-memory Python Union-Find.

4. **MCP server.** The library includes MCP tools that AOE can proxy through its own MCP server, providing ER capabilities to external AI agents without additional implementation.

5. **Extensibility.** AOE adds one custom scoring dimension — topological similarity (shared graph neighbors) — on top of the library's field-level scoring. This is a small extension, not a full reimplementation.

## Consequences

### Positive

- Significant development time saved (7–10 weeks of ER infrastructure)
- Production-tested blocking, scoring, and clustering logic
- Automatic GAE integration for Enterprise deployments
- MCP tools included — ER operations exposed to AI agents
- Field-by-field `explain_match` provides transparency for domain experts

### Negative

- External dependency — library updates may require AOE compatibility testing
- Library's data model (collections, field names) must be adopted, slightly constraining schema choices
- Custom scoring dimensions (topological similarity) must be integrated via the library's extension points rather than directly

### Mitigations

- Pin library version in `pyproject.toml` and test on upgrade
- Topological similarity scoring is implemented as an AOE-specific service that feeds scores into the library's candidate pipeline
- Library collections (`similarTo`, `entity_clusters`, `golden_records`) are created via a dedicated migration
