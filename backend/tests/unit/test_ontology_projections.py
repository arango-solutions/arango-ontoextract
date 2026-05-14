"""Unit tests for ``app.services.ontology_projections``.

These tests pin the wire contract of the ``?include=summary`` field
projection used by ``GET /ontology/{id}/classes`` and
``GET /ontology/{id}/edges``. The contract is:

* Heavy fields (``evidence``, ``parent_evidence``, ``embedding``, ``_rev``)
  are NEVER returned in the summary projection.
* All declared allow-list fields are ALWAYS returned (as ``None`` if the
  source document lacks them) so frontend consumers can rely on a stable
  shape regardless of whether a field happened to be set on a row.
* The AQL ``RETURN`` clauses are derived from the same Python tuple as the
  in-Python helpers, so they cannot drift out of sync.

If a future change adds a new heavy field to a class/edge writer, these
tests will continue to pass (the allow-list is closed) -- which is the
point. New fields must be explicitly added to the allow-list in
``ontology_projections.py``, where the size impact is reviewed.
"""

from __future__ import annotations

import pytest

from app.services.ontology_projections import (
    CLASS_SUMMARY_FIELDS,
    CLASS_SUMMARY_RETURN,
    EDGE_SUMMARY_FIELDS,
    EDGE_SUMMARY_RETURN,
    INCLUDE_FULL,
    INCLUDE_SUMMARY,
    VALID_INCLUDE_VALUES,
    normalize_include,
    summarize_class,
    summarize_edge,
)

# ---------------------------------------------------------------------------
# Allow-list contract: heavy fields are excluded, identity fields included.
# ---------------------------------------------------------------------------


HEAVY_FIELDS = ("evidence", "parent_evidence", "embedding", "_rev")


class TestClassSummaryFields:
    def test_drops_evidence_arrays(self) -> None:
        for field in HEAVY_FIELDS:
            assert field not in CLASS_SUMMARY_FIELDS, (
                f"Heavy field '{field}' must not appear in CLASS_SUMMARY_FIELDS "
                "-- the whole point of the summary profile is to drop it"
            )

    def test_keeps_identity_fields(self) -> None:
        for field in ("_key", "_id", "uri", "ontology_id"):
            assert field in CLASS_SUMMARY_FIELDS

    def test_keeps_canvas_lens_fields(self) -> None:
        # These drive the canvas's lens rendering (color, ring, label).
        for field in ("label", "confidence", "rdf_type", "tier", "status"):
            assert field in CLASS_SUMMARY_FIELDS

    def test_keeps_temporal_fields(self) -> None:
        # Used by the VCR / timeline lens.
        for field in ("created", "expired"):
            assert field in CLASS_SUMMARY_FIELDS


class TestEdgeSummaryFields:
    def test_drops_heavy_fields(self) -> None:
        for field in HEAVY_FIELDS:
            assert field not in EDGE_SUMMARY_FIELDS

    def test_keeps_topology_fields(self) -> None:
        # Without _from / _to / edge_type / _key the canvas cannot draw the edge.
        for field in ("_key", "_id", "_from", "_to", "edge_type"):
            assert field in EDGE_SUMMARY_FIELDS

    def test_keeps_lens_fields(self) -> None:
        for field in ("label", "confidence", "status"):
            assert field in EDGE_SUMMARY_FIELDS


# ---------------------------------------------------------------------------
# AQL RETURN clauses are kept in sync with the Python tuples.
# ---------------------------------------------------------------------------


class TestAqlReturnClauses:
    def test_class_aql_mentions_every_summary_field(self) -> None:
        # AQL: RETURN { _key: c._key, label: c.label, ... }
        # Each field must appear exactly once on the LHS of a `:`.
        for field in CLASS_SUMMARY_FIELDS:
            assert f"{field}: c.{field}" in CLASS_SUMMARY_RETURN, (
                f"CLASS_SUMMARY_RETURN is out of sync with CLASS_SUMMARY_FIELDS "
                f"-- missing '{field}: c.{field}'"
            )

    def test_class_aql_does_not_leak_heavy_fields(self) -> None:
        for field in HEAVY_FIELDS:
            assert f"c.{field}" not in CLASS_SUMMARY_RETURN

    def test_edge_aql_mentions_every_summary_field(self) -> None:
        for field in EDGE_SUMMARY_FIELDS:
            assert f"{field}: e.{field}" in EDGE_SUMMARY_RETURN

    def test_edge_aql_does_not_leak_heavy_fields(self) -> None:
        for field in HEAVY_FIELDS:
            assert f"e.{field}" not in EDGE_SUMMARY_RETURN

    def test_class_aql_starts_with_return(self) -> None:
        # Caller concatenates this onto a FOR/SORT preamble; must start with RETURN.
        assert CLASS_SUMMARY_RETURN.startswith("RETURN ")
        assert CLASS_SUMMARY_RETURN.endswith(" }")

    def test_edge_aql_starts_with_return(self) -> None:
        assert EDGE_SUMMARY_RETURN.startswith("RETURN ")
        assert EDGE_SUMMARY_RETURN.endswith(" }")


# ---------------------------------------------------------------------------
# In-Python projection helpers.
# ---------------------------------------------------------------------------


class TestSummarizeClass:
    def test_drops_evidence(self) -> None:
        full = {
            "_key": "c1",
            "_id": "ontology_classes/c1",
            "_rev": "_rev_token",
            "uri": "ex:Foo",
            "label": "Foo",
            "confidence": 0.9,
            "ontology_id": "ont1",
            "evidence": [{"text": "a" * 5000}],
            "parent_evidence": [{"text": "b" * 1000}],
            "embedding": [0.1] * 1536,
        }
        out = summarize_class(full)
        assert "evidence" not in out
        assert "parent_evidence" not in out
        assert "embedding" not in out
        assert "_rev" not in out

    def test_returns_none_for_missing_optional_fields(self) -> None:
        # tier/status/parent_uri are optional; canvas treats missing as null.
        full = {
            "_key": "c1",
            "_id": "ontology_classes/c1",
            "uri": "ex:Foo",
            "label": "Foo",
            "ontology_id": "ont1",
        }
        out = summarize_class(full)
        assert out["tier"] is None
        assert out["status"] is None
        assert out["parent_uri"] is None

    def test_returns_exactly_the_allow_list_keys(self) -> None:
        full = {name: f"value-{name}" for name in CLASS_SUMMARY_FIELDS}
        full["evidence"] = ["should be dropped"]
        out = summarize_class(full)
        assert set(out.keys()) == set(CLASS_SUMMARY_FIELDS)

    def test_does_not_mutate_input(self) -> None:
        full = {"_key": "c1", "label": "Foo", "evidence": [1, 2, 3]}
        before = dict(full)
        summarize_class(full)
        assert full == before


class TestSummarizeEdge:
    def test_drops_evidence(self) -> None:
        full = {
            "_key": "e1",
            "_id": "rdfs_domain/e1",
            "_from": "ontology_classes/c1",
            "_to": "ontology_classes/c2",
            "_rev": "_rev_token",
            "edge_type": "rdfs_domain",
            "confidence": 0.85,
            "evidence": [{"text": "a" * 2000}],
            "embedding": [0.1] * 768,
        }
        out = summarize_edge(full)
        assert "evidence" not in out
        assert "embedding" not in out
        assert "_rev" not in out

    def test_preserves_topology_and_confidence(self) -> None:
        full = {
            "_key": "e1",
            "_id": "rdfs_domain/e1",
            "_from": "ontology_classes/c1",
            "_to": "ontology_classes/c2",
            "edge_type": "rdfs_domain",
            "confidence": 0.85,
            "label": "has",
            "evidence": ["dropped"],
        }
        out = summarize_edge(full)
        assert out["_from"] == "ontology_classes/c1"
        assert out["_to"] == "ontology_classes/c2"
        assert out["confidence"] == 0.85
        assert out["edge_type"] == "rdfs_domain"
        assert out["label"] == "has"

    def test_returns_exactly_the_allow_list_keys(self) -> None:
        full = {name: f"value-{name}" for name in EDGE_SUMMARY_FIELDS}
        full["evidence"] = ["should be dropped"]
        out = summarize_edge(full)
        assert set(out.keys()) == set(EDGE_SUMMARY_FIELDS)


# ---------------------------------------------------------------------------
# normalize_include() -- query parameter parsing.
# ---------------------------------------------------------------------------


class TestNormalizeInclude:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("full", INCLUDE_FULL),
            ("summary", INCLUDE_SUMMARY),
            ("FULL", INCLUDE_FULL),
            ("Summary", INCLUDE_SUMMARY),
            ("  summary  ", INCLUDE_SUMMARY),
        ],
    )
    def test_valid_values_normalised(self, raw: str, expected: str) -> None:
        assert normalize_include(raw) == expected

    def test_none_defaults_to_full(self) -> None:
        # Backwards compatibility -- callers that don't pass ?include= must
        # see the legacy full payload.
        assert normalize_include(None) == INCLUDE_FULL

    def test_unknown_value_falls_back_to_full(self) -> None:
        # Defensive: a typo'd ?include=summery shouldn't break the request.
        assert normalize_include("summery") == INCLUDE_FULL
        assert normalize_include("") == INCLUDE_FULL

    def test_valid_include_values_constant_matches_helpers(self) -> None:
        # Sanity check that the public constant lists exactly the values
        # normalize_include() will accept.
        assert frozenset({INCLUDE_FULL, INCLUDE_SUMMARY}) == VALID_INCLUDE_VALUES
