"""Regression: library edge counts must be ONE AQL round-trip, not O(collections).

python-arango's ``has_collection`` and ``collections`` each issue a full
``GET /_api/collection`` round-trip; on a remote (cloud, WAN) ArangoDB the old
"has_collection + AQL per edge collection" shape made ``/library`` ~10
round-trips and seconds slow. These tests pin the single-round-trip behaviour.
"""

from unittest.mock import MagicMock, patch

from app.api.ontology import _batch_edge_counts_for_ontology_ids


def test_batch_edge_counts_single_combined_query() -> None:
    db = MagicMock()
    # One collections() snapshot; subclass_of + rdfs_domain present, others absent.
    db.collections.return_value = [
        {"name": "subclass_of"},
        {"name": "rdfs_domain"},
        {"name": "ontology_classes"},
    ]

    calls = {"n": 0}

    def fake_run_aql(_db, query, bind_vars=None, **kwargs):
        calls["n"] += 1
        assert bind_vars is not None
        assert "IN @oids" in query
        # All present edge collections are unioned into one query...
        assert "subclass_of" in query
        assert "rdfs_domain" in query
        # ...and absent ones are excluded.
        assert "related_to" not in query
        # Server-side aggregation across collections.
        assert "FLATTEN" in query
        assert "AGGREGATE" in query
        # The DB returns already-summed counts (ont_a's 2 + 1 across collections).
        return iter([{"oid": "ont_a", "cnt": 3}, {"oid": "ont_b", "cnt": 5}])

    with patch("app.api.ontology.run_aql", side_effect=fake_run_aql):
        counts = _batch_edge_counts_for_ontology_ids(db, ["ont_a", "ont_b"])

    assert calls["n"] == 1  # single round-trip regardless of collection count
    assert db.has_collection.call_count == 0  # no per-collection metadata probes
    assert counts["ont_a"] == 3
    assert counts["ont_b"] == 5


def test_batch_edge_counts_uses_caller_supplied_collection_set() -> None:
    """When the caller passes ``existing``, we must NOT re-probe collections()."""
    db = MagicMock()
    with patch("app.api.ontology.run_aql", return_value=iter([{"oid": "o", "cnt": 4}])):
        counts = _batch_edge_counts_for_ontology_ids(db, ["o"], existing={"subclass_of"})
    db.collections.assert_not_called()
    assert counts["o"] == 4


def test_batch_edge_counts_no_edge_collections_returns_zeros() -> None:
    db = MagicMock()
    with patch("app.api.ontology.run_aql") as run_aql_mock:
        counts = _batch_edge_counts_for_ontology_ids(db, ["a", "b"], existing={"ontology_classes"})
    run_aql_mock.assert_not_called()  # nothing to query
    assert counts == {"a": 0, "b": 0}


def test_batch_edge_counts_empty_ids() -> None:
    db = MagicMock()
    assert _batch_edge_counts_for_ontology_ids(db, []) == {}
