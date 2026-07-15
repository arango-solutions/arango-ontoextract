"""Unit tests for the alignment service (Stream 20 / AL-PR1 + AL-PR2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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


class TestVerdictHelpers:
    def test_type_from_verdict(self) -> None:
        assert al._type_from_verdict("subclass", "x") == "rdfs:subClassOf"
        assert al._type_from_verdict("superclass", "x") == "rdfs:subClassOf"
        assert al._type_from_verdict("equivalent", "x") == "owl:equivalentClass"
        assert al._type_from_verdict("related", "x") == "skos:relatedMatch"
        assert al._type_from_verdict("none", "fallback") == "fallback"

    def test_recommendation(self) -> None:
        assert al._recommendation("equivalent", 0.9) == "accept"
        assert al._recommendation("subclass", 0.5) == "accept"
        assert al._recommendation("subclass", 0.3) == "review"
        assert al._recommendation("none", 0.9) == "reject"
        assert al._recommendation("related", 0.9) == "review"

    def test_parse_verdict_code_fenced_and_clamped(self) -> None:
        fenced = '```json\n{"verdict":"related","confidence":2,"rationale":"x"}\n```'
        out = al._parse_verdict(fenced)
        assert out["verdict"] == "related"
        assert out["confidence"] == 1.0  # clamped

    def test_parse_verdict_invalid_returns_uncertain(self) -> None:
        assert al._parse_verdict("no json here")["verdict"] == "uncertain"
        assert al._parse_verdict('{"verdict":"bogus","confidence":0.5}')["verdict"] == "uncertain"


class TestAdjudicateCandidate:
    async def test_parses_llm_verdict(self) -> None:
        llm = MagicMock()
        llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content='{"verdict":"equivalent","confidence":0.9,"rationale":"same concept"}'
            )
        )
        with patch.object(al, "_get_llm", return_value=llm):
            out = await al.adjudicate_candidate("Account", "Compte", {"combined": 0.7})
        assert out["verdict"] == "equivalent"
        assert out["confidence"] == 0.9

    async def test_fallback_to_uncertain_on_llm_error(self) -> None:
        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(al, "_get_llm", return_value=llm):
            out = await al.adjudicate_candidate("A", "B", {})
        assert out["verdict"] == "uncertain"
        assert out["confidence"] == 0.0


class TestAdjudicateSession:
    async def test_auto_accepts_high_and_llm_only_for_borderline(self) -> None:
        db = MagicMock()
        cands = [
            {
                "_key": "c1",
                "confidence": 0.95,
                "type": "owl:equivalentClass",
                "source_a": {"label": "Account"},
                "source_b": {"label": "Account"},
                "scores": {"combined": 0.95},
            },
            {
                "_key": "c2",
                "confidence": 0.6,
                "type": "skos:relatedMatch",
                "source_a": {"label": "Client"},
                "source_b": {"label": "Customer"},
                "scores": {"combined": 0.6},
            },
        ]
        with (
            patch.object(al.alignment_repo, "list_correspondences", return_value=cands),
            patch.object(
                al,
                "adjudicate_candidate",
                new=AsyncMock(
                    return_value={"verdict": "subclass", "confidence": 0.8, "rationale": "r"}
                ),
            ) as adj,
            patch.object(al.alignment_repo, "set_correspondence_adjudication") as setadj,
        ):
            out = await al.adjudicate_session(db, session_id="S1", auto_accept_band=0.92)

        assert out == {"session_id": "S1", "adjudicated": 2, "llm_calls": 1}
        adj.assert_awaited_once()  # only the borderline c2 hit the LLM
        # c1 auto-accepted via score; c2 llm-adjudicated to rdfs:subClassOf
        by_key = {call.args[1]: call for call in setadj.call_args_list}
        assert by_key["c1"].args[2]["method"] == "score"
        assert by_key["c1"].args[2]["recommendation"] == "accept"
        assert by_key["c2"].args[2]["method"] == "llm"
        assert by_key["c2"].kwargs["correspondence_type"] == "rdfs:subClassOf"
