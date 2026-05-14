"""Unit tests for ``app.services.edge_dedup``.

Covers the contract that ``dedupe_live_edges``:

  * refuses unknown collections (allowlist gate),
  * gracefully handles a missing collection,
  * keeps the smallest-``created`` edge per duplicate pair,
  * stamps expired edges with the ``dedup_meta`` audit marker,
  * is idempotent (a second non-dry-run is a no-op),
  * never mutates anything in dry-run mode.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from app.db.temporal_constants import NEVER_EXPIRES
from app.services import edge_dedup
from app.services.edge_dedup import (
    DEDUP_SOURCE_MARKER,
    DEDUPABLE_COLLECTIONS,
    DedupReport,
    dedupe_live_edges,
)


def _db_with_collections(*present: str) -> MagicMock:
    db = MagicMock()
    db.has_collection.side_effect = lambda name: name in present
    return db


def _patch_run_aql(monkeypatch, responses: list[Any]) -> dict[str, Any]:
    """Patch ``run_aql`` to return the next response in sequence and
    record every call.

    Each entry in ``responses`` may be a list (treated as the rows of
    the next cursor) or any object (returned as-is for the UPDATE
    statement which doesn't iterate).
    """
    captured: dict[str, Any] = {"calls": [], "n": 0}
    iter_responses = iter(responses)

    def fake(_db, query, bind_vars=None, **_kw):
        captured["calls"].append({"query": query, "bind_vars": bind_vars})
        captured["n"] += 1
        try:
            nxt = next(iter_responses)
        except StopIteration:
            return iter([])
        if isinstance(nxt, list):
            return iter(nxt)
        return nxt

    monkeypatch.setattr(edge_dedup, "run_aql", fake)
    return captured


class TestAllowlistGate:
    def test_unknown_collection_raises_value_error(self):
        db = _db_with_collections("foo")
        with pytest.raises(ValueError, match="not in the dedup allowlist"):
            dedupe_live_edges(db, "ont-1", "foo")

    def test_dedupable_collections_set_does_not_include_subclass_of(self):
        # Locking this in so a future contributor can't silently add
        # subclass_of (which carries per-edge evidence) without
        # solving the evidence-merge problem first.
        assert "subclass_of" not in DEDUPABLE_COLLECTIONS
        # And to make sure the gate has at least the two collections
        # the duplicate-edge bug actually produced in the wild:
        assert "rdfs_domain" in DEDUPABLE_COLLECTIONS
        assert "rdfs_range_class" in DEDUPABLE_COLLECTIONS


class TestMissingCollection:
    def test_returns_skipped_report_when_collection_missing(self, monkeypatch):
        db = _db_with_collections()  # no collections present

        # Patch run_aql so a stray call would surface as an
        # AssertionError rather than silently noop.
        def boom(*_a, **_kw):
            raise AssertionError("run_aql must not be invoked when the collection is missing")

        monkeypatch.setattr(edge_dedup, "run_aql", boom)

        report = dedupe_live_edges(db, "ont-1", "rdfs_domain")
        assert isinstance(report, DedupReport)
        assert report.skipped_collection_missing is True
        assert report.pairs_with_duplicates == 0
        assert report.extra_edges == 0
        assert report.deduped == []


class TestDryRunPreview:
    def test_returns_pair_breakdown_without_writing(self, monkeypatch):
        db = _db_with_collections("rdfs_domain")
        groups = [
            {
                "pair": "ontology_object_properties/A|ontology_classes/X",
                # AQL sorts by created ASC then _key ASC inside the
                # query, so the first element is the kept edge.
                "edges": [
                    {"_key": "edge_old", "created": 100.0},
                    {"_key": "edge_new", "created": 200.0},
                ],
            },
            {
                "pair": "ontology_object_properties/B|ontology_classes/Y",
                "edges": [
                    {"_key": "edge_b1", "created": 50.0},
                    {"_key": "edge_b2", "created": 60.0},
                    {"_key": "edge_b3", "created": 70.0},
                ],
            },
        ]
        captured = _patch_run_aql(monkeypatch, [groups])

        report = dedupe_live_edges(db, "ont-1", "rdfs_domain", dry_run=True)

        # No UPDATE statement should have been issued.
        assert captured["n"] == 1
        update_calls = [c for c in captured["calls"] if "UPDATE" in c["query"]]
        assert update_calls == []

        assert report.dry_run is True
        assert report.pairs_with_duplicates == 2
        assert report.extra_edges == 1 + 2  # one per pair beyond the keeper

        # First duplicate group: edge_old is kept (smaller created),
        # edge_new is queued for expiration.
        assert report.deduped[0].kept_key == "edge_old"
        assert report.deduped[0].expired_keys == ["edge_new"]
        # Three-way group: keep edge_b1, expire edge_b2 + edge_b3.
        assert report.deduped[1].kept_key == "edge_b1"
        assert report.deduped[1].expired_keys == ["edge_b2", "edge_b3"]

    def test_query_filters_by_ontology_and_never_expires(self, monkeypatch):
        """Lock in the AQL invariants -- the probe MUST scope by
        ontology_id and MUST exclude already-expired edges, otherwise
        we'd consider edges from other ontologies and re-expire
        already-expired edges (silly, but observable in the report)."""
        db = _db_with_collections("rdfs_domain")
        captured = _patch_run_aql(monkeypatch, [[]])

        dedupe_live_edges(db, "ont-1", "rdfs_domain")

        q = captured["calls"][0]["query"]
        assert "FOR e IN rdfs_domain" in q
        assert "e.ontology_id == @oid" in q
        assert "e.expired == @never" in q
        assert "LENGTH(group) > 1" in q
        bind = captured["calls"][0]["bind_vars"]
        assert bind == {"oid": "ont-1", "never": NEVER_EXPIRES}


class TestApplyExpiresDuplicates:
    def test_apply_issues_update_and_stamps_dedup_meta(self, monkeypatch):
        db = _db_with_collections("rdfs_domain")
        groups = [
            {
                "pair": "p|q",
                "edges": [
                    {"_key": "keep_me", "created": 100.0},
                    {"_key": "expire_me", "created": 200.0},
                ],
            }
        ]
        # Fixed clock so the test asserts an exact ``expired`` value.
        monkeypatch.setattr(edge_dedup.time, "time", lambda: 9999.0)
        captured = _patch_run_aql(monkeypatch, [groups, MagicMock()])

        report = dedupe_live_edges(db, "ont-1", "rdfs_domain", dry_run=False)

        # Two AQL calls: one SELECT (groups), one UPDATE.
        assert captured["n"] == 2
        update_call = captured["calls"][1]
        assert "UPDATE" in update_call["query"]
        assert "dedup_meta" in update_call["query"]
        # Bind vars must carry the exact set of expired keys + the
        # marker so the audit can find these edges later.
        assert update_call["bind_vars"]["keys"] == ["expire_me"]
        assert update_call["bind_vars"]["now"] == 9999.0
        assert update_call["bind_vars"]["marker"] == DEDUP_SOURCE_MARKER

        assert report.dry_run is False
        assert report.pairs_with_duplicates == 1
        assert report.extra_edges == 1
        assert report.deduped[0].kept_key == "keep_me"
        assert report.deduped[0].expired_keys == ["expire_me"]

    def test_apply_with_zero_duplicates_skips_update(self, monkeypatch):
        """The expensive UPDATE statement must NOT fire when there's
        nothing to expire -- a no-op apply on a clean ontology should
        cost exactly one cheap COLLECT pass."""
        db = _db_with_collections("rdfs_domain")
        captured = _patch_run_aql(monkeypatch, [[]])

        report = dedupe_live_edges(db, "ont-1", "rdfs_domain", dry_run=False)

        assert captured["n"] == 1  # only the SELECT, no UPDATE
        assert report.pairs_with_duplicates == 0
        assert report.extra_edges == 0
        assert report.deduped == []


class TestIdempotency:
    def test_second_apply_is_a_noop(self, monkeypatch):
        """The second non-dry-run pass against the same data must
        find zero duplicates (the first pass expired them all) and
        issue no UPDATE."""
        db = _db_with_collections("rdfs_domain")
        groups_first = [
            {
                "pair": "p|q",
                "edges": [
                    {"_key": "keep", "created": 100.0},
                    {"_key": "extra", "created": 200.0},
                ],
            }
        ]
        # Sequence: first call's SELECT -> first call's UPDATE ->
        # second call's SELECT (returns []) -- no second UPDATE.
        captured = _patch_run_aql(monkeypatch, [groups_first, MagicMock(), []])

        first = dedupe_live_edges(db, "ont-1", "rdfs_domain", dry_run=False)
        second = dedupe_live_edges(db, "ont-1", "rdfs_domain", dry_run=False)

        assert first.extra_edges == 1
        assert second.extra_edges == 0
        assert second.deduped == []
        assert captured["n"] == 3  # two SELECTs + one UPDATE


class TestReportShape:
    def test_to_dict_round_trip(self, monkeypatch):
        db = _db_with_collections("rdfs_domain")
        _patch_run_aql(
            monkeypatch,
            [
                [
                    {
                        "pair": "p|q",
                        "edges": [
                            {"_key": "k", "created": 1.0},
                            {"_key": "x", "created": 2.0},
                        ],
                    }
                ]
            ],
        )

        report = dedupe_live_edges(db, "ont-1", "rdfs_domain")
        d = report.to_dict()

        assert d["ontology_id"] == "ont-1"
        assert d["collection"] == "rdfs_domain"
        assert d["dry_run"] is True
        assert d["pairs_with_duplicates"] == 1
        assert d["extra_edges"] == 1
        assert d["skipped_collection_missing"] is False
        assert d["deduped"] == [
            {
                "pair": "p|q",
                "kept_key": "k",
                "expired_keys": ["x"],
            }
        ]
