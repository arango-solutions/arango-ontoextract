"""Quality metrics service — computes ontology and extraction quality scores.

Provides structural, confidence, and curation-based quality indicators
for individual ontologies and aggregate summaries (PRD §6.13, §3.2).
"""

from __future__ import annotations

import logging
import sys
from typing import Any, cast

from arango.database import StandardDatabase

from app.db.utils import run_aql

log = logging.getLogger(__name__)

NEVER_EXPIRES: int = sys.maxsize


def _has(db: StandardDatabase, name: str) -> bool:
    """Check whether a collection exists, swallowing errors."""
    try:
        return cast(bool, db.has_collection(name))
    except Exception:
        return False


def compute_ontology_quality(
    db: StandardDatabase,
    ontology_id: str,
    *,
    include_estimated_cost: bool = True,
) -> dict[str, Any]:
    """Compute structural and confidence quality metrics for a single ontology.

    Returns
    -------
    dict with keys:
        avg_confidence, class_count, property_count, completeness,
        orphan_count, has_cycles, classes_without_properties
    """
    class_count = 0
    property_count = 0
    avg_confidence: float | None = None

    avg_faithfulness: float | None = None
    avg_semantic_validity: float | None = None

    if _has(db, "ontology_classes"):
        rows = list(run_aql(db,
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id == @oid AND c.expired == @never "
            "COLLECT AGGREGATE cnt = COUNT_UNIQUE(c._key), "
            "  avg_conf = AVG(c.confidence), "
            "  avg_faith = AVG(c.faithfulness_score), "
            "  avg_sem = AVG(c.semantic_validity_score) "
            "RETURN { cnt, avg_conf, avg_faith, avg_sem }",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))
        if rows:
            class_count = rows[0].get("cnt", 0) or 0
            avg_confidence = rows[0].get("avg_conf")
            avg_faithfulness = rows[0].get("avg_faith")
            avg_semantic_validity = rows[0].get("avg_sem")

    if _has(db, "ontology_properties"):
        rows = list(run_aql(db,
            "FOR p IN ontology_properties "
            "FILTER p.ontology_id == @oid AND p.expired == @never "
            "COLLECT WITH COUNT INTO cnt RETURN cnt",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))
        property_count = rows[0] if rows else 0

    classes_with_props = 0
    if class_count > 0 and _has(db, "has_property"):
        rows = list(run_aql(db,
            "FOR e IN has_property "
            "FILTER e.ontology_id == @oid AND e.expired == @never "
            "COLLECT from_id = e._from "
            "COLLECT WITH COUNT INTO cnt "
            "RETURN cnt",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))
        classes_with_props = rows[0] if rows else 0

    completeness = (
        (classes_with_props / class_count * 100) if class_count > 0 else 0.0
    )
    classes_without_properties = max(0, class_count - classes_with_props)

    orphan_count = _count_orphans(db, ontology_id)
    has_cycles = _detect_cycles(db, ontology_id)

    relationship_count = 0
    classes_with_relationships = 0
    if class_count > 0 and _has(db, "related_to"):
        rows = list(run_aql(db,
            "FOR e IN related_to "
            "FILTER e.ontology_id == @oid AND e.expired == @never "
            "COLLECT WITH COUNT INTO cnt RETURN cnt",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))
        relationship_count = rows[0] if rows else 0
        if relationship_count > 0:
            rows2 = list(run_aql(db,
                "FOR e IN related_to "
                "FILTER e.ontology_id == @oid AND e.expired == @never "
                "COLLECT from_id = e._from "
                "COLLECT WITH COUNT INTO cnt RETURN cnt",
                bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
            ))
            classes_with_relationships = rows2[0] if rows2 else 0

    connectivity = (
        (classes_with_relationships / class_count * 100) if class_count > 0 else 0.0
    )

    chunk_count = 0
    if _has(db, "has_chunk"):
        rows = list(run_aql(db,
            "FOR e IN has_chunk "
            "FILTER e.ontology_id == @oid "
            "COLLECT WITH COUNT INTO cnt RETURN cnt",
            bind_vars={"oid": ontology_id},
        ))
        chunk_count = rows[0] if rows else 0

    schema_metrics = _compute_schema_metrics(
        db, ontology_id, class_count, property_count,
        relationship_count, subclass_edge_count=_count_edges(db, "subclass_of", ontology_id),
    )

    health_score: int | None = None
    if class_count > 0:
        health_score = compute_health_score(
            completeness=completeness / 100.0,
            has_cycles=has_cycles,
            orphan_count=orphan_count,
            total_classes=class_count,
            avg_confidence=avg_confidence if avg_confidence is not None else 0.5,
            total_properties=property_count,
            chunk_count=chunk_count,
            connectivity=connectivity / 100.0,
        )

    # Estimated cost: trace ontology_registry → extraction_run → cost
    estimated_cost: float | None = None
    ontology_name: str = ontology_id
    ontology_tier: str = "unknown"
    if _has(db, "ontology_registry"):
        try:
            reg_rows = list(run_aql(db,
                "FOR o IN ontology_registry FILTER o._key == @oid "
                "RETURN { run_id: o.extraction_run_id, name: o.name, tier: o.tier }",
                bind_vars={"oid": ontology_id},
            ))
            if reg_rows and reg_rows[0]:
                ontology_name = reg_rows[0].get("name") or ontology_id
                ontology_tier = reg_rows[0].get("tier") or "unknown"
                ext_run_id = reg_rows[0].get("run_id")
                if include_estimated_cost and ext_run_id and _has(db, "extraction_runs"):
                    from app.services.extraction import get_run_cost
                    cost_data = get_run_cost(
                        db,
                        run_id=ext_run_id,
                        include_quality_metrics=False,
                    )
                    estimated_cost = cost_data.get("estimated_cost")
        except Exception:
            log.debug("could not fetch cost for ontology %s", ontology_id, exc_info=True)

    return {
        "ontology_id": ontology_id,
        "name": ontology_name,
        "tier": ontology_tier,
        "avg_confidence": round(avg_confidence, 4) if avg_confidence is not None else None,
        "avg_faithfulness": round(avg_faithfulness, 4) if avg_faithfulness is not None else None,
        "avg_semantic_validity": round(avg_semantic_validity, 4) if avg_semantic_validity is not None else None,
        "class_count": class_count,
        "property_count": property_count,
        "completeness": round(completeness, 2),
        "connectivity": round(connectivity, 2),
        "relationship_count": relationship_count,
        "orphan_count": orphan_count,
        "has_cycles": has_cycles,
        "classes_without_properties": classes_without_properties,
        "health_score": health_score,
        "estimated_cost": round(estimated_cost, 6) if estimated_cost is not None else None,
        "schema_metrics": schema_metrics,
    }


def _count_edges(db: StandardDatabase, collection: str, ontology_id: str) -> int:
    """Count active edges in a collection for an ontology."""
    if not _has(db, collection):
        return 0
    rows = list(run_aql(db,
        f"FOR e IN {collection} "
        "FILTER e.ontology_id == @oid AND e.expired == @never "
        "COLLECT WITH COUNT INTO cnt RETURN cnt",
        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
    ))
    return rows[0] if rows else 0


def _compute_schema_metrics(
    db: StandardDatabase,
    ontology_id: str,
    class_count: int,
    property_count: int,
    relationship_count: int,
    subclass_edge_count: int,
) -> dict[str, Any]:
    """Compute OntoQA/OQuaRE-aligned schema metrics."""
    total_edges = subclass_edge_count + relationship_count
    relationship_richness = (
        (relationship_count / total_edges) if total_edges > 0 else 0.0
    )

    attribute_richness = (
        (property_count / class_count) if class_count > 0 else 0.0
    )

    classes_with_children = 0
    if subclass_edge_count > 0 and _has(db, "subclass_of"):
        rows = list(run_aql(db,
            "FOR e IN subclass_of "
            "FILTER e.ontology_id == @oid AND e.expired == @never "
            "COLLECT parent = e._to "
            "COLLECT WITH COUNT INTO cnt RETURN cnt",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))
        classes_with_children = rows[0] if rows else 0
    inheritance_richness = (
        (subclass_edge_count / classes_with_children)
        if classes_with_children > 0 else 0.0
    )

    max_depth = 0
    if _has(db, "ontology_classes") and _has(db, "subclass_of") and subclass_edge_count > 0:
        rows = list(run_aql(db,
            "LET roots = ("
            "  FOR c IN ontology_classes "
            "  FILTER c.ontology_id == @oid AND c.expired == @never "
            "  LET is_child = LENGTH("
            "    FOR e IN subclass_of "
            "    FILTER e._from == c._id AND e.expired == @never "
            "    LIMIT 1 RETURN 1"
            "  ) "
            "  FILTER is_child == 0 "
            "  RETURN c "
            ") "
            "FOR root IN roots "
            "  FOR v, e, p IN 0..20 INBOUND root subclass_of "
            "    OPTIONS {uniqueVertices: 'path'} "
            "    FILTER e == null OR e.expired == @never "
            "    COLLECT AGGREGATE md = MAX(LENGTH(p.edges)) "
            "RETURN md",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))
        max_depth = rows[0] if rows and rows[0] else 0

    annotation_completeness = 0.0
    if class_count > 0 and _has(db, "ontology_classes"):
        rows = list(run_aql(db,
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id == @oid AND c.expired == @never "
            "  AND c.description != null AND LENGTH(c.description) > 20 "
            "COLLECT WITH COUNT INTO cnt RETURN cnt",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))
        described = rows[0] if rows else 0
        annotation_completeness = described / class_count

    relationship_diversity = 0
    if relationship_count > 0 and _has(db, "related_to"):
        rows = list(run_aql(db,
            "FOR e IN related_to "
            "FILTER e.ontology_id == @oid AND e.expired == @never "
            "COLLECT label = e.label "
            "COLLECT WITH COUNT INTO cnt RETURN cnt",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))
        relationship_diversity = rows[0] if rows else 0

    avg_connectivity_degree = (
        (total_edges / class_count) if class_count > 0 else 0.0
    )

    uri_consistency = 1.0
    if class_count > 1 and _has(db, "ontology_classes"):
        rows = list(run_aql(db,
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id == @oid AND c.expired == @never AND c.uri != null "
            "LET ns = REGEX_REPLACE(c.uri, '#[^#]*$', '#') "
            "COLLECT namespace = ns WITH COUNT INTO cnt "
            "SORT cnt DESC "
            "LIMIT 1 "
            "RETURN {namespace, cnt}",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))
        if rows and rows[0]:
            primary_ns_count = rows[0].get("cnt", 0)
            uri_consistency = primary_ns_count / class_count if class_count > 0 else 1.0

    return {
        "relationship_richness": round(relationship_richness, 4),
        "attribute_richness": round(attribute_richness, 2),
        "inheritance_richness": round(inheritance_richness, 2),
        "max_depth": max_depth,
        "annotation_completeness": round(annotation_completeness, 4),
        "relationship_diversity": relationship_diversity,
        "avg_connectivity_degree": round(avg_connectivity_degree, 2),
        "uri_consistency": round(uri_consistency, 4),
    }


def _count_orphans(db: StandardDatabase, ontology_id: str) -> int:
    """Count classes with no subclass_of parent that are not root classes.

    A root class is one where at least one other class is a subclass of it.
    An orphan is a class with no parent AND no children — truly disconnected.
    """
    if not _has(db, "ontology_classes"):
        return 0
    if not _has(db, "subclass_of"):
        rows = list(run_aql(db,
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id == @oid AND c.expired == @never "
            "COLLECT WITH COUNT INTO cnt RETURN cnt",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        ))
        count = rows[0] if rows else 0
        return count if count > 1 else 0

    rows = list(run_aql(db,
        "LET all_classes = ("
        "  FOR c IN ontology_classes "
        "  FILTER c.ontology_id == @oid AND c.expired == @never "
        "  RETURN c._id "
        ") "
        "LET children = ("
        "  FOR e IN subclass_of "
        "  FILTER e.ontology_id == @oid AND e.expired == @never "
        "  RETURN DISTINCT e._from "
        ") "
        "LET parents = ("
        "  FOR e IN subclass_of "
        "  FILTER e.ontology_id == @oid AND e.expired == @never "
        "  RETURN DISTINCT e._to "
        ") "
        "LET connected = UNION_DISTINCT(children, parents) "
        "FOR cls_id IN all_classes "
        "  FILTER cls_id NOT IN connected "
        "  COLLECT WITH COUNT INTO cnt "
        "RETURN cnt",
        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
    ))
    return rows[0] if rows else 0


def _detect_cycles(db: StandardDatabase, ontology_id: str) -> bool:
    """Detect cycles in the subclass_of hierarchy via AQL traversal."""
    if not _has(db, "subclass_of") or not _has(db, "ontology_classes"):
        return False

    rows = list(run_aql(db,
        "FOR c IN ontology_classes "
        "FILTER c.ontology_id == @oid AND c.expired == @never "
        "LET cycle_check = ("
        "  FOR v, e, p IN 1..100 OUTBOUND c subclass_of "
        "    OPTIONS {uniqueEdges: 'path'} "
        "    FILTER e.expired == @never "
        "    FILTER v._id == c._id "
        "    LIMIT 1 "
        "    RETURN true "
        ") "
        "FILTER LENGTH(cycle_check) > 0 "
        "LIMIT 1 "
        "RETURN true",
        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
    ))
    return len(rows) > 0


def compute_health_score(
    completeness: float,
    has_cycles: bool,
    orphan_count: int,
    total_classes: int,
    avg_confidence: float,
    total_properties: int,
    chunk_count: int,
    connectivity: float = 0.0,
) -> int:
    """Compute a 0-100 composite ontology health score.

    Both ``completeness`` and ``connectivity`` must be 0-1 decimals
    (i.e. pre-divided by 100 at the call site).

    Dimensions (weights):
      - Completeness (20%): ratio of classes with properties
      - Connectivity (20%): ratio of classes with inter-class relationships
      - Structural integrity (15%): penalizes cycles and orphans
      - Average confidence (20%): mean multi-signal confidence
      - Property richness (15%): properties-per-class ratio
      - Source coverage (10%): chunks-per-class ratio (capped at 1.0)

    An ontology with only datatype properties but no inter-class
    relationships will score low on connectivity, preventing a
    flat taxonomy from getting a high health score.

    Returns an integer 0-100.
    """
    cycle_penalty = 0.3 if has_cycles else 0.0
    orphan_ratio = (orphan_count / total_classes) if total_classes > 0 else 0.0
    structural = max(0.0, 1.0 - cycle_penalty - orphan_ratio)

    prop_per_class = (total_properties / total_classes) if total_classes > 0 else 0.0
    property_richness = min(prop_per_class / 3.0, 1.0)

    chunks_per_class = (chunk_count / total_classes) if total_classes > 0 else 0.0
    source_coverage = min(chunks_per_class, 1.0)

    raw = (
        0.20 * min(completeness, 1.0)
        + 0.20 * min(connectivity, 1.0)
        + 0.15 * structural
        + 0.20 * avg_confidence
        + 0.15 * property_richness
        + 0.10 * source_coverage
    )
    return max(0, min(100, round(raw * 100)))


def compute_extraction_quality(
    db: StandardDatabase,
    ontology_id: str,
) -> dict[str, Any]:
    """Compute extraction-process quality metrics (curation acceptance, time-to-ontology).

    Returns
    -------
    dict with keys: acceptance_rate, time_to_ontology_ms
    """
    acceptance_rate: float | None = None
    if _has(db, "curation_decisions"):
        rows = list(run_aql(db,
            "FOR d IN curation_decisions "
            "FILTER d.ontology_id == @oid "
            "  OR (HAS(d, 'run_id') AND d.run_id IN ("
            "    FOR r IN extraction_runs "
            "    FILTER HAS(r, 'ontology_id') AND r.ontology_id == @oid "
            "    RETURN r._key"
            "  )) "
            "COLLECT AGGREGATE "
            "  accepted = SUM(d.action == 'approve' ? 1 : 0), "
            "  rejected = SUM(d.action == 'reject' ? 1 : 0), "
            "  edited   = SUM(d.action == 'edit' ? 1 : 0) "
            "RETURN { accepted, rejected, edited }",
            bind_vars={"oid": ontology_id},
        ))
        if rows:
            r = rows[0]
            total = (r.get("accepted") or 0) + (r.get("rejected") or 0) + (r.get("edited") or 0)
            if total > 0:
                acceptance_rate = round((r.get("accepted") or 0) / total, 4)

    time_to_ontology_ms: int | None = None
    if _has(db, "ontology_registry") and _has(db, "extraction_runs"):
        rows = list(run_aql(db,
            "FOR o IN ontology_registry "
            "FILTER o._key == @oid "
            "LIMIT 1 "
            "LET run_id = o.extraction_run_id "
            "LET run = DOCUMENT(CONCAT('extraction_runs/', run_id)) "
            "LET doc_id = o.source_document_id "
            "LET doc = doc_id ? DOCUMENT(CONCAT('documents/', doc_id)) : null "
            "RETURN { "
            "  completed_at: run.completed_at, "
            "  uploaded_at: doc.uploaded_at "
            "}",
            bind_vars={"oid": ontology_id},
        ))
        if rows and rows[0]:
            completed = rows[0].get("completed_at")
            uploaded = rows[0].get("uploaded_at")
            if completed and uploaded:
                time_to_ontology_ms = int((completed - uploaded) * 1000)

    return {
        "ontology_id": ontology_id,
        "acceptance_rate": acceptance_rate,
        "time_to_ontology_ms": time_to_ontology_ms,
    }


def _summarise_ontologies(ontologies: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate quality metrics from pre-computed per-ontology scorecards."""
    if not ontologies:
        return {
            "ontology_count": 0,
            "total_classes": 0,
            "total_properties": 0,
            "avg_confidence": None,
            "avg_faithfulness": None,
            "avg_semantic_validity": None,
            "avg_completeness": 0.0,
            "avg_health_score": None,
            "ontologies_with_cycles": 0,
            "total_orphans": 0,
        }

    total_classes = 0
    total_properties = 0
    all_confidences: list[float] = []
    all_faithfulness: list[float] = []
    all_semantic_validity: list[float] = []
    all_completeness: list[float] = []
    all_health_scores: list[int] = []
    ontologies_with_cycles = 0
    total_orphans = 0

    for oq in ontologies:
        total_classes += oq["class_count"]
        total_properties += oq["property_count"]
        if oq["avg_confidence"] is not None:
            all_confidences.append(oq["avg_confidence"])
        if oq.get("avg_faithfulness") is not None:
            all_faithfulness.append(oq["avg_faithfulness"])
        if oq.get("avg_semantic_validity") is not None:
            all_semantic_validity.append(oq["avg_semantic_validity"])
        all_completeness.append(oq["completeness"])
        if oq["health_score"] is not None:
            all_health_scores.append(oq["health_score"])
        if oq["has_cycles"]:
            ontologies_with_cycles += 1
        total_orphans += oq["orphan_count"]

    avg_confidence = (
        round(sum(all_confidences) / len(all_confidences), 4)
        if all_confidences
        else None
    )
    avg_faithfulness = (
        round(sum(all_faithfulness) / len(all_faithfulness), 4)
        if all_faithfulness
        else None
    )
    avg_semantic_validity = (
        round(sum(all_semantic_validity) / len(all_semantic_validity), 4)
        if all_semantic_validity
        else None
    )
    avg_completeness = (
        round(sum(all_completeness) / len(all_completeness), 2)
        if all_completeness
        else 0.0
    )
    avg_health_score = (
        round(sum(all_health_scores) / len(all_health_scores))
        if all_health_scores
        else None
    )

    return {
        "ontology_count": len(ontologies),
        "total_classes": total_classes,
        "total_properties": total_properties,
        "avg_confidence": avg_confidence,
        "avg_faithfulness": avg_faithfulness,
        "avg_semantic_validity": avg_semantic_validity,
        "avg_completeness": avg_completeness,
        "avg_health_score": avg_health_score,
        "ontologies_with_cycles": ontologies_with_cycles,
        "total_orphans": total_orphans,
    }


def get_class_scores(
    db: StandardDatabase,
    ontology_id: str,
) -> list[dict[str, Any]]:
    """Return per-class faithfulness + semantic validity for distribution charts."""
    if not _has(db, "ontology_classes"):
        return []

    return list(run_aql(db,
        "FOR c IN ontology_classes "
        "FILTER c.ontology_id == @oid AND c.expired == @never "
        "RETURN { "
        "  _key: c._key, "
        "  uri: c.uri, "
        "  label: c.label, "
        "  confidence: c.confidence, "
        "  faithfulness_score: c.faithfulness_score, "
        "  semantic_validity_score: c.semantic_validity_score "
        "}",
        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
    ))


def get_qualitative_evaluation(
    db: StandardDatabase,
    ontology_id: str,
) -> dict[str, Any] | None:
    """Retrieve the qualitative evaluation from the extraction run linked to this ontology."""
    if not _has(db, "ontology_registry") or not _has(db, "extraction_runs"):
        return None

    rows = list(run_aql(db,
        "FOR o IN ontology_registry FILTER o._key == @oid LIMIT 1 "
        "LET run = DOCUMENT(CONCAT('extraction_runs/', o.extraction_run_id)) "
        "RETURN run.stats.qualitative_evaluation",
        bind_vars={"oid": ontology_id},
    ))
    if rows and rows[0]:
        return cast(dict[str, Any], rows[0])
    return None


def compute_dashboard_payload(db: StandardDatabase) -> dict[str, Any]:
    """Assemble the full dashboard payload: summary + per-ontology scorecards."""
    ontology_ids: list[str] = []
    if _has(db, "ontology_registry"):
        ontology_ids = list(run_aql(db,
            "FOR o IN ontology_registry RETURN o._key"
        ))

    ontologies: list[dict[str, Any]] = []
    for oid in ontology_ids:
        try:
            ontologies.append(compute_ontology_quality(db, oid))
        except Exception:
            log.warning("dashboard: quality failed for %s", oid, exc_info=True)

    summary = _summarise_ontologies(ontologies)

    # Compute flags/alerts
    alerts: list[dict[str, str]] = []
    for oq in ontologies:
        oid = oq["ontology_id"]
        name = oq.get("name", oid)
        if oq.get("has_cycles"):
            alerts.append({"ontology_id": oid, "name": name, "flag": "has_cycles", "severity": "red"})
        if oq.get("class_count", 0) > 0:
            orphan_ratio = oq.get("orphan_count", 0) / oq["class_count"]
            if orphan_ratio > 0.3:
                alerts.append({"ontology_id": oid, "name": name, "flag": "high_orphan_ratio", "severity": "yellow"})
        if oq.get("avg_confidence") is not None and oq["avg_confidence"] < 0.5:
            alerts.append({"ontology_id": oid, "name": name, "flag": "low_confidence", "severity": "yellow"})
        if oq.get("avg_faithfulness") is not None and oq["avg_faithfulness"] < 0.4:
            alerts.append({"ontology_id": oid, "name": name, "flag": "low_faithfulness", "severity": "red"})
        if oq.get("completeness", 0) == 0 and oq.get("class_count", 0) > 0:
            alerts.append({"ontology_id": oid, "name": name, "flag": "zero_completeness", "severity": "red"})
        if oq.get("avg_semantic_validity") is not None and oq["avg_semantic_validity"] < 0.5:
            alerts.append({"ontology_id": oid, "name": name, "flag": "low_semantic_validity", "severity": "yellow"})

    return {
        "summary": summary,
        "ontologies": ontologies,
        "alerts": alerts,
    }
