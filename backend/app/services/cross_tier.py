"""Cross-tier edge creation and conflict detection for Tier 2 ontologies.

Creates ``extends_domain`` edges linking local EXTENSION classes to their
domain parents, and detects conflicts where local extractions contradict
domain ontology definitions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.ontology_repo import create_edge
from app.db.utils import run_aql
from app.services.temporal import NEVER_EXPIRES

log = logging.getLogger(__name__)


class ConflictType(StrEnum):
    SAME_URI = "same_uri"
    CONTRADICTING_RANGE = "contradicting_range"
    HIERARCHY_REDEFINITION = "hierarchy_redefinition"


@dataclass
class ConflictReport:
    """A single conflict between a local extraction and the domain ontology."""

    entity_key: str
    conflict_type: ConflictType
    description: str
    domain_entity_key: str


@dataclass
class CrossTierResult:
    """Result of cross-tier edge creation and conflict detection."""

    edges_created: int = 0
    conflicts: list[ConflictReport] = field(default_factory=list)


def create_cross_tier_edges(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
    ontology_id: str,
) -> CrossTierResult:
    """Create ``extends_domain`` edges for EXTENSION entities in a run.

    For each entity in the staging ontology classified as EXTENSION,
    creates an edge from the local class to its domain parent class.
    """
    if db is None:
        db = get_db()

    result = CrossTierResult()
    staging_ontology_id = f"extraction_{run_id}"

    staging_classes = _get_classes_by_classification(db, staging_ontology_id, "extension")

    for cls in staging_classes:
        parent_domain_uri = cls.get("parent_domain_uri") or cls.get("parent_uri")
        if not parent_domain_uri:
            continue

        domain_class = _find_domain_class_by_uri(db, ontology_id, parent_domain_uri)
        if domain_class is None:
            log.warning(
                "domain parent not found for extension",
                extra={
                    "local_uri": cls.get("uri"),
                    "parent_domain_uri": parent_domain_uri,
                },
            )
            continue

        create_edge(
            db,
            edge_collection="extends_domain",
            from_id=cls["_id"],
            to_id=domain_class["_id"],
            data={
                "run_id": run_id,
                "relationship_type": "rdfs:subClassOf",
                "source_ontology_id": staging_ontology_id,
                "target_ontology_id": ontology_id,
            },
        )
        result.edges_created += 1

    log.info(
        "cross-tier edges created",
        extra={"run_id": run_id, "edges": result.edges_created},
    )
    return result


def detect_conflicts(
    db: StandardDatabase | None = None,
    *,
    run_id: str,
    ontology_id: str,
) -> list[ConflictReport]:
    """Detect conflicts between a staging extraction and the domain ontology.

    Conflict types per PRD Section 6.3:
    - same_uri: Local class has same URI as a domain class
    - contradicting_range: Local property contradicts domain property range
    - hierarchy_redefinition: Local class redefines domain class hierarchy
    """
    if db is None:
        db = get_db()

    conflicts: list[ConflictReport] = []
    staging_ontology_id = f"extraction_{run_id}"

    _detect_same_uri_conflicts(db, staging_ontology_id, ontology_id, conflicts)
    _detect_range_conflicts(db, staging_ontology_id, ontology_id, conflicts)
    _detect_hierarchy_conflicts(db, staging_ontology_id, ontology_id, conflicts)

    log.info(
        "conflict detection complete",
        extra={"run_id": run_id, "conflict_count": len(conflicts)},
    )
    return conflicts


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_classes_by_classification(
    db: StandardDatabase,
    ontology_id: str,
    classification: str,
) -> list[dict[str, Any]]:
    if not db.has_collection("ontology_classes"):
        return []

    return list(
        run_aql(
            db,
            """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  FILTER cls.classification == @cls
  FILTER cls.expired == @never
  RETURN cls""",
            bind_vars={
                "oid": ontology_id,
                "cls": classification,
                "never": NEVER_EXPIRES,
            },
        )
    )


def _find_domain_class_by_uri(
    db: StandardDatabase,
    ontology_id: str,
    uri: str,
) -> dict[str, Any] | None:
    if not db.has_collection("ontology_classes"):
        return None

    results = list(
        run_aql(
            db,
            """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  FILTER cls.uri == @uri
  FILTER cls.expired == @never
  LIMIT 1
  RETURN cls""",
            bind_vars={"oid": ontology_id, "uri": uri, "never": NEVER_EXPIRES},
        )
    )
    return results[0] if results else None


def _detect_same_uri_conflicts(
    db: StandardDatabase,
    staging_ontology_id: str,
    domain_ontology_id: str,
    conflicts: list[ConflictReport],
) -> None:
    """Flag when a local class has the same URI as a domain class."""
    if not db.has_collection("ontology_classes"):
        return

    results = list(
        run_aql(
            db,
            """\
FOR local IN ontology_classes
  FILTER local.ontology_id == @staging_oid
  FILTER local.expired == @never
  FOR domain IN ontology_classes
    FILTER domain.ontology_id == @domain_oid
    FILTER domain.expired == @never
    FILTER local.uri == domain.uri
    FILTER local.classification != "existing"
    RETURN {
      local_key: local._key,
      domain_key: domain._key,
      uri: local.uri
    }""",
            bind_vars={
                "staging_oid": staging_ontology_id,
                "domain_oid": domain_ontology_id,
                "never": NEVER_EXPIRES,
            },
        )
    )

    for row in results:
        conflicts.append(
            ConflictReport(
                entity_key=row["local_key"],
                conflict_type=ConflictType.SAME_URI,
                description=(
                    f"Local class has same URI '{row['uri']}' as domain class. "
                    "Consider owl:equivalentClass or rename."
                ),
                domain_entity_key=row["domain_key"],
            )
        )


def _detect_range_conflicts(
    db: StandardDatabase,
    staging_ontology_id: str,
    domain_ontology_id: str,
    conflicts: list[ConflictReport],
) -> None:
    """Flag when a local property contradicts a domain property's range."""
    _detect_range_conflicts_legacy_properties(
        db, staging_ontology_id, domain_ontology_id, conflicts
    )
    _detect_range_conflicts_pgt_datatype(db, staging_ontology_id, domain_ontology_id, conflicts)
    _detect_range_conflicts_pgt_object(db, staging_ontology_id, domain_ontology_id, conflicts)


def _append_range_conflicts(
    results: list[dict[str, Any]],
    conflicts: list[ConflictReport],
) -> None:
    for row in results:
        conflicts.append(
            ConflictReport(
                entity_key=row["local_key"],
                conflict_type=ConflictType.CONTRADICTING_RANGE,
                description=(
                    f"Property '{row['uri']}' has range '{row['local_range']}' "
                    f"but domain defines range '{row['domain_range']}'. "
                    "Domain property takes precedence unless overridden."
                ),
                domain_entity_key=row["domain_key"],
            )
        )


def _detect_range_conflicts_legacy_properties(
    db: StandardDatabase,
    staging_ontology_id: str,
    domain_ontology_id: str,
    conflicts: list[ConflictReport],
) -> None:
    if not db.has_collection("ontology_properties"):
        return

    results = list(
        run_aql(
            db,
            """\
FOR local_prop IN ontology_properties
  FILTER local_prop.ontology_id == @staging_oid
  FILTER local_prop.expired == @never
  FOR domain_prop IN ontology_properties
    FILTER domain_prop.ontology_id == @domain_oid
    FILTER domain_prop.expired == @never
    FILTER local_prop.uri == domain_prop.uri
    FILTER local_prop.range != domain_prop.range
    RETURN {
      local_key: local_prop._key,
      domain_key: domain_prop._key,
      uri: local_prop.uri,
      local_range: local_prop.range,
      domain_range: domain_prop.range
    }""",
            bind_vars={
                "staging_oid": staging_ontology_id,
                "domain_oid": domain_ontology_id,
                "never": NEVER_EXPIRES,
            },
        )
    )
    _append_range_conflicts(results, conflicts)


def _detect_range_conflicts_pgt_datatype(
    db: StandardDatabase,
    staging_ontology_id: str,
    domain_ontology_id: str,
    conflicts: list[ConflictReport],
) -> None:
    if not db.has_collection("ontology_datatype_properties"):
        return

    results = list(
        run_aql(
            db,
            """\
FOR local IN ontology_datatype_properties
  FILTER local.ontology_id == @staging_oid
  FILTER local.expired == @never
  FOR domain IN ontology_datatype_properties
    FILTER domain.ontology_id == @domain_oid
    FILTER domain.expired == @never
    FILTER local.uri == domain.uri
    FILTER local.range_datatype != domain.range_datatype
    RETURN {
      local_key: local._key,
      domain_key: domain._key,
      uri: local.uri,
      local_range: local.range_datatype,
      domain_range: domain.range_datatype
    }""",
            bind_vars={
                "staging_oid": staging_ontology_id,
                "domain_oid": domain_ontology_id,
                "never": NEVER_EXPIRES,
            },
        )
    )
    _append_range_conflicts(results, conflicts)


def _detect_range_conflicts_pgt_object(
    db: StandardDatabase,
    staging_ontology_id: str,
    domain_ontology_id: str,
    conflicts: list[ConflictReport],
) -> None:
    if not db.has_collection("ontology_object_properties"):
        return
    if not db.has_collection("rdfs_range_class"):
        return

    results = list(
        run_aql(
            db,
            """\
FOR local IN ontology_object_properties
  FILTER local.ontology_id == @staging_oid
  FILTER local.expired == @never
  LET local_range = FIRST(
    FOR e IN rdfs_range_class
      FILTER e._from == local._id AND e.expired == @never
      LET target = DOCUMENT(e._to)
      RETURN target.uri
  )
  FOR domain IN ontology_object_properties
    FILTER domain.ontology_id == @domain_oid
    FILTER domain.expired == @never
    FILTER domain.uri == local.uri
    LET domain_range = FIRST(
      FOR e IN rdfs_range_class
        FILTER e._from == domain._id AND e.expired == @never
        LET target = DOCUMENT(e._to)
        RETURN target.uri
    )
    FILTER local_range != null AND domain_range != null
    FILTER local_range != domain_range
    RETURN {
      local_key: local._key,
      domain_key: domain._key,
      uri: local.uri,
      local_range: local_range,
      domain_range: domain_range
    }""",
            bind_vars={
                "staging_oid": staging_ontology_id,
                "domain_oid": domain_ontology_id,
                "never": NEVER_EXPIRES,
            },
        )
    )
    _append_range_conflicts(results, conflicts)


def _detect_hierarchy_conflicts(
    db: StandardDatabase,
    staging_ontology_id: str,
    domain_ontology_id: str,
    conflicts: list[ConflictReport],
) -> None:
    """Flag when a local class redefines a domain class hierarchy."""
    if not db.has_collection("ontology_classes") or not db.has_collection("subclass_of"):
        return

    domain_edges = list(
        run_aql(
            db,
            """\
FOR e IN subclass_of
  FILTER e.expired == @never
  LET child = DOCUMENT(e._from)
  LET parent = DOCUMENT(e._to)
  FILTER child.ontology_id == @domain_oid
  FILTER parent.ontology_id == @domain_oid
  RETURN {child_uri: child.uri, parent_uri: parent.uri}""",
            bind_vars={
                "domain_oid": domain_ontology_id,
                "never": NEVER_EXPIRES,
            },
        )
    )
    domain_parent_map = {
        e["child_uri"]: e["parent_uri"] for e in domain_edges if e.get("child_uri")
    }

    staging_classes = list(
        run_aql(
            db,
            """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @staging_oid
  FILTER cls.expired == @never
  FILTER cls.parent_uri != null
  RETURN {key: cls._key, uri: cls.uri, parent_uri: cls.parent_uri}""",
            bind_vars={
                "staging_oid": staging_ontology_id,
                "never": NEVER_EXPIRES,
            },
        )
    )

    for cls in staging_classes:
        uri = cls.get("uri", "")
        if uri in domain_parent_map:
            domain_parent = domain_parent_map[uri]
            local_parent = cls.get("parent_uri", "")
            if local_parent and local_parent != domain_parent:
                domain_class = _find_domain_class_by_uri(db, domain_ontology_id, uri)
                domain_key = domain_class["_key"] if domain_class else "unknown"
                conflicts.append(
                    ConflictReport(
                        entity_key=cls["key"],
                        conflict_type=ConflictType.HIERARCHY_REDEFINITION,
                        description=(
                            f"Local class '{uri}' redefines parent from "
                            f"'{domain_parent}' to '{local_parent}'. "
                            "Requires expert approval."
                        ),
                        domain_entity_key=domain_key,
                    )
                )
