"""Unit tests for the CQ coverage-gap backlog repository (Stream 22 / CQ-PR6)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.db import cq_gap_repo as repo


class TestGapKey:
    def test_deterministic_and_ontology_scoped(self) -> None:
        k1 = repo.gap_key("o1", "Who supplies part X?")
        assert k1 == repo.gap_key("o1", "Who supplies part X?")  # stable
        assert k1 != repo.gap_key("o2", "Who supplies part X?")  # scoped by ontology
        assert k1 != repo.gap_key("o1", "Different question?")


class TestUpsertGap:
    def test_inserts_new_open_gap(self) -> None:
        db = MagicMock()
        col = MagicMock()
        col.get.return_value = None
        db.collection.return_value = col
        newly = repo.upsert_gap(
            db,
            ontology_id="o1",
            cq_text="q",
            use_case="UC",
            priority="high",
            gap_kind="unanswerable",
            now=123.0,
        )
        assert newly is True
        doc = col.insert.call_args.args[0]
        assert doc["status"] == repo.STATUS_OPEN
        assert doc["gap_kind"] == "unanswerable"
        assert doc["created"] == 123.0

    def test_reopen_resolved_returns_true(self) -> None:
        db = MagicMock()
        col = MagicMock()
        col.get.return_value = {"_key": "k", "status": repo.STATUS_RESOLVED}
        db.collection.return_value = col
        newly = repo.upsert_gap(
            db,
            ontology_id="o1",
            cq_text="q",
            use_case="UC",
            priority="high",
            gap_kind="unanswerable",
            now=200.0,
        )
        assert newly is True  # was resolved -> re-opened counts as newly open
        upd = col.update.call_args.args[0]
        assert upd["status"] == repo.STATUS_OPEN
        assert upd["resolved_at"] is None

    def test_still_open_returns_false(self) -> None:
        db = MagicMock()
        col = MagicMock()
        col.get.return_value = {"_key": "k", "status": repo.STATUS_OPEN}
        db.collection.return_value = col
        newly = repo.upsert_gap(
            db,
            ontology_id="o1",
            cq_text="q",
            use_case="UC",
            priority="high",
            gap_kind="unanswerable",
        )
        assert newly is False  # already open, not newly opened


class TestResolveAndList:
    def test_resolve_gaps_not_in_counts_rows(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        with patch.object(repo, "run_aql", return_value=iter([1, 1, 1])):
            n = repo.resolve_gaps_not_in(db, "o1", {"keepme"}, now=1.0)
        assert n == 3

    def test_resolve_missing_collection_is_zero(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        assert repo.resolve_gaps_not_in(db, "o1", set()) == 0

    def test_list_gaps_default_open(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [{"_key": "k1"}, {"_key": "k2"}]
        with patch.object(repo, "run_aql", return_value=iter(rows)) as mk:
            out = repo.list_gaps(db, "o1")
        assert out == rows
        assert mk.call_args.kwargs["bind_vars"]["status"] == repo.STATUS_OPEN
