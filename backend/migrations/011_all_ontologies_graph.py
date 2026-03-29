"""011 — (Removed) all_ontologies graph was redundant with domain_ontology.

This migration is kept as a no-op to preserve migration numbering.
The domain_ontology graph serves as the shared composite view.
"""

from __future__ import annotations

from arango.database import StandardDatabase


def up(db: StandardDatabase) -> None:
    if db.has_graph("all_ontologies"):
        db.delete_graph("all_ontologies", drop_collections=False)
