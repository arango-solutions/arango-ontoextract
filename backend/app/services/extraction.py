"""ExtractionRunService — orchestrates extraction pipeline lifecycle.

Creates extraction_runs records, dispatches LangGraph pipeline, updates status,
and tracks token usage and cost.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from typing import Any

from arango.database import StandardDatabase

from app.api.errors import NotFoundError
from app.config import settings
from app.db.client import get_db
from app.db.pagination import paginate
from app.extraction.pipeline import run_pipeline
from app.models.common import PaginatedResponse

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
    document_id: str,
    config_overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create an extraction run record (synchronous).

    Returns the run record immediately so the HTTP response can be sent
    before the pipeline starts executing.
    """
    if db is None:
        db = get_db()

    run_id = _generate_run_id()
    now = time.time()

    run_record = {
        "_key": run_id,
        "doc_id": document_id,
        "model": settings.llm_extraction_model,
        "prompt_version": "tier1_standard",
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

    if config_overrides:
        run_record["stats"].update(config_overrides)

    col = _get_collection(db, "extraction_runs")
    col.insert(run_record)

    chunks = _load_document_chunks(db, document_id)
    log.info(
        "extraction run created",
        extra={"run_id": run_id, "doc_id": document_id, "chunk_count": len(chunks)},
    )

    return run_record


async def execute_run(
    run_id: str,
    document_id: str,
    config_overrides: dict[str, Any] | None = None,
    event_callback: Any | None = None,
) -> dict[str, Any]:
    """Execute the extraction pipeline for an existing run record.

    Designed to run as a background task after the HTTP response is sent.
    """
    db = get_db()
    col = _get_collection(db, "extraction_runs")
    run_record = col.get(run_id)
    if run_record is None:
        raise NotFoundError(f"Extraction run '{run_id}' not found")

    chunks = _load_document_chunks(db, document_id)

    final_state: dict[str, Any] | None = None
    try:
        final_state = await run_pipeline(
            run_id=run_id,
            document_id=document_id,
            chunks=chunks,
            event_callback=event_callback,
        )

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
                sl_dict = sl if isinstance(sl, dict) else (sl.model_dump() if hasattr(sl, "model_dump") else dict(sl))
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
            ontology_id = _auto_register_ontology(
                db,
                run_id=run_id,
                document_id=document_id,
                result=final_state["consistency_result"],
            )
            if ontology_id:
                _materialize_to_graph(
                    db,
                    run_id=run_id,
                    document_id=document_id,
                    ontology_id=ontology_id,
                    result=final_state["consistency_result"],
                )
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

    updated = col.get(run_id)
    return updated


async def start_run(
    db: StandardDatabase | None = None,
    *,
    document_id: str,
    config_overrides: dict[str, Any] | None = None,
    event_callback: Any | None = None,
) -> dict[str, Any]:
    """Create and execute an extraction run synchronously (legacy helper)."""
    if db is None:
        db = get_db()
    run_record = create_run_record(db, document_id=document_id, config_overrides=config_overrides)
    return await execute_run(
        run_id=run_record["_key"],
        document_id=document_id,
        config_overrides=config_overrides,
        event_callback=event_callback,
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
    run = col.get(run_id)
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
    results_doc = col.get(results_key)

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

    return await start_run(
        db,
        document_id=run["doc_id"],
        event_callback=event_callback,
    )


def get_run_cost(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Get token usage and estimated cost for a run."""
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

    return list(db.aql.execute(query, bind_vars={"doc_id": document_id}))


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
) -> None:
    """Write extracted classes/properties into graph collections with edges."""
    now = time.time()
    classes = result.classes if hasattr(result, "classes") else result.get("classes", [])

    for col_name in ("ontology_classes", "ontology_properties",
                     "has_property", "subclass_of", "related_to", "extracted_from"):
        if not db.has_collection(col_name):
            edge = col_name in ("has_property", "subclass_of", "related_to", "extracted_from")
            db.create_collection(col_name, edge=edge)

    cls_col = db.collection("ontology_classes")
    prop_col = db.collection("ontology_properties")
    has_prop_col = db.collection("has_property")
    extracted_col = db.collection("extracted_from")
    subclass_col = db.collection("subclass_of")
    related_col = db.collection("related_to")

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
                "rdf_type": "owl:ObjectProperty" if prop.get("range", "").startswith("http") else "owl:DatatypeProperty",
                "created": now,
                "expired": NEVER_EXPIRES,
            }
            try:
                prop_col.insert(prop_doc, overwrite=True)
            except Exception as exc:
                log.warning("property insert failed for %s: %s", prop_key, exc)

            try:
                has_prop_col.insert({
                    "_from": f"ontology_classes/{key}",
                    "_to": f"ontology_properties/{prop_key}",
                    "ontology_id": ontology_id,
                    "created": now,
                    "expired": NEVER_EXPIRES,
                })
            except Exception:
                pass

        try:
            extracted_col.insert({
                "_from": f"ontology_classes/{key}",
                "_to": f"documents/{document_id}",
                "run_id": run_id,
                "ontology_id": ontology_id,
                "created": now,
            })
        except Exception:
            pass

    for child_key, parent_uri in class_parent_uris:
        parent_key = uri_to_key.get(parent_uri)
        if not parent_key:
            parent_frag = parent_uri.split("#")[-1].split("/")[-1]
            parent_key = class_keys.get(parent_frag) or class_keys.get(parent_uri)
        if parent_key:
            try:
                subclass_col.insert({
                    "_from": f"ontology_classes/{child_key}",
                    "_to": f"ontology_classes/{parent_key}",
                    "ontology_id": ontology_id,
                    "created": now,
                    "expired": NEVER_EXPIRES,
                })
            except Exception:
                pass

    log.info(
        "materialized extraction to graph",
        extra={"run_id": run_id, "classes": len(class_keys), "ontology_id": ontology_id},
    )


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
        from app.db import registry_repo, documents_repo

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
            extra={"run_id": run_id, "name": name, "classes": class_count, "ontology_id": ontology_id},
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
