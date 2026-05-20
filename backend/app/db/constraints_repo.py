"""Repository for the ``ontology_constraints`` collection.

Stream 3 PR 1 -- the first writer (extraction materialization in
``app.services.extraction._materialize_to_graph``) and the first reader
(``GET /library/{id}/constraints`` in ``app.api.ontology``) for this
collection.

Constraint documents follow the PRD §6.14 shape:

* ``constraint_type``: one of ``"owl:Restriction"``, ``"sh:NodeShape"``,
  ``"sh:PropertyShape"``. PR 1 only writes the OWL flavour; SHACL is
  PR 3's job.
* ``on_class``: the class the constraint applies to, as a full Arango
  document id like ``ontology_classes/Customer``.
* ``property_id``: the property the restriction targets, as a full id
  like ``ontology_datatype_properties/customer_hasName``. May be
  ``None`` when the LLM-supplied ``property_uri`` couldn't be resolved
  to an extracted property at materialization time.
* ``property_uri``: the raw URI from the extraction. Always populated
  so that a later repair pass (or curator) can recover the link.
* ``restriction_type``: the OWL restriction kind --
  ``minCardinality`` / ``maxCardinality`` / ``cardinality`` /
  ``allValuesFrom`` / ``someValuesFrom`` / ``hasValue``.
* ``restriction_value``: the value, interpreted per ``restriction_type``
  (see ``app.models.ontology.ExtractedConstraint``).

Temporal fields (``created`` / ``expired``) follow the same convention
as every other versioned vertex (PRD §5.3): ``NEVER_EXPIRES`` for the
live row, a Unix timestamp once superseded.
"""

from __future__ import annotations

import logging
from typing import Any

from arango.database import StandardDatabase

from app.db.client import get_db
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql

log = logging.getLogger(__name__)


CONSTRAINT_COLLECTION = "ontology_constraints"


def list_constraints_for_ontology(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    constraint_type: str | None = None,
    include_unresolved: bool = True,
) -> list[dict[str, Any]]:
    """Return all live constraint documents for ``ontology_id``.

    Args:
        db: Database handle; defaults to the request-scoped one.
        ontology_id: Filter to this ontology only.
        constraint_type: Optional exact-match filter on
            ``constraint_type`` (e.g. ``"owl:Restriction"``). ``None``
            returns every kind.
        include_unresolved: When ``False``, drop rows whose
            ``property_id`` is ``None`` (the LLM gave a property URI
            that didn't match any extracted property). Defaults to
            ``True`` because the UI generally wants to surface
            unresolved constraints so curators can fix the link.

    Returns the rows in insertion order; for stable display sorts the
    caller should sort by (``on_class``, ``property_uri``).
    """
    if db is None:
        db = get_db()
    if not db.has_collection(CONSTRAINT_COLLECTION):
        return []

    filters = [
        "c.ontology_id == @ontology_id",
        "c.expired == @never",
    ]
    bind: dict[str, Any] = {
        "ontology_id": ontology_id,
        "never": NEVER_EXPIRES,
    }
    if constraint_type is not None:
        filters.append("c.constraint_type == @ctype")
        bind["ctype"] = constraint_type
    if not include_unresolved:
        filters.append("c.property_id != null")

    query = f"FOR c IN {CONSTRAINT_COLLECTION} FILTER {' AND '.join(filters)} RETURN c"
    return list(run_aql(db, query, bind_vars=bind))


def list_constraints_for_class(
    db: StandardDatabase | None = None,
    *,
    class_id: str,
) -> list[dict[str, Any]]:
    """Return all live constraints attached to a specific class.

    ``class_id`` is the full Arango document id, e.g.
    ``ontology_classes/Customer``.
    """
    if db is None:
        db = get_db()
    if not db.has_collection(CONSTRAINT_COLLECTION):
        return []

    query = (
        f"FOR c IN {CONSTRAINT_COLLECTION} "
        "FILTER c.on_class == @class_id AND c.expired == @never "
        "RETURN c"
    )
    return list(
        run_aql(
            db,
            query,
            bind_vars={"class_id": class_id, "never": NEVER_EXPIRES},
        )
    )


def count_constraints_for_ontology(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
) -> int:
    """Return the count of live constraints for ``ontology_id``.

    Returns 0 if the collection doesn't exist. Useful for the library
    summary card without paying the cost of materializing every row.
    """
    if db is None:
        db = get_db()
    if not db.has_collection(CONSTRAINT_COLLECTION):
        return 0
    rows = list(
        run_aql(
            db,
            f"FOR c IN {CONSTRAINT_COLLECTION} "
            "FILTER c.ontology_id == @ontology_id AND c.expired == @never "
            "COLLECT WITH COUNT INTO n "
            "RETURN n",
            bind_vars={"ontology_id": ontology_id, "never": NEVER_EXPIRES},
        )
    )
    return int(rows[0]) if rows else 0
