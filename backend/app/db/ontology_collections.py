"""Canonical ArangoDB collection-name allowlists for ontology storage.

Single source of truth for the property *vertex* collection triple defined by
ADR-006 (PGT-aligned property collections). Several services previously
re-declared this exact triple inline; centralizing it here means a future
collection rename or addition is a one-line change.

Only the property triple is shared here. The various *edge* collection lists
across the codebase intentionally differ in membership (e.g. the temporal
snapshot list adds ``extracted_from`` provenance; the deletion-impact list adds
``has_constraint`` / ``has_chunk`` / ``produced_by``; the live-projection list
is a curated 6-collection subset). Those are deliberately scoped per use case
and must NOT be collapsed into one list.
"""

from __future__ import annotations

from typing import Final

# Property vertex collections in lookup order: the legacy single collection
# first (pre-ADR-006 data), then the PGT-aligned object/datatype split.
# Callers iterate these and skip collections that do not exist, so the legacy
# entry is harmless on PGT-only deployments.
PROPERTY_VERTEX_COLLECTIONS: Final[tuple[str, ...]] = (
    "ontology_properties",
    "ontology_object_properties",
    "ontology_datatype_properties",
)
