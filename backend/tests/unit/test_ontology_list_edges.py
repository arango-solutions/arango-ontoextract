"""Unit tests for ``GET /api/v1/ontology/{id}/edges`` after T2.

T2 collapsed the previous 8-14 sequential WAN round-trips (one
``has_collection`` HEAD plus one AQL per of the 6 edge collections, plus
the same pair per of the 2 property collections) into 2 round-trips: one
``db.collections()`` call to discover existing collections, then one AQL
with two ``FLATTEN`` subqueries returning ``{edges, props}``.

The acceptance criteria these tests pin:

1. ``list_ontology_edges`` issues exactly ONE AQL call (regression --
   would catch a re-introduction of the per-collection loop).
2. The generated AQL only references collections that actually exist
   (older ontologies / mid-migration databases may be missing some).
3. The wire shape is unchanged from the previous implementation:
   each edge carries ``edge_type`` matching its source collection, and
   ``rdfs_range_class`` edges are still enriched with the owning
   property's label / description / confidence / evidence.
4. ``?include=summary`` continues to project the response to the
   workspace canvas's narrow allow-list.
5. The query-string builder is deterministic and cached so we don't
   re-stringify on every request (collection sets are effectively
   static during a process's lifetime).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.ontology import (
    _LIVE_EDGE_COLLECTIONS,
    _LIVE_PROP_COLLECTIONS,
    _LIVE_EDGES_AND_PROPS_QUERY_CACHE,
    _build_live_edges_and_props_query,
    _fetch_live_edges_and_properties,
)
from app.db.temporal_constants import NEVER_EXPIRES


# ---------------------------------------------------------------------------
# Fixtures: stubs for db.collections() and run_aql so tests run in <1s.
# ---------------------------------------------------------------------------


def _collections_listing(names: list[str]) -> list[dict[str, Any]]:
    """Mimic the shape ``db.collections()`` returns (one dict per col)."""
    return [{"name": n, "system": False} for n in names]


def _make_db_with_existing(names: list[str]) -> MagicMock:
    """Stub db whose ``collections()`` returns the given existing names."""
    db = MagicMock()
    db.collections.return_value = _collections_listing(names)
    # Belt-and-braces: ensure the obsolete fan-out path can't be silently
    # taken if list_ontology_edges regresses to it -- ``has_collection``
    # would mean a re-introduction of the per-collection loop.
    db.has_collection.side_effect = AssertionError(
        "has_collection() was called on the bulk path -- the T2 collapse "
        "regressed to the per-collection has_collection + AQL fan-out."
    )
    return db


@pytest.fixture(autouse=True)
def _reset_query_cache():
    """Clear the AQL string cache between tests so we observe builds."""
    _LIVE_EDGES_AND_PROPS_QUERY_CACHE.clear()
    yield
    _LIVE_EDGES_AND_PROPS_QUERY_CACHE.clear()


# ---------------------------------------------------------------------------
# _build_live_edges_and_props_query
# ---------------------------------------------------------------------------


class TestBuildLiveEdgesAndPropsQuery:
    def test_emits_one_subquery_per_existing_edge_collection(self):
        q = _build_live_edges_and_props_query(
            ("subclass_of", "rdfs_domain"),
            ("ontology_object_properties",),
        )
        assert "FOR e IN subclass_of" in q
        assert "FOR e IN rdfs_domain" in q
        assert "FOR p IN ontology_object_properties" in q
        # ``rdfs_range_class`` was NOT in the input set, must not appear.
        assert "rdfs_range_class" not in q

    def test_tags_each_edge_with_its_collection_via_edge_type(self):
        q = _build_live_edges_and_props_query(
            ("subclass_of", "has_property"), ()
        )
        assert 'edge_type: "subclass_of"' in q
        assert 'edge_type: "has_property"' in q

    def test_uses_flatten_to_handle_zero_one_or_many_subqueries(self):
        # 0 collections -> empty array literal, no FLATTEN.
        q = _build_live_edges_and_props_query((), ())
        assert "LET edges = []" in q
        assert "LET props = []" in q

        # 1 collection -> still wrapped in FLATTEN (uniform handling).
        q1 = _build_live_edges_and_props_query(("subclass_of",), ())
        assert "FLATTEN(" in q1
        assert "FOR e IN subclass_of" in q1

    def test_returns_combined_payload_shape(self):
        q = _build_live_edges_and_props_query(
            ("subclass_of",), ("ontology_object_properties",)
        )
        # The envelope the endpoint reads back: a single document with
        # both lists. Pinning this exact substring catches accidental
        # renames like ``edges_list`` that would silently break the
        # endpoint.
        assert "RETURN { edges: edges, props: props }" in q

    def test_caches_query_string_per_collection_set(self):
        a = _build_live_edges_and_props_query(
            ("subclass_of", "rdfs_domain"), ("ontology_object_properties",)
        )
        b = _build_live_edges_and_props_query(
            ("subclass_of", "rdfs_domain"), ("ontology_object_properties",)
        )
        # Same key -> exact same string object (cached).
        assert a is b

    def test_different_collection_sets_produce_different_queries(self):
        a = _build_live_edges_and_props_query(
            ("subclass_of",), ("ontology_object_properties",)
        )
        b = _build_live_edges_and_props_query(
            ("subclass_of", "rdfs_domain"), ("ontology_object_properties",)
        )
        assert a != b

    def test_inlined_collection_names_come_only_from_allowlist(self):
        # Defensive contract test: the caller MUST pass tuples drawn
        # from the module-level allowlists, since names are interpolated
        # into AQL with no escaping. If the allowlist were ever
        # accidentally widened to read external input, this guard would
        # be the one we rely on -- so encode the allowlist content here.
        for col in _LIVE_EDGE_COLLECTIONS:
            assert col.replace("_", "").isalnum(), (
                f"edge collection name {col!r} contains characters "
                "unsafe for AQL string interpolation"
            )
        for col in _LIVE_PROP_COLLECTIONS:
            assert col.replace("_", "").isalnum(), (
                f"property collection name {col!r} contains characters "
                "unsafe for AQL string interpolation"
            )


# ---------------------------------------------------------------------------
# _fetch_live_edges_and_properties
# ---------------------------------------------------------------------------


class TestFetchLiveEdgesAndProperties:
    def test_issues_exactly_one_aql_call(self):
        db = _make_db_with_existing(
            [
                "subclass_of",
                "rdfs_domain",
                "rdfs_range_class",
                "ontology_object_properties",
                "ontology_datatype_properties",
            ]
        )
        with patch("app.api.ontology.run_aql") as run_aql_mock:
            run_aql_mock.return_value = [{"edges": [], "props": []}]
            _fetch_live_edges_and_properties(db, "ont1")
            assert run_aql_mock.call_count == 1, (
                "T2 regression: list_ontology_edges should issue exactly "
                "one AQL call, not one per collection"
            )

    def test_aql_only_references_existing_collections(self):
        # Only a subset of the allowlist exists -- e.g. an older ontology
        # that pre-dates the rdfs_range_class / equivalent_class
        # collections. The query must NOT reference missing collections,
        # otherwise AQL parse-time validation would 500 the request.
        db = _make_db_with_existing(
            ["subclass_of", "has_property", "ontology_object_properties"]
        )
        with patch("app.api.ontology.run_aql") as run_aql_mock:
            run_aql_mock.return_value = [{"edges": [], "props": []}]
            _fetch_live_edges_and_properties(db, "ont1")
            sent_query = run_aql_mock.call_args.args[1]
            assert "subclass_of" in sent_query
            assert "has_property" in sent_query
            assert "ontology_object_properties" in sent_query
            for missing in (
                "rdfs_domain",
                "rdfs_range_class",
                "equivalent_class",
                "related_to",
                "ontology_datatype_properties",
            ):
                assert missing not in sent_query, (
                    f"query references {missing!r} but db.collections() "
                    "didn't list it -- AQL would fail at parse time"
                )

    def test_passes_ontology_id_and_never_expired_sentinel(self):
        db = _make_db_with_existing(["subclass_of"])
        with patch("app.api.ontology.run_aql") as run_aql_mock:
            run_aql_mock.return_value = [{"edges": [], "props": []}]
            _fetch_live_edges_and_properties(db, "ont42")
            bind = run_aql_mock.call_args.kwargs["bind_vars"]
            assert bind == {"oid": "ont42", "never": NEVER_EXPIRES}

    def test_returns_edges_and_property_map_from_envelope(self):
        db = _make_db_with_existing(
            ["subclass_of", "ontology_object_properties"]
        )
        edge_doc = {
            "_key": "e1",
            "_id": "subclass_of/e1",
            "edge_type": "subclass_of",
            "ontology_id": "ont1",
        }
        prop_doc = {
            "_key": "p1",
            "_id": "ontology_object_properties/p1",
            "label": "owns",
            "ontology_id": "ont1",
        }
        with patch("app.api.ontology.run_aql") as run_aql_mock:
            run_aql_mock.return_value = [
                {"edges": [edge_doc], "props": [prop_doc]}
            ]
            edges, props_by_id = _fetch_live_edges_and_properties(db, "ont1")

        assert edges == [edge_doc]
        assert props_by_id == {"ontology_object_properties/p1": prop_doc}

    def test_empty_envelope_returns_empty_results(self):
        db = _make_db_with_existing(["subclass_of"])
        with patch("app.api.ontology.run_aql") as run_aql_mock:
            run_aql_mock.return_value = [{"edges": [], "props": []}]
            edges, props_by_id = _fetch_live_edges_and_properties(db, "ont1")
        assert edges == []
        assert props_by_id == {}

    def test_no_collections_at_all_skips_aql_entirely(self):
        # Brand-new database -- no edge or property collections yet.
        # We must not even submit the query, since FLATTEN([]) on an
        # empty array would still be valid AQL but the caller side
        # would just ignore the result; saving the round-trip is a
        # nice-to-have correctness/perf win.
        db = _make_db_with_existing([])
        with patch("app.api.ontology.run_aql") as run_aql_mock:
            edges, props_by_id = _fetch_live_edges_and_properties(db, "ont1")
            run_aql_mock.assert_not_called()
        assert edges == []
        assert props_by_id == {}

    def test_skips_non_dict_rows_in_envelope(self):
        # Defensive: if a future AQL bug returns a stray scalar inside
        # ``edges`` or ``props``, we must filter it out rather than
        # crash the endpoint.
        db = _make_db_with_existing(
            ["subclass_of", "ontology_object_properties"]
        )
        edge_doc = {"_key": "e1", "_id": "subclass_of/e1"}
        prop_doc = {
            "_key": "p1",
            "_id": "ontology_object_properties/p1",
        }
        with patch("app.api.ontology.run_aql") as run_aql_mock:
            run_aql_mock.return_value = [
                {
                    "edges": [edge_doc, "not-a-dict", None],
                    "props": [prop_doc, 42, {"_id": None}],
                }
            ]
            edges, props_by_id = _fetch_live_edges_and_properties(db, "ont1")

        assert edges == [edge_doc]
        assert props_by_id == {"ontology_object_properties/p1": prop_doc}


# ---------------------------------------------------------------------------
# GET /api/v1/ontology/{id}/edges -- end-to-end via TestClient
# ---------------------------------------------------------------------------


class TestListOntologyEdgesEndpoint:
    def _client(self, db: MagicMock) -> TestClient:
        patcher = patch("app.api.ontology.get_db", return_value=db)
        patcher.start()
        from app.main import app

        client = TestClient(app)
        client._patcher = patcher  # type: ignore[attr-defined]
        return client

    def test_returns_enriched_rdfs_range_class_edges(self):
        # rdfs_range_class scaffolding edges are intentionally minimal --
        # the canvas requires that the owning property's label /
        # confidence / evidence be lifted onto the edge at read time.
        # This is the historical wire contract; T2 must preserve it.
        db = _make_db_with_existing(
            ["rdfs_range_class", "ontology_object_properties"]
        )
        prop_doc = {
            "_key": "p1",
            "_id": "ontology_object_properties/p1",
            "label": "generates Risk Profile",
            "description": "domain -> range",
            "confidence": 0.9,
            "evidence": [{"text": "p", "evidence_confidence": 0.9}],
            "ontology_id": "ont1",
            "expired": NEVER_EXPIRES,
        }
        edge_doc = {
            "_key": "e1",
            "_id": "rdfs_range_class/e1",
            "_from": "ontology_object_properties/p1",
            "_to": "ontology_classes/c1",
            "ontology_id": "ont1",
            "expired": NEVER_EXPIRES,
            "edge_type": "rdfs_range_class",
        }
        with patch("app.api.ontology.run_aql") as run_aql_mock:
            run_aql_mock.return_value = [
                {"edges": [edge_doc], "props": [prop_doc]}
            ]
            client = self._client(db)
            try:
                r = client.get("/api/v1/ontology/ont1/edges")
            finally:
                client._patcher.stop()  # type: ignore[attr-defined]

            assert r.status_code == 200
            edges = r.json()["data"]
            assert len(edges) == 1
            assert edges[0]["label"] == "generates Risk Profile"
            assert edges[0]["confidence"] == 0.9
            assert edges[0]["edge_type"] == "rdfs_range_class"
            # And exactly ONE AQL call -- the bulk path.
            assert run_aql_mock.call_count == 1

    def test_summary_profile_strips_evidence(self):
        # ?include=summary projects the response down to the canvas
        # allow-list; ``evidence`` arrays (the largest field) are
        # dropped. Pin this so a future projection refactor can't
        # silently re-introduce them and bloat the wire payload.
        db = _make_db_with_existing(["subclass_of"])
        edge_doc = {
            "_key": "e1",
            "_id": "subclass_of/e1",
            "_from": "ontology_classes/a",
            "_to": "ontology_classes/b",
            "edge_type": "subclass_of",
            "label": "rdfs:subClassOf",
            "confidence": 0.95,
            "evidence": [
                {"text": "long evidence passage" * 100, "evidence_confidence": 0.95}
            ],
            "ontology_id": "ont1",
            "expired": NEVER_EXPIRES,
        }
        with patch("app.api.ontology.run_aql") as run_aql_mock:
            run_aql_mock.return_value = [
                {"edges": [edge_doc], "props": []}
            ]
            client = self._client(db)
            try:
                r = client.get("/api/v1/ontology/ont1/edges?include=summary")
            finally:
                client._patcher.stop()  # type: ignore[attr-defined]

        assert r.status_code == 200
        edges = r.json()["data"]
        assert len(edges) == 1
        assert "evidence" not in edges[0]
        assert edges[0]["label"] == "rdfs:subClassOf"
        assert edges[0]["confidence"] == 0.95

    def test_handles_missing_collections_gracefully(self):
        # An older ontology may not have all 6 edge collections yet --
        # the endpoint must still 200 with whatever subset exists.
        db = _make_db_with_existing(["subclass_of"])  # only one
        with patch("app.api.ontology.run_aql") as run_aql_mock:
            run_aql_mock.return_value = [{"edges": [], "props": []}]
            client = self._client(db)
            try:
                r = client.get("/api/v1/ontology/ont1/edges")
            finally:
                client._patcher.stop()  # type: ignore[attr-defined]
        assert r.status_code == 200
        assert r.json() == {"data": []}

    def test_brand_new_database_returns_empty_without_aql(self):
        # No edge or property collections at all -- e.g. a fresh test
        # database that hasn't run the bootstrap migrations. The
        # endpoint must 200 with [] and skip the AQL call entirely.
        db = _make_db_with_existing([])
        with patch("app.api.ontology.run_aql") as run_aql_mock:
            client = self._client(db)
            try:
                r = client.get("/api/v1/ontology/ont1/edges")
            finally:
                client._patcher.stop()  # type: ignore[attr-defined]
            run_aql_mock.assert_not_called()
        assert r.status_code == 200
        assert r.json() == {"data": []}
