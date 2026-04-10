"""Domain ontology context serialization for Tier 2 extraction.

Serializes domain ontology class hierarchy into compact text for LLM prompt
injection, enabling context-aware extraction that classifies entities as
EXISTING, EXTENSION, or NEW relative to the domain.
"""

from __future__ import annotations

import logging
from typing import Any, cast

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.utils import run_aql
from app.services.temporal import NEVER_EXPIRES

log = logging.getLogger(__name__)


def serialize_domain_context(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
) -> str:
    """Query domain ontology classes + hierarchy, serialize as compact text.

    Format::

        Domain: <ontology_name>
        Classes:
        - ParentClass
          - ChildClass (props: p1, p2)
          - ChildClass2
        ...

    Only current (non-expired) classes and edges are included.
    """
    if db is None:
        db = get_db()

    ontology_name = _get_ontology_name(db, ontology_id)
    classes = _get_current_classes(db, ontology_id)
    hierarchy = _get_subclass_edges(db, ontology_id)

    if not classes:
        return f"Domain: {ontology_name}\nClasses: (none)"

    class_by_id: dict[str, dict[str, Any]] = {c["_id"]: c for c in classes}
    class_ids = list(class_by_id.keys())
    children_map: dict[str, list[str]] = {}
    child_ids: set[str] = set()

    for edge in hierarchy:
        parent_id = edge.get("_to", "")
        child_id = edge.get("_from", "")
        if parent_id in class_by_id and child_id in class_by_id:
            children_map.setdefault(parent_id, []).append(child_id)
            child_ids.add(child_id)

    rdfs_labels = (
        _property_labels_from_rdfs_domain(db, ontology_id, class_ids)
        if class_ids and db.has_collection("rdfs_domain")
        else {}
    )
    legacy_labels: dict[str, list[str]] = {}
    if db.has_collection("ontology_properties"):
        legacy_labels = _legacy_property_labels_by_class(
            _get_class_properties(db, ontology_id),
            class_by_id,
        )

    props_map: dict[str, list[str]] = {}
    for cid in class_ids:
        merged: list[str] = []
        merged.extend(rdfs_labels.get(cid, []))
        merged.extend(legacy_labels.get(cid, []))
        seen: set[str] = set()
        uniq: list[str] = []
        for label in merged:
            if label and label not in seen:
                seen.add(label)
                uniq.append(label)
        if uniq:
            props_map[cid] = uniq

    root_ids = [cid for cid in class_by_id if cid not in child_ids]
    root_ids.sort(key=lambda cid: class_by_id[cid].get("label", ""))

    lines = [f"Domain: {ontology_name}", "Classes:"]

    def _render_tree(class_id: str, depth: int) -> None:
        cls = class_by_id[class_id]
        label = cls.get("label", cls.get("uri", "unknown"))
        prop_names = props_map.get(class_id, [])
        suffix = f" (props: {', '.join(prop_names)})" if prop_names else ""
        indent = "  " * depth
        lines.append(f"{indent}- {label}{suffix}")

        for child_id in sorted(
            children_map.get(class_id, []),
            key=lambda cid: class_by_id[cid].get("label", ""),
        ):
            _render_tree(child_id, depth + 1)

    for root_id in root_ids:
        _render_tree(root_id, 0)

    return "\n".join(lines)


def get_domain_ontology_for_org(
    db: StandardDatabase | None = None,
    *,
    org_id: str,
) -> list[str]:
    """Return ontology_ids selected by an organization.

    Reads from the ``organizations`` collection's ``selected_ontologies`` field.
    Falls back to an empty list if the org or field doesn't exist.
    """
    if db is None:
        db = get_db()

    if not db.has_collection("organizations"):
        return []

    query = """\
FOR org IN organizations
  FILTER org._key == @org_id
  LIMIT 1
  RETURN org.selected_ontologies"""

    results = list(run_aql(db,query, bind_vars={"org_id": org_id}))
    if not results or results[0] is None:
        return []
    return list(results[0])


def set_domain_ontology_for_org(
    db: StandardDatabase | None = None,
    *,
    org_id: str,
    ontology_ids: list[str],
) -> dict[str, Any]:
    """Update the selected base ontologies for an organization.

    Validates that all referenced ontology_ids exist in the registry.
    Returns the updated organization document.
    """
    if db is None:
        db = get_db()

    if db.has_collection("ontology_registry"):
        for oid in ontology_ids:
            exists = list(
                run_aql(db,
                    "FOR r IN ontology_registry FILTER r._key == @k LIMIT 1 RETURN 1",
                    bind_vars={"k": oid},
                )
            )
            if not exists:
                raise ValueError(f"Ontology '{oid}' not found in registry")

    if not db.has_collection("organizations"):
        db.create_collection("organizations")

    existing = list(
        run_aql(db,
            "FOR org IN organizations FILTER org._key == @k LIMIT 1 RETURN org",
            bind_vars={"k": org_id},
        )
    )
    if existing:
        result = cast("dict[str, Any]", db.collection("organizations").update(
            {"_key": org_id, "selected_ontologies": ontology_ids},
            return_new=True,
        ))
        return result["new"]

    result = cast("dict[str, Any]", db.collection("organizations").insert(
        {"_key": org_id, "selected_ontologies": ontology_ids},
        return_new=True,
    ))
    return result["new"]


def serialize_multi_domain_context(
    db: StandardDatabase | None = None,
    *,
    ontology_ids: list[str],
) -> str:
    """Serialize context from multiple domain ontologies for Tier 2 prompts."""
    if db is None:
        db = get_db()

    if not ontology_ids:
        return ""

    parts: list[str] = []
    for oid in ontology_ids:
        ctx = serialize_domain_context(db, ontology_id=oid)
        parts.append(ctx)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _get_ontology_name(db: StandardDatabase, ontology_id: str) -> str:
    if not db.has_collection("ontology_registry"):
        return ontology_id

    results = list(
        run_aql(db,
            "FOR r IN ontology_registry FILTER r._key == @k LIMIT 1 RETURN r.name",
            bind_vars={"k": ontology_id},
        )
    )
    return results[0] if results and results[0] else ontology_id


def _get_current_classes(
    db: StandardDatabase, ontology_id: str
) -> list[dict[str, Any]]:
    if not db.has_collection("ontology_classes"):
        return []

    return list(
        run_aql(db,
            """\
FOR cls IN ontology_classes
  FILTER cls.ontology_id == @oid
  FILTER cls.expired == @never
  RETURN cls""",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )


def _get_subclass_edges(
    db: StandardDatabase, ontology_id: str
) -> list[dict[str, Any]]:
    if not db.has_collection("subclass_of"):
        return []

    return list(
        run_aql(db,
            """\
FOR e IN subclass_of
  FILTER e.expired == @never
  RETURN e""",
            bind_vars={"never": NEVER_EXPIRES},
        )
    )


def _get_class_properties(
    db: StandardDatabase, ontology_id: str
) -> list[dict[str, Any]]:
    if not db.has_collection("ontology_properties"):
        return []

    return list(
        run_aql(db,
            """\
FOR prop IN ontology_properties
  FILTER prop.ontology_id == @oid
  FILTER prop.expired == @never
  RETURN prop""",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )


def _property_labels_from_rdfs_domain(
    db: StandardDatabase,
    ontology_id: str,
    class_ids: list[str],
) -> dict[str, list[str]]:
    """Map class document id → property labels via PGT ``rdfs_domain`` edges (ADR-006)."""
    if not class_ids:
        return {}

    rows = list(
        run_aql(
            db,
            """\
FOR e IN rdfs_domain
  FILTER e.ontology_id == @oid AND e.expired == @never
  FILTER e._to IN @cids
  LET prop = DOCUMENT(e._from)
  FILTER prop != null AND prop.expired == @never AND prop.ontology_id == @oid
  RETURN { "class_id": e._to, "label": prop.label }""",
            bind_vars={
                "oid": ontology_id,
                "never": NEVER_EXPIRES,
                "cids": class_ids,
            },
        )
    )
    out: dict[str, list[str]] = {}
    for row in rows:
        cid = row.get("class_id")
        label = row.get("label")
        if cid and label:
            out.setdefault(cid, []).append(label)
    return out


def _legacy_property_labels_by_class(
    properties: list[dict[str, Any]],
    class_by_id: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    """Build class_id → labels from legacy ``ontology_properties`` documents."""
    out: dict[str, list[str]] = {}
    for prop in properties:
        domain_id = prop.get("domain_class_id")
        if not domain_id and prop.get("domain_class"):
            frag = str(prop["domain_class"]).split("#")[-1].split("/")[-1]
            domain_id = f"ontology_classes/{frag}"
        if not domain_id or domain_id not in class_by_id:
            continue
        label = prop.get("label") or prop.get("uri") or ""
        if label:
            out.setdefault(domain_id, []).append(label)
    return out
