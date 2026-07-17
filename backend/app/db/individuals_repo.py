"""Persistence for the assertion graph (A-box) — Stream 21 / AB-PR1.

Named individuals (instances) + their type (``rdf_type``) and relationship
assertions (``individual_assertion``), grounded in the extracted/merged T-box.
Individuals are temporal (versioned) like T-box classes; edges use the temporal
edge helper. Span-level ``provenance`` (doc/chunk/char-span) is carried on every
individual and assertion so each fact is traceable (FR-18.5).
"""

from __future__ import annotations

from typing import Any

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.ontology_repo import create_edge
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.services.temporal import create_version

INDIVIDUALS = "ontology_individuals"
RDF_TYPE = "rdf_type"
ASSERTION = "individual_assertion"


def create_individual(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    class_key: str,
    label: str,
    uri: str | None = None,
    provenance: list[dict[str, Any]] | None = None,
    data: dict[str, Any] | None = None,
    created_by: str = "abox",
) -> dict[str, Any]:
    """Create a named individual and its ``rdf_type`` edge to a T-box class.

    Returns the individual document. The individual is a temporal version; the
    type link is a temporal edge to ``ontology_classes/<class_key>``.
    """
    if db is None:
        db = get_db()
    doc = {
        **(data or {}),
        "ontology_id": ontology_id,
        "label": label,
        "uri": uri,
        "provenance": provenance or [],
        "version": 1,
    }
    individual = create_version(
        db,
        collection=INDIVIDUALS,
        data=doc,
        created_by=created_by,
        change_type="initial",
        change_summary=f"Created individual {label}",
    )
    create_edge(
        db,
        edge_collection=RDF_TYPE,
        from_id=str(individual["_id"]),
        to_id=f"ontology_classes/{class_key}",
        data={"ontology_id": ontology_id},
    )
    return individual


def add_assertion(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    from_individual_id: str,
    to_id: str,
    predicate: str,
    provenance: list[dict[str, Any]] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Add a relationship assertion edge between individuals (or to a value)."""
    if db is None:
        db = get_db()
    return create_edge(
        db,
        edge_collection=ASSERTION,
        from_id=from_individual_id,
        to_id=to_id,
        data={
            **(data or {}),
            "ontology_id": ontology_id,
            "predicate": predicate,
            "provenance": provenance or [],
        },
    )


def list_individuals_with_types(
    db: StandardDatabase | None,
    ontology_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List live individuals for an ontology, each with its rdf:type class.

    Resolves the ``rdf_type`` edge to the T-box class in one AQL pass so the
    instance-lens UI (AB-PR6) can show ``label`` + type + provenance without a
    per-row follow-up. Returns ``[]`` if the A-box collection is absent.
    """
    if db is None:
        db = get_db()
    if not db.has_collection(INDIVIDUALS):
        return []
    return list(
        run_aql(
            db,
            f"""
            FOR i IN {INDIVIDUALS}
              FILTER i.ontology_id == @oid AND i.expired == @never
              LET t = FIRST(
                FOR e IN {RDF_TYPE}
                  FILTER e._from == i._id AND e.expired == @never
                  FOR c IN ontology_classes FILTER c._id == e._to
                    LIMIT 1 RETURN {{key: c._key, label: c.label}}
              )
              SORT i.label ASC
              LIMIT @offset, @count
              RETURN {{
                _key: i._key,
                label: i.label,
                provenance: i.provenance,
                type_key: t.key,
                type_label: t.label
              }}
            """,
            bind_vars={
                "oid": ontology_id,
                "never": NEVER_EXPIRES,
                "offset": offset,
                "count": limit,
            },
        )
    )


def get_individual(db: StandardDatabase | None, key: str) -> dict[str, Any] | None:
    if db is None:
        db = get_db()
    rows = list(
        run_aql(
            db,
            f"FOR i IN {INDIVIDUALS} FILTER i._key == @key AND i.expired == @never "
            f"LIMIT 1 RETURN i",
            bind_vars={"key": key, "never": NEVER_EXPIRES},
        )
    )
    return rows[0] if rows else None


def list_individuals(
    db: StandardDatabase | None,
    ontology_id: str,
    *,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    if db is None:
        db = get_db()
    if not db.has_collection(INDIVIDUALS):
        return []
    return list(
        run_aql(
            db,
            f"""
            FOR i IN {INDIVIDUALS}
              FILTER i.ontology_id == @oid AND i.expired == @never
              SORT i.label ASC
              LIMIT @offset, @count
              RETURN i
            """,
            bind_vars={
                "oid": ontology_id,
                "never": NEVER_EXPIRES,
                "offset": offset,
                "count": limit,
            },
        )
    )
