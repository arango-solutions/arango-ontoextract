"""023 -- Repair orphan ``ontology_object_properties`` ranges.

Backfills the missing ``rdfs_range_class`` edge for every object property
that has a live ``rdfs_domain`` edge but no live ``rdfs_range_class``
edge. The range class is inferred from the property's own
``description`` / ``evidence_text`` / ``source_spans`` by matching
existing class names -- see
``app.services.edge_repair.find_range_class_for_orphan`` for the rules
and ``app.services.edge_repair.repair_orphan_object_property_ranges``
for the orchestrator.

Why this exists
---------------

The extraction writer (``app.services.extraction``) writes the property
vertex + ``rdfs_domain`` edge unconditionally, but only writes the
``rdfs_range_class`` edge if the LLM-supplied ``target_class_uri``
resolves against an extracted class. When that resolution fails the
range edge is silently skipped, leaving the property orphaned and
invisible on the workspace canvas (which only draws class-to-class
links from paired ``rdfs_domain`` + ``rdfs_range_class``). A scan
across the demo ontologies showed 23 / 63 (37 %) of object properties
were orphans by this definition, of which 78 % could be auto-repaired
from the property's own recorded text.

This migration runs that auto-repair once on the existing data. The
companion pipeline fix (forthcoming) will prevent new orphans on the
next extraction.

Idempotent: running this migration a second time finds zero orphans
(the first run wrote the missing range edges, so the orphan filter no
longer matches them). Running it on a brand-new database with no
ontologies is a no-op.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.services.edge_repair import repair_orphan_object_property_ranges

log = logging.getLogger(__name__)


def _live_ontology_ids(db: StandardDatabase) -> list[str]:
    """Distinct ``ontology_id`` values currently present on object properties.

    Iterating registry entries would only catch ontologies that registered
    cleanly. This catches every ontology that has at least one object
    property in flight, which is the actual eligibility condition for the
    repair.
    """
    if not db.has_collection("ontology_object_properties"):
        return []
    rows = list(
        run_aql(
            db,
            "FOR p IN ontology_object_properties "
            "FILTER p.expired == @never "
            "COLLECT oid = p.ontology_id "
            "RETURN oid",
            bind_vars={"never": NEVER_EXPIRES},
        )
    )
    return [r for r in rows if isinstance(r, str)]


def up(db: StandardDatabase) -> None:
    ontology_ids = _live_ontology_ids(db)
    if not ontology_ids:
        log.debug(
            "023_repair_orphan_object_property_ranges: no ontologies present -- nothing to do"
        )
        return

    grand_orphans = 0
    grand_repaired = 0
    grand_unrecoverable = 0
    grand_no_domain = 0

    for oid in ontology_ids:
        report = repair_orphan_object_property_ranges(db, oid)
        grand_orphans += report.orphans_found
        grand_repaired += len(report.repaired)
        grand_unrecoverable += len(report.unrecoverable)
        grand_no_domain += len(report.no_domain)

    log.info(
        "023_repair_orphan_object_property_ranges: scanned %d ontology(ies) -- "
        "found %d orphan(s), repaired %d, unrecoverable %d, no_domain %d",
        len(ontology_ids),
        grand_orphans,
        grand_repaired,
        grand_unrecoverable,
        grand_no_domain,
    )
