"""ExtractionRunService — orchestrates extraction pipeline lifecycle.

Creates extraction_runs records, dispatches LangGraph pipeline, updates status,
and tracks token usage and cost.
"""

from __future__ import annotations

import contextlib
import logging
import sys
import time
import uuid
from typing import Any, cast

from arango.database import StandardDatabase

from app.api.errors import NotFoundError
from app.config import settings
from app.db.client import get_db
from app.db.pagination import paginate
from app.db.utils import doc_get, run_aql
from app.extraction.pipeline import run_pipeline
from app.models.common import PaginatedResponse
from app.services.confidence import compute_class_confidence

log = logging.getLogger(__name__)

_COST_PER_1K_TOKENS: dict[str, float] = {
    "claude-sonnet-4-20250514": 0.003,
    "claude-3-5-sonnet-20241022": 0.003,
    "gpt-4o": 0.005,
    "gpt-4o-mini": 0.00015,
}


def _generate_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


def _get_collection(db: StandardDatabase, name: str):
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

    domain_context = ""
    if domain_ontology_ids:
        try:
            from app.services.ontology_context import serialize_multi_domain_context

            domain_context = serialize_multi_domain_context(
                db, ontology_ids=domain_ontology_ids,
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

    chunks: list[dict[str, Any]] = []
    for did in doc_ids:
        chunks.extend(_load_document_chunks(db, did))

    primary_doc_id = doc_ids[0] if doc_ids else "unknown"

    final_state: dict[str, Any] = {}
    try:
        final_state = cast("dict[str, Any]", await run_pipeline(
            run_id=run_id,
            document_id=primary_doc_id,
            chunks=chunks,
            event_callback=event_callback,
            domain_context=domain_context,
            domain_ontology_ids=domain_ontology_ids or [],
        ))

        completed_at = time.time()
        status = "completed"
        if final_state.get("errors"):
            status = "completed_with_errors"
        if final_state.get("consistency_result") is None:
            status = "failed"

        consistency = final_state.get("consistency_result")
        classes_extracted = len(consistency.classes) if consistency else 0
        properties_extracted = (
            sum(len(c.properties) for c in consistency.classes) if consistency else 0
        )
        pass_results = final_state.get("extraction_passes", [])
        pass_agreement_rate = _compute_agreement_rate(pass_results) if pass_results else 0.0
        if pass_agreement_rate == 0.0:
            for sl in final_state.get("step_logs", []):
                sl_dict = (
                    sl if isinstance(sl, dict)
                    else (sl.model_dump() if hasattr(sl, "model_dump") else dict(sl))
                )
                if sl_dict.get("step") == "consistency_checker":
                    rates = sl_dict.get("metadata", {}).get("agreement_rates", {})
                    if rates:
                        pass_agreement_rate = sum(rates.values()) / len(rates)
                    break

        update_data: dict[str, Any] = {
            "completed_at": completed_at,
            "status": status,
            "stats": {
                **run_record["stats"],
                "token_usage": final_state.get("token_usage", {}),
                "errors": final_state.get("errors", []),
                "step_logs": [
                    _serialize_step_log(sl) for sl in final_state.get("step_logs", [])
                ],
                "classes_extracted": classes_extracted,
                "properties_extracted": properties_extracted,
                "pass_agreement_rate": pass_agreement_rate,
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
                try:
                    from app.services.ontology_graphs import ensure_ontology_graph
                    graph_name = ensure_ontology_graph(ontology_id, db=db)
                    log.info("ensured per-ontology graph %s", graph_name)
                except Exception:
                    log.warning(
                        "per-ontology graph creation failed",
                        exc_info=True,
                    )

    except Exception as exc:
        log.exception("extraction pipeline failed", extra={"run_id": run_id})
        partial_logs: list[dict[str, Any]] = []
        if final_state and final_state.get("step_logs"):
            partial_logs = [
                _serialize_step_log(sl) for sl in final_state["step_logs"]
            ]
        col.update({
            "_key": run_id,
            "status": "failed",
            "completed_at": time.time(),
            "stats": {
                **run_record["stats"],
                "errors": [str(exc)],
                "step_logs": partial_logs,
                "token_usage": (
                    final_state.get("token_usage", {}) if final_state else {}
                ),
            },
        })

    updated = doc_get(col, run_id)
    return updated or {}


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
) -> PaginatedResponse[dict]:
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
    return run.get("stats", {}).get("step_logs", [])


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
        return results_doc["extraction_result"]

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
) -> dict[str, Any]:
    """Get token usage and estimated cost for a run.

    Also includes quality indicators (avg_confidence, completeness_pct)
    when the run has an associated ontology.
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
    cost_per_1k = _COST_PER_1K_TOKENS.get(model, 0.003)
    estimated_cost = (total_tokens / 1000) * cost_per_1k

    started = run.get("started_at", 0)
    completed = run.get("completed_at", 0)
    duration_ms = int((completed - started) * 1000) if started and completed else 0

    avg_confidence: float | None = None
    completeness_pct: float | None = None
    ontology_id = run.get("ontology_id")
    if not ontology_id and db.has_collection("ontology_registry"):
        matches = list(run_aql(db,
            "FOR o IN ontology_registry "
            "FILTER o.extraction_run_id == @rid "
            "LIMIT 1 RETURN o._key",
            bind_vars={"rid": run_id},
        ))
        if matches:
            ontology_id = matches[0]

    if ontology_id:
        try:
            from app.services.quality_metrics import compute_ontology_quality

            oq = compute_ontology_quality(db, ontology_id)
            avg_confidence = oq.get("avg_confidence")
            completeness_pct = oq.get("completeness")
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
        "cost_per_1k_tokens": cost_per_1k,
        "avg_confidence": avg_confidence,
        "completeness_pct": completeness_pct,
    }


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

    return list(run_aql(db,query, bind_vars={"doc_id": document_id}))


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


NEVER_EXPIRES: int = sys.maxsize


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
    """Write extracted classes/properties into graph collections with edges."""
    now = time.time()
    classes = result.classes if hasattr(result, "classes") else result.get("classes", [])

    edge_collections = ("has_property", "subclass_of", "related_to",
                         "extracted_from", "has_chunk", "produced_by")
    for col_name in ("ontology_classes", "ontology_properties", *edge_collections):
        if not db.has_collection(col_name):
            db.create_collection(col_name, edge=(col_name in edge_collections))

    cls_col = db.collection("ontology_classes")
    prop_col = db.collection("ontology_properties")
    has_prop_col = db.collection("has_property")
    extracted_col = db.collection("extracted_from")
    subclass_col = db.collection("subclass_of")
    db.collection("related_to")

    class_keys: dict[str, str] = {}
    uri_to_key: dict[str, str] = {}
    class_parent_uris: list[tuple[str, str]] = []

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
            "rdf_type": "owl:Class",
            "created": now,
            "expired": NEVER_EXPIRES,
        }
        try:
            cls_col.insert(class_doc, overwrite=True)
        except Exception as exc:
            log.warning("class insert failed for %s: %s", key, exc)
        class_keys[label] = key
        uri_to_key[uri] = key

        parent_uri = cls_data.get("parent_uri")
        if parent_uri:
            class_parent_uris.append((key, parent_uri))

        props = cls_data.get("properties", [])
        for prop in props:
            prop_label = prop.get("label", "unknown_prop")
            prop_key = f"{key}_{prop_label.replace(' ', '_').lower()}"
            prop_doc = {
                "_key": prop_key,
                "label": prop_label,
                "uri": f"{uri.rsplit('#', 1)[0]}#{prop_label.replace(' ', '')}",
                "description": prop.get("description", ""),
                "domain_class": key,
                "range": prop.get("range", "xsd:string"),
                "ontology_id": ontology_id,
                "confidence": prop.get("confidence", 0.0),
                "rdf_type": (
                    "owl:ObjectProperty"
                    if prop.get("range", "").startswith("http")
                    else "owl:DatatypeProperty"
                ),
                "created": now,
                "expired": NEVER_EXPIRES,
            }
            try:
                prop_col.insert(prop_doc, overwrite=True)
            except Exception as exc:
                log.warning("property insert failed for %s: %s", prop_key, exc)

            with contextlib.suppress(Exception):
                has_prop_col.insert({
                    "_from": f"ontology_classes/{key}",
                    "_to": f"ontology_properties/{prop_key}",
                    "ontology_id": ontology_id,
                    "created": now,
                    "expired": NEVER_EXPIRES,
                })

        with contextlib.suppress(Exception):
            extracted_col.insert({
                "_from": f"ontology_classes/{key}",
                "_to": f"documents/{document_id}",
                "run_id": run_id,
                "ontology_id": ontology_id,
                "created": now,
                "expired": NEVER_EXPIRES,
            })

    for child_key, parent_uri in class_parent_uris:
        parent_key = uri_to_key.get(parent_uri)
        if not parent_key:
            parent_frag = parent_uri.split("#")[-1].split("/")[-1]
            parent_key = class_keys.get(parent_frag) or class_keys.get(parent_uri)
        if parent_key:
            with contextlib.suppress(Exception):
                subclass_col.insert({
                    "_from": f"ontology_classes/{child_key}",
                    "_to": f"ontology_classes/{parent_key}",
                    "ontology_id": ontology_id,
                    "created": now,
                    "expired": NEVER_EXPIRES,
                })

    has_chunk_col = db.collection("has_chunk")
    if db.has_collection("chunks"):
        chunk_docs = list(run_aql(db,
            "FOR c IN chunks FILTER c.doc_id == @doc_id RETURN c._key",
            bind_vars={"doc_id": document_id},
        ))
        for chunk_key in chunk_docs:
            with contextlib.suppress(Exception):
                has_chunk_col.insert({
                    "_from": f"documents/{document_id}",
                    "_to": f"chunks/{chunk_key}",
                    "ontology_id": ontology_id,
                    "run_id": run_id,
                    "created": now,
                    "expired": NEVER_EXPIRES,
                }, overwrite=True)

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

    Parameters
    ----------
    faithfulness_scores:
        Per-class URI → faithfulness score from the LLM judge. Defaults to
        the class's ``llm_confidence`` when not available.
    validity_scores:
        Per-class URI → semantic validity score from the validator.
    property_agreement_scores:
        Per-class URI → cross-pass property agreement (Jaccard). Falls back
        to the ``property_agreement`` field on the class model.
    """
    if faithfulness_scores is None:
        faithfulness_scores = {}
    if validity_scores is None:
        validity_scores = {}
    if property_agreement_scores is None:
        property_agreement_scores = {}

    cls_col = db.collection("ontology_classes")
    db.collection("ontology_properties")
    has_prop_col = db.collection("has_property")
    subclass_col = db.collection("subclass_of")
    extracted_col = db.collection("extracted_from")

    has_related = db.has_collection("related_to")
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
            uri, cls_data.get("llm_confidence", 0.5),
        )
        semantic_validity = validity_scores.get(uri, 0.5)
        prop_agreement = property_agreement_scores.get(
            uri, cls_data.get("property_agreement", 1.0),
        )

        prop_type_counts = list(run_aql(db,
            "FOR e IN @@hp FILTER e._from == @cls_id AND e.ontology_id == @oid "
            "LET prop = DOCUMENT(e._to) "
            "COLLECT rdf = prop.rdf_type WITH COUNT INTO cnt "
            "RETURN {rdf, cnt}",
            bind_vars={
                "@hp": has_prop_col.name,
                "cls_id": class_id,
                "oid": ontology_id,
            },
        ))
        datatype_count = 0
        object_count = 0
        for row in prop_type_counts:
            rdf = row.get("rdf", "")
            cnt = row.get("cnt", 0)
            if rdf == "owl:ObjectProperty":
                object_count += cnt
            else:
                datatype_count += cnt

        has_parent = bool(list(run_aql(db,
            "FOR e IN @@col FILTER e._from == @cls_id AND e.ontology_id == @oid "
            "LIMIT 1 RETURN true",
            bind_vars={
                "@col": subclass_col.name,
                "cls_id": class_id,
                "oid": ontology_id,
            },
        )))

        has_children = bool(list(run_aql(db,
            "FOR e IN @@col FILTER e._to == @cls_id AND e.ontology_id == @oid "
            "LIMIT 1 RETURN true",
            bind_vars={
                "@col": subclass_col.name,
                "cls_id": class_id,
                "oid": ontology_id,
            },
        )))

        has_lateral = False
        if has_related:
            has_lateral = bool(list(run_aql(db,
                "FOR e IN related_to "
                "FILTER (e._from == @cls_id OR e._to == @cls_id) "
                "AND e.ontology_id == @oid "
                "LIMIT 1 RETURN true",
                bind_vars={"cls_id": class_id, "oid": ontology_id},
            )))
        if not has_lateral and has_extends:
            has_lateral = bool(list(run_aql(db,
                "FOR e IN extends_domain "
                "FILTER (e._from == @cls_id OR e._to == @cls_id) "
                "AND e.ontology_id == @oid "
                "LIMIT 1 RETURN true",
                bind_vars={"cls_id": class_id, "oid": ontology_id},
            )))

        provenance_count_result = list(run_aql(db,
            "FOR e IN @@col FILTER e._from == @cls_id "
            "COLLECT WITH COUNT INTO cnt RETURN cnt",
            bind_vars={
                "@col": extracted_col.name,
                "cls_id": class_id,
            },
        ))
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
            cls_col.update({"_key": key, "confidence": new_confidence})
        except Exception as exc:
            log.warning("confidence update failed for %s: %s", key, exc)


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
        col.insert({
            "_from": f"ontology_registry/{ontology_id}",
            "_to": f"extraction_runs/{run_id}",
            "created": time.time(),
            "expired": NEVER_EXPIRES,
        }, overwrite=True)
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
        new_prop_count = sum(
            len(c.properties if hasattr(c, "properties") else c.get("properties", []))
            for c in classes
        )

        registry_repo.update_registry_entry(ontology_id, {
            "class_count": entry.get("class_count", 0) + new_class_count,
            "property_count": entry.get("property_count", 0) + new_prop_count,
            "extraction_run_id": run_id,
        })
        log.info(
            "updated existing ontology for incremental extraction",
            extra={"ontology_id": ontology_id, "run_id": run_id, "new_classes": new_class_count},
        )
        return ontology_id
    except Exception:
        log.warning("failed to update existing ontology %s", ontology_id, exc_info=True)
        return None


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

        entry = registry_repo.create_registry_entry({
            "name": name,
            "description": f"Ontology extracted from {filename}",
            "tier": "local",
            "source_document_id": document_id,
            "extraction_run_id": run_id,
            "class_count": class_count,
            "property_count": sum(
                len(c.properties if hasattr(c, "properties") else c.get("properties", []))
                for c in classes
            ),
            "namespace": "http://example.org/ontology#",
        })
        ontology_id = entry.get("_key", run_id)
        log.info(
            "auto-registered ontology",
            extra={
                "run_id": run_id,
                "ontology_name": name,
                "classes": class_count,
                "ontology_id": ontology_id,
            },
        )
        return ontology_id
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
        return step_log
    if hasattr(step_log, "model_dump"):
        return step_log.model_dump()
    return dict(step_log)
