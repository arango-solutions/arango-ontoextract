"""Unit tests for ontology edge resolution and status updates."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.temporal import NEVER_EXPIRES


def test_resolve_ontology_edge_finds_active_document() -> None:
    from app.db import ontology_repo

    db = MagicMock()
    col_a = MagicMock()
    col_a.get.return_value = None
    col_b = MagicMock()
    col_b.get.return_value = {
        "_key": "e1",
        "ontology_id": "onto1",
        "expired": NEVER_EXPIRES,
    }

    def has_collection(name: str) -> bool:
        return name in ("subclass_of", "related_to")

    def collection(name: str) -> MagicMock:
        if name == "subclass_of":
            return col_a
        if name == "related_to":
            return col_b
        return MagicMock()

    db.has_collection.side_effect = has_collection
    db.collection.side_effect = collection

    out = ontology_repo.resolve_ontology_edge(db, edge_key="e1")
    assert out is not None
    assert out[0] == "related_to"
    assert out[1]["_key"] == "e1"


def test_resolve_ontology_edge_skips_expired() -> None:
    from app.db import ontology_repo

    db = MagicMock()
    col = MagicMock()
    col.get.return_value = {"_key": "e1", "expired": 1}
    db.has_collection.return_value = True
    db.collection.return_value = col

    assert ontology_repo.resolve_ontology_edge(db, edge_key="e1") is None
