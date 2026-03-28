# ADR 005: Extraction Pipeline Orchestration

**Status:** Accepted
**Date:** 2026-02-25
**Decision Makers:** AOE Core Team

---

## Context

AOE's ontology extraction pipeline involves multiple sequential and conditional steps:

1. **Strategy Selection** — analyze document type and select model/prompt configuration
2. **N-Pass Extraction** — run the LLM multiple times with self-correction on validation failures
3. **Consistency Checking** — compare N-pass results, keep concepts appearing in ≥ M passes
4. **Entity Resolution** — detect duplicates against existing ontologies
5. **Pre-Curation Filtering** — remove noise, annotate confidence, add provenance
6. **Staging** — store results in a staging graph for human review
7. **Human-in-the-Loop** — pause pipeline, wait for curation decisions, optionally resume

The pipeline needs:

- **State persistence** — survive process restarts; resume after failures
- **Conditional routing** — different paths based on document type, error conditions, or human decisions
- **Checkpointing** — save intermediate state after each agent step
- **Observability** — structured logging and WebSocket events for each step
- **Human-in-the-loop** — pause execution and wait for external input (curation decisions)

Two approaches were evaluated:

1. **LangGraph** — a stateful graph-based orchestration framework from LangChain
2. **Custom orchestration** — bespoke Python pipeline with explicit state management

## Decision

We chose **LangGraph** for extraction pipeline orchestration.

## Rationale

### LangGraph Provides

| Feature | Description |
|---------|-------------|
| StateGraph | Define pipeline as a directed graph with typed state schema |
| Conditional edges | Route between agents based on state (e.g., retry on validation failure) |
| Checkpointing | Built-in state persistence to Redis or database; pipeline resumable after crash |
| Human-in-the-loop | First-class support for pausing execution and waiting for external input |
| Streaming | Stream intermediate results and events during execution |
| TypedDict state | Strongly typed pipeline state schema with Pydantic validation |

### Custom Orchestration Would Require

| Component | Estimated Effort |
|-----------|-----------------|
| State machine with persistence | 2 weeks |
| Checkpoint/resume logic | 1–2 weeks |
| Conditional routing engine | 1 week |
| Human-in-the-loop breakpoints | 1–2 weeks |
| Event streaming infrastructure | 1 week |
| Error handling and retry logic | 1 week |
| **Total** | **7–9 weeks** |

### Comparison

| Factor | LangGraph | Custom |
|--------|----------|--------|
| Time to implement | ~2 weeks (define graph + agents) | 7–9 weeks (build infrastructure + agents) |
| Checkpoint/resume | Built-in, battle-tested | Must build and test from scratch |
| Human-in-the-loop | First-class API | Custom WebSocket + state machine coordination |
| Conditional routing | Declarative edge conditions | Imperative if/else chains |
| Observability | Callback hooks at each node | Must instrument manually |
| Debugging | LangSmith integration, step-by-step replay | Custom logging and replay |
| Vendor lock-in | Moderate — LangChain ecosystem | None |
| Flexibility | Constrained to graph paradigm | Unlimited |

### Why LangGraph Wins for AOE

1. **Human-in-the-loop is critical.** The pipeline must pause after pre-curation filtering, emit a WebSocket event, and wait for domain experts to make curation decisions before optionally resuming. LangGraph provides this as a first-class feature.

2. **Checkpointing prevents rework.** LLM extraction is expensive (tokens cost money). If the pipeline fails at step 4 of 6, LangGraph's checkpointing allows resuming from step 4 rather than re-running steps 1–3.

3. **Conditional routing is natural.** The pipeline has several branching points: retry on validation failure, skip ER for Tier 1-only runs, route to different prompt templates based on strategy selection. LangGraph's conditional edges express these cleanly.

4. **Observability is built in.** LangGraph's node callbacks integrate directly with WebSocket event publishing for the Pipeline Monitor Dashboard. Each step emits `step_started`, `step_completed`, and `step_failed` events.

5. **Ecosystem alignment.** AOE already uses LangChain for structured LLM outputs. LangGraph is the natural orchestration layer in this ecosystem.

## Consequences

### Positive

- 5–7 weeks saved vs. custom orchestration
- Checkpoint/resume protects expensive LLM token usage
- Human-in-the-loop breakpoints work out of the box
- Pipeline Monitor Dashboard receives events via LangGraph callbacks
- Conditional routing is declarative and easy to extend
- LangSmith integration available for debugging complex pipelines

### Negative

- **Vendor dependency** — tied to LangChain/LangGraph ecosystem; migration would require rewriting pipeline orchestration
- **Learning curve** — LangGraph's graph paradigm and state management require team onboarding
- **Abstraction overhead** — simple linear pipelines are over-engineered with a graph framework (acceptable because AOE's pipeline is genuinely non-linear)
- **Version churn** — LangGraph is actively developed; API changes may require periodic updates

### Mitigations

- Agent logic (extraction, consistency, ER, filtering) is in standalone modules that can be reused with any orchestration framework
- Pipeline state schema is a standard Pydantic TypedDict — not LangGraph-specific
- Pin LangGraph version in `pyproject.toml`; upgrade on a scheduled cadence
