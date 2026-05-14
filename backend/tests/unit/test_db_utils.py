"""Unit tests for ``app.db.utils``.

The headline coverage here is :func:`insert_temporal_edge_if_absent`,
the helper that closes the duplicate-rdfs_domain-edge bug surfaced
by the workspace ``FloatingDetailPanel`` (commit d7442d2 fixed the
read-side dedup; this helper closes the write-side leak).

Pattern: MagicMock collection + ``run_aql`` patched per-test to
return either an empty cursor (no live edge -> insert) or a single
``1`` row (live edge already present -> skip).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from app.db import utils
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import insert_temporal_edge_if_absent


def _patch_run_aql(monkeypatch, rows: list[Any]) -> dict[str, Any]:
    """Patch ``run_aql`` to return ``rows`` and capture the last call."""
    captured: dict[str, Any] = {"query": None, "bind_vars": None, "calls": 0}

    def fake(_db, query, bind_vars=None, **_kw):
        captured["query"] = query
        captured["bind_vars"] = bind_vars
        captured["calls"] += 1
        return iter(rows)

    monkeypatch.setattr(utils, "run_aql", fake)
    return captured


def _mock_collection(name: str = "rdfs_domain") -> MagicMock:
    col = MagicMock()
    col.name = name
    return col


class TestInsertTemporalEdgeIfAbsent:
    def test_inserts_when_no_live_edge_exists(self, monkeypatch):
        col = _mock_collection()
        captured = _patch_run_aql(monkeypatch, rows=[])

        inserted = insert_temporal_edge_if_absent(
            db=MagicMock(),
            collection=col,
            from_id="ontology_object_properties/p1",
            to_id="ontology_classes/c1",
            ontology_id="ont-1",
            now=1700000000.0,
        )

        assert inserted is True
        col.insert.assert_called_once()
        doc = col.insert.call_args[0][0]
        assert doc == {
            "_from": "ontology_object_properties/p1",
            "_to": "ontology_classes/c1",
            "ontology_id": "ont-1",
            "created": 1700000000.0,
            "expired": NEVER_EXPIRES,
        }
        # The probe AQL must scope by all three: from, to, ontology_id.
        # Missing any of these would let the helper insert a duplicate
        # for an unrelated ontology that happens to share endpoints.
        assert "e._from == @f" in captured["query"]
        assert "e._to == @t" in captured["query"]
        assert "e.ontology_id == @oid" in captured["query"]
        assert "e.expired == @never" in captured["query"]
        assert captured["bind_vars"] == {
            "f": "ontology_object_properties/p1",
            "t": "ontology_classes/c1",
            "oid": "ont-1",
            "never": NEVER_EXPIRES,
        }

    def test_skips_when_live_edge_already_exists(self, monkeypatch):
        col = _mock_collection()
        # Probe returns a row -> live edge exists -> no insert.
        _patch_run_aql(monkeypatch, rows=[1])

        inserted = insert_temporal_edge_if_absent(
            db=MagicMock(),
            collection=col,
            from_id="ontology_object_properties/p1",
            to_id="ontology_classes/c1",
            ontology_id="ont-1",
            now=1700000000.0,
        )

        assert inserted is False
        col.insert.assert_not_called()

    def test_uses_collection_name_in_aql(self, monkeypatch):
        """The probe must query the SAME collection the caller wants
        to insert into -- not a hardcoded collection name. A typo
        here would make the helper "idempotent" against the wrong
        collection (always insert)."""
        captured = _patch_run_aql(monkeypatch, rows=[])
        col = _mock_collection(name="rdfs_range_class")

        insert_temporal_edge_if_absent(
            db=MagicMock(),
            collection=col,
            from_id="x/1",
            to_id="y/2",
            ontology_id="ont-1",
            now=1.0,
        )

        assert "FOR e IN rdfs_range_class" in captured["query"]

    def test_extra_fields_are_merged_into_inserted_edge(self, monkeypatch):
        col = _mock_collection()
        _patch_run_aql(monkeypatch, rows=[])

        insert_temporal_edge_if_absent(
            db=MagicMock(),
            collection=col,
            from_id="x/1",
            to_id="y/2",
            ontology_id="ont-1",
            now=1.0,
            extra_fields={"evidence": ["e1"], "weight": 0.9},
        )

        doc = col.insert.call_args[0][0]
        assert doc["evidence"] == ["e1"]
        assert doc["weight"] == 0.9
        # Canonical fields must remain untouched even if extra_fields
        # tries to override them (defensive: a caller can't accidentally
        # bypass the never-expires invariant by passing expired=...).
        assert doc["expired"] == NEVER_EXPIRES

    def test_extra_fields_cannot_override_canonical_fields(self, monkeypatch):
        """If a caller passes ``extra_fields={"expired": <something>}``
        the canonical NEVER_EXPIRES wins -- otherwise the helper's
        idempotency contract (probe matches on ``expired==@never``)
        would silently break for that edge."""
        col = _mock_collection()
        _patch_run_aql(monkeypatch, rows=[])

        insert_temporal_edge_if_absent(
            db=MagicMock(),
            collection=col,
            from_id="x/1",
            to_id="y/2",
            ontology_id="ont-1",
            now=42.0,
            extra_fields={
                "expired": 1234.0,  # malicious / mistaken
                "created": 0.0,  # malicious / mistaken
                "_from": "wrong/0",  # malicious / mistaken
                "extra": "kept",
            },
        )

        doc = col.insert.call_args[0][0]
        # Canonical fields preserved.
        assert doc["expired"] == NEVER_EXPIRES
        assert doc["created"] == 42.0
        assert doc["_from"] == "x/1"
        # Genuinely-new field still merged.
        assert doc["extra"] == "kept"

    def test_no_extra_fields_yields_minimal_canonical_doc(self, monkeypatch):
        col = _mock_collection()
        _patch_run_aql(monkeypatch, rows=[])

        insert_temporal_edge_if_absent(
            db=MagicMock(),
            collection=col,
            from_id="x/1",
            to_id="y/2",
            ontology_id="ont-1",
            now=1.0,
        )

        doc = col.insert.call_args[0][0]
        assert set(doc.keys()) == {
            "_from",
            "_to",
            "ontology_id",
            "created",
            "expired",
        }

    def test_idempotent_under_repeated_calls(self, monkeypatch):
        """Simulate a re-extraction: first call inserts, second call
        sees the live edge (mocked) and skips. This is the core
        contract that fixes the WTW duplicate-edge bug."""
        col = _mock_collection()
        # First probe: no live edge. Second probe: live edge present.
        # We model this by making run_aql alternate via a stateful
        # closure -- the iterator from the FIRST call is consumed by
        # the helper before the SECOND call patches it again.
        states = iter([[], [1]])

        def fake_run_aql(_db, _q, bind_vars=None, **_kw):
            return iter(next(states))

        monkeypatch.setattr(utils, "run_aql", fake_run_aql)

        first = insert_temporal_edge_if_absent(
            db=MagicMock(),
            collection=col,
            from_id="x/1",
            to_id="y/2",
            ontology_id="ont-1",
            now=1.0,
        )
        second = insert_temporal_edge_if_absent(
            db=MagicMock(),
            collection=col,
            from_id="x/1",
            to_id="y/2",
            ontology_id="ont-1",
            now=2.0,
        )

        assert first is True
        assert second is False
        # Exactly one insert across two calls.
        assert col.insert.call_count == 1

    def test_probe_limits_to_one_row_for_efficiency(self, monkeypatch):
        """``LIMIT 1`` matters: scanning every duplicate just to
        check existence would be wasteful on a class with many
        attributes. Lock the optimisation in a test so a future
        refactor can't silently drop it."""
        captured = _patch_run_aql(monkeypatch, rows=[])

        insert_temporal_edge_if_absent(
            db=MagicMock(),
            collection=_mock_collection(),
            from_id="x/1",
            to_id="y/2",
            ontology_id="ont-1",
            now=1.0,
        )

        assert "LIMIT 1" in captured["query"]
