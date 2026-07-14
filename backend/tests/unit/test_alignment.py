"""Unit tests for the alignment service (Stream 20 / AL-PR1 + AL-PR2)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import alignment as al


def _class(key: str, oid: str, label: str, desc: str = "", uri: str = "") -> dict:
    return {"_key": key, "ontology_id": oid, "label": label, "description": desc, "uri": uri}


class TestGenerateCandidates:
    def test_requires_two_distinct_sources(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        assert al.generate_candidates(db, source_ontology_ids=["a"]) == []
        assert al.generate_candidates(db, source_ontology_ids=["a", "a"]) == []

    def test_pairs_only_across_sources_and_filters_by_min_score(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [
            _class("A1", "ontA", "Account", "a bank account"),
            _class("A2", "ontA", "Widget", "a gadget"),
            _class("B1", "ontB", "Account", "a bank account"),  # exact match to A1
            _class("B2", "ontB", "Zebra", "an animal"),
        ]
        with patch.object(al, "run_aql", return_value=iter(rows)):
            cands = al.generate_candidates(db, source_ontology_ids=["ontA", "ontB"], min_score=0.6)
        # A1<->B1 is a strong match; A2/B2 pairs fall below threshold.
        assert len(cands) == 1
        c = cands[0]
        assert {c["source_a"]["ontology_id"], c["source_b"]["ontology_id"]} == {"ontA", "ontB"}
        assert {c["source_a"]["entity_key"], c["source_b"]["entity_key"]} == {"A1", "B1"}
        assert c["confidence"] >= 0.6
        assert c["type"] == "owl:equivalentClass"  # combined >= 0.9 band
        assert c["status"] == "candidate"

    def test_sorted_by_confidence_desc(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [
            _class("A1", "ontA", "Account", "bank account"),
            _class("B1", "ontB", "Account", "bank account"),  # ~1.0
            _class("B2", "ontB", "Accounts", "bank accounts"),  # slightly lower
        ]
        with patch.object(al, "run_aql", return_value=iter(rows)):
            cands = al.generate_candidates(db, source_ontology_ids=["ontA", "ontB"], min_score=0.5)
        confidences = [c["confidence"] for c in cands]
        assert confidences == sorted(confidences, reverse=True)

    def test_uri_equality_forces_equivalent_type(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [
            _class("A1", "ontA", "Acct", "x", uri="http://ex/Account"),
            _class("B1", "ontB", "Compte", "y", uri="http://ex/Account"),
        ]
        with patch.object(al, "run_aql", return_value=iter(rows)):
            cands = al.generate_candidates(db, source_ontology_ids=["ontA", "ontB"], min_score=0.0)
        assert cands and cands[0]["type"] == "owl:equivalentClass"


class TestCreateAlignmentSession:
    def test_rejects_fewer_than_two_sources(self) -> None:
        db = MagicMock()
        with pytest.raises(ValueError, match="at least 2"):
            al.create_alignment_session(db, source_ontology_ids=["only"])

    def test_creates_session_generates_and_persists(self) -> None:
        db = MagicMock()
        session = {"_key": "S1", "_id": "alignment_sessions/S1", "source_ontology_ids": ["a", "b"]}
        with (
            patch.object(al.alignment_repo, "create_session", return_value=session) as mk,
            patch.object(
                al, "generate_candidates", return_value=[{"confidence": 0.9}, {"confidence": 0.7}]
            ),
            patch.object(al.alignment_repo, "save_correspondences", return_value=2) as save,
        ):
            out = al.create_alignment_session(db, source_ontology_ids=["a", "b"], min_score=0.5)
        mk.assert_called_once()
        save.assert_called_once()
        assert out["candidate_count"] == 2
        assert out["_key"] == "S1"


class TestSetCandidateStatus:
    def test_rejects_invalid_status(self) -> None:
        db = MagicMock()
        with pytest.raises(ValueError, match="invalid correspondence status"):
            al.set_candidate_status(db, "c1", "bogus")
