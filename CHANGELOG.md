# Changelog

All notable changes to Arango-OntoExtract are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
The backend version is the single source of truth in `backend/app/__init__.py`.

## [Unreleased]

## [1.2.2] - 2026-07-14

Documentation / planning release. No functional code change.

### Documentation

- **`docs/IMPLEMENTATION_PLAN_ALIGNMENT_ABOX_CQ.md`:** a PR-sized, sequenced build plan for
  the new capability program — Stream 20 (alignment), Stream 21 (A-box extraction), Stream 22
  (competency-question requirements). Shared embedding/vector-search foundation (SF.1/SF.2),
  per-stream sprints with concrete file targets, dependencies, acceptance criteria mapped to
  FR IDs, a 4-milestone build order, migrations/flags/test-and-eval strategy, and a risks table.
- **PRD-sync (2026-07-14):** audited implementation vs PRD; 10 open drift gaps recorded to the
  shared `drift_alerts` collection (6 MISSING, 4 PARTIAL) — all correspond to planned Streams
  8/14/15/16/19/20/21/22, no surprises.

## [1.2.1] - 2026-07-13

Documentation / planning release. No functional code change — cut so the PRD and
implementation plan for the new capability program land on the release remote.

### Documentation

- **PRD §6.17 Multi-Source Ontology Alignment & Merging** (FR-17.1–17.13): discover
  correspondences across N independently-authored ontologies and merge into a reconciled
  master — embedding-retrieval + selective-LLM adjudication, minimally-destructive modular
  incoherence repair, bounded human confirmation, hallucination control. Realizes CDF M3 / RE-2.
- **PRD §6.18 Assertion-Graph (A-box) Extraction** (FR-18.1–18.12): schema-grounded instance
  + relation extraction (EDC-style) with canonicalization, span-level provenance, and
  per-domain routing via the Stream 16 `domain_tag`. Resolves Stream 15 SO.4.
- **PRD §6.19 Use-Case / Competency-Question-Driven Requirements** (FR-19.1–19.11): specify
  use cases as competency questions that both scope extraction and validate coverage,
  uniformly across relational / graph / semi-structured / unstructured sources.
- **Implementation plan:** Stream 20 upgraded to the SOTA-backed alignment design; new
  Stream 21 (A-box) and Stream 22 (competency-question requirements).
- **`docs/research/alignment-abox-cq-sota-2026-07.md`:** the cited deep-research report
  (2023–2025 SOTA, adversarially verified) behind the three new sections.

## [1.2.0] - 2026-07-13

Feature release on top of v1.1.0: domain detection & multi-ontology routing and
the slide-aware chunking foundation. Also corrects the frontend package version,
which had drifted from the backend single-source version.

### Added

- **Domain detection & multi-ontology routing (Stream 16 DD.1–DD.3):** segment a
  document into domain regions, tag chunks by domain, and surface a non-blocking
  multi-domain warning so a mixed-domain corpus no longer silently collapses into
  a single ontology.
- **Slide-aware chunking + topic units (Stream 17 CH.2–CH.5):** a
  slide-boundary-preserving deck chunker (never merges two slides into one chunk;
  splits a slide only past `chunk_max_tokens`; speaker notes become a distinct
  linked chunk), topic-unit grouping of continuation slides with topic-unit-aware
  extractor batching, categorize-then-chunk ordering, and `Settings`-driven
  size / overlap / slide-aware knobs. Non-deck documents chunk byte-identically.

### Changed

- **Relational extra requires `relational-schema-analyzer>=0.2`:** bumped from
  `>=0.1` to the corrected release that resolved the r2g<->RSA fork drift. 0.2.0
  adds an additive, omitted-when-empty `extra` passthrough on `Column`/`Table`
  (for downstream consumers like r2g's governance classification); AOE does not
  consume `extra`, so extracted ontologies are byte-identical to 0.1.0. Aligns
  AOE with r2g's `[ontology]` floor and avoids resolving the pre-fix 0.1.0.
- **Frontend package version corrected** to track the backend single-source
  version (it had been left at `1.0.0`).

### Documentation

- Recorded multi-source ontology alignment (Contextual Data Fabric M3 / AOE
  RE-2) as **not built** — a build, not a confirm — and surfaced AOE's shipped
  structured→ontology path (relational-schema-analyzer wiring) in the README
  and a new Stream 20 of the remaining-work plan.

## [1.1.0] - 2026-07-01

Incremental release on top of v1.0.0: one ingestion feature, a large internal
refactor of the ontology API into a package, documentation, and the fixes that
returned CI to green across the full pyramid. ~9 commits since `v1.0.0`.

### Added

- **Document-format-aware chunking (Stream 17 CH.1):** `doc_format` is now
  persisted on every chunk (with a legacy fallback that infers it from the
  parent document's MIME type), so the strategy selector routes text-only decks
  (`.pptx`) to the presentation extraction strategy instead of the prose default.
- **Relational (SQL) schema extraction → ontology:** point AOE at a relational
  database (PostgreSQL / MySQL / SQL Server / Snowflake / DuckDB / Databricks /
  CSV) via the optional `relational-schema-analyzer` library and reverse-engineer
  its tables → `owl:Class`, columns → `owl:DatatypeProperty`, foreign keys →
  `owl:ObjectProperty`, and NOT NULL / UNIQUE / CHECK-enum constraints → SHACL
  shapes, imported through the standard pipeline with per-class provenance. The
  full vertical ships in this release: the `list_relational_tables` preview and
  `extract_relational_schema` service (`app/services/relational_schema_extraction.py`),
  two POST endpoints (`/schema/relational/tables`, `/schema/relational/extract`),
  two MCP tools (`preview_relational_schema`, `extract_relational_schema`), and the
  `RelationalExtractionOverlay` opened from the canvas "Extract from Relational DB…"
  menu. Extracted ontologies are ordinary AOE ontologies, so all existing curation,
  temporal, import, export, and quality tooling applies unchanged.

### Changed

- **Ontology API package split (Stream 14 CQ.3):** the ~3.6k-line
  `app/api/ontology.py` module became a cohesive `app/api/ontology/` package of
  seven sub-routers (`library`, `domain`, `entities_read`, `mutations`,
  `imports_io`, `imports`, `schema_temporal`) plus a `_shared` module for
  cross-cutting dependencies. The public surface (`/api/v1/ontology`) and route
  precedence are unchanged; a new assembly regression test guards both.
- **Repository housekeeping:** moved stale top-level planning docs under `docs/`
  and stopped tracking generated PDF artifacts.
- **Documentation:** added the Medium article and one-pager, framing
  LLM-assisted release governance and the domain-segmentation / relational-schema
  roadmap.

### Fixed

- **CI lint tier:** narrowed python-arango `Result[...]` unions
  (`find`/`insert`/`graphs`/`edge_definitions`/`databases`) in the visualizer
  installer with `cast(...)`, clearing 14 mypy errors that had kept the pipeline
  red.
- **Router-assembly regression test:** re-based on `app.openapi()` so it is
  robust to FastAPI ≥ 0.139's lazy `_IncludedRouter` mounting (which made the
  previous `router.routes` introspection read back empty).

## [1.0.0] - 2026-06-19

First production release. Closes the remaining PRD tail on top of v0.4.0 —
Stream 3 constraint curation, the Stream 15 self-optimizing structural gate, and
the Stream 12 T6 workspace-switch performance work — completing the v1.0.0
functional scope (full PRD §6 feature coverage). ~10 commits since `v0.4.0`.

### Added

- **Constraint curation (Stream 3 I.7):** curator approve / reject / edit of OWL
  + SHACL constraints — three mutation endpoints
  (`POST /{id}/constraints/{key}/approve`, `.../reject`, `PUT .../{key}`) backed
  by temporal repo helpers, plus the `ConstraintManageRow` workspace UI. Closes
  Stream 3.
- **Self-optimizing structural gate (Stream 15 SO.1 + SO.2):** flag-gated
  in-pipeline structural gate (URI normalization + link recovery) between belief
  revision and filter, now enabled by default with a faithfulness-no-regression
  guarantee; post-write graph-health metrics (structural integrity, island
  detection) surfaced on the dashboard.
- **Arango AI brand theme:** green primary, Inter typeface, favicon.

### Changed

- **Workspace switch performance (Stream 12 T6):** added per-stage `ms_*`
  telemetry to `compute_effective_ontology` (the endpoint the canvas loads), then
  rewrote effective-graph subclass-cycle detection from an all-paths DFS to a
  linear-time three-colour DFS — 3000-class effective graph 1.9s → 42ms (~45×),
  the conflict-detection stage 1818ms → 3.7ms (~490×). `/edges` + `/effective`
  pagination is no longer needed. Adds a standalone real-DB profiling harness
  (`benchmarks/operations/bench_effective_ontology.py`).
- **Quality dashboard performance:** ~61s → ~9s, with busy states.
- **Ontology library performance:** batched library edge counts and snapshotted
  collection names.
- De-staled the implementation plan and remaining-work plan against the shipped
  code; fixed system-review errors.
- Integration-test ArangoDB host port is now configurable (`ARANGO_TEST_PORT`).

### Fixed

- Effective-graph cycle detection no longer mislabels an all-local subclass cycle
  as import-induced when a pre-cycle path edge originates in an import.

## [0.4.0] - 2026-06-01

The largest release since the initial cut: closes Belief Revision, Imports &
Composition, Entity Resolution, Constraints, Schema Extraction, Production Ops,
Image-Aware Extraction, the 5-tier CI pipeline, and the Sigma.js workspace core
— roughly 95% of the PRD. ~78 commits since `v0.3.0`.

### Added

- **Belief Revision (Stream 11, Phase 3):** Revisions Inbox overlay with inline
  detail panel, accept/reject/modify REST endpoints + service, background
  consolidation job with admin endpoints, four runtime safety guards, a Quality
  Dashboard "Revisions Activity" tile, and six MCP tools (IBR.14–IBR.21).
- **Imports, Composition & Dependencies (Stream 1):** `owl:imports` tracking and
  CRUD, registry-level imports DAG, bundled standard-ontology catalog, cascade-
  on-delete impact analysis, base-ontology selector on extraction, OWL exports
  preserving `owl:imports`, effective-ontology API with inline merge-conflict
  detection, effective-graph canvas rendering of imported entities, drag-and-drop
  import composition with undo toast, and import-aware extraction prompts.
- **Entity Resolution (Stream 2):** workspace "Find Duplicates" merge-candidates
  overlay with per-pair accept/reject/explain, run-scoped `/api/v1/er/` REST, and
  three MCP tools (hand-rolled scorer + union-find clustering + golden-record merge).
- **Constraints — OWL & SHACL (Stream 3):** extract → OWL restriction import →
  SHACL shapes import → materialize → API → temporal, rule-engine alignment,
  workspace constraint display, and Turtle restriction + SHACL shape exports.
- **Schema Extraction (Stream 5):** named-graph-aware reverse extraction from any
  ArangoDB with provenance + auto-imports, a workspace overlay, schema-validation
  / unique-index → SHACL reverse-engineering, and a cross-ontology schema-diff
  endpoint with a `SchemaDiffOverlay`.
- **Image-Aware Extraction (Stream 13):** visual asset inventory (PPTX/PDF/scanned
  pages), visual-aware chunking + `tier1_visual_aware` strategy, OpenAI Vision and
  on-prem Tesseract caption adapters, and visual-orphan run warnings.
- **Quality Dashboard (Stream 4):** event-tagged history snapshots (Q.2), trend
  sparklines (Q.3), gold-standard recall comparison (Q.4), and a client-measured
  curation throughput timer with `GET /curation/throughput` (Q.5).
- **Production Ops (Stream 7):** TTL garbage-collection retention, post-extraction
  Visualizer auto-install, OpenTelemetry tracing across the ingest→extraction
  pipeline, production alerting + hardened docker-compose, and an ops benchmark harness.
- **Testing & CI (Stream 6):** 5-tier GitHub Actions pipeline (lint → unit →
  integration → E2E → Docker smoke), frontend coverage gate, Codecov upload, and a
  Python 3.11/3.12 matrix.
- **Developer experience:** pre-commit (Tier A) + pre-push (Tier B) +
  branch-protection (Tier C) hooks, a solo-dev dual-push release workflow
  (`make release-to-org`), and a mock-fidelity rule.
- **Workspace:** keyboard navigation across sidebar rows (W.7), schema-diff overlay,
  and Playwright E2E coverage.
- **`make doctor` preflight:** validates config, ArangoDB, Redis, and the LLM +
  embedding keys/models with tiny live calls, printing actionable `[FAIL]`/`[WARN]`
  fixes — so misconfiguration surfaces up front instead of deep in the pipeline.

### Changed

- **Default extraction model is now `claude-sonnet-4-6`.** The previous
  `claude-sonnet-4-20250514` snapshot is deprecated (Anthropic retires it
  2026-06-15) and already returns HTTP 404 for many keys.
- Extraction performance: quality-snapshot cache on `/runs/{id}/cost` (T7),
  bulk-enriched `/runs` in 2 AQL calls (T8), and opt-in keyset pagination on
  `/classes` (T10).
- Version is now single-sourced from `backend/app/__init__.py`; onboarding docs
  are UI-first; added `CONTRIBUTING.md`; code-quality consolidation (CQ.1–CQ.4).

### Fixed

- **Security:** blocked AQL injection via the `paginate` `sort_field` parameter.
- **Extraction:** non-retryable provider HTTP errors (400/401/403/404) are now
  surfaced with actionable messages instead of being masked as "parse error" and
  retried 5×; the Visualizer asset loader is CWD-independent (no more
  `ModuleNotFoundError: No module named 'scripts'` under `make backend`).
- **Local dev:** restored the `/api` proxy rewrite and dev login bypass; proxied
  `/ready` + `/health` through Next so the backend status card works; capped the
  ontology-library request limit at 100 (was a 422).
- **Imports graph:** use a supported `uniqueEdges` option in the rooted traversal
  (was a 500 on the dependency overlay).

## [0.3.0] - 2026-05-13

Performance and importer-robustness release: `?include=summary` projections on
`/classes` + `/edges`, single-item `/edges/{key}` and `/properties/{key}`
endpoints, a client-side `ontologyDataCache` with in-flight dedup, RDF format
sniffing that overrides misleading extensions, and stage-level perf telemetry.
This baseline also unblocked BYOC packaging.

## [0.2.0] - 2026

Iterative Belief Revision substrate (Stream 11, Phases 1 + 2): `revision_meta`
collection, evidence-age/-count signals, confidence decay, the ontology rule
engine (R1–R4), touchpoint discovery, the mechanical verdict classifier, the LLM
revision agent, the Levi-identity supersede helper, and the LangGraph
belief-revision node behind a feature flag.

## [0.1.0] - 2026

Initial release: end-to-end extraction pipeline, ontology editor, pipeline
monitor, quality metrics, multi-document support, and the temporal substrate.

[1.2.2]: https://github.com/ArthurKeen/arango-ontoextract/releases/tag/v1.2.2
[1.2.1]: https://github.com/ArthurKeen/arango-ontoextract/releases/tag/v1.2.1
[1.2.0]: https://github.com/ArthurKeen/arango-ontoextract/releases/tag/v1.2.0
[1.1.0]: https://github.com/ArthurKeen/arango-ontoextract/releases/tag/v1.1.0
[1.0.0]: https://github.com/ArthurKeen/arango-ontoextract/releases/tag/v1.0.0
[0.4.0]: https://github.com/ArthurKeen/arango-ontoextract/releases/tag/v0.4.0
[0.3.0]: https://github.com/ArthurKeen/arango-ontoextract/releases/tag/v0.3.0
[0.2.0]: https://github.com/ArthurKeen/arango-ontoextract/releases/tag/v0.2.0
[0.1.0]: https://github.com/ArthurKeen/arango-ontoextract/releases/tag/v0.1.0
