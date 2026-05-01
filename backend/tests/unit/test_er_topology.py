"""Unit tests for entity resolution topology functions.

Tests _jaccard, compute_topological_similarity, compute_batch_topological_similarity,
and _get_class_neighborhood with mocked DB calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.er_topology import (
    _get_class_neighborhood,
    _jaccard,
    compute_batch_topological_similarity,
    compute_topological_similarity,
)

# ---------------------------------------------------------------------------
# _jaccard
# ---------------------------------------------------------------------------


class TestJaccard:
    def test_both_empty(self):
        assert _jaccard(set(), set()) == 0.0

    def test_identical_sets(self):
        assert _jaccard({"a", "b"}, {"a", "b"}) == 1.0

    def test_disjoint_sets(self):
        assert _jaccard({"a"}, {"b"}) == 0.0

    def test_partial_overlap(self):
        result = _jaccard({"a", "b", "c"}, {"b", "c", "d"})
        # intersection=2, union=4
        assert result == pytest.approx(0.5)

    def test_one_empty(self):
        assert _jaccard({"a"}, set()) == 0.0


# ---------------------------------------------------------------------------
# _get_class_neighborhood
# ---------------------------------------------------------------------------


class TestGetClassNeighborhood:
    def test_returns_properties_parents_children(self):
        mock_db = MagicMock()
        mock_db.has_collection.return_value = True

        # First call: has_property, second: subclass_of (checked twice)
        def mock_has_collection(name):
            return name in ("has_property", "subclass_of")

        mock_db.has_collection.side_effect = mock_has_collection

        call_count = [0]

        def mock_run_aql(db, query, bind_vars=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return iter(["http://ex.org#prop1", "http://ex.org#prop2"])
            elif call_count[0] == 2:
                return iter(["http://ex.org#Parent"])
            elif call_count[0] == 3:
                return iter(["http://ex.org#Child1", None, "http://ex.org#Child2"])
            return iter([])

        with patch("app.services.er_topology.run_aql", side_effect=mock_run_aql):
            result = _get_class_neighborhood(mock_db, "cls_key")

        assert result["properties"] == {"http://ex.org#prop1", "http://ex.org#prop2"}
        assert result["parents"] == {"http://ex.org#Parent"}
        # None values should be filtered out
        assert result["children"] == {"http://ex.org#Child1", "http://ex.org#Child2"}

    def test_returns_empty_when_no_collections(self):
        mock_db = MagicMock()
        mock_db.has_collection.return_value = False

        result = _get_class_neighborhood(mock_db, "cls_key")
        assert result["properties"] == set()
        assert result["parents"] == set()
        assert result["children"] == set()

    def test_merges_rdfs_domain_and_has_property_uris(self):
        mock_db = MagicMock()

        def mock_has_collection(name: str) -> bool:
            return name in ("rdfs_domain", "has_property", "subclass_of")

        mock_db.has_collection.side_effect = mock_has_collection

        call_count = [0]

        def mock_run_aql(db, query, bind_vars=None):
            call_count[0] += 1
            if "INBOUND" in query and "rdfs_domain" in query:
                return iter(["http://ex.org#fromRdfs"])
            if "OUTBOUND" in query and "has_property" in query:
                return iter(["http://ex.org#fromLegacy"])
            if "OUTBOUND" in query and "subclass_of" in query:
                return iter([])
            if "INBOUND" in query and "subclass_of" in query:
                return iter([])
            return iter([])

        with patch("app.services.er_topology.run_aql", side_effect=mock_run_aql):
            result = _get_class_neighborhood(mock_db, "cls_key")

        assert result["properties"] == {"http://ex.org#fromRdfs", "http://ex.org#fromLegacy"}


# ---------------------------------------------------------------------------
# compute_topological_similarity
# ---------------------------------------------------------------------------


class TestComputeTopologicalSimilarity:
    def test_identical_neighborhoods(self):
        neighborhood = {
            "properties": {"p1", "p2"},
            "parents": {"parent1"},
            "children": {"child1"},
        }
        with (
            patch("app.services.er_topology.get_db", return_value=MagicMock()),
            patch(
                "app.services.er_topology._get_class_neighborhood",
                return_value=neighborhood,
            ),
        ):
            score = compute_topological_similarity(class_key_1="a", class_key_2="b")
        assert score == 1.0

    def test_disjoint_neighborhoods(self):
        n1 = {"properties": {"p1"}, "parents": {"par1"}, "children": {"c1"}}
        n2 = {"properties": {"p2"}, "parents": {"par2"}, "children": {"c2"}}

        call_count = [0]

        def fake_neighborhood(db, key):
            call_count[0] += 1
            return n1 if call_count[0] == 1 else n2

        with (
            patch("app.services.er_topology.get_db", return_value=MagicMock()),
            patch(
                "app.services.er_topology._get_class_neighborhood",
                side_effect=fake_neighborhood,
            ),
        ):
            score = compute_topological_similarity(class_key_1="a", class_key_2="b")
        assert score == 0.0

    def test_empty_neighborhoods(self):
        empty = {"properties": set(), "parents": set(), "children": set()}
        with (
            patch("app.services.er_topology.get_db", return_value=MagicMock()),
            patch(
                "app.services.er_topology._get_class_neighborhood",
                return_value=empty,
            ),
        ):
            score = compute_topological_similarity(class_key_1="a", class_key_2="b")
        assert score == 0.0

    def test_accepts_explicit_db(self):
        mock_db = MagicMock()
        empty = {"properties": set(), "parents": set(), "children": set()}
        with patch(
            "app.services.er_topology._get_class_neighborhood",
            return_value=empty,
        ):
            score = compute_topological_similarity(mock_db, class_key_1="a", class_key_2="b")
        assert score == 0.0

    def test_score_is_clamped_and_rounded(self):
        n = {"properties": {"p1", "p2"}, "parents": {"par1"}, "children": set()}
        with (
            patch("app.services.er_topology.get_db", return_value=MagicMock()),
            patch(
                "app.services.er_topology._get_class_neighborhood",
                return_value=n,
            ),
        ):
            score = compute_topological_similarity(class_key_1="a", class_key_2="a")
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# compute_batch_topological_similarity
# ---------------------------------------------------------------------------


class TestBatchTopologicalSimilarity:
    def test_computes_for_multiple_pairs(self):
        neighborhoods = {
            "a": {"properties": {"p1"}, "parents": set(), "children": set()},
            "b": {"properties": {"p1"}, "parents": set(), "children": set()},
            "c": {"properties": {"p2"}, "parents": set(), "children": set()},
        }

        def fake_neighborhood(db, key):
            return neighborhoods[key]

        with (
            patch("app.services.er_topology.get_db", return_value=MagicMock()),
            patch(
                "app.services.er_topology._get_class_neighborhood",
                side_effect=fake_neighborhood,
            ),
        ):
            results = compute_batch_topological_similarity(pairs=[("a", "b"), ("a", "c")])

        assert ("a", "b") in results
        assert ("a", "c") in results
        # a and b share p1, so should be higher than a and c
        assert results[("a", "b")] > results[("a", "c")]

    def test_empty_pairs(self):
        with patch("app.services.er_topology.get_db", return_value=MagicMock()):
            results = compute_batch_topological_similarity(pairs=[])
        assert results == {}

    def test_caches_neighborhoods(self):
        """Each class key should only be fetched once even if it appears in multiple pairs."""
        n = {"properties": set(), "parents": set(), "children": set()}
        mock_get = MagicMock(return_value=n)

        with (
            patch("app.services.er_topology.get_db", return_value=MagicMock()),
            patch(
                "app.services.er_topology._get_class_neighborhood",
                side_effect=mock_get,
            ),
        ):
            compute_batch_topological_similarity(pairs=[("a", "b"), ("a", "c")])

        # "a" appears twice but should only be fetched once via caching
        keys_fetched = [c.args[1] for c in mock_get.call_args_list]
        assert keys_fetched.count("a") == 1
