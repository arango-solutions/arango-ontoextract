# Multi-Source Ontology Alignment & Source-Change Cascade — Feature Spec

> **Status:** Planned (no code yet). Drafted July 2026 for the **Contextual Data Fabric** project, which depends on AOE for its M3 (Ontology Alignment) module. Fabric-side requirements: `contextual-data-fabric/docs/architecture/_repo-enhancements/ontology-extractor-structured.md` (RE-2 alignment API, RE-4 source-change cascade, RE-5 change-control hooks) and `module-03-ontology-alignment/specification.md`.
>
> **Why this doc exists:** the README Features table is explicit that multi-source alignment is **Not built** — "a build, not a confirm." This spec defines that build in terms of the primitives AOE already has, so the work is orchestration, not greenfield.

---

## Part A — Multi-source ontology alignment (fabric RE-2 / M3)

### A.1 Problem

AOE extracts one ontology per source (unstructured corpus, SQL schema, ArangoDB schema — all → OWL/SHACL). The fabric needs N independently-built **source ontologies** reconciled into one **master conceptual model**: `customer account` (Postgres) vs `client account` (docs corpus) vs `account` (warehouse) must resolve to a single concept, with taxonomies wired so there are no orphan classes, and with every master element traceable to the source elements it came from.

### A.2 What exists today (the building blocks)

| Primitive | Where | Role in alignment |
|-----------|-------|-------------------|
| Effective-graph union + import **conflict flagging** | OWL/TTL import path | Overlay N source ontologies into one working view; surface clashes |
| Cross-tier **overlap-candidate finder** | Cross-Tier ER (Partial) | Propose "these two classes may be the same concept" candidates |
| **Pairwise class merge** | Curation workspace + `/api/v1/curation/merge`, `/api/v1/er/merge` | Execute a single accepted equivalence |
| ER pipeline (blocking + vector similarity + scoring) | Extraction pipeline ER agent | Score candidate equivalences (`ER_VECTOR_SIMILARITY_THRESHOLD`) |
| Belief revision (verdicts, Levi identity, Revisions Inbox) | §6.16 / ADR-008 | Absorb a *new* source into an *existing* master iteratively |
| Temporal substrate (versions, snapshots, diffs) | ADR-002 | Version the master; make every alignment pass auditable/rewindable |
| Staging → Production promotion | Curation flow | The human/agent "bless" step |

**The missing piece is orchestration:** nothing walks N source ontologies, generates + scores equivalence/subsumption candidates *between* them, drives accept/reject per policy, and emits a reconciled master with provenance.

### A.3 Requirements

| ID | Requirement |
|----|-------------|
| MSA.1 | **Alignment run:** `align(source_ontology_ids[], master_id?, policy) -> alignment_run` — N source ontologies in; if `master_id` is given, align *into* the existing master (incremental); else bootstrap a new master. |
| MSA.2 | **Candidate generation:** reuse the overlap-candidate finder + ER scoring across *all* source pairs (not just cross-tier) to propose `equivalent-class`, `equivalent-property`, and `subclass-of` candidates with confidence scores and evidence (name similarity, vector similarity, shared-property overlap, instance overlap where available). |
| MSA.3 | **Diff/delta report:** for each source ontology vs the (draft) master: *new concepts*, *matched concepts* (with candidate mapping), *conflicts* (same name, incompatible definitions — reuse import conflict flagging). This is the artifact the fabric's M3 surfaces to humans. |
| MSA.4 | **Accept/reject per policy:** auto-accept above a per-deployment confidence threshold, queue the rest for curation — through the existing Revisions Inbox pattern, so alignment decisions and belief revisions share one review surface. Target the fabric's "human confirms ~2%" demo story. |
| MSA.5 | **Master emission with provenance:** the master is a first-class ontology on the temporal substrate; every master element carries `derivedFrom` links to its source elements (source ontology + element + alignment run). Export via the existing TTL/JSON-LD path. |
| MSA.6 | **Iterative refinement:** re-running `align` with an updated source ontology converges — unchanged elements are no-ops, changes flow through the belief-revision verdicts (REINFORCED / REFINED / CONTRADICTED / …) rather than a from-scratch rebuild. |
| MSA.7 | **API + MCP surface:** REST endpoints plus MCP tools (mirroring the belief-revision tool pattern) so the fabric's M3 — or any agent — can drive alignment programmatically. |

### A.4 Phasing

- **MSA-P1 (fabric Phase 2):** MSA.1–MSA.5 for two sources (one structured + one unstructured) — replaces the fabric's hand-constructed Phase-1 master.
- **MSA-P2 (fabric Phase 2/3):** MSA.6 iterative refinement; ≥3 sources; MSA.7 MCP tools.
- *(Fabric Phase 1 needs nothing from this spec: the plan of record is a hand-constructed master, authored in the existing curation workspace.)*

### A.5 Non-functional

Precision-first (a wrong auto-merge in the master poisons every downstream mapping — same failure mode as ER over-merge); every alignment decision auditable (who/what accepted, on what evidence, reversible via the temporal substrate); no orphan classes in the emitted master (structural validation gate before promotion).

---

## Part B — Source-change cascade (fabric RE-4)

### B.1 Problem

Belief revision today triggers when **new evidence arrives via an extraction run**. It does not yet trigger when a **source changes underneath the ontology**: a table dropped from a schema, a document deleted from the corpus, a column renamed. The fabric needs source lifecycle events to cascade: elements whose *only* support came from a removed source get retraction proposals; elements with remaining support get weakened-evidence annotations.

### B.2 Requirements

| ID | Requirement |
|----|-------------|
| SCC.1 | **Source snapshot fingerprinting:** persist a fingerprint (per-element hash) of each ingested source (schema bundle or document set) so re-ingestion computes a source-level diff (added / removed / changed elements). For relational sources this pairs with `relational-schema-analyzer` incremental re-analysis (fabric `schema-analyzers-metadata-sampling` RE-4). |
| SCC.2 | **Dependency walk:** from a changed/removed source element, walk provenance links to every dependent ontology element (and, via Part A's `derivedFrom`, into the master). |
| SCC.3 | **Cascade verdicts:** feed affected elements through the existing belief-revision verdict machinery — sole-support removed → **retraction proposal** (Levi-identity contraction, never hard delete); partial-support removed → evidence-weakened annotation; changed → CONTRADICTED/REFINED path as today. Structural retractions on approved classes go to the Revisions Inbox, same as any other revision. |
| SCC.4 | **Trigger surface:** a `source-changed` API/MCP entry point (called by re-ingestion, by the fabric's connectors, or manually) — no requirement for AOE to poll sources itself. |

### B.3 Phasing

- **SCC-P1 (fabric Phase 3):** SCC.1–SCC.4 for the two P1 source types (relational bundle + document corpus).

---

## Part C — Change-control hooks (fabric RE-5 remainder)

Time-travel, snapshots, and diffs exist; staging→production promotion exists. The remaining gap is exposing **bless-before-release programmatically**: a `promote(ontology_id, version, approver)` API/MCP tool with policy hooks (auto-promote below a risk threshold, require human sign-off above it), so the fabric's change-control story ("a human or agent blesses expansions") is drivable by agents, not only through the workspace UI. Small surface; ride along with MSA.7.

---

## Open questions

1. **Alignment algorithm shape:** greedy pairwise merge driven by the overlap-candidate finder vs cluster-then-merge (build candidate clusters across all N sources first, then resolve each cluster to one master concept). Cluster-then-merge handles the 3+-source case better; greedy is simpler for MSA-P1's two sources.
2. **Where the master lives:** same ArangoDB deployment as the source ontologies (current tier model suggests yes — the master is effectively a new tier) vs a separate database per fabric deployment.
3. **Equivalence semantics in OWL:** `owl:equivalentClass` between master and source elements vs collapsing into one class with `derivedFrom` provenance edges (PGT storage favors the latter; export can synthesize the former).
4. **Instance-level evidence:** should MSA.2 use A-box overlap (shared resolved entities across sources) as an alignment signal in MSA-P1, or is that P2 (it drags in the AER integration currently deferred)?
