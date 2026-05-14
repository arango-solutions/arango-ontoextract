# ADR 008: Iterative Refinement & Belief Revision Substrate

**Status:** Accepted
**Date:** 2026-05-08
**Decision Makers:** AOE Core Team
**Context Branch:** main

---

## Context

AOE's extraction pipeline currently treats each document as an independent extraction event. When document `D2` arrives after `D1`:

1. `D1`'s extraction produced classes / properties / edges in the ontology.
2. Domain experts curated `D1`'s output.
3. `D2` is extracted and merged via Entity Resolution against the existing ontology.
4. **No backward pass occurs.** Conclusions made from `D1` are never revisited in light of `D2`'s evidence — even when `D2` directly contradicts, refines, or supersedes them.

This is a real-world need with established names in the literature: **abductive refinement**, **belief revision**, **iterative knowledge construction**, **continual KG refinement**. Without it, an ontology accumulates errors and stale assumptions as more documents arrive — and the curator's only recourse is to manually re-review every prior decision.

We need a controller that, when new evidence arrives, **decides what to do with each existing belief that the new evidence touches**: reinforce it, refine it, retract it, merge it with the new concept, or flag it for human review.

### Constraints

| Constraint | Implication |
|---|---|
| LLM tokens are expensive | Can't re-extract everything from scratch on each new doc |
| Curators have already invested effort | Approved beliefs must not be silently overwritten |
| Temporal history must be preserved | All revisions are versions, never destructive edits |
| External agents (MCP) must observe revisions | Revision lifecycle must be inspectable via API |
| Pipeline already orchestrated by LangGraph (ADR-005) | Add a new node, don't fork the architecture |
| Temporal versioning is edge-interval (ADR-002) | Revision = expire old version + insert new version |

### State of the Art (2024–2026, surveyed May 2026)

| Approach | Source | What we want to keep |
|---|---|---|
| **AGM belief revision** (Alchourrón–Gärdenfels–Makinson 1985) | Foundational | Three operators (expansion, contraction, revision via Levi identity); minimal-change postulate |
| **Truth Maintenance Systems** (Doyle 1979; de Kleer 1986) | Foundational | Justification-based dependency tracking; *current beliefs* vs *stale-but-derivable* |
| **TRAIL** (2025) | LLM + KG | Confidence-driven generate → validate → insert/prune; **re-evaluates previously inserted facts** when new evidence arrives; bounded session cache |
| **Evo-DKD** (Jul 2025) | LLM ontology evolution | Closed loop: every structured edit must be paired with a textual justification that the validator cross-checks |
| **Evontree** (Oct 2025) | LLM + ontology rules | Lightweight rules (subClassOf+synonym triangle, subClassOf transitivity, disjointness) detect internal contradictions cheaply |
| **HyDRA** (2025) | Neurosymbolic | Competency questions as verifiable contracts |
| **Self-Refine / Reflexion** (2023–2025) | Generic LLM | The generate → critique → refine control loop |
| **Graph-Native Cognitive Memory** (2026) | Versioned graph + AGM | Architectural template: AGM postulates over a versioned property graph with provenance edges, `Supersedes`-style status pointers, URI addressing, **safety-hardened consolidation** (published-item protection, circuit breakers, dry-run, cursor-resumable jobs) |

### Existing Substrate in AOE

Most of the infrastructure a belief revision system needs is **already present**:

| Belief-revision primitive | Already in AOE | Status |
|---|---|---|
| Versioned beliefs | Edge-interval temporal versioning (ADR-002) | Done |
| Provenance / justifications | `extracted_from` edges + per-assertion `evidence` (FR-13.1a) | Done |
| Confidence | 7-signal multi-dim scoring (§6.13.1) | Done |
| Status pointer | `expired = NEVER_EXPIRES` for current versions | Done |
| Pipeline orchestration | LangGraph (ADR-005) | Done |
| Curation reject cascade | Reject expires class + dependent edges | Done |
| Soft-delete with referential integrity | Temporal soft-delete | Done |
| MCP runtime tools | Existing MCP server | Extensible |
| Ontology rule engine (R1, R2, disjointness) | Partial — pre-curation filter checks some constraints | Gap |
| Evidence-age + evidence-count signals | Not computed | Gap |
| Confidence decay | Not implemented | Gap |
| Per-document "revisit affected beliefs" pass | Not implemented | **Core gap** |
| Background consolidation job | Not implemented | Gap |
| "Revisions inbox" curation surface | Not implemented | Gap |

## Alternatives Considered

### Alternative 1: Re-extract from scratch on each new document

Treat every new document as a fresh extraction over the full corpus.

| Pro | Con |
|---|---|
| Conceptually simple | O(N²) token cost — extracting 50 docs costs 50× the per-doc baseline |
| No new infrastructure | Destroys curation history (curators re-review the same decisions) |
| | Doesn't scale past ~10 documents per ontology |

**Rejected.** Cost-prohibitive at scale; destroys human work.

### Alternative 2: LLM-agent-only revision (Self-Refine + ER)

A single LLM agent reviews every existing belief against every new chunk, producing accept/revise/retract verdicts.

| Pro | Con |
|---|---|
| Maximal semantic understanding | Expensive — every belief × every chunk is O(B × C) LLM calls |
| Handles novel revision types | No structural awareness; can violate ontology constraints |
| | Hard to audit; no formal guarantees |

**Rejected.** Cost-prohibitive; lacks structural rigor.

### Alternative 3: Rule-engine-only revision

Deterministic rules (R1, R2, disjointness, cardinality) decide every revision; no LLM in the revision loop.

| Pro | Con |
|---|---|
| Cheap; deterministic; fully auditable | Misses semantic refinements (e.g., "this is a sharper definition of an existing concept") |
| Can run on every doc with no LLM cost | Brittle on noisy LLM extraction output; no recourse for "uncertain" cases |

**Rejected as sole approach.** Too narrow; misses the cases that most need revision.

### Alternative 4: Background consolidation only

No per-document revision pass. Instead, a periodic job sweeps the ontology and proposes revisions.

| Pro | Con |
|---|---|
| Cheap (one job, not per-doc overhead) | Stale: revisions only land at the next sweep |
| Easy to schedule | Hard to attribute a revision to a specific new document |
| | Loses tight feedback loop with the document upload UX |

**Rejected as sole approach.** Useful as a complement, not a replacement.

### Alternative 5: Continual fine-tuning (Evontree-style)

Distill ontology revisions back into the LLM via fine-tuning.

| Pro | Con |
|---|---|
| Improves the LLM itself over time | We use commercial LLMs (OpenAI, Anthropic); fine-tuning is expensive and slow |
| | Doesn't help users today; horizon is months, not days |

**Rejected for now.** Out of scope; possible future enhancement once we run open models.

## Decision

We adopt the **Incremental Belief Revision (IBR)** substrate: a four-phase hybrid that combines mechanical rules, LLM-based semantic judgment, and human-in-the-loop fallback over our existing temporal substrate.

### The Four Phases

```
new doc → extraction → consistency → ER → ★ Belief Revision Agent ★ → quality judge → pre-curation → staging
                                              │
                                              ├─ Phase 1: Touchpoint Discovery (mechanical, every doc)
                                              ├─ Phase 2: Mechanical Verdict (rule + score)
                                              ├─ Phase 3: LLM Revision Agent (only for hard cases)
                                              └─ Phase 4: Background Consolidation (periodic)
```

**Phase 1 — Touchpoint discovery (mechanical, every doc):**
For each newly-extracted concept, find candidate "touchpoints" in the existing ontology via embedding similarity + URI/label match + entity-overlap on `extracted_from` chunks.

**Phase 2 — Mechanical verdict (rule + score):**
For each `(extracted, existing)` touchpoint pair, classify with deterministic rules into one of six verdicts:

| Verdict | Trigger | Action |
|---|---|---|
| **REINFORCED** | Same domain/range, compatible label | Boost confidence; append chunk to provenance; no version bump |
| **REFINED** | New evidence enriches (new property, sharper description, narrower range) | Propose a new version (supersedes old via Levi identity) |
| **GAP-FILLING** | New edge connects existing classes that previously had no relationship | Create new edge directly |
| **REDUNDANT** | Extracted concept overlaps existing on multiple signals | Hand off to ER as merge candidate |
| **CONTRADICTED** | New evidence asserts incompatible domain/range or violates rule (R1/R2/disjointness) | **Defer to Phase 3** |
| **UNCERTAIN** | Mechanical rules can't decide | **Defer to Phase 3** |

**Phase 3 — LLM revision agent (expensive; only for CONTRADICTED + UNCERTAIN):**
Given `(existing belief + its provenance text + new evidence text)`, the agent emits exactly one of `REINFORCE | REVISE(new_version) | RETRACT | FLAG_FOR_CURATION`, with a grounded textual justification (Evo-DKD pattern: every structured action must be paired with a textual justification, validated by a cross-check). High-confidence outputs auto-apply; low-confidence outputs become curation tasks.

**Phase 4 — Background consolidation (periodic, cron or on-demand):**
A "dream state" job runs over the full ontology to re-run rules, recompute confidence with all evidence, apply confidence decay to stale beliefs, and produce a consolidation report for the Quality Dashboard. Includes safety guards: published-item protection, circuit breakers, dry-run mode, cursor-based resumption.

### Mapping to AGM Operators

The four-phase pipeline is the implementation of the three AGM operators over our temporal substrate:

| AGM Operator | IBR Realization | Temporal mechanic |
|---|---|---|
| **Expansion** `K + φ` | Phase 2 GAP-FILLING + REINFORCED | Insert new version with `created = now`; old version still has `expired = NEVER_EXPIRES` if compatible |
| **Contraction** `K − φ` | Phase 3 RETRACT verdict | Set `expired = now` on the current version (already idempotent in our model) |
| **Revision** `K * φ` | Phase 2 REFINED + Phase 3 REVISE verdicts | Levi identity: contract the negation (expire old version) + expand (insert new version with `created = now`) |

We honor the **minimal-change** postulate (Relevance) because temporal versioning preserves the old belief — nothing is destroyed, only superseded. We **reject the Recovery postulate** following Hansson (1999) and Graph-Native Cognitive Memory (2026), preferring belief-base semantics over belief-set semantics for natural-language beliefs.

## Rationale

### Why hybrid over pure approaches

The decision matrix:

| Concern | Rule-only | LLM-only | Hybrid (chosen) |
|---|---|---|---|
| Cost per doc | $ | $$$$ | $$ |
| Semantic understanding | Low | High | High (where needed) |
| Deterministic for easy cases | Yes | No | Yes |
| Handles novel cases | No | Yes | Yes |
| Auditable | High | Medium | High |
| Constraint-safe | Yes | No | Yes |

The hybrid wins because **80% of revisions are mechanical** (REINFORCED is the common case when a new doc mentions an already-extracted concept), and we only pay for LLM judgment on the 20% that are genuinely contested (CONTRADICTED + UNCERTAIN).

### Why a new LangGraph node, not a new pipeline

ADR-005 chose LangGraph specifically for first-class human-in-the-loop, checkpointing, and conditional routing — exactly what belief revision needs. Inserting Belief Revision as a new node:

- Reuses existing checkpoint/resume infrastructure (Phase 3 LLM cost protected on failure)
- Reuses existing WebSocket event publishing (revision actions visible in Pipeline Monitor)
- Allows conditional routing (skip LLM if no CONTRADICTED/UNCERTAIN verdicts emerged in Phase 2)
- Keeps the Pipeline Monitor a single source of truth for "what is the system doing right now"

### Why integrate with curation, not bypass it

Approved classes carry implicit human authority. Auto-revising an approved class would erode trust. Our resolution:

- **Reversible revisions** (REINFORCE confidence boost, GAP-FILLING new edge) auto-apply; if wrong, easy to retract
- **Structural revisions** on approved classes (REFINED new version, RETRACT) **cannot** auto-apply — they always go to the Revisions Inbox
- The curator can override the published-item protection on a per-revision basis

This mirrors the field-tested pattern from Graph-Native Cognitive Memory (published-item protection in safety-hardened consolidation).

### Why edge-interval temporal versioning is the right substrate

ADR-002 chose edge-interval over immutable-proxy. For belief revision specifically, this is the right call because:

1. The Levi identity (revision = contract + expand) is exactly two existing operations: `expire(old)` then `insert(new)`. Both are O(1) on a single document.
2. Point-in-time snapshots (`/snapshot?at=t`) give us "what did the ontology believe at the time the curator approved?" for free — essential for audit.
3. The temporal diff endpoint (`/diff?t1=&t2=`) trivially answers "what changed in this revision pass?" for the Revisions Inbox UI.

If we had chosen immutable-proxy in ADR-002, every revision would require multi-hop traversal to resolve the current entity — a significant cost. Edge-interval pays off here.

## Consequences

### Positive

- **Closed loop on iterative knowledge construction.** New documents revisit conclusions made from earlier documents without manual re-review.
- **Cost-bounded.** The Phase 2 mechanical pass handles the easy 80%; LLM cost grows with contradictions, not with corpus size.
- **Formally grounded.** AGM operators map cleanly onto our temporal model; revisions are auditable and reversible.
- **Trust-preserving.** Approved classes are protected; structural revisions to them require curator approval.
- **Reuses existing infrastructure.** Temporal versioning, provenance, confidence scoring, LangGraph orchestration, and the curation surface are all already in place.
- **External-agent observable.** New MCP tools expose the revision lifecycle for autonomous agents.

### Negative

- **New cost dimension to monitor.** LLM revision cost per doc must be tracked and budgeted; a runaway revision loop (every doc contradicts everything) would be expensive.
  - *Mitigation:* circuit breaker halts the LLM revision agent if revision rate exceeds a configurable threshold per minute.
- **New failure mode: bad revisions.** A wrong auto-applied revision creates a new version of a class with incorrect content.
  - *Mitigation:* every revision is reversible (revert to prior temporal version); every revision carries a `revision_meta` doc with the agent's justification, so curators can spot-check.
- **Expanded curation surface area.** The "Revisions Inbox" is a new thing curators must learn.
  - *Mitigation:* surface revisions in the workspace using the same context-menu and floating-panel patterns as ER merge candidates and class details (per `ui-architecture.mdc`).
- **Confidence decay introduces non-stationarity.** A class's confidence will drift downward without new evidence, even if it remains correct.
  - *Mitigation:* decay is configurable per ontology; decayed confidence is marked separately from extraction confidence in the UI; consolidation report flags decayed beliefs for explicit re-affirmation.
- **Background job infrastructure is new.** AOE doesn't currently run periodic background jobs.
  - *Mitigation:* start with admin-triggered consolidation only; add scheduling once the manual workflow is validated.

### Mitigations Summary

| Risk | Mitigation |
|---|---|
| Runaway LLM cost | Circuit breaker + per-org token budget for revision |
| Bad auto-revision | Reversible via temporal revert; published-item protection on approved classes |
| Curator overload | Default ranking surfaces high-impact revisions first (touch many edges, contradict approved beliefs) |
| Confidence decay confusion | Separate "extraction confidence" from "current confidence with decay" in UI |
| Background job complexity | Admin-triggered first, scheduled second; cursor-based resumption from day one |

## Implementation Phasing

See `docs/REMAINING_WORK_PLAN.md` Stream 11 for the detailed task breakdown. High level:

| Phase | Focus | Duration |
|---|---|---|
| Phase 1 | Substrate (`revision_meta`, evidence-age signals, decay, rule engine, touchpoint discovery) | 1.5 weeks |
| Phase 2 | Per-document Belief Revision LangGraph node (mechanical + LLM) | 2 weeks |
| Phase 3 | Curation UX (Revisions Inbox) + background consolidation + safety guards + MCP tools | 1.5 weeks |

**Total:** ~5 weeks. Can run in parallel with Stream 1 Phase 2 (composition) and Stream 4 (quality dashboard).

## References

- Alchourrón, Gärdenfels, Makinson (1985). On the logic of theory change.
- Doyle, J. (1979). A truth maintenance system.
- Hansson, S. O. (1999). A textbook of belief dynamics. (Belief-base semantics; rejection of Recovery.)
- TRAIL (2025). *arXiv:2508.04474* — Joint Inference and Refinement of Knowledge Graphs with LLMs.
- Evo-DKD (Jul 2025). *arXiv:2507.21438* — Dual-Knowledge Decoding for autonomous ontology evolution.
- Evontree (Oct 2025). *arXiv:2510.26683* — Ontology Rule-Guided Self-Evolution of LLMs.
- HyDRA (2025). *arXiv:2507.15917v2* — Hybrid-Driven Reasoning Architecture for Verifiable KGs.
- Graph-Native Cognitive Memory (2026). *arXiv:2603.17244v1* — Formal AGM belief revision over versioned property graphs.
- ADR-002 — Temporal Versioning Pattern (the substrate this builds on).
- ADR-005 — Extraction Pipeline Orchestration (where the new node lives).

---

## Implementation Status (as of v0.4.0-dev, May 2026)

Stream 11 from `docs/REMAINING_WORK_PLAN.md` tracks the IBR rollout. Phases
1 and 2 shipped in v0.2.0; Phase 3 shipped in v0.4.0-dev with the items
below.

| Task | Surface | Where it lives |
|---|---|---|
| IBR.1–IBR.13 | Substrate + per-doc node | `backend/app/services/revision_*`, `backend/app/extraction/agents/belief_revision.py`, `revision_meta` collection (ADR-002 temporal semantics) |
| IBR.16 — Accept / Reject / Modify | REST | `POST /api/v1/revisions/{key}/{accept,reject,modify}` (`backend/app/api/revisions.py`); business logic in `backend/app/services/revision_actions.py`. See [API reference](../api-reference.md#belief-revision). |
| IBR.17 — Background consolidation | Admin REST | `POST /api/v1/admin/ontology/{id}/consolidate?dry_run=true` + `GET /api/v1/admin/consolidation-jobs[/{key}]` (`backend/app/api/admin.py`); orchestrator `backend/app/services/consolidation.py` chains rule engine, confidence decay, and stale-belief scan with cursor-based resumption (`ConsolidationCursor`). |
| IBR.18 — Safety guards | Library | `backend/app/services/revision_safety.py` — published-item protection, in-memory `RevisionRateLimiter` (circuit breaker; configured via `belief_revision_circuit_*` settings), `PlannedAction` dry-run helper, persistent `ConsolidationCursor`. Wired into `belief_revision.revise()` so structural revisions on `status="approved"` entities are downgraded to `FLAG_FOR_CURATION` and LLM calls are skipped when the breaker is tripped. |
| IBR.19 — Quality dashboard tile | Frontend | "Revisions Activity" section in `frontend/src/components/dashboard/QualityReportOverlay.tsx` — Total / Pending / Applied / Rejected KPIs, verdict-distribution chips, and a "Show inbox" CTA wired to IBR.14. |
| IBR.14 — Revisions Inbox overlay | Frontend | `frontend/src/components/workspace/RevisionsInboxOverlay.tsx`; opened from the ontology context menu ("Show Pending Revisions") and the canvas context menu when an ontology is loaded. Inline accept/reject buttons with optimistic row removal + toast confirmation. |
| IBR.15 — Revision detail panel | Frontend | Sibling `RevisionDetailPanel` inside the same overlay file — full reasoning, evidence quotes, confidence delta, agent identity, and a Modify pane for `override_action` + audit note. |
| IBR.20 — MCP tools | MCP | `backend/app/mcp/tools/belief_revision.py` registers six tools: `list_revisions_inbox`, `list_recent_revisions`, `get_revision`, `decide_revision`, `run_consolidation` (defaults to `dry_run=True`), and `get_circuit_breaker_state`. See [MCP server reference](../mcp-server.md#belief-revision-tools). |

**Operator notes:**

- The circuit breaker is in-memory per backend process. Multi-replica deployments should set `belief_revision_circuit_max_per_minute` low enough that any single replica stays well under the LLM provider's rate limit, since cross-replica coordination is intentionally out of scope (see ADR-005 — single-leader pipeline).
- `POST /api/v1/admin/ontology/{id}/consolidate` defaults to `dry_run=false`. The MCP `run_consolidation` tool defaults to `dry_run=true` because external agents are more likely to call it speculatively.
- `ConsolidationCursor` rows live in the `consolidation_jobs` collection and are safe to truncate; a missing cursor causes the job to start from scratch, not to fail.

**Curator notes:**

- The Revisions Inbox is the canonical surface for `FLAG_FOR_CURATION` rows. Items reach it because (a) the LLM agent flagged them, (b) the published-item guard downgraded a structural change to an approved entity, or (c) the circuit breaker tripped while a contradicted/uncertain row was being processed.
- Accept applies the revision via the same Levi-identity `supersede` path used by per-document extraction — the resulting version is indistinguishable in the temporal record from a normal extraction, except that `revision_meta.decision_log[].decided_by` records the curator id.
- Reject leaves the graph untouched and only updates `revision_meta`; the row disappears from the inbox immediately.
- Modify lets the curator pick a different action (e.g. `RETRACT` instead of `REVISE`) or attach an explanatory note before accepting; the modified action is stamped onto `revision_meta` and applied as if the agent had emitted it.
