"""Unit tests for the single-item ``GET /edges/{key}`` and
``GET /properties/{key}`` endpoints.

These endpoints exist to fix the workspace ``FloatingDetailPanel``'s
N+1 anti-pattern: it used to fetch the entire edge or property list
just to call ``.find()`` on a single key. The acceptance criteria for
these endpoints are:

1. They return one document, not a list.
2. They preserve the same wire shape as the corresponding entry in the
   list endpoint -- specifically, ``rdfs_range_class`` edges must be
   enriched with the owning property's label / description / confidence
   / evidence so the canvas rendering does not change between
   "loaded via list" and "loaded via single fetch".
3. They reject mismatched ontology / expired / missing rows with 404.
4. They probe the property collections in object-then-datatype-then-
   legacy order; the first match wins so a key collision across
   collections cannot return the wrong document.
5. They annotate the returned property document with
   ``property_collection`` so the detail panel can branch on object vs
   datatype without an extra round-trip.

All tests stub the ArangoDB layer so they run in <1s with no network.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.db.temporal_constants import NEVER_EXPIRES

# ---------------------------------------------------------------------------
# Test fixtures: a stub db with per-collection ``.get()`` and ``.has_collection()``.
# ---------------------------------------------------------------------------


def _make_collection_stub(docs_by_key: dict[str, dict[str, Any]] | None = None) -> MagicMock:
    """Build a MagicMock that mimics ``db.collection(name)`` with ``.get(key)``."""
    col = MagicMock()
    docs = docs_by_key or {}
    col.get.side_effect = lambda k: docs.get(k)
    return col


@pytest.fixture()
def db_with_collections():
    """Return a factory that creates a stub db with the named collections.

    Caller passes ``{collection_name: {key: doc, ...}}``. Any collection
    not in the dict reports ``has_collection -> False``, which mirrors
    the real Arango client's behaviour for missing collections.
    """

    def _build(collections: dict[str, dict[str, dict[str, Any]]]) -> MagicMock:
        db = MagicMock()
        db.has_collection.side_effect = lambda name: name in collections
        col_stubs = {name: _make_collection_stub(docs) for name, docs in collections.items()}
        db.collection.side_effect = lambda name: col_stubs.get(name) or _make_collection_stub()
        return db

    return _build


@pytest.fixture()
def client_factory(db_with_collections):
    """Yield a function that builds a TestClient bound to a custom stub db."""

    def _build(collections: dict[str, dict[str, dict[str, Any]]]) -> TestClient:
        db = db_with_collections(collections)
        # Patch both import paths -- ``get_db`` is re-exported from app.db.client
        # and imported directly at the top of app.api.ontology.
        patcher_main = patch("app.api.ontology._shared.get_db", return_value=db)
        patcher_main.start()
        from app.main import app

        client = TestClient(app)
        # Attach so the test can stop the patch after use.
        client._patcher = patcher_main  # type: ignore[attr-defined]
        return client

    yield _build


def _live_edge(
    *,
    key: str,
    edge_col: str,
    ontology_id: str = "ont1",
    from_: str = "ontology_classes/c1",
    to: str = "ontology_classes/c2",
    confidence: float | None = 0.85,
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "_key": key,
        "_id": f"{edge_col}/{key}",
        "_from": from_,
        "_to": to,
        "ontology_id": ontology_id,
        "confidence": confidence,
        "evidence": evidence or [{"text": "supporting passage", "evidence_confidence": 0.9}],
        "created": 1000.0,
        "expired": NEVER_EXPIRES,
    }


def _live_property(
    *,
    key: str,
    col: str = "ontology_object_properties",
    ontology_id: str = "ont1",
    label: str = "relates to",
    confidence: float = 0.9,
) -> dict[str, Any]:
    return {
        "_key": key,
        "_id": f"{col}/{key}",
        "uri": f"ex:{key}",
        "label": label,
        "description": f"description for {key}",
        "ontology_id": ontology_id,
        "confidence": confidence,
        "evidence": [{"text": "p", "evidence_confidence": confidence}],
        "created": 1000.0,
        "expired": NEVER_EXPIRES,
    }


# ---------------------------------------------------------------------------
# GET /{ontology_id}/edges/{edge_key}
# ---------------------------------------------------------------------------


class TestGetEdgeDetail:
    def test_returns_edge_found_in_first_collection(self, client_factory):
        edge = _live_edge(key="e1", edge_col="subclass_of")
        client = client_factory({"subclass_of": {"e1": edge}})
        try:
            r = client.get("/api/v1/ontology/ont1/edges/e1")
            assert r.status_code == 200
            body = r.json()
            assert body["_key"] == "e1"
            assert body["edge_type"] == "subclass_of"
            assert body["_from"] == "ontology_classes/c1"
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]

    def test_probes_other_collections_when_not_in_first(self, client_factory):
        edge = _live_edge(key="e2", edge_col="rdfs_domain")
        client = client_factory(
            {
                "subclass_of": {},
                "rdfs_domain": {"e2": edge},
            }
        )
        try:
            r = client.get("/api/v1/ontology/ont1/edges/e2")
            assert r.status_code == 200
            assert r.json()["edge_type"] == "rdfs_domain"
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]

    def test_returns_404_when_not_found_anywhere(self, client_factory):
        client = client_factory({"subclass_of": {}, "rdfs_domain": {}})
        try:
            r = client.get("/api/v1/ontology/ont1/edges/missing")
            assert r.status_code == 404
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]

    def test_rejects_edge_in_different_ontology(self, client_factory):
        edge = _live_edge(key="e3", edge_col="subclass_of", ontology_id="other_ont")
        client = client_factory({"subclass_of": {"e3": edge}})
        try:
            r = client.get("/api/v1/ontology/ont1/edges/e3")
            assert r.status_code == 404
            # The error message must call out the mismatch -- a generic
            # "not found" would be misleading because the edge does exist.
            # Error envelope shape comes from app.api.errors._error_body:
            # {"error": {"code": ..., "message": ...}}
            msg = r.json()["error"]["message"].lower()
            assert "ontology" in msg or "ont1" in msg
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]

    def test_rejects_expired_edge(self, client_factory):
        edge = _live_edge(key="e4", edge_col="subclass_of")
        edge["expired"] = 999999.0  # explicitly not NEVER_EXPIRES
        client = client_factory({"subclass_of": {"e4": edge}})
        try:
            r = client.get("/api/v1/ontology/ont1/edges/e4")
            assert r.status_code == 404
            msg = r.json()["error"]["message"].lower()
            assert "live" in msg or "expired" in msg
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]

    def test_rdfs_range_class_enrichment_lifts_label_and_confidence(self, client_factory):
        """The contract that justifies this endpoint's existence.

        For ``rdfs_range_class`` edges the underlying edge document carries
        no human-readable label and no confidence. Both must be lifted
        from the owning ``ontology_object_properties`` document so the
        detail panel matches the canvas's confidence-lens rendering.
        """
        prop = _live_property(key="hasOwner", label="has owner", confidence=0.92)
        edge = {
            "_key": "rrc1",
            "_id": "rdfs_range_class/rrc1",
            "_from": "ontology_object_properties/hasOwner",
            "_to": "ontology_classes/Person",
            "ontology_id": "ont1",
            "created": 1000.0,
            "expired": NEVER_EXPIRES,
            # No top-level label / confidence -- these come from the property.
        }
        client = client_factory(
            {
                "subclass_of": {},
                "rdfs_domain": {},
                "rdfs_range_class": {"rrc1": edge},
                "ontology_object_properties": {"hasOwner": prop},
            }
        )
        try:
            r = client.get("/api/v1/ontology/ont1/edges/rrc1")
            assert r.status_code == 200
            body = r.json()
            assert body["edge_type"] == "rdfs_range_class"
            assert body["label"] == "has owner", (
                "rdfs_range_class label must be lifted from property"
            )
            assert body["confidence"] == 0.92, (
                "rdfs_range_class confidence must be lifted from property"
            )
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]

    def test_summary_profile_drops_evidence(self, client_factory):
        edge = _live_edge(key="e5", edge_col="subclass_of")
        client = client_factory({"subclass_of": {"e5": edge}})
        try:
            r = client.get("/api/v1/ontology/ont1/edges/e5?include=summary")
            assert r.status_code == 200
            body = r.json()
            assert "evidence" not in body
            # Identity + lens fields preserved
            assert body["_key"] == "e5"
            assert body["confidence"] == 0.85
            assert body["edge_type"] == "subclass_of"
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]

    def test_default_profile_returns_full_shape(self, client_factory):
        edge = _live_edge(key="e6", edge_col="subclass_of")
        client = client_factory({"subclass_of": {"e6": edge}})
        try:
            r = client.get("/api/v1/ontology/ont1/edges/e6")
            assert r.status_code == 200
            body = r.json()
            # Backwards compatibility: no ?include= must keep ALL fields.
            assert "evidence" in body
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]

    def test_confidence_derived_from_evidence_when_missing(self, client_factory):
        """When the edge has no top-level confidence but has evidence, the
        endpoint must compute it (mean of evidence_confidence) -- same as
        the list endpoint's :func:`compute_edge_confidence` step."""
        edge = _live_edge(
            key="e7",
            edge_col="subclass_of",
            confidence=None,
            evidence=[
                {"text": "a", "evidence_confidence": 0.8},
                {"text": "b", "evidence_confidence": 0.6},
            ],
        )
        client = client_factory({"subclass_of": {"e7": edge}})
        try:
            r = client.get("/api/v1/ontology/ont1/edges/e7")
            assert r.status_code == 200
            body = r.json()
            assert body["confidence"] == pytest.approx(0.7), (
                "Endpoint must compute confidence from evidence when the edge "
                "document does not carry a top-level confidence field"
            )
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# GET /{ontology_id}/properties/{prop_key}
# ---------------------------------------------------------------------------


class TestGetPropertyDetail:
    def test_returns_property_from_object_collection(self, client_factory):
        prop = _live_property(key="hasOwner", col="ontology_object_properties")
        client = client_factory({"ontology_object_properties": {"hasOwner": prop}})
        try:
            r = client.get("/api/v1/ontology/ont1/properties/hasOwner")
            assert r.status_code == 200
            body = r.json()
            assert body["_key"] == "hasOwner"
            assert body["property_collection"] == "ontology_object_properties"
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]

    def test_returns_property_from_datatype_collection(self, client_factory):
        prop = _live_property(key="age", col="ontology_datatype_properties")
        client = client_factory(
            {
                "ontology_object_properties": {},
                "ontology_datatype_properties": {"age": prop},
            }
        )
        try:
            r = client.get("/api/v1/ontology/ont1/properties/age")
            assert r.status_code == 200
            body = r.json()
            assert body["_key"] == "age"
            assert body["property_collection"] == "ontology_datatype_properties"
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]

    def test_object_collection_wins_on_key_collision(self, client_factory):
        """If the same _key exists in both collections (legacy data), the
        object-properties collection must win because the API probes that
        first. This pins the probe order so a future shuffle of the loop
        is caught."""
        prop_obj = _live_property(key="x", col="ontology_object_properties", label="object-x")
        prop_dt = _live_property(key="x", col="ontology_datatype_properties", label="datatype-x")
        client = client_factory(
            {
                "ontology_object_properties": {"x": prop_obj},
                "ontology_datatype_properties": {"x": prop_dt},
            }
        )
        try:
            r = client.get("/api/v1/ontology/ont1/properties/x")
            assert r.status_code == 200
            assert r.json()["label"] == "object-x"
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]

    def test_keeps_probing_when_first_match_is_in_wrong_ontology(self, client_factory):
        """Same _key in two collections, only the second belongs to the
        requested ontology -- the endpoint must skip the wrong-ontology
        match and return the right one."""
        wrong_ont = _live_property(
            key="x", col="ontology_object_properties", ontology_id="other_ont"
        )
        right = _live_property(
            key="x", col="ontology_datatype_properties", ontology_id="ont1", label="correct"
        )
        client = client_factory(
            {
                "ontology_object_properties": {"x": wrong_ont},
                "ontology_datatype_properties": {"x": right},
            }
        )
        try:
            r = client.get("/api/v1/ontology/ont1/properties/x")
            assert r.status_code == 200
            assert r.json()["label"] == "correct"
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]

    def test_skips_expired_versions(self, client_factory):
        expired = _live_property(key="legacy", col="ontology_object_properties")
        expired["expired"] = 12345.0
        client = client_factory({"ontology_object_properties": {"legacy": expired}})
        try:
            r = client.get("/api/v1/ontology/ont1/properties/legacy")
            assert r.status_code == 404
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]

    def test_returns_404_when_not_found(self, client_factory):
        client = client_factory(
            {"ontology_object_properties": {}, "ontology_datatype_properties": {}}
        )
        try:
            r = client.get("/api/v1/ontology/ont1/properties/missing")
            assert r.status_code == 404
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]

    def test_falls_back_to_legacy_collection(self, client_factory):
        """Older ontologies have a single ``ontology_properties`` collection.
        The endpoint must still find them there after the two PGT collections
        miss."""
        prop = _live_property(key="legacy_prop", col="ontology_properties")
        client = client_factory(
            {
                "ontology_object_properties": {},
                "ontology_datatype_properties": {},
                "ontology_properties": {"legacy_prop": prop},
            }
        )
        try:
            r = client.get("/api/v1/ontology/ont1/properties/legacy_prop")
            assert r.status_code == 200
            assert r.json()["property_collection"] == "ontology_properties"
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]
