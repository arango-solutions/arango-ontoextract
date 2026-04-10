"""Regression: library list must not run O(n) sequential AQL per ontology (event-loop stall)."""

from unittest.mock import MagicMock, patch

from app.api.ontology import _batch_edge_counts_for_ontology_ids


def test_batch_edge_counts_one_query_per_collection() -> None:
    db = MagicMock()
    db.has_collection.return_value = True

    def fake_run_aql(_db, query, bind_vars=None, **kwargs):
        assert bind_vars is not None
        assert "IN @oids" in query
        if "subclass_of" in query:
            return iter([{"oid": "ont_a", "cnt": 2}, {"oid": "ont_b", "cnt": 5}])
        if "rdfs_domain" in query:
            return iter([{"oid": "ont_a", "cnt": 1}])
        return iter([])

    with patch("app.api.ontology.run_aql", side_effect=fake_run_aql):
        counts = _batch_edge_counts_for_ontology_ids(db, ["ont_a", "ont_b"])

    assert counts["ont_a"] == 3
    assert counts["ont_b"] == 5


def test_batch_edge_counts_empty_ids() -> None:
    db = MagicMock()
    assert _batch_edge_counts_for_ontology_ids(db, []) == {}
