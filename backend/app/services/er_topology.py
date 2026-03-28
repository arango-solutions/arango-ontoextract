"""AOE-specific topological similarity scoring for entity resolution.

Computes graph-neighborhood similarity between ontology classes by comparing
shared properties, parent classes, child classes, and Jaccard similarity
of neighbor sets.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

from app.db.client import get_db
from app.services.temporal import NEVER_EXPIRES

log = logging.getLogger(__name__)


def compute_topological_similarity(
    db: StandardDatabase | None = None,
    *,
    class_key_1: str,
    class_key_2: str,
) -> float:
    """Compute topological similarity between two ontology classes.

    Score is a weighted combination of:
    - Shared property count (Jaccard)
    - Shared parent classes (Jaccard)
    - Shared child classes (Jaccard)
    - Overall neighbor Jaccard similarity

    Returns a value in [0.0, 1.0].
    """
    if db is None:
        db = get_db()

    neighbors_1 = _get_class_neighborhood(db, class_key_1)
    neighbors_2 = _get_class_neighborhood(db, class_key_2)

    prop_sim = _jaccard(neighbors_1["properties"], neighbors_2["properties"])
    parent_sim = _jaccard(neighbors_1["parents"], neighbors_2["parents"])
    child_sim = _jaccard(neighbors_1["children"], neighbors_2["children"])

    all_neighbors_1 = neighbors_1["properties"] | neighbors_1["parents"] | neighbors_1["children"]
    all_neighbors_2 = neighbors_2["properties"] | neighbors_2["parents"] | neighbors_2["children"]
    overall_sim = _jaccard(all_neighbors_1, all_neighbors_2)

    score = (
        0.35 * prop_sim
        + 0.30 * parent_sim
        + 0.15 * child_sim
        + 0.20 * overall_sim
    )

    return round(min(max(score, 0.0), 1.0), 4)


def compute_batch_topological_similarity(
    db: StandardDatabase | None = None,
    *,
    pairs: list[tuple[str, str]],
) -> dict[tuple[str, str], float]:
    """Compute topological similarity for a batch of class pairs."""
    if db is None:
        db = get_db()

    cache: dict[str, dict[str, set[str]]] = {}
    results: dict[tuple[str, str], float] = {}

    for key1, key2 in pairs:
        if key1 not in cache:
            cache[key1] = _get_class_neighborhood(db, key1)
        if key2 not in cache:
            cache[key2] = _get_class_neighborhood(db, key2)

        n1, n2 = cache[key1], cache[key2]
        prop_sim = _jaccard(n1["properties"], n2["properties"])
        parent_sim = _jaccard(n1["parents"], n2["parents"])
        child_sim = _jaccard(n1["children"], n2["children"])
        all_n1 = n1["properties"] | n1["parents"] | n1["children"]
        all_n2 = n2["properties"] | n2["parents"] | n2["children"]
        overall_sim = _jaccard(all_n1, all_n2)

        score = 0.35 * prop_sim + 0.30 * parent_sim + 0.15 * child_sim + 0.20 * overall_sim
        results[(key1, key2)] = round(min(max(score, 0.0), 1.0), 4)

    return results


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _jaccard(set_a: set[str], set_b: set[str]) -> float:
    """Jaccard similarity coefficient."""
    if not set_a and not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def _get_class_neighborhood(
    db: StandardDatabase, class_key: str
) -> dict[str, set[str]]:
    """Get the graph neighborhood of a class: properties, parents, children."""
    class_id = f"ontology_classes/{class_key}"
    result: dict[str, set[str]] = {
        "properties": set(),
        "parents": set(),
        "children": set(),
    }

    if db.has_collection("has_property"):
        props = list(
            db.aql.execute(
                """\
FOR v, e IN 1..1 OUTBOUND @cls_id has_property
  FILTER e.expired == @never
  RETURN v.uri""",
                bind_vars={"cls_id": class_id, "never": NEVER_EXPIRES},
            )
        )
        result["properties"] = {p for p in props if p}

    if db.has_collection("subclass_of"):
        parents = list(
            db.aql.execute(
                """\
FOR v, e IN 1..1 OUTBOUND @cls_id subclass_of
  FILTER e.expired == @never
  RETURN v.uri""",
                bind_vars={"cls_id": class_id, "never": NEVER_EXPIRES},
            )
        )
        result["parents"] = {p for p in parents if p}

        children = list(
            db.aql.execute(
                """\
FOR v, e IN 1..1 INBOUND @cls_id subclass_of
  FILTER e.expired == @never
  RETURN v.uri""",
                bind_vars={"cls_id": class_id, "never": NEVER_EXPIRES},
            )
        )
        result["children"] = {c for c in children if c}

    return result
