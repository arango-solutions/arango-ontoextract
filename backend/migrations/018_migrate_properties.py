"""018 — Migrate properties from old schema to PGT-aligned collections.

Converts data from ``ontology_properties`` (mixed ObjectProperty/DatatypeProperty)
into ``ontology_object_properties`` / ``ontology_datatype_properties`` vertex
collections and creates ``rdfs_domain`` / ``rdfs_range_class`` edges.

Old collections are NOT deleted — they will be cleaned up in a later migration.
Uses ``overwrite=True`` on all inserts for idempotency.

See ADR-006.
"""

from __future__ import annotations

import logging

from arango.database import StandardDatabase

from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql

log = logging.getLogger(__name__)


def up(db: StandardDatabase) -> None:
    if not db.has_collection("ontology_properties"):
        log.info("no ontology_properties collection found — nothing to migrate")
        return

    for name in ("ontology_object_properties", "ontology_datatype_properties"):
        if not db.has_collection(name):
            db.create_collection(name)
            log.info("created vertex collection %s", name)

    for name in ("rdfs_domain", "rdfs_range_class"):
        if not db.has_collection(name):
            db.create_collection(name, edge=True)
            log.info("created edge collection %s", name)

    obj_prop_col = db.collection("ontology_object_properties")
    dt_prop_col = db.collection("ontology_datatype_properties")
    rdfs_domain_col = db.collection("rdfs_domain")
    rdfs_range_col = db.collection("rdfs_range_class")

    class_keys: set[str] = set()
    if db.has_collection("ontology_classes"):
        class_keys = set(run_aql(
            db,
            "FOR c IN ontology_classes "
            "FILTER c.expired == @never "
            "RETURN c._key",
            bind_vars={"never": NEVER_EXPIRES},
        ))

    properties = list(run_aql(
        db,
        "FOR p IN ontology_properties "
        "FILTER p.expired == @never "
        "RETURN p",
        bind_vars={"never": NEVER_EXPIRES},
    ))

    obj_count = 0
    dt_count = 0
    domain_edge_count = 0
    range_edge_count = 0

    for prop in properties:
        key = prop["_key"]
        rdf_type = prop.get("rdf_type", "owl:DatatypeProperty")
        domain_class = prop.get("domain_class", "")
        range_val = prop.get("range", "xsd:string")
        ontology_id = prop.get("ontology_id", "")

        if rdf_type == "owl:ObjectProperty":
            obj_doc = {
                "_key": key,
                "uri": prop.get("uri", ""),
                "label": prop.get("label", ""),
                "description": prop.get("description", ""),
                "ontology_id": ontology_id,
                "confidence": prop.get("confidence", 0.0),
                "status": prop.get("status"),
                "created": prop.get("created"),
                "expired": prop.get("expired"),
            }
            try:
                obj_prop_col.insert(obj_doc, overwrite=True)
                obj_count += 1
            except Exception as exc:
                log.warning("object property insert failed for %s: %s", key, exc)

            if domain_class:
                domain_key = domain_class.split("#")[-1].split("/")[-1]
                try:
                    rdfs_domain_col.insert({
                        "_key": f"{key}__domain",
                        "_from": f"ontology_object_properties/{key}",
                        "_to": f"ontology_classes/{domain_key}",
                        "ontology_id": ontology_id,
                        "created": prop.get("created"),
                        "expired": NEVER_EXPIRES,
                    }, overwrite=True)
                    domain_edge_count += 1
                except Exception as exc:
                    log.warning("rdfs_domain edge failed for %s: %s", key, exc)

            if range_val:
                range_key = range_val.split("#")[-1].split("/")[-1]
                if range_key in class_keys:
                    try:
                        rdfs_range_col.insert({
                            "_key": f"{key}__range",
                            "_from": f"ontology_object_properties/{key}",
                            "_to": f"ontology_classes/{range_key}",
                            "ontology_id": ontology_id,
                            "created": prop.get("created"),
                            "expired": NEVER_EXPIRES,
                        }, overwrite=True)
                        range_edge_count += 1
                    except Exception as exc:
                        log.warning("rdfs_range_class edge failed for %s: %s", key, exc)
        else:
            dt_doc = {
                "_key": key,
                "uri": prop.get("uri", ""),
                "label": prop.get("label", ""),
                "description": prop.get("description", ""),
                "range_datatype": range_val,
                "ontology_id": ontology_id,
                "confidence": prop.get("confidence", 0.0),
                "status": prop.get("status"),
                "created": prop.get("created"),
                "expired": prop.get("expired"),
            }
            try:
                dt_prop_col.insert(dt_doc, overwrite=True)
                dt_count += 1
            except Exception as exc:
                log.warning("datatype property insert failed for %s: %s", key, exc)

            if domain_class:
                domain_key = domain_class.split("#")[-1].split("/")[-1]
                try:
                    rdfs_domain_col.insert({
                        "_key": f"{key}__domain",
                        "_from": f"ontology_datatype_properties/{key}",
                        "_to": f"ontology_classes/{domain_key}",
                        "ontology_id": ontology_id,
                        "created": prop.get("created"),
                        "expired": NEVER_EXPIRES,
                    }, overwrite=True)
                    domain_edge_count += 1
                except Exception as exc:
                    log.warning("rdfs_domain edge failed for %s: %s", key, exc)

    log.info(
        "Migrated %d object properties, %d datatype properties, "
        "%d rdfs_domain edges, %d rdfs_range_class edges",
        obj_count, dt_count, domain_edge_count, range_edge_count,
    )
