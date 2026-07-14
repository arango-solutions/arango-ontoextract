"""027 — Placeholder for the ontology-entity vector indexes (SF.1).

Alignment (Stream 20), the A-box schema retriever (Stream 21), and
competency-question term matching (Stream 22) all rely on vector search over
ontology entity embeddings (``ontology_classes`` /
``ontology_object_properties`` / ``ontology_datatype_properties``, field
``embedding``).

Like the ``chunks.embedding`` index (migration 008), the FAISS-IVF vector index
CANNOT be created at migration time: ArangoDB trains the index over existing
vectors, and a freshly-migrated database has none. Index creation is therefore
handled at runtime by
``app.services.ontology_embeddings.ensure_entity_vector_index`` once embeddings
have been populated by ``embed_ontology_entities``.

This migration is a documented no-op placeholder: it reserves the sequence
number, records the design decision alongside 008, and defensively drops any
stale/broken vector index left by an aborted earlier run so runtime re-creation
starts clean. It intentionally does not create an index.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

log = logging.getLogger(__name__)

_ENTITY_COLLECTIONS = (
    "ontology_classes",
    "ontology_object_properties",
    "ontology_datatype_properties",
)


def up(db: StandardDatabase) -> None:
    for collection in _ENTITY_COLLECTIONS:
        if not db.has_collection(collection):
            continue
        index_name = f"idx_{collection}_embedding_vector"
        col = db.collection(collection)
        for idx in col.indexes():
            if idx.get("name") == index_name and idx.get("type") != "vector":
                # A non-vector index squatting on the reserved name would block
                # runtime creation; drop it so ensure_entity_vector_index wins.
                col.delete_index(idx["id"])
                log.info("dropped stale non-vector index %s from %s", index_name, collection)
    log.debug("027: vector indexes are created at runtime; nothing to build here")
