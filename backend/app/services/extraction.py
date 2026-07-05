"""ExtractionRunService — orchestrates extraction pipeline lifecycle.

Creates extraction_runs records, dispatches LangGraph pipeline, updates status,
and tracks token usage and cost.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
import time
import uuid
from pathlib import Path
from typing import Any, cast

from arango.collection import StandardCollection
from arango.database import StandardDatabase

from app.api.errors import NotFoundError
from app.api.metrics import (
    EXTRACTION_DURATION,
    EXTRACTION_RUNS,
    QUEUE_DEPTH,
)
from app.config import settings
from app.db.client import get_db
from app.db.pagination import paginate
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import doc_get, insert_temporal_edge_if_absent, run_aql
from app.extraction.judges.qualitative_eval_node import run_qualitative_evaluation
from app.extraction.pipeline import run_pipeline
from app.models.common import PaginatedResponse
from app.observability import get_tracer
from app.services.confidence import compute_class_confidence
from app.services.domain_detection import (
    assign_domain_tags,
    build_multi_domain_warning,
    detected_domains_from_segments,
)
from app.services.edge_repair import resolve_range_class
from app.services.visual_extraction import (
    aggregate_document_visual_diagnostics,
    build_orphan_risk_warning,
)

log = logging.getLogger(__name__)
tracer = get_tracer(__name__)
_BACKGROUND_TASKS: set[asyncio.Task[None]] = set()

_MODEL_TOKEN_RATES_PER_MILLION: dict[str, dict[str, float]] = {
    "claude-sonnet-4-20250514": {"input": 3.0, "output": 15.0},
    "claude-3-5-sonnet-20241022": {"input": 3.0, "output": 15.0},
    "gpt-4o": {"input": 2.5, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}


def _generate_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def _get_collection(db: StandardDatabase, name: str) -> StandardCollection:
    if not db.has_collection(name):
        db.create_collection(name)
    return db.collection(name)


def create_run_record(
    db: StandardDatabase | None = None,
    *,
    document_id: str | None = None,
    document_ids: list[str] | None = None,
    config_overrides: dict[str, Any] | None = None,
    domain_ontology_ids: list[str] | None = None,
    target_ontology_id: str | None = None,
    base_ontology_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Create an extraction run record (synchronous).

    Returns the run record immediately so the HTTP response can be sent
    before the pipeline starts executing.

    Accepts either ``document_id`` (single, backward compat) or
    ``document_ids`` (multi-doc).  Both are normalized into
    ``doc_ids: list[str]`` on the stored record.
    """
    if db is None:
        db = get_db()

    doc_ids = _normalize_doc_ids(document_id=document_id, document_ids=document_ids)
    if not doc_ids:
        raise ValueError("At least one document ID is required")

    run_id = _generate_run_id()
    now = time.time()

    is_tier2 = bool(domain_ontology_ids)
    prompt_version = "tier2_standard" if is_tier2 else "tier1_standard"

    run_record: dict[str, Any] = {
        "_key": run_id,
        "doc_id": doc_ids[0],
        "doc_ids": doc_ids,
        "model": settings.llm_extraction_model,
        "prompt_version": prompt_version,
        "started_at": now,
        "completed_at": None,
        "status": "running",
        "stats": {
            "passes": settings.extraction_passes,
            "consistency_threshold": settings.extraction_consistency_threshold,
            "token_usage": {},
            "errors": [],
            "step_logs": [],
        },
    }

    if domain_ontology_ids:
        run_record["domain_ontology_ids"] = domain_ontology_ids
    if target_ontology_id:
        run_record["target_ontology_id"] = target_ontology_id
    # H.8 -- separate from `domain_ontology_ids` (which feeds Tier 2
    # context) because these become `owl:imports` edges from the new
    # ontology post-success. Persist on the run record so retries and
    # post-restart resumes pick them up the same way the existing
    # `domain_ontology_ids` does.
    if base_ontology_ids:
        run_record["base_ontology_ids"] = base_ontology_ids

    if config_overrides:
        run_record["stats"].update(config_overrides)

    col = _get_collection(db, "extraction_runs")
    col.insert(run_record)

    total_chunks = sum(len(_load_document_chunks(db, did)) for did in doc_ids)
    log.info(
        "extraction run created",
        extra={"run_id": run_id, "doc_ids": doc_ids, "chunk_count": total_chunks},
    )

    return run_record


def _normalize_doc_ids(
    *,
    document_id: str | None = None,
    document_ids: list[str] | None = None,
) -> list[str]:
    """Merge singular/plural document ID args into a deduplicated list.

    Returns an empty list (instead of raising) when called from
    ``execute_run`` with both args ``None`` — the caller fills in from the
    stored run record.
    """
    ids: list[str] = []
    if document_ids:
        ids.extend(document_ids)
    if document_id and document_id not in ids:
        ids.insert(0, document_id)
    return ids


async def execute_run(
    run_id: str,
    document_id: str | None = None,
    document_ids: list[str] | None = None,
    config_overrides: dict[str, Any] | None = None,
    event_callback: Any | None = None,
    domain_ontology_ids: list[str] | None = None,
    target_ontology_id: str | None = None,
    base_ontology_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Execute the extraction pipeline for an existing run record.

    Designed to run as a background task after the HTTP response is sent.
    When no event_callback is provided, defaults to publishing events
    over WebSocket via the extraction event bus.
    """
    if event_callback is None:
        from app.api.ws_extraction import publish_event

        event_callback = publish_event

    db = get_db()
    col = _get_collection(db, "extraction_runs")
    run_record = doc_get(col, run_id)
    if run_record is None:
        raise NotFoundError(f"Extraction run '{run_id}' not found")

    doc_ids = _normalize_doc_ids(document_id=document_id, document_ids=document_ids)
    if not doc_ids:
        doc_ids = run_record.get("doc_ids") or []
        if not doc_ids and run_record.get("doc_id"):
            doc_ids = [run_record["doc_id"]]

    if target_ontology_id is None:
        target_ontology_id = run_record.get("target_ontology_id")

    if domain_ontology_ids is None:
        domain_ontology_ids = run_record.get("domain_ontology_ids")

    if base_ontology_ids is None:
        base_ontology_ids = run_record.get("base_ontology_ids")

    domain_context = ""
    if domain_ontology_ids:
        try:
            from app.services.ontology_context import serialize_multi_domain_context

            domain_context = serialize_multi_domain_context(
                db,
                ontology_ids=domain_ontology_ids,
            )
            log.info(
                "serialized domain context for tier 2",
                extra={
                    "run_id": run_id,
                    "ontology_ids": domain_ontology_ids,
                    "context_length": len(domain_context),
                },
            )
        except Exception:
            log.warning(
                "failed to serialize domain context, falling back to tier 1",
                exc_info=True,
                extra={"run_id": run_id},
            )

    # Stream 1 H.17: prepend the *effective* (own + imports closure) view
    # of the target ontology so the LLM knows which classes already
    # exist (and where they came from) and can reuse them via
    # rdfs:subClassOf / owl:equivalentClass instead of minting duplicate
    # URIs that the H.13 conflict detector will later flag. The function
    # returns ``""`` for fresh-and-importless targets so greenfield runs
    # are unchanged; failures are non-fatal -- we log and continue so an
    # extraction can still complete even if the closure walk hits a
    # transient DB error.
    if target_ontology_id:
        try:
            from app.services.ontology_context import serialize_effective_ontology_context

            effective_context = serialize_effective_ontology_context(
                db,
                ontology_id=target_ontology_id,
            )
        except Exception:
            log.warning(
                "failed to serialize effective ontology context",
                exc_info=True,
                extra={"run_id": run_id, "target_ontology_id": target_ontology_id},
            )
            effective_context = ""

        if effective_context:
            domain_context = (
                effective_context + "\n" + domain_context if domain_context else effective_context
            )
            log.info(
                "prepended effective ontology context",
                extra={
                    "run_id": run_id,
                    "target_ontology_id": target_ontology_id,
                    "effective_context_length": len(effective_context),
                },
            )

    chunks: list[dict[str, Any]] = []
    for did in doc_ids:
        chunks.extend(_load_document_chunks(db, did))

    primary_doc_id = doc_ids[0] if doc_ids else "unknown"

    final_state: dict[str, Any] = {}
    try:
        # Stream 7 PR 2 -- E.1: trace the pipeline execution. Wrapping
        # ``run_pipeline`` (not the whole ``execute_run`` body) keeps
        # the diff small and the trace focused on the actual LangGraph
        # work; FastAPI's request span already covers the surrounding
        # API call, and the background-task path propagates context
        # via contextvars. No-op when otel_enabled=False.
        with tracer.start_as_current_span(
            "extraction.run",
            attributes={
                "run.id": run_id,
                "run.primary_doc_id": primary_doc_id,
                "run.num_documents": len(doc_ids),
                "run.num_chunks": len(chunks),
            },
        ) as run_span:
            final_state = cast(
                "dict[str, Any]",
                await run_pipeline(
                    run_id=run_id,
                    document_id=primary_doc_id,
                    chunks=chunks,
                    event_callback=event_callback,
                    domain_context=domain_context,
                    domain_ontology_ids=domain_ontology_ids or [],
                ),
            )
            run_span.set_attribute("run.errors", len(final_state.get("errors", []) or []))

        completed_at = time.time()
        status = "completed"
        if final_state.get("errors"):
            status = "completed_with_errors"
        if final_state.get("consistency_result") is None:
            status = "failed"

        # Stream 7 PR 3 -- E.2: record run outcome + duration on the
        # Prometheus counters that back the extraction-failure-rate
        # and extraction-throughput alerts. We tag by ``status`` so
        # the alert rule can compute ``rate(failed) / rate(total)``
        # without re-deriving from logs. Duration is bucketed by the
        # histogram declared in ``app/api/metrics.py`` (1s -> 600s).
        EXTRACTION_RUNS.labels(status=status).inc()
        started_at = run_record.get("started_at") or completed_at
        EXTRACTION_DURATION.observe(max(0.0, completed_at - started_at))

        consistency = final_state.get("consistency_result")
        classes_extracted = len(consistency.classes) if consistency else 0
        properties_extracted = (
            sum(_count_class_properties(c) for c in consistency.classes) if consistency else 0
        )
        pass_results = final_state.get("extraction_passes", [])
        pass_agreement_rate = _compute_agreement_rate(pass_results) if pass_results else 0.0
        if pass_agreement_rate == 0.0:
            for sl in final_state.get("step_logs", []):
                sl_dict = (
                    sl
                    if isinstance(sl, dict)
                    else (sl.model_dump() if hasattr(sl, "model_dump") else dict(sl))
                )
                if sl_dict.get("step") == "consistency_checker":
                    rates = sl_dict.get("metadata", {}).get("agreement_rates", {})
                    if rates:
                        pass_agreement_rate = sum(rates.values()) / len(rates)
                    break

        # Belief-revision summary (IBR.12). The belief_revision agent
        # writes one summary dict to state with counts of touchpoints,
        # verdicts, auto-applied / flagged revisions, and LLM calls --
        # OR a ``status="skipped"`` payload (with ``reason`` like
        # ``feature_flag_off`` / ``no_extraction_results``) when the
        # phase short-circuited. Either way we surface it on the run
        # so the Pipeline Monitor can render the IBR tiles without
        # parsing audit step_logs. ``None`` here means the agent never
        # ran (e.g. pipeline crashed before the IBR node fired); the
        # frontend renders that as a neutral "no data" tile rather
        # than zeros.
        belief_revision_summary = final_state.get("belief_revision_summary")

        # IMG.7: surface a non-blocking warning when visual-heavy inputs
        # produce many parent-less classes. Skip entirely when no
        # consistency_result was produced (failed run) -- no classes to
        # judge orphan-ness against, and the failed-run path is handled
        # separately below.
        warnings_list: list[dict[str, Any]] = list(run_record["stats"].get("warnings") or [])
        visual_summary: dict[str, Any] = {}
        if consistency is not None:
            try:
                # Use documents_repo so we don't go through the symbol
                # mocked by extraction-service tests (``app.services
                # .extraction.doc_get``). Each test that wants warning
                # coverage can mock ``documents_repo.get_document``
                # explicitly.
                from app.db import documents_repo

                run_documents: list[dict[str, Any]] = []
                for did in doc_ids:
                    doc = documents_repo.get_document(did, db=db)
                    if doc:
                        run_documents.append(doc)
                visual_summary = aggregate_document_visual_diagnostics(run_documents)
                orphan_count = sum(1 for c in consistency.classes if not c.parent_uri)
                warning = build_orphan_risk_warning(
                    orphan_class_count=orphan_count,
                    total_classes=classes_extracted,
                    visual_summary=visual_summary,
                    orphan_ratio_threshold=settings.visual_orphan_warning_orphan_ratio,
                    min_visual_assets=settings.visual_orphan_warning_min_assets,
                )
                if warning is not None:
                    warnings_list.append(warning)
                    log.info(
                        "visual-heavy orphan warning attached to run %s "
                        "(orphans=%d/%d, visual_assets=%d)",
                        run_id,
                        orphan_count,
                        classes_extracted,
                        warning["visual_asset_count"],
                    )
            except Exception:
                log.warning(
                    "failed to compute visual-extraction summary for run %s",
                    run_id,
                    exc_info=True,
                )

        # Stream 16 DD.2/DD.3: turn the domain_segmenter's segments into
        # run-level detected_domains, stamp each class with its domain_tag
        # (mutating the consistency_result classes in place BEFORE they are
        # stored + materialized below), and attach a non-blocking
        # multi_domain warning when the document spans >1 domain. Empty
        # segments (detection disabled or a graceful failure) leave classes
        # untagged and produce no detected_domains -- byte-identical to a
        # run without domain detection.
        domain_segments: list[dict[str, Any]] = list(final_state.get("domain_segments") or [])
        detected_domains: list[str] = []
        if domain_segments:
            detected_domains = detected_domains_from_segments(
                domain_segments, settings.domain_detection_min_confidence
            )
            if consistency is not None and detected_domains:
                class_domain_counts = assign_domain_tags(
                    consistency.classes,
                    domain_segments,
                    min_confidence=settings.domain_detection_min_confidence,
                )
                domain_warning = build_multi_domain_warning(
                    detected_domains=detected_domains,
                    segments=domain_segments,
                    class_domain_counts=class_domain_counts,
                )
                if domain_warning is not None:
                    warnings_list.append(domain_warning)
                    log.info(
                        "multi-domain warning attached to run %s (domains=%s)",
                        run_id,
                        detected_domains,
                    )

        update_data: dict[str, Any] = {
            "completed_at": completed_at,
            "status": status,
            "stats": {
                **run_record["stats"],
                "token_usage": final_state.get("token_usage", {}),
                "errors": final_state.get("errors", []),
                "step_logs": [_serialize_step_log(sl) for sl in final_state.get("step_logs", [])],
                "classes_extracted": classes_extracted,
                "properties_extracted": properties_extracted,
                "pass_agreement_rate": pass_agreement_rate,
                "belief_revision": belief_revision_summary,
                "visual_extraction_summary": visual_summary,
                "detected_domains": detected_domains,
                "warnings": warnings_list,
            },
        }
        col.update({"_key": run_id, **update_data})

        if final_state.get("consistency_result"):
            _store_results(db, run_id=run_id, result=final_state["consistency_result"])

            if target_ontology_id:
                ontology_id = _update_existing_ontology(
                    db,
                    ontology_id=target_ontology_id,
                    run_id=run_id,
                    result=final_state["consistency_result"],
                )
            else:
                ontology_id = _auto_register_ontology(
                    db,
                    run_id=run_id,
                    document_id=primary_doc_id,
                    result=final_state["consistency_result"],
                )

            if ontology_id:
                col.update({"_key": run_id, "ontology_id": ontology_id})
                # Stream 7 PR 2 -- E.1: trace the materialization step
                # (RDF/PGT writes to ArangoDB). One span covers all
                # documents in the run; per-document tagging via
                # ``materialize.doc_ids`` keeps cardinality bounded.
                # No-op when otel_enabled=False.
                with tracer.start_as_current_span(
                    "extraction.materialize",
                    attributes={
                        "materialize.run_id": run_id,
                        "materialize.ontology_id": ontology_id,
                        "materialize.num_documents": len(doc_ids),
                    },
                ):
                    for did in doc_ids:
                        _materialize_to_graph(
                            db,
                            run_id=run_id,
                            document_id=did,
                            ontology_id=ontology_id,
                            result=final_state["consistency_result"],
                            faithfulness_scores=final_state.get("faithfulness_scores"),
                            validity_scores=final_state.get("validity_scores"),
                        )
                _create_produced_by_edge(db, ontology_id=ontology_id, run_id=run_id)

                # H.8 -- record `owl:imports` edges from this new
                # ontology to every base ontology declared on the
                # extraction request. Done post-success on purpose so a
                # failed extraction doesn't leave orphan edges pointing
                # to an unregistered ontology. Wrapped because import
                # recording is not allowed to abort the run.
                if base_ontology_ids:
                    try:
                        _record_base_ontology_imports(
                            db,
                            ontology_id=ontology_id,
                            base_ontology_ids=base_ontology_ids,
                            run_id=run_id,
                        )
                    except Exception:
                        log.warning(
                            "base ontology imports recording failed",
                            exc_info=True,
                            extra={
                                "run_id": run_id,
                                "ontology_id": ontology_id,
                            },
                        )

                # Stream 7 PR 2 -- E.1: trace the per-ontology graph
                # creation. Last step of the extraction-write pipeline;
                # closing this span signals "extraction is fully landed".
                with tracer.start_as_current_span(
                    "ontology.graph.ensure",
                    attributes={"ontology_id": ontology_id},
                ) as graph_span:
                    try:
                        from app.services.ontology_graphs import ensure_ontology_graph

                        graph_name = ensure_ontology_graph(ontology_id, db=db)
                        graph_span.set_attribute("graph_name", graph_name)
                        log.info("ensured per-ontology graph %s", graph_name)
                    except Exception as exc:
                        graph_name = None
                        graph_span.record_exception(exc)
                        log.warning(
                            "per-ontology graph creation failed",
                            exc_info=True,
                        )

                # Stream 7 PR 1 -- E.4: auto-install the ArangoDB Visualizer
                # assets for the new per-ontology graph so users get a
                # graph-aware visualisation immediately on first open
                # without having to run ``install_visualizer.py`` by hand.
                # Delegated to a helper so the failure-shielding logic
                # (which must NOT abort the extraction write path) is
                # unit-testable without standing up the whole extraction
                # loop.
                _auto_install_visualizer_assets(
                    db,
                    ontology_id=ontology_id,
                    graph_name=graph_name,
                )

                # Track the task so it is not garbage-collected before completion.
                task = asyncio.create_task(
                    _run_qualitative_eval_background(
                        run_id=run_id,
                        final_state=final_state,
                    )
                )
                _BACKGROUND_TASKS.add(task)
                task.add_done_callback(_BACKGROUND_TASKS.discard)
                # Stream 7 PR 3 -- E.2: keep the queue-depth gauge
                # current so the "extraction queue depth > 10" alert
                # has a live signal. Set on add + discard; the
                # done-callback below uses a lambda so the discard
                # path also re-reads ``len(...)``.
                QUEUE_DEPTH.labels(queue="extraction").set(len(_BACKGROUND_TASKS))
                task.add_done_callback(
                    lambda _t: QUEUE_DEPTH.labels(queue="extraction").set(len(_BACKGROUND_TASKS))
                )

                # Q.2 (Stream 4) — record a quality history snapshot tagged
                # with the originating run so the dashboard's trend chart
                # has one data point per real ontology mutation, not one
                # per "user opened the quality report" event. Wrapped to
                # never break the extraction write path.
                try:
                    from app.db import quality_history_repo

                    quality_history_repo.record_event_snapshot(
                        ontology_id,
                        source="extraction_completion",
                        run_id=run_id,
                        db=db,
                    )
                except Exception:
                    log.warning(
                        "post-extraction quality snapshot failed",
                        extra={"run_id": run_id, "ontology_id": ontology_id},
                        exc_info=True,
                    )

    except Exception as exc:
        log.exception("extraction pipeline failed", extra={"run_id": run_id})
        # Stream 7 PR 3 -- E.2: failed runs that bypassed the
        # success path (eg crashed before completed_at was computed)
        # still need to tick the counter so the failure-rate alert
        # sees them. Duration is best-effort: ``started_at`` was
        # stamped when the run record was created; if it's missing
        # we observe 0.0 so the count is still recorded.
        EXTRACTION_RUNS.labels(status="failed").inc()
        started_at = run_record.get("started_at") or time.time()
        EXTRACTION_DURATION.observe(max(0.0, time.time() - started_at))
        partial_logs: list[dict[str, Any]] = []
        partial_belief_revision: dict[str, Any] | None = None
        if final_state and final_state.get("step_logs"):
            partial_logs = [_serialize_step_log(sl) for sl in final_state["step_logs"]]
        if final_state:
            # If the IBR node ran before the crash (or was skipped via
            # feature-flag), preserve its summary on the failed run so
            # the Pipeline Monitor can still show "IBR ran: N
            # touchpoints, then pipeline failed". ``None`` means the
            # crash happened before the IBR node fired.
            partial_belief_revision = final_state.get("belief_revision_summary")
        col.update(
            {
                "_key": run_id,
                "status": "failed",
                "completed_at": time.time(),
                "stats": {
                    **run_record["stats"],
                    "errors": [str(exc)],
                    "step_logs": partial_logs,
                    "token_usage": (final_state.get("token_usage", {}) if final_state else {}),
                    "belief_revision": partial_belief_revision,
                },
            }
        )

    updated = doc_get(col, run_id)
    return updated or {}


async def _run_qualitative_eval_background(
    *,
    run_id: str,
    final_state: dict[str, Any],
) -> None:
    """Fire-and-forget qualitative evaluation — never blocks staging."""
    try:
        consistency_result = final_state.get("consistency_result")
        if consistency_result is None or not getattr(consistency_result, "classes", None):
            return

        classes = consistency_result.classes
        chunks = final_state.get("document_chunks", [])
        strategy_config = final_state.get("strategy_config", {})
        batch_size = strategy_config.get("chunk_batch_size", 5)

        result = await run_qualitative_evaluation(
            classes=classes,
            chunks=chunks,
            batch_size=batch_size,
        )

        # Persist to extraction run record
        db = get_db()
        if db.has_collection("extraction_runs"):
            col = db.collection("extraction_runs")
            run_doc = doc_get(col, run_id)
            if run_doc:
                stats = run_doc.get("stats", {})
                stats["qualitative_evaluation"] = result
                col.update({"_key": run_id, "stats": stats})
                log.info("qualitative evaluation stored for run %s", run_id)

    except Exception:
        log.warning(
            "background qualitative evaluation failed for run %s",
            run_id,
            exc_info=True,
        )


async def start_run(
    db: StandardDatabase | None = None,
    *,
    document_id: str,
    config_overrides: dict[str, Any] | None = None,
    event_callback: Any | None = None,
    target_ontology_id: str | None = None,
    domain_ontology_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Create and execute an extraction run synchronously (legacy helper)."""
    if db is None:
        db = get_db()
    run_record = create_run_record(
        db,
        document_id=document_id,
        config_overrides=config_overrides,
        target_ontology_id=target_ontology_id,
        domain_ontology_ids=domain_ontology_ids,
    )
    return await execute_run(
        run_id=run_record["_key"],
        document_ids=[document_id],
        config_overrides=config_overrides,
        event_callback=event_callback,
        target_ontology_id=target_ontology_id,
        domain_ontology_ids=domain_ontology_ids,
    )


def get_run(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Get extraction run details."""
    if db is None:
        db = get_db()

    col = _get_collection(db, "extraction_runs")
    run = doc_get(col, run_id)
    if run is None:
        raise NotFoundError(f"Extraction run '{run_id}' not found")
    return run


def list_runs(
    db: StandardDatabase | None = None,
    *,
    cursor: str | None = None,
    limit: int = 25,
    status: str | None = None,
) -> PaginatedResponse[dict[str, Any]]:
    """List extraction runs with cursor-based pagination."""
    if db is None:
        db = get_db()

    _get_collection(db, "extraction_runs")

    filters: dict[str, Any] = {}
    if status:
        filters["status"] = status

    return paginate(
        db,
        collection="extraction_runs",
        sort_field="started_at",
        sort_order="desc",
        limit=limit,
        cursor=cursor,
        filters=filters if filters else None,
        extra_aql='FILTER NOT STARTS_WITH(doc._key, "results_")',
    )


def get_run_steps(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
) -> list[dict[str, Any]]:
    """Get per-agent step logs for a run."""
    run = get_run(db, run_id=run_id)
    logs = run.get("stats", {}).get("step_logs", [])
    return cast(list[dict[str, Any]], logs)


def get_run_results(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Get extraction results (stored classes and properties) for a run."""
    if db is None:
        db = get_db()

    run = get_run(db, run_id=run_id)
    results_key = f"results_{run_id}"

    col = _get_collection(db, "extraction_runs")
    results_doc = doc_get(col, results_key)

    if results_doc and "extraction_result" in results_doc:
        return cast(dict[str, Any], results_doc["extraction_result"])

    return {
        "classes": [],
        "properties": [],
        "run_id": run_id,
        "status": run.get("status", "unknown"),
    }


async def retry_run(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
    event_callback: Any | None = None,
) -> dict[str, Any]:
    """Retry a failed extraction run."""
    if db is None:
        db = get_db()

    run = get_run(db, run_id=run_id)
    if run["status"] not in ("failed", "completed_with_errors"):
        raise ValueError(f"Can only retry failed runs, current status: {run['status']}")

    doc_ids = run.get("doc_ids") or [run["doc_id"]]
    return await start_run(
        db,
        document_id=doc_ids[0],
        event_callback=event_callback,
        target_ontology_id=run.get("target_ontology_id"),
        domain_ontology_ids=run.get("domain_ontology_ids"),
    )


def get_run_cost(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
    include_quality_metrics: bool = True,
    refresh: bool = False,
) -> dict[str, Any]:
    """Get token usage and estimated cost for a run.

    Also includes quality indicators (avg_confidence, completeness_pct)
    when the run has an associated ontology.

    Caching (Stream 12 T7)
    ----------------------
    The quality fields (``avg_confidence`` + ``completeness_pct``) used
    to be recomputed via ``compute_ontology_quality`` on every call,
    which walked the entire ontology -- ~9s on the WTW demo. Quality
    on the run-cost endpoint is conceptually a point-in-time view (the
    run is already complete; the cost numbers above are immutable), so
    we now cache the computed quality on the run document under
    ``stats.cached_quality`` and short-circuit on subsequent calls. The
    cache carries ``computed_at`` (epoch ms) plus the
    ``ontology_id`` it was computed against so a future ontology-id
    flip on the run document invalidates automatically. Callers that
    *need* fresh numbers (the user just landed an approve/reject and
    wants to see the new value) pass ``refresh=True`` -- exposed as
    ``?refresh=true`` on the route -- to bypass the cache and rewrite
    the stored snapshot.

    The response always includes ``quality_computed_at`` so the frontend
    (and any external consumer) can render a "(snapshot from N min ago)"
    hint without a second call.
    """
    if db is None:
        db = get_db()

    run = get_run(db, run_id=run_id)
    stats = run.get("stats", {})
    token_usage = stats.get("token_usage", {})
    model = run.get("model", settings.llm_extraction_model)

    prompt_tokens = token_usage.get("prompt_tokens", 0)
    completion_tokens = token_usage.get("completion_tokens", 0)
    total_tokens = token_usage.get("total_tokens", prompt_tokens + completion_tokens)
    rates = _MODEL_TOKEN_RATES_PER_MILLION.get(
        model,
        {"input": 3.0, "output": 15.0},
    )
    estimated_cost = (prompt_tokens / 1_000_000) * rates["input"] + (
        completion_tokens / 1_000_000
    ) * rates["output"]

    started = run.get("started_at", 0)
    completed = run.get("completed_at", 0)
    duration_ms = int((completed - started) * 1000) if started and completed else 0

    avg_confidence: float | None = None
    completeness_pct: float | None = None
    quality_computed_at: float | None = None
    quality_from_cache = False

    ontology_id = run.get("ontology_id") or run.get("target_ontology_id")
    if not ontology_id and db.has_collection("ontology_registry"):
        matches = list(
            run_aql(
                db,
                "FOR o IN ontology_registry "
                "FILTER o.extraction_run_id == @rid "
                "LIMIT 1 RETURN o._key",
                bind_vars={"rid": run_id},
            )
        )
        if matches:
            ontology_id = matches[0]
    if not ontology_id and db.has_collection("ontology_registry"):
        doc_ids = run.get("doc_ids") or ([run["doc_id"]] if run.get("doc_id") else [])
        if doc_ids:
            matches = list(
                run_aql(
                    db,
                    "FOR o IN ontology_registry "
                    "FILTER o.source_document_id IN @dids OR o.source_document IN @dids "
                    "LIMIT 1 RETURN o._key",
                    bind_vars={"dids": doc_ids},
                )
            )
            if matches:
                ontology_id = matches[0]

    if include_quality_metrics and ontology_id:
        cached = stats.get("cached_quality") or {}
        cache_is_fresh = (
            not refresh
            and isinstance(cached, dict)
            and cached.get("ontology_id") == ontology_id
            and "avg_confidence" in cached
            and "completeness" in cached
        )

        if cache_is_fresh:
            avg_confidence = cached.get("avg_confidence")
            completeness_pct = cached.get("completeness")
            quality_computed_at = cached.get("computed_at")
            quality_from_cache = True
        else:
            try:
                from app.services.quality_metrics import compute_ontology_quality

                t0 = time.time()
                oq = compute_ontology_quality(db, ontology_id, include_estimated_cost=False)
                compute_ms = int((time.time() - t0) * 1000)
                avg_confidence = oq.get("avg_confidence")
                completeness_pct = oq.get("completeness")
                quality_computed_at = time.time()

                # Best-effort cache write -- the cache is a perf hack,
                # not a source of truth, so a failure here MUST NOT
                # poison the response. The next call will simply
                # recompute and try again.
                snapshot = {
                    "ontology_id": ontology_id,
                    "avg_confidence": avg_confidence,
                    "completeness": completeness_pct,
                    "computed_at": quality_computed_at,
                    "compute_ms": compute_ms,
                }
                try:
                    col = _get_collection(db, "extraction_runs")
                    next_stats = dict(stats)
                    next_stats["cached_quality"] = snapshot
                    col.update({"_key": run_id, "stats": next_stats})
                    log.info(
                        "run_cost quality cache populated",
                        extra={
                            "run_id": run_id,
                            "ontology_id": ontology_id,
                            "compute_ms": compute_ms,
                            "refresh": refresh,
                        },
                    )
                except Exception:
                    log.warning(
                        "failed to persist cached_quality on run %s",
                        run_id,
                        exc_info=True,
                    )
            except Exception:
                log.debug("quality metrics unavailable for run %s", run_id, exc_info=True)

    return {
        "run_id": run_id,
        "model": model,
        "total_duration_ms": duration_ms,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated_cost": round(estimated_cost, 6),
        "classes_extracted": stats.get("classes_extracted", 0),
        "properties_extracted": stats.get("properties_extracted", 0),
        "pass_agreement_rate": stats.get("pass_agreement_rate", 0.0),
        "token_usage": token_usage,
        "input_cost_per_million_tokens": rates["input"],
        "output_cost_per_million_tokens": rates["output"],
        "avg_confidence": avg_confidence,
        "completeness_pct": completeness_pct,
        # Stream 12 T7: snapshot timestamp so the UI can render a
        # "snapshot from N min ago" hint without an extra round trip.
        # ``quality_from_cache`` lets ops grep the logs / tests assert
        # the fast path actually fired.
        "quality_computed_at": quality_computed_at,
        "quality_from_cache": quality_from_cache,
        # IBR.12: belief-revision summary surfaced for the Pipeline
        # Monitor's IBR tiles. ``None`` means the agent never ran on
        # this run (legacy run pre-IBR, or a crash before the IBR
        # node fired). A populated dict carries the touchpoint /
        # verdict / auto-applied / flagged-for-curation counts plus
        # ``status`` / ``reason`` so the frontend can distinguish
        # "ran with N revisions" from "skipped: feature_flag_off".
        "belief_revision": stats.get("belief_revision"),
    }


# CH.1: map the document's stored MIME type to the ``doc_format`` string
# the parsers emit, used to backfill ``doc_format`` on legacy chunks that
# were persisted before the field existed (see ``_load_document_chunks``).
# Mirrors the parser dispatch in ``app.tasks._MIME_PARSERS``; ``.doc``
# resolves to ``docx`` because ``parse_doc`` converts then delegates.
_MIME_TO_DOC_FORMAT: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "application/msword": "docx",
    "text/markdown": "markdown",
}


def _doc_format_from_mime(db: StandardDatabase, document_id: str) -> str:
    """Resolve a chunk's ``doc_format`` from the parent document's MIME type.

    Returns ``""`` when the document or MIME type is unknown; callers must
    treat an empty result as "leave the chunk unchanged".
    """
    from app.db import documents_repo

    try:
        doc = documents_repo.get_document(document_id, db=db)
    except Exception:  # pragma: no cover - defensive; never block extraction
        log.warning("doc_format backfill: failed to load document %s", document_id)
        return ""
    if not doc:
        return ""
    return _MIME_TO_DOC_FORMAT.get((doc.get("mime_type") or "").lower(), "")


def _load_document_chunks(
    db: StandardDatabase,
    document_id: str,
) -> list[dict[str, Any]]:
    """Load chunks for a document from the database."""
    if not db.has_collection("chunks"):
        return []

    query = """\
FOR chunk IN chunks
  FILTER chunk.doc_id == @doc_id
  SORT chunk.chunk_index ASC
  RETURN chunk"""

    chunks = list(run_aql(db, query, bind_vars={"doc_id": document_id}))

    # CH.1: chunks persisted before ``doc_format`` was stored lack the key
    # the strategy selector relies on to detect decks. Backfill it once
    # from the parent document's MIME type so legacy documents still route
    # correctly. New chunks already carry ``doc_format`` and skip this.
    if chunks and any(not chunk.get("doc_format") for chunk in chunks):
        fmt = _doc_format_from_mime(db, document_id)
        if fmt:
            for chunk in chunks:
                if not chunk.get("doc_format"):
                    chunk["doc_format"] = fmt

    return chunks


def _store_results(
    db: StandardDatabase,
    *,
    run_id: str,
    result: Any,
) -> None:
    """Persist extraction results alongside the run record."""
    col = _get_collection(db, "extraction_runs")
    results_key = f"results_{run_id}"

    result_data = result.model_dump() if hasattr(result, "model_dump") else result
    doc = {
        "_key": results_key,
        "run_id": run_id,
        "extraction_result": result_data,
        "stored_at": time.time(),
    }

    try:
        col.insert(doc)
    except Exception:
        col.update({"_key": results_key, **doc})


def _count_class_properties(cls: Any) -> int:
    """Count total properties (attributes + relationships), with legacy fallback."""
    if hasattr(cls, "attributes"):
        n = len(cls.attributes) + len(cls.relationships)
        if n > 0:
            return n
        return len(cls.properties)
    if isinstance(cls, dict):
        attrs = cls.get("attributes", [])
        rels = cls.get("relationships", [])
        if attrs or rels:
            return len(attrs) + len(rels)
        return len(cls.get("properties", []))
    return 0


_XSD_TYPES = {
    "xsd:string",
    "xsd:integer",
    "xsd:int",
    "xsd:decimal",
    "xsd:float",
    "xsd:double",
    "xsd:boolean",
    "xsd:date",
    "xsd:dateTime",
    "xsd:time",
    "xsd:anyURI",
    "xsd:long",
    "xsd:short",
    "xsd:byte",
    "xsd:nonNegativeInteger",
    "xsd:positiveInteger",
    "xsd:duration",
    "xsd:gYear",
    "xsd:gMonth",
    "xsd:base64Binary",
    "xsd:hexBinary",
    "xsd:normalizedString",
    "xsd:token",
}


def _is_object_property(
    range_val: str,
    property_type: str,
    uri_to_key: dict[str, str],
    class_keys: dict[str, str],
) -> bool:
    """Determine if a property is an object property (relationship between classes)."""
    if property_type == "object":
        return True
    if property_type == "datatype":
        return False
    if range_val.startswith("http"):
        return True
    if range_val.lower() in _XSD_TYPES or range_val.lower().startswith("xsd:"):
        return False
    if "#" in range_val:
        frag = range_val.split("#")[-1]
        if frag in class_keys or range_val in uri_to_key:
            return True
        return True
    frag = range_val.split("/")[-1]
    return frag in class_keys or range_val in class_keys


def _infer_property_type(
    range_val: str,
    property_type: str,
    uri_to_key: dict[str, str],
    class_keys: dict[str, str],
) -> str:
    """Return 'owl:ObjectProperty' or 'owl:DatatypeProperty'."""
    if _is_object_property(range_val, property_type, uri_to_key, class_keys):
        return "owl:ObjectProperty"
    return "owl:DatatypeProperty"


def _materialize_to_graph(
    db: StandardDatabase,
    *,
    run_id: str,
    document_id: str,
    ontology_id: str,
    result: Any,
    faithfulness_scores: dict[str, float] | None = None,
    validity_scores: dict[str, float] | None = None,
) -> None:
    """Write extracted classes/properties into PGT-aligned graph collections.

    Attributes  → ``ontology_datatype_properties`` + ``rdfs_domain`` edges
    Relationships → ``ontology_object_properties`` + ``rdfs_domain`` + ``rdfs_range_class`` edges

    Backward compat: if a class has only legacy ``properties`` (no ``attributes``
    / ``relationships``), they are split using ``_is_object_property()``.
    """
    now = time.time()
    classes = result.classes if hasattr(result, "classes") else result.get("classes", [])

    vertex_collections = (
        "ontology_classes",
        "ontology_datatype_properties",
        "ontology_object_properties",
        "ontology_constraints",
    )
    edge_collections = (
        "rdfs_domain",
        "rdfs_range_class",
        "subclass_of",
        "extracted_from",
        "has_chunk",
        "produced_by",
    )
    for col_name in (*vertex_collections, *edge_collections):
        if not db.has_collection(col_name):
            db.create_collection(col_name, edge=(col_name in edge_collections))

    cls_col = db.collection("ontology_classes")
    dt_prop_col = db.collection("ontology_datatype_properties")
    obj_prop_col = db.collection("ontology_object_properties")
    rdfs_domain_col = db.collection("rdfs_domain")
    rdfs_range_col = db.collection("rdfs_range_class")
    extracted_col = db.collection("extracted_from")
    subclass_col = db.collection("subclass_of")
    constraint_col = db.collection("ontology_constraints")

    class_keys: dict[str, str] = {}  # label -> key (legacy name; really label_to_key)
    uri_to_key: dict[str, str] = {}  # full URI -> key
    fragment_to_key: dict[str, str] = {}  # URI fragment -> key (for resolver tier 2)
    class_parent_uris: list[tuple[str, str, list[dict[str, Any]]]] = []
    deferred_rels: list[dict[str, Any]] = []
    # Stream 3 PR 1 -- OWL restrictions get materialized AFTER all
    # properties (attributes + relationships) so that ``property_uri``
    # can be resolved to the property's Arango ``_id``. We collect
    # (class_key, raw_constraints, class_property_uri_map) tuples here
    # and process at the bottom of this function.
    deferred_constraints: list[tuple[str, list[dict[str, Any]], dict[str, tuple[str, str]]]] = []

    for cls in classes:
        cls_data = cls.model_dump() if hasattr(cls, "model_dump") else dict(cls)
        label = cls_data.get("label", "Unknown")
        uri = cls_data.get("uri", f"http://example.org/ontology#{label.replace(' ', '')}")
        key = uri.split("#")[-1].split("/")[-1]

        class_doc = {
            "_key": key,
            "label": label,
            "uri": uri,
            "description": cls_data.get("description", ""),
            "ontology_id": ontology_id,
            "extraction_run_id": run_id,
            "confidence": cls_data.get("confidence", 0.0),
            "faithfulness_score": cls_data.get("faithfulness_score"),
            "semantic_validity_score": cls_data.get("semantic_validity_score"),
            "evidence": cls_data.get("evidence", []),
            "parent_evidence": cls_data.get("parent_evidence", []),
            "rdf_type": "owl:Class",
            "created": now,
            "expired": NEVER_EXPIRES,
        }
        # Stream 16 DD.2: persist the topical domain when present. Added
        # conditionally so detection-disabled runs write the exact same
        # class document as before (byte-identical).
        domain_tag = cls_data.get("domain_tag")
        if domain_tag:
            class_doc["domain_tag"] = domain_tag
        try:
            cls_col.insert(class_doc, overwrite=True)
        except Exception as exc:
            log.warning("class insert failed for %s: %s", key, exc)
        class_keys[label] = key
        uri_to_key[uri] = key
        # Index by URI fragment (post ``#`` / final path segment) so the
        # range resolver can find a class by fragment even when its label
        # diverges from the URI suffix (the common LLM case).
        fragment_to_key[key] = key

        parent_uri = cls_data.get("parent_uri")
        if parent_uri:
            class_parent_uris.append((key, parent_uri, cls_data.get("parent_evidence", [])))

        # --- PGT-aligned property handling ---
        attributes: list[dict[str, Any]] = cls_data.get("attributes", [])
        relationships: list[dict[str, Any]] = cls_data.get("relationships", [])

        # Backward compat: split legacy properties when PGT fields are absent
        if not attributes and not relationships:
            for prop in cls_data.get("properties", []):
                prop_range = prop.get("range", "xsd:string")
                prop_type = prop.get("property_type", "")
                if _is_object_property(prop_range, prop_type, uri_to_key, class_keys):
                    relationships.append(
                        {
                            "uri": prop.get("uri", ""),
                            "label": prop.get("label", ""),
                            "description": prop.get("description", ""),
                            "target_class_uri": prop_range,
                            "confidence": prop.get("confidence", 0.0),
                            "evidence": prop.get("evidence", []),
                        }
                    )
                else:
                    attributes.append(
                        {
                            "uri": prop.get("uri", ""),
                            "label": prop.get("label", ""),
                            "description": prop.get("description", ""),
                            "range_datatype": prop_range,
                            "confidence": prop.get("confidence", 0.0),
                            "evidence": prop.get("evidence", []),
                        }
                    )

        # Per-class URI → (prop_key, collection) lookup. Populated as we
        # walk attributes (immediate insert) and queue relationships
        # (deferred insert) so that constraint materialization later can
        # resolve property_uri back to a specific property document on
        # THIS class.
        class_prop_uri_map: dict[str, tuple[str, str]] = {}

        # Attributes → ontology_datatype_properties + rdfs_domain
        for attr in attributes:
            attr_label = attr.get("label", "unknown_attr")
            prop_key = f"{key}_{attr_label.replace(' ', '_').lower()}"
            attr_uri = attr.get("uri") or f"{uri.rsplit('#', 1)[0]}#{attr_label.replace(' ', '')}"
            class_prop_uri_map[attr_uri] = (prop_key, "ontology_datatype_properties")
            prop_doc = {
                "_key": prop_key,
                "uri": attr_uri,
                "label": attr_label,
                "description": attr.get("description", ""),
                "range_datatype": attr.get("range_datatype", "xsd:string"),
                "ontology_id": ontology_id,
                "confidence": attr.get("confidence", 0.0),
                "evidence": attr.get("evidence", []),
                "created": now,
                "expired": NEVER_EXPIRES,
            }
            try:
                dt_prop_col.insert(prop_doc, overwrite=True)
            except Exception as exc:
                log.warning("datatype property insert failed for %s: %s", prop_key, exc)

            # Idempotent: a re-extraction of the same class from a
            # second document used to silently insert a duplicate
            # rdfs_domain edge here, leaving N>1 live rows for the
            # same logical (datatype-property, class) pair. See
            # ``app.db.utils.insert_temporal_edge_if_absent`` for the
            # full bug-history rationale.
            with contextlib.suppress(Exception):
                insert_temporal_edge_if_absent(
                    db,
                    rdfs_domain_col,
                    from_id=f"ontology_datatype_properties/{prop_key}",
                    to_id=f"ontology_classes/{key}",
                    ontology_id=ontology_id,
                    now=now,
                )

        # Collect relationships for deferred processing (need all class_keys first)
        for rel in relationships:
            rel_label = rel.get("label", "unknown_rel")
            prop_key = f"{key}_{rel_label.replace(' ', '_').lower()}"
            rel_uri = rel.get("uri") or f"{uri.rsplit('#', 1)[0]}#{rel_label.replace(' ', '')}"
            class_prop_uri_map[rel_uri] = (prop_key, "ontology_object_properties")
            deferred_rels.append(
                {
                    "domain_key": key,
                    "prop_key": prop_key,
                    "uri": rel_uri,
                    "label": rel_label,
                    "description": rel.get("description", ""),
                    "target_class_uri": rel.get("target_class_uri", ""),
                    # Forward an LLM-supplied target_class_label if present
                    # (the prompts don't request it today, but the resolver
                    # accepts it and a future prompt change can start emitting
                    # it without further pipeline work).
                    "target_class_label": rel.get("target_class_label"),
                    "confidence": rel.get("confidence", 0.0),
                    "evidence": rel.get("evidence", []),
                }
            )

        with contextlib.suppress(Exception):
            extracted_col.insert(
                {
                    "_from": f"ontology_classes/{key}",
                    "_to": f"documents/{document_id}",
                    "run_id": run_id,
                    "ontology_id": ontology_id,
                    "created": now,
                    "expired": NEVER_EXPIRES,
                }
            )

        # Stream 3 PR 1 -- queue OWL restrictions on this class. Actual
        # insert happens at the bottom of this function, AFTER the
        # deferred-relationships loop has determined every property's key.
        raw_constraints = cls_data.get("constraints", [])
        if raw_constraints:
            deferred_constraints.append((key, raw_constraints, class_prop_uri_map))

    # subclass_of edges
    for child_key, parent_uri, parent_evidence in class_parent_uris:
        parent_key = uri_to_key.get(parent_uri)
        if not parent_key:
            parent_frag = parent_uri.split("#")[-1].split("/")[-1]
            parent_key = class_keys.get(parent_frag) or class_keys.get(parent_uri)
        if parent_key and parent_key != child_key:
            with contextlib.suppress(Exception):
                subclass_col.insert(
                    {
                        "_from": f"ontology_classes/{child_key}",
                        "_to": f"ontology_classes/{parent_key}",
                        "ontology_id": ontology_id,
                        "evidence": parent_evidence,
                        "created": now,
                        "expired": NEVER_EXPIRES,
                    }
                )
        elif parent_key == child_key:
            log.warning("skipping self-referential subclass_of: %s", child_key)

    # Deferred relationships → ontology_object_properties + rdfs_domain + rdfs_range_class
    #
    # Resolution uses ``edge_repair.resolve_range_class`` which tries four
    # ordered tiers (uri / fragment / label / miss). The raw
    # ``target_class_uri`` and the humanised ``target_class_label`` are
    # persisted on every property document regardless of resolution success,
    # so a later repair pass (or a curator) can always recover the LLM's
    # original intent. Misses now log a WARNING (the silent failure mode
    # was the original orphan-property bug).
    for rel in deferred_rels:
        target_uri = rel["target_class_uri"]
        resolution = resolve_range_class(
            target_uri,
            uri_to_key=uri_to_key,
            fragment_to_key=fragment_to_key,
            label_to_key=class_keys,
            target_label=rel.get("target_class_label"),
        )

        prop_key = rel["prop_key"]
        prop_doc = {
            "_key": prop_key,
            "uri": rel["uri"],
            "label": rel["label"],
            "description": rel["description"],
            "ontology_id": ontology_id,
            "confidence": rel["confidence"],
            "evidence": rel.get("evidence", []),
            # Persist the LLM's range intent even when resolution missed,
            # so future repair / re-extraction can pick up where this run
            # left off.
            "target_class_uri": target_uri,
            "target_class_label": resolution.target_label,
            "created": now,
            "expired": NEVER_EXPIRES,
        }
        try:
            obj_prop_col.insert(prop_doc, overwrite=True)
        except Exception as exc:
            log.warning("object property insert failed for %s: %s", prop_key, exc)

        domain_key = rel["domain_key"]
        # Idempotent (see datatype-property branch above for the bug
        # rationale). The previous bare insert here was the dominant
        # source of duplicate live rdfs_domain edges in the wild --
        # an audit on WTW Ontology found 6 duplicated pairs, all
        # from object-property re-extraction across documents.
        try:
            insert_temporal_edge_if_absent(
                db,
                rdfs_domain_col,
                from_id=f"ontology_object_properties/{prop_key}",
                to_id=f"ontology_classes/{domain_key}",
                ontology_id=ontology_id,
                now=now,
            )
        except Exception as exc:
            log.warning(
                "rdfs_domain insert failed for object property %s -> %s: %s",
                prop_key,
                domain_key,
                exc,
            )

        if resolution.class_key:
            if resolution.tier == "label":
                # Tier 4 hit -- the URI didn't match anything but the
                # humanised label matched a class. Worth an INFO line so
                # we can monitor how often the resolver is bailing out
                # the LLM in the wild.
                log.info(
                    "resolved object-property %s range via label match: "
                    "target_uri=%r -> class_key=%r (label=%r)",
                    prop_key,
                    target_uri,
                    resolution.class_key,
                    resolution.target_label,
                )
            # Idempotent: live audit on WTW Ontology found zero
            # duplicate pairs here (rdfs_range_class is more
            # brittle to re-resolve, so the second extraction
            # often skipped this insert anyway), but the fix is
            # cheap and the contract is the same as rdfs_domain --
            # one live edge per logical (property, range-class)
            # pair, no exceptions.
            try:
                insert_temporal_edge_if_absent(
                    db,
                    rdfs_range_col,
                    from_id=f"ontology_object_properties/{prop_key}",
                    to_id=f"ontology_classes/{resolution.class_key}",
                    ontology_id=ontology_id,
                    now=now,
                )
            except Exception as exc:
                log.warning(
                    "rdfs_range_class insert failed for object property %s -> %s: %s",
                    prop_key,
                    resolution.class_key,
                    exc,
                )
        else:
            # All four resolver tiers missed. The property still exists with
            # its rdfs_domain edge and persisted target_class_{uri,label},
            # so post-hoc repair (``edge_repair.repair_orphan_object_property_ranges``)
            # can still recover it. But surface it now -- the original bug
            # was that this case was silent.
            log.warning(
                "could not resolve target_class_uri for object property %s "
                "(target_uri=%r, target_label=%r); property persisted as "
                "orphan and will be a candidate for edge_repair",
                prop_key,
                target_uri,
                resolution.target_label,
            )

    # Stream 3 PR 1 -- materialize OWL restrictions into ontology_constraints.
    #
    # One restriction document per row (the OWL-native shape, matching
    # PRD §6.14). A class that has both "min 1 holder" and "max 5
    # holders" yields TWO documents; the rule engine groups them at
    # evaluation time. ``property_id`` is left null when the URI can't
    # be resolved to a property on the same class, so post-hoc repair
    # can pick it up; the LLM's raw ``property_uri`` is always retained.
    if deferred_constraints:
        for class_key, raw_constraints, class_prop_uri_map in deferred_constraints:
            for raw_c in raw_constraints:
                restriction_type = raw_c.get("restriction_type")
                if not restriction_type:
                    continue
                property_uri = raw_c.get("property_uri", "") or ""
                resolved = class_prop_uri_map.get(property_uri)
                if resolved is None and property_uri:
                    # Defensive: the LLM occasionally drifts on URI suffix
                    # casing. Try fragment match against the same class.
                    target_frag = property_uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
                    for known_uri, lookup in class_prop_uri_map.items():
                        if known_uri.rsplit("#", 1)[-1].rsplit("/", 1)[-1] == target_frag:
                            resolved = lookup
                            break
                if resolved is None:
                    log.warning(
                        "constraint property_uri %r could not be resolved to a "
                        "property on class %s; persisting with property_id=null",
                        property_uri,
                        class_key,
                    )
                    property_id: str | None = None
                else:
                    prop_key, prop_col_name = resolved
                    property_id = f"{prop_col_name}/{prop_key}"

                constraint_doc: dict[str, Any] = {
                    "constraint_type": "owl:Restriction",
                    "on_class": f"ontology_classes/{class_key}",
                    "property_id": property_id,
                    "property_uri": property_uri,
                    "restriction_type": restriction_type,
                    "restriction_value": raw_c.get("restriction_value"),
                    "description": raw_c.get("description", "") or "",
                    "ontology_id": ontology_id,
                    "extraction_run_id": run_id,
                    "confidence": raw_c.get("confidence", 0.5),
                    "evidence": raw_c.get("evidence", []),
                    "created": now,
                    "expired": NEVER_EXPIRES,
                }
                try:
                    constraint_col.insert(constraint_doc)
                except Exception as exc:
                    log.warning(
                        "constraint insert failed for class %s, property_uri=%r: %s",
                        class_key,
                        property_uri,
                        exc,
                    )

    # has_chunk edges
    if db.has_collection("has_chunk"):
        has_chunk_col = db.collection("has_chunk")
    else:
        # ``create_collection`` is typed as ``StandardCollection | AsyncJob |
        # BatchJob | None`` because the same handle is reused for batch / async
        # execution; on a ``StandardDatabase`` only ``StandardCollection`` is
        # ever returned for a successful create.
        has_chunk_col = cast(
            StandardCollection,
            db.create_collection("has_chunk", edge=True),
        )
    if db.has_collection("chunks"):
        chunk_docs = list(
            run_aql(
                db,
                "FOR c IN chunks FILTER c.doc_id == @doc_id RETURN c._key",
                bind_vars={"doc_id": document_id},
            )
        )
        for chunk_key in chunk_docs:
            with contextlib.suppress(Exception):
                has_chunk_col.insert(
                    {
                        "_from": f"documents/{document_id}",
                        "_to": f"chunks/{chunk_key}",
                        "ontology_id": ontology_id,
                        "run_id": run_id,
                        "created": now,
                        "expired": NEVER_EXPIRES,
                    },
                    overwrite=True,
                )

    _recompute_multi_signal_confidence(
        db,
        ontology_id=ontology_id,
        classes=classes,
        class_keys=class_keys,
        uri_to_key=uri_to_key,
        faithfulness_scores=faithfulness_scores,
        validity_scores=validity_scores,
    )

    log.info(
        "materialized extraction to graph",
        extra={"run_id": run_id, "classes": len(class_keys), "ontology_id": ontology_id},
    )


def _recompute_multi_signal_confidence(
    db: StandardDatabase,
    *,
    ontology_id: str,
    classes: list[Any],
    class_keys: dict[str, str],
    uri_to_key: dict[str, str],
    faithfulness_scores: dict[str, float] | None = None,
    validity_scores: dict[str, float] | None = None,
    property_agreement_scores: dict[str, float] | None = None,
) -> None:
    """Second pass: recompute confidence for each class using multi-signal scoring.

    Runs AFTER all classes, properties, and edges have been materialized so
    that structural connectivity is fully available.

    Uses ``rdfs_domain`` to count properties per class (split by source
    collection) and ``rdfs_range_class`` / ``extends_domain`` for lateral
    connectivity.
    """
    if faithfulness_scores is None:
        faithfulness_scores = {}
    if validity_scores is None:
        validity_scores = {}
    if property_agreement_scores is None:
        property_agreement_scores = {}

    cls_col = db.collection("ontology_classes")
    subclass_col = db.collection("subclass_of")
    extracted_col = db.collection("extracted_from")

    has_rdfs_domain = db.has_collection("rdfs_domain")
    has_rdfs_range = db.has_collection("rdfs_range_class")
    has_extends = db.has_collection("extends_domain")

    all_descriptions: list[str] = []
    for cls in classes:
        cls_data = cls.model_dump() if hasattr(cls, "model_dump") else dict(cls)
        all_descriptions.append(cls_data.get("description", ""))

    for cls in classes:
        cls_data = cls.model_dump() if hasattr(cls, "model_dump") else dict(cls)
        label = cls_data.get("label", "Unknown")
        uri = cls_data.get("uri", "")
        key = uri_to_key.get(uri) or class_keys.get(label)
        if not key:
            continue

        agreement_ratio = cls_data.get("confidence", 0.5)
        description = cls_data.get("description", "")
        class_id = f"ontology_classes/{key}"

        faithfulness = faithfulness_scores.get(
            uri,
            cls_data.get("llm_confidence", 0.5),
        )
        semantic_validity = validity_scores.get(uri, 0.5)
        prop_agreement = property_agreement_scores.get(
            uri,
            cls_data.get("property_agreement", 1.0),
        )

        # Count properties via rdfs_domain edges pointing TO this class,
        # grouped by source collection (datatype vs object).
        datatype_count = 0
        object_count = 0
        if has_rdfs_domain:
            prop_type_counts = list(
                run_aql(
                    db,
                    "FOR e IN rdfs_domain "
                    "FILTER e._to == @cls_id AND e.ontology_id == @oid "
                    "LET col = PARSE_IDENTIFIER(e._from).collection "
                    "COLLECT type = col WITH COUNT INTO cnt "
                    "RETURN {type, cnt}",
                    bind_vars={"cls_id": class_id, "oid": ontology_id},
                )
            )
            for row in prop_type_counts:
                t = row.get("type", "")
                cnt = row.get("cnt", 0)
                if t == "ontology_object_properties":
                    object_count += cnt
                elif t == "ontology_datatype_properties":
                    datatype_count += cnt

        has_parent = bool(
            list(
                run_aql(
                    db,
                    "FOR e IN @@col FILTER e._from == @cls_id AND e.ontology_id == @oid "
                    "LIMIT 1 RETURN true",
                    bind_vars={
                        "@col": subclass_col.name,
                        "cls_id": class_id,
                        "oid": ontology_id,
                    },
                )
            )
        )

        has_children = bool(
            list(
                run_aql(
                    db,
                    "FOR e IN @@col FILTER e._to == @cls_id AND e.ontology_id == @oid "
                    "LIMIT 1 RETURN true",
                    bind_vars={
                        "@col": subclass_col.name,
                        "cls_id": class_id,
                        "oid": ontology_id,
                    },
                )
            )
        )

        # Lateral connectivity: class is domain of an object property, or
        # range of one, or linked via extends_domain.
        has_lateral = object_count > 0
        if not has_lateral and has_rdfs_range:
            has_lateral = bool(
                list(
                    run_aql(
                        db,
                        "FOR e IN rdfs_range_class "
                        "FILTER e._to == @cls_id AND e.ontology_id == @oid "
                        "LIMIT 1 RETURN true",
                        bind_vars={"cls_id": class_id, "oid": ontology_id},
                    )
                )
            )
        if not has_lateral and has_extends:
            has_lateral = bool(
                list(
                    run_aql(
                        db,
                        "FOR e IN extends_domain "
                        "FILTER (e._from == @cls_id OR e._to == @cls_id) "
                        "AND e.ontology_id == @oid "
                        "LIMIT 1 RETURN true",
                        bind_vars={"cls_id": class_id, "oid": ontology_id},
                    )
                )
            )

        provenance_count_result = list(
            run_aql(
                db,
                "FOR e IN @@col FILTER e._from == @cls_id COLLECT WITH COUNT INTO cnt RETURN cnt",
                bind_vars={
                    "@col": extracted_col.name,
                    "cls_id": class_id,
                },
            )
        )
        provenance_count = provenance_count_result[0] if provenance_count_result else 0

        new_confidence = compute_class_confidence(
            agreement_ratio=agreement_ratio,
            faithfulness=faithfulness,
            semantic_validity=semantic_validity,
            datatype_property_count=datatype_count,
            object_property_count=object_count,
            has_parent=has_parent,
            has_children=has_children,
            has_lateral_edges=has_lateral,
            description=description,
            all_descriptions=all_descriptions,
            provenance_count=provenance_count,
            property_agreement=prop_agreement,
        )

        try:
            cls_col.update(
                {
                    "_key": key,
                    "confidence": new_confidence,
                    "faithfulness_score": faithfulness,
                    "semantic_validity_score": semantic_validity,
                }
            )
        except Exception as exc:
            log.warning("confidence update failed for %s: %s", key, exc)


def _load_visualizer_installer() -> Any:
    """Resolve ``install_for_ontology_graph`` from the visualizer
    setup script. Isolated so tests can monkeypatch this single
    entry point (``app.services.extraction._load_visualizer_installer``)
    without touching ``sys.modules`` or ``sys.path``, which sibling
    tests in the suite manipulate and would otherwise cause
    cross-test pollution.

    The import is lazy (inside the function body) so the
    visualizer asset loader doesn't become a hard dependency of
    the extraction service when the assets aren't packaged into a
    given deployment (eg a slim API-only image).

    ``make backend`` launches uvicorn from ``backend/`` (``cd backend &&
    uvicorn app.main:app``), so the repo root that holds the top-level
    ``scripts`` package is not on ``sys.path`` and the import below would
    otherwise raise ``ModuleNotFoundError: No module named 'scripts'``
    regardless of how clean the environment is. Resolve the repo root from
    this module's own location (``<root>/backend/app/services/extraction.py``)
    and prepend it to ``sys.path`` so the visualizer assets install no matter
    what the process CWD is. The insert is idempotent (guarded by membership)
    so repeated extractions don't grow ``sys.path``.
    """
    repo_root = str(Path(__file__).resolve().parents[3])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    from scripts.setup.install_visualizer import install_for_ontology_graph

    return install_for_ontology_graph


def _auto_install_visualizer_assets(
    db: StandardDatabase,
    *,
    ontology_id: str,
    graph_name: str | None,
) -> None:
    """Install ArangoDB Visualizer assets for a per-ontology graph.

    Stream 7 PR 1 -- E.4. After ``ensure_ontology_graph`` succeeds,
    the curator expects to open the Visualizer and see graph-aware
    theme + canvas actions + saved queries pre-wired. Doing it by
    hand (``scripts/setup/install_visualizer.py --graph ...``) was
    the previous flow; this helper closes the loop so a fresh
    extraction is immediately usable.

    Contract:

    * ``graph_name is None`` -> ``ensure_ontology_graph`` failed
      earlier and there's nothing to install assets onto. Skip
      silently (the upstream warning already surfaced the failure).
    * Any exception from the visualizer install path is **caught and
      logged**. The extraction write path must NEVER fail because a
      visualizer asset file is missing or a registry write timed out
      -- those are operator-facing problems the curator can fix
      offline by re-running ``install_visualizer.py``.
    """
    if graph_name is None:
        return

    try:
        install_for_ontology_graph = _load_visualizer_installer()
        install_result = install_for_ontology_graph(db, graph_name)
        log.info(
            "installed visualizer assets for per-ontology graph",
            extra={
                "graph_name": graph_name,
                "ontology_id": ontology_id,
                "summary": install_result,
            },
        )
    except Exception:
        log.warning(
            "visualizer auto-install failed; fall back to manual install_visualizer.py run",
            extra={"graph_name": graph_name, "ontology_id": ontology_id},
            exc_info=True,
        )


def _create_produced_by_edge(
    db: StandardDatabase,
    *,
    ontology_id: str,
    run_id: str,
) -> None:
    """Create a produced_by edge from ontology_registry → extraction_runs."""
    try:
        for col_name in ("produced_by",):
            if not db.has_collection(col_name):
                db.create_collection(col_name, edge=True)

        col = db.collection("produced_by")
        col.insert(
            {
                "_from": f"ontology_registry/{ontology_id}",
                "_to": f"extraction_runs/{run_id}",
                "created": time.time(),
                "expired": NEVER_EXPIRES,
            },
            overwrite=True,
        )
        log.info(
            "created produced_by edge",
            extra={"ontology_id": ontology_id, "run_id": run_id},
        )
    except Exception:
        log.warning("produced_by edge creation failed", exc_info=True)


def _update_existing_ontology(
    db: StandardDatabase,
    *,
    ontology_id: str,
    run_id: str,
    result: Any,
) -> str | None:
    """Update an existing ontology registry entry for incremental extraction.

    Increments class/property counts and updates the timestamp.
    Returns the ontology_id on success, None on failure.
    """
    try:
        from app.db import registry_repo

        entry = registry_repo.get_registry_entry(ontology_id)
        if entry is None:
            log.warning(
                "target ontology %s not found, falling back to new registration",
                ontology_id,
            )
            return None

        classes = result.classes if hasattr(result, "classes") else result.get("classes", [])
        new_class_count = len(classes)
        new_prop_count = sum(_count_class_properties(c) for c in classes)

        registry_repo.update_registry_entry(
            ontology_id,
            {
                "class_count": entry.get("class_count", 0) + new_class_count,
                "property_count": entry.get("property_count", 0) + new_prop_count,
                "extraction_run_id": run_id,
            },
        )
        log.info(
            "updated existing ontology for incremental extraction",
            extra={"ontology_id": ontology_id, "run_id": run_id, "new_classes": new_class_count},
        )
        return ontology_id
    except Exception:
        log.warning("failed to update existing ontology %s", ontology_id, exc_info=True)
        return None


def _record_base_ontology_imports(
    db: StandardDatabase,
    *,
    ontology_id: str,
    base_ontology_ids: list[str],
    run_id: str,
) -> dict[str, list[str]]:
    """Record ``owl:imports`` edges from the newly-registered ontology to
    every base ontology declared on the extraction request (Stream 1 H.8).

    Mirrors the validation that ``add_ontology_import`` performs (target
    must exist, no self-import, no duplicate, no cycle) but is
    batch-friendly: a bad base id only skips that one edge rather than
    failing the whole run. The skipped categories are returned so the
    extraction logs (and any future UI surface) can show the user exactly
    which bases were honoured.

    Skipped categories:

    * ``missing`` -- base ontology id is not in the registry.
    * ``self`` -- the new ontology equals a base id (UI quirk; ignore).
    * ``duplicate`` -- a live ``imports`` edge to that base already
      exists. The pre-extraction registry entry has no edges so this
      only fires when the user retries an extraction after manually
      adding the same import.
    * ``cycle`` -- adding the edge would create a cycle through the
      named graph (matches ``add_ontology_import``'s 10-hop check).
    """
    summary: dict[str, list[str]] = {
        "created": [],
        "missing": [],
        "self": [],
        "duplicate": [],
        "cycle": [],
    }

    if not base_ontology_ids:
        return summary

    if not db.has_collection("imports"):
        log.warning(
            "imports collection missing; skipping base ontology recording",
            extra={"run_id": run_id, "ontology_id": ontology_id},
        )
        for bid in base_ontology_ids:
            summary["missing"].append(bid)
        return summary

    from app.db import ontology_repo, registry_repo

    from_id = f"ontology_registry/{ontology_id}"

    for base_id in base_ontology_ids:
        if base_id == ontology_id:
            summary["self"].append(base_id)
            continue

        target = registry_repo.get_registry_entry(base_id, db=db)
        if target is None:
            summary["missing"].append(base_id)
            log.warning(
                "base ontology not in registry, skipping",
                extra={"run_id": run_id, "ontology_id": ontology_id, "base_id": base_id},
            )
            continue

        to_id = f"ontology_registry/{base_id}"

        existing = list(
            run_aql(
                db,
                "FOR e IN imports "
                "FILTER e._from == @f AND e._to == @t AND e.expired == @never "
                "RETURN e._key",
                bind_vars={"f": from_id, "t": to_id, "never": NEVER_EXPIRES},
            )
        )
        if existing:
            summary["duplicate"].append(base_id)
            continue

        # Cycle check: would the base (transitively) already import us?
        # Mirrors add_ontology_import's check so behaviour matches.
        cycle_check = list(
            run_aql(
                db,
                """
                FOR v IN 1..10 OUTBOUND @target_id imports
                  FILTER v._key == @source_key
                  LIMIT 1
                  RETURN true
                """,
                bind_vars={"target_id": to_id, "source_key": ontology_id},
            )
        )
        if cycle_check:
            summary["cycle"].append(base_id)
            log.warning(
                "skipping base import that would create a cycle",
                extra={
                    "run_id": run_id,
                    "ontology_id": ontology_id,
                    "base_id": base_id,
                },
            )
            continue

        try:
            ontology_repo.create_edge(
                db=db,
                edge_collection="imports",
                from_id=from_id,
                to_id=to_id,
                data={"import_iri": target.get("uri", "")},
            )
            summary["created"].append(base_id)
        except Exception:
            # Defensive: a write failure for one base must not abort the
            # rest of the recording or the surrounding extraction.
            log.warning(
                "failed to create base import edge",
                exc_info=True,
                extra={
                    "run_id": run_id,
                    "ontology_id": ontology_id,
                    "base_id": base_id,
                },
            )
            summary["missing"].append(base_id)

    log.info(
        "recorded base ontology imports",
        extra={
            "run_id": run_id,
            "ontology_id": ontology_id,
            "summary": {k: len(v) for k, v in summary.items()},
        },
    )
    return summary


def _auto_register_ontology(
    db: StandardDatabase,
    *,
    run_id: str,
    document_id: str,
    result: Any,
) -> str | None:
    """Register an ontology in the library after successful extraction.

    Returns the ontology_id (_key) on success, None on failure.
    """
    try:
        from app.db import documents_repo, registry_repo

        doc = documents_repo.get_document(document_id)
        filename = doc.get("filename", "unknown") if doc else "unknown"
        name = filename.rsplit(".", 1)[0].replace("-", " ").replace("_", " ").title()

        classes = result.classes if hasattr(result, "classes") else result.get("classes", [])
        class_count = len(classes)

        entry = registry_repo.create_registry_entry(
            {
                "name": name,
                "description": f"Ontology extracted from {filename}",
                "tier": "local",
                "source_document_id": document_id,
                "extraction_run_id": run_id,
                "class_count": class_count,
                "property_count": sum(_count_class_properties(c) for c in classes),
                "namespace": "http://example.org/ontology#",
            }
        )
        ontology_id_raw = entry.get("_key", run_id)
        ontology_key = str(ontology_id_raw)
        log.info(
            "auto-registered ontology",
            extra={
                "run_id": run_id,
                "ontology_name": name,
                "classes": class_count,
                "ontology_id": ontology_key,
            },
        )
        return ontology_key
    except Exception:
        log.warning("auto-registration failed — ontology can be registered manually", exc_info=True)
        return None


def _compute_agreement_rate(pass_results: list[Any]) -> float:
    """Compute cross-pass agreement rate as fraction of overlapping class URIs."""
    if len(pass_results) < 2:
        return 1.0
    uri_sets: list[set[str]] = []
    for pr in pass_results:
        classes = pr.classes if hasattr(pr, "classes") else pr.get("classes", [])
        uris = set()
        for c in classes:
            uri = c.uri if hasattr(c, "uri") else c.get("uri", "")
            if uri:
                uris.add(uri)
        uri_sets.append(uris)
    if not uri_sets or all(len(s) == 0 for s in uri_sets):
        return 0.0
    intersection = uri_sets[0]
    union = set(uri_sets[0])
    for s in uri_sets[1:]:
        intersection = intersection & s
        union = union | s
    return len(intersection) / len(union) if union else 0.0


def _serialize_step_log(step_log: dict[str, Any] | Any) -> dict[str, Any]:
    """Serialize a step log entry for storage."""
    if isinstance(step_log, dict):
        return cast(dict[str, Any], step_log)
    if hasattr(step_log, "model_dump"):
        return cast(dict[str, Any], step_log.model_dump())
    return cast(dict[str, Any], dict(step_log))
