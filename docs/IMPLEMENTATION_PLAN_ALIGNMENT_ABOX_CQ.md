# Implementation Plan — Alignment, A-box & Competency Questions

**Streams:** 20 (Multi-Source Ontology Alignment), 21 (Assertion-Graph / A-box Extraction),
22 (Use-Case / Competency-Question Requirements).
**PRD:** §6.17 / §6.18 / §6.19 (FR-17.\*, FR-18.\*, FR-19.\*).
**SOTA basis:** `docs/research/alignment-abox-cq-sota-2026-07.md`.
**Status source of truth:** `docs/REMAINING_WORK_PLAN.md` (this doc is the *build-level*
decomposition of those three streams; keep the stream task tables as the status ledger).
**Date:** 2026-07-14.

> This plan is PR-sized and buildable. Each PR names concrete file targets, dependencies,
> acceptance criteria, and tests. Migration numbers continue from `026_*` (next free: `027`).
> New top-level API router `alignment.py` mirrors `api/er.py`; ontology-scoped surfaces
> (requirements, individuals) go in the `api/ontology/` package.

---

## 0. Overview

### 0.1 Why these three interlock
- **Competency questions (S22)** define *what the ontology must answer* → they **scope**
  extraction and the alignment master, and **select** which A-box individuals matter
  (FR-19.9).
- **A-box (S21)** is the instance layer; it needs a **T-box** (from extraction or the
  aligned master) to ground against.
- **Alignment (S20)** produces the reconciled **master T-box** from N sources; CQs keep it
  small and use-case-scoped (CDF M3 P1).

They share one substrate: **entity embeddings + ArangoDB vector search** (alignment
candidate retrieval, the A-box schema retriever, and CQ term matching all use it). Build
that substrate **once, first**.

### 0.2 Build order & milestones

| Milestone | Contents | Demoable exit |
|-----------|----------|---------------|
| **M0 — Shared foundation** | SF.1 entity embeddings + vector index, SF.2 shared matcher | `POST`-retrieve top-k similar classes across two ontologies via vector search |
| **M1 — Capability P1 (parallelizable across ≤3 devs)** | S22 sprints A–B; S21 sprints A–B; S20 sprint A (P1) | Each capability works end-to-end on a seeded fixture, independently |
| **M2 — Wire the interlocks** | S22 sprint C (scope + gate), S21 sprint C (validate/curate/export), CQ→alignment/A-box scoping (FR-19.9) | A use-case spec scopes an extraction, an A-box is produced + validated, an aligned master is materialized and curated |
| **M3 — Alignment P2/P3 + feedback loops** | S20 sprints B–C, S22 gap-feedback, S21 open-mode → belief revision | Coherent master with modular repair + eval harness; unanswerable CQs feed the backlog |

**Sequencing note:** M1 can run 3 tracks in parallel — they touch disjoint services
(`competency_questions.py`, `abox_extractor.py`, `alignment.py`) once M0 lands. If staffing
is single-track, do **M0 → S20 P1** first (CDF M3 headline), then S21, then S22 — but you
lose the "CQs scope everything" benefit until S22 lands, so prefer the parallel M1.

### 0.3 Conventions
- **Flags:** every new pipeline behavior is flag-gated in `backend/app/config.py`
  (`alignment_enabled`, `extract_abox`, `cq_scope_injection_enabled`), default OFF, so
  nothing changes for existing runs until turned on.
- **Temporal:** all new vertex/edge collections use the standard temporal fields
  (`created` / `expired` = `NEVER_EXPIRES`) and go through the temporal service.
- **Tests:** backend unit (mock LLM + mock DB), integration (seeded ArangoDB), frontend Jest;
  each PR ships green + ruff + mypy clean; version-parity guard applies on any release.

---

## 1. Shared Foundation (SF)

### SF.1 — Ontology entity embeddings + vector index
- **Files:** `backend/migrations/027_ontology_entity_vector_index.py` (HNSW/FAISS-IVF vector
  index on `ontology_classes.embedding` + `ontology_object_properties` / `ontology_datatype_properties`);
  new `backend/app/services/ontology_embeddings.py` (embed `label + description`, reusing the
  chunk embedding provider from §6.1; optional LLM natural-language *definition* enrichment
  behind `ontology_embedding_enrich_definitions` — GenOM-style — off by default; batch upsert
  of `embedding` onto entities).
- **Deps:** none (embedding provider + vector search already exist for chunks).
- **Acceptance:** every live class/property can carry an `embedding`; an AQL vector-search
  returns top-k cross-ontology neighbours by cosine.
- **Tests:** unit (embedding build + projection + enrich-flag off/on), integration (seed 2
  ontologies, vector search round-trip). Reuse the `bench_effective_ontology.py` seeding
  pattern for the integration fixture.

### SF.2 — Shared candidate matcher (generalize the ER scorer)
- **Files:** new `backend/app/services/matching.py` — lift the lexical (Jaro-Winkler) +
  token-overlap scoring out of `er.py::get_cross_tier_candidates` into a reusable,
  N-source-aware blend `score_candidate(a, b) → {lexical, structural, embedding, combined}`;
  `er.py` cross-tier path refactored to call it (no behavior change, pinned by existing tests).
- **Deps:** SF.1 (for the embedding-cosine signal).
- **Acceptance:** the scorer runs on arbitrary entity pairs from ≥2 ontologies; ER cross-tier
  behavior unchanged.
- **Tests:** scoring pins (each signal + blend); ER regression stays green.

---

## 2. Stream 22 — Competency-Question Requirements

### Sprint 22A — Spec + authoring
**CQ-PR1 · Requirements data model + CRUD**
- **Files:** `backend/migrations/028_ontology_requirements.py` (`ontology_requirements`
  collection); `backend/app/db/requirements_repo.py`; `backend/app/api/ontology/requirements.py`
  (CRUD, wired into the `api/ontology/__init__.py` router); Pydantic models in
  `backend/app/models/`.
- **Model:** ORSD-style — `{ purpose, scope, intended_uses[], use_cases:[{ name, priority,
  competency_questions:[{ id, text, priority, expected_answer_shape, query?, status }] }] }`,
  attached to a target `ontology_id` (or extraction run).
- **Deps:** none. **Acceptance (FR-19.1):** attach/read/update/delete a spec on an ontology.
  **Tests:** repo + API CRUD.

**CQ-PR2 · LLM-assisted CQ authoring + pitfall lint**
- **Files:** `backend/app/services/competency_questions.py` (`suggest_cqs(purpose, samples)`
  → candidate CQs; `lint_cq(text)` VSPO-style pitfall check); frontend
  `frontend/src/components/workspace/RequirementsOverlay.tsx` (write CQs, accept LLM
  suggestions one-by-one, see pitfall warnings) + context-menu entry.
- **Deps:** CQ-PR1. **Acceptance (FR-19.2):** LLM suggests, **human must accept** each CQ;
  malformed CQs flagged, never auto-committed. **Tests:** service unit (mock LLM) + component.

### Sprint 22B — Formalize + validate
**CQ-PR3 · CQ → AQL formalization**
- **Files:** extend `competency_questions.py` (`formalize_cq(cq, ontology) → AQL`,
  LLM-assisted, stored on the CQ; human-verified toggle). SPARQL variant deferred to the RDF
  export path.
- **Deps:** CQ-PR1. **Acceptance (FR-19.3):** each CQ carries a runnable parameterized AQL.
  **Tests:** formalization pins (mock LLM) + AQL validity check via `validate-aql`.

**CQ-PR4 · Coverage validation + report**
- **Files:** `backend/app/services/cq_coverage.py` (run each CQ's AQL → `answerable | partial |
  unanswerable` + the specific missing classes/properties/instances); `POST /ontology/{id}/coverage`
  in `api/ontology/requirements.py`.
- **Deps:** CQ-PR3. **Acceptance (FR-19.5):** coverage report with % satisfied + gap list.
  **Tests:** coverage classification on a seeded ontology (answerable + gap cases).

### Sprint 22C — Drive + gate (interlock)
**CQ-PR5 · Scope injection into extraction (all adapters)**
- **Files:** extend `backend/app/services/ontology_context.py` (emit a CQ term set as
  *required/priority concepts*, mirroring the H.17 effective-context prepend); wire into
  `services/extraction.py`, the relational adapter (`relational_schema_extraction.py`), and the
  ArangoDB schema adapter (`schema_extraction.py`). Flag `cq_scope_injection_enabled`.
- **Deps:** CQ-PR1. **Acceptance (FR-19.4, FR-19.7):** CQ terms appear in extraction prompts
  across unstructured / relational / graph adapters. **Tests:** each adapter sees CQ terms;
  off-flag = byte-identical prompt.

**CQ-PR6 · Gap feedback + dashboard tile + release gate**
- **Files:** route unanswerable-CQ gaps to belief revision / backlog (`services/revision_agent.py`
  or a new backlog collection); `frontend/src/components/dashboard/CQCoverageTile.tsx`; expose
  coverage as a Release Readiness signal (consumed by Stream 19 when built).
- **Deps:** CQ-PR4. **Acceptance (FR-19.6, FR-19.8, FR-19.11):** gaps become actionable items;
  tile shows coverage over time; a release can require ≥N% priority CQs answerable. **Tests:**
  gap routing + tile render + gate threshold.

---

## 3. Stream 21 — Assertion-Graph (A-box) Extraction

### Sprint 21A — Model + grounded extraction
**AB-PR1 · A-box data model + migration**
- **Files:** `backend/migrations/029_abox_collections.py` (`ontology_individuals` vertex;
  `rdf_type` edge; `individual_assertion` edge for object-property assertions; datatype values
  as fields — all temporal); `backend/app/db/individuals_repo.py`.
- **Deps:** none. **Acceptance (FR-18.1):** individuals persist, typed to a T-box class, with
  assertions, temporally versioned + org/ontology-scoped. **Tests:** repo CRUD + temporal.

**AB-PR2 · Schema retriever + grounded extraction node**
- **Files:** `backend/app/services/schema_retriever.py` (RAG over SF.1 vector index → the
  text-relevant T-box slice, EDC-style); new LangGraph node
  `backend/app/extraction/agents/abox_extractor.py`; wire into `extraction/pipeline.py` behind
  `extract_abox`; prompt in `backend/app/extraction/prompts/abox_extraction.py`.
- **Deps:** SF.1, AB-PR1. **Acceptance (FR-18.2, FR-18.3):** schema-guided mode emits typed
  individuals + assertions referencing existing T-box URIs; open mode proposes new
  types/individuals (feeds §6.16). **Tests:** grounded extraction on a fixture (mock LLM);
  retriever returns only relevant T-box fragments.

### Sprint 21B — Canonicalize + provenance + routing
**AB-PR3 · Canonicalization / entity linking (reuse ER)**
- **Files:** extend `services/er.py` to cluster *individuals* (blocking → SF.2 scoring →
  union-find → golden individual), across chunks + documents.
- **Deps:** AB-PR1, SF.2. **Acceptance (FR-18.4):** coreferent mentions collapse to one
  individual. **Tests:** dedup a fixture with 3 mentions → 1 golden.

**AB-PR4 · Span provenance + multi-domain routing**
- **Files:** stamp `extracted_from` with `{doc_id, chunk_id, char_span}` on every individual +
  assertion; route each individual to the correct domain ontology using the Stream 16
  `domain_tag` (`services/domain_detection.py`); cross-domain relationships → cross-ontology
  edges.
- **Deps:** AB-PR2. **Acceptance (FR-18.5, FR-18.6):** every fact traceable to a span;
  individuals partition per domain ontology. **Tests:** multi-domain fixture routes correctly;
  provenance present on all assertions.

### Sprint 21C — Validate + curate + export
**AB-PR5 · Constraint validation + hallucination control**
- **Files:** validate assertions against §6.14 OWL/SHACL constraints via
  `services/ontology_rule_engine.py`; reject/flag individuals not grounded in a span or
  referencing a non-existent T-box term.
- **Deps:** AB-PR4. **Acceptance (FR-18.7, FR-18.8):** violations flagged (not dropped);
  ungrounded rejected/flagged. **Tests:** cardinality/datatype violation + ungrounded-reject.

**AB-PR6 · Instance lens + metrics + API + export**
- **Files:** workspace **instance lens** (`frontend/src/components/workspace/` + a canvas lens);
  `GET /ontology/{id}/individuals`, `GET /individuals/{id}` (in `api/ontology/individuals.py`);
  A-box quality metrics in `services/quality_metrics.py`; RDF export (`owl:NamedIndividual` +
  `rdf:type` + assertions) in `services/export.py`.
- **Deps:** AB-PR1. **Acceptance (FR-18.9, FR-18.10, FR-18.11, FR-18.12):** individuals
  curatable (approve/reject/edit, temporal), metrics surfaced, exportable as RDF. **Tests:**
  API + export round-trip + metrics.

---

## 4. Stream 20 — Multi-Source Ontology Alignment

### Sprint 20A — P1 core (embedding retrieval + selective LLM + master)
**AL-PR1 · Alignment session model + API skeleton**
- **Files:** `backend/migrations/030_alignment_sessions.py` (`alignment_sessions` +
  `correspondences` collections); `backend/app/db/alignment_repo.py`; new top-level router
  `backend/app/api/alignment.py` (`POST /alignment/sessions`, `GET .../candidates`,
  `POST .../candidates/{id}/{accept|reject|edit}`, `POST .../materialize`, `GET .../master`),
  registered in `api/__init__.py`.
- **Deps:** none. **Acceptance (FR-17.1):** create a session over N≥2 ontology ids;
  re-runnable, auditable. **Tests:** session CRUD + API routing.

**AL-PR2 · Embedding retrieval + multi-signal scoring**
- **Files:** `backend/app/services/alignment.py` — for each source entity, SF.1 top-k retrieval
  → SF.2 scored candidate correspondences (no LLM yet).
- **Deps:** SF.1, SF.2, AL-PR1. **Acceptance (FR-17.2, FR-17.3):** candidate set with per-signal
  + combined scores. **Tests:** candidate generation on a seeded 2-ontology fixture.

**AL-PR3 · Selective LLM adjudication**
- **Files:** extend `alignment.py` — only *borderline*-band pairs go to an LLM
  equivalence/subsumption judge; auto-accept high / auto-reject low; emit correspondence type
  (`owl:equivalentClass` / `rdfs:subClassOf` / `skos:relatedMatch`) + confidence + evidence.
  Flag `alignment_enabled`; borderline band configurable.
- **Deps:** AL-PR2. **Acceptance (FR-17.4):** LLM invoked only on borderline pairs (assert call
  count). **Tests:** band routing + type emission (mock LLM).

**AL-PR4 · Conflict resolution → master materialization + provenance**
- **Files:** extend `ontology_effective._detect_conflicts` from flag-only to accept/reject/merge
  **decisions**; `alignment.py::materialize_master` writes a new registry entry + `owl:equivalentClass`
  edges + `source_ontology_id[]` provenance (temporal, ETag parity with `/effective`).
- **Deps:** AL-PR3. **Acceptance (FR-17.6, FR-17.7):** a coherent master is written with
  provenance + equivalence axioms. **Tests:** master-write correctness + provenance + conflict
  resolution.

**AL-PR5 · Bounded human confirmation UI (DualLoop)**
- **Files:** `frontend/src/components/workspace/AlignmentReviewOverlay.tsx` — borderline
  correspondences sorted by impact; accept/reject/edit; active-learning re-rank of remaining
  pairs after each decision.
- **Deps:** AL-PR3. **Acceptance (FR-17.8):** curator confirms only borderline; list re-ranks;
  ~2% confirm target on a use-case-scoped master. **Tests:** overlay flow + re-rank.

**AL-PR6 · API finalize + MCP tools + P1 end-to-end tests**
- **Files:** finalize `api/alignment.py`; MCP tools in `backend/app/mcp/tools/alignment.py`
  (`align_ontologies`, `list_correspondences`, `accept`/`reject_correspondence`,
  `materialize_master`).
- **Deps:** AL-PR1–5. **Acceptance (FR-17.12, FR-17.13):** full P1 flow via API + MCP.
  **Tests:** end-to-end P1 (seed 2 ontologies → candidates → confirm → master).

### Sprint 20B — P2 (repair + ensemble + hallucination)
**AL-PR7 · Incoherence detection + minimally-destructive modular repair**
- **Files:** extend `services/ontology_rule_engine.py` with AML core-fragment extraction +
  repair that prefers removing low-confidence correspondences; report every removal.
- **Deps:** AL-PR4. **Acceptance (FR-17.5):** master is coherent; removals reported, never
  silent. **Tests:** planted incoherence repaired minimally.

**AL-PR8 · Classical-anchor ensemble + hallucination control**
- **Files:** optional LogMap/AML signal adapter (`services/matching.py` ensemble hook);
  OAEI-LLM-style validation that every LLM correspondence has a grounded source anchor;
  disagreements flagged for humans.
- **Deps:** AL-PR3. **Acceptance (FR-17.9, FR-17.10):** disagreements prioritized; ungrounded
  never auto-accepted. **Tests:** disagreement prioritization + ungrounded flag.

### Sprint 20C — P3 (eval + scale)
**AL-PR9 · Evaluation harness**
- **Files:** `benchmarks/operations/bench_alignment.py` — P/R/F1 vs a reference alignment +
  interaction-count-vs-F-measure curve (OAEI-Interactive style); seeded fixture.
- **Deps:** AL-PR6. **Acceptance (FR-17.11):** metrics + human-effort curve reported.

**AL-PR10 · Iterative refinement (RE-3)**
- **Files:** re-align on source change; dependency-directed cascade (overlaps belief-management
  RE-4). **Deps:** AL-PR4. **Acceptance:** a source edit re-triggers a scoped re-alignment.

---

## 5. Cross-cutting

### 5.1 Migrations added
`027` entity vector index · `028` ontology_requirements · `029` A-box collections ·
`030` alignment sessions. Each idempotent, guarded, with a migration test (per the existing
migration-test pattern).

### 5.2 Config flags (all default OFF)
`ontology_embedding_enrich_definitions`, `cq_scope_injection_enabled`, `extract_abox`,
`alignment_enabled` (+ borderline-band bounds, embedding top-k, confirm-target %).

### 5.3 Test & eval strategy
- Unit: mock LLM + mock DB for every service; scoring/formalization/coverage pins.
- Integration: seed ArangoDB (reuse `bench_effective_ontology.py` seeding) for vector search,
  A-box routing, alignment end-to-end.
- Eval harnesses: `bench_alignment.py` (P/R/F1 + interaction curve); CQ coverage % as an
  ongoing quality-dashboard metric; A-box grounding-rate metric.
- Hallucination: OAEI-LLM-style categories for both alignment correspondences and A-box
  assertions.

### 5.4 Risks & mitigations
| Risk | Mitigation |
|------|-----------|
| LLM alignment hallucination (invented correspondences) | Grounded-anchor requirement + OAEI-LLM validation + human confirm on borderline (AL-PR8, AL-PR5) |
| Automated CQ generation unreliable (~25% usable) | Human-accept-required authoring; LLM only *suggests* (CQ-PR2) |
| A-box context blow-up on large T-box | EDC schema retriever injects only relevant fragments (AB-PR2) |
| Cost of LLM on large ontologies | Selective-LLM band (MILA pattern) — LLM only on borderline pairs; embeddings do the bulk (AL-PR3) |
| Modular repair is 2015-era vs LLM-generated axioms | Treat as P2; measure coherence before/after; prefer low-confidence removal (AL-PR7) |
| Multi-domain mis-routing of individuals | Reuse the already-shipped Stream 16 `domain_tag`; flag low-confidence routing for curation (AB-PR4) |

### 5.5 Definition of done (per stream)
- **S22:** a curated CQ spec scopes an extraction across all adapters and a coverage report
  gates a release.
- **S21:** extraction emits a grounded, canonicalized, per-domain A-box with span provenance,
  validated against constraints, curatable + exportable.
- **S20:** ≥2 sources → candidate correspondences → bounded human confirm → a coherent
  reconciled master with provenance + equivalence axioms; eval harness reports P/R/F1.
