"""029 — Assertion-graph (A-box) collections (Stream 21 / AB-PR1).

Creates the instance layer that sits beneath the extracted T-box (PRD §6.18):

* ``ontology_individuals`` -- versioned vertex; one document per named
  individual (instance), scoped to an ``ontology_id`` (its domain ontology).
* ``rdf_type`` -- edge; individual ``_from`` -> ``ontology_classes`` ``_to``
  (the individual's asserted type).
* ``individual_assertion`` -- edge; relationship assertions between individuals
  (and object-property values), carrying a ``predicate`` + span ``provenance``.

Individuals + assertions are temporal (``created`` / ``expired`` = NEVER_EXPIRES,
``ttlExpireAt``) like the T-box collections, so the A-box participates in time
travel and TTL GC on the same footing.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase
from arango.exceptions import IndexCreateError

log = logging.getLogger(__name__)

_INDIVIDUALS = "ontology_individuals"
_RDF_TYPE = "rdf_type"
_ASSERTION = "individual_assertion"

# (collection, is_edge, ((index_name, fields, sparse), ...))
_COLLECTIONS = (
    (
        _INDIVIDUALS,
        False,
        (
            ("idx_individuals_ontology_expired", ["ontology_id", "expired"], False),
            ("idx_individuals_ttl", ["ttlExpireAt"], True),
        ),
    ),
    (
        _RDF_TYPE,
        True,
        (
            ("idx_rdf_type_ontology_expired", ["ontology_id", "expired"], False),
            ("idx_rdf_type_ttl", ["ttlExpireAt"], True),
        ),
    ),
    (
        _ASSERTION,
        True,
        (
            ("idx_assertion_ontology_expired", ["ontology_id", "expired"], False),
            ("idx_assertion_predicate", ["predicate"], False),
            ("idx_assertion_ttl", ["ttlExpireAt"], True),
        ),
    ),
)


def up(db: StandardDatabase) -> None:
    for name, is_edge, indexes in _COLLECTIONS:
        if not db.has_collection(name):
            db.create_collection(name, edge=is_edge)
            log.info("created %s collection %s", "edge" if is_edge else "document", name)
        col = db.collection(name)
        existing = {idx.get("name") for idx in col.indexes()}
        for idx_name, fields, sparse in indexes:
            if idx_name in existing:
                continue
            try:
                col.add_persistent_index(fields=fields, name=idx_name, sparse=sparse)
                log.info("created index %s on %s", idx_name, name)
            except IndexCreateError:
                log.warning("could not create index %s on %s", idx_name, name, exc_info=True)
