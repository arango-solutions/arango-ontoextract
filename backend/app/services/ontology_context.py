"""Domain ontology context serialization for Tier 2 extraction.

Serializes domain ontology class hierarchy into compact text for LLM prompt
injection, enabling context-aware extraction that classifies entities as
EXISTING, EXTENSION, or NEW relative to the domain.
"""

from __future__ import annotations

import logging
from typing import Any

from arango.database import StandardDatabase

from app.db.client import get_db
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
    properties = _get_class_properties(db, ontology_id)

    if not classes:
        return f"Domain: {ontology_name}\nClasses: (none)"

    class_by_id: dict[str, dict[str, Any]] = {c["_id"]: c for c in classes}
    children_map: dict[str, list[str]] = {}
    child_ids: set[str] = set()

    for edge in hierarchy:
        parent_id = edge.get("_to", "")
        child_id = edge.get("_from", "")
        if parent_id in class_by_id and child_id in class_by_id:
            children_map.setdefault(parent_id, []).append(child_id)
            child_ids.add(child_id)

    props_map: dict[str, list[str]] = {}
    for prop in properties:
        domain_id = prop.get("domain_class_id", "")
        if domain_id in class_by_id:
            props_map.setdefault(domain_id, []).append(prop.get("label", prop.get("uri", "")))

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

    results = list(db.aql.execute(query, bind_vars={"org_id": org_id}))
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
                db.aql.execute(
                    "FOR r IN ontology_registry FILTER r._key == @k LIMIT 1 RETURN 1",
                    bind_vars={"k": oid},
                )
            )
            if not exists:
                raise ValueError(f"Ontology '{oid}' not found in registry")

    if not db.has_collection("organizations"):
        db.create_collection("organizations")

    existing = list(
        db.aql.execute(
            "FOR org IN organizations FILTER org._key == @k LIMIT 1 RETURN org",
            bind_vars={"k": org_id},
        )
    )
    if existing:
        result = db.collection("organizations").update(
            {"_key": org_id, "selected_ontologies": ontology_ids},
            return_new=True,
        )
        return result["new"]

    result = db.collection("organizations").insert(
        {"_key": org_id, "selected_ontologies": ontology_ids},
        return_new=True,
    )
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
        db.aql.execute(
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
        db.aql.execute(
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
        db.aql.execute(
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
        db.aql.execute(
            """\
FOR prop IN ontology_properties
  FILTER prop.ontology_id == @oid
  FILTER prop.expired == @never
  RETURN prop""",
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
        )
    )
