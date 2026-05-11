"""Unit tests for :mod:`app.db.temporal_revisions_repo` (Stream 11 IBR.9).

Mocks the underlying temporal helpers and ``record_revision`` to verify
the supersede dispatch table, idempotency contract, audit-record
contract, and convenience adapters. No live ArangoDB required.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.db.revision_meta_repo import (
    ACTION_FLAG_FOR_CURATION,
    ACTION_GAP_FILL,
    ACTION_REINFORCE,
    ACTION_RETRACT,
    ACTION_REVISE,
    AGENT_LLM,
    AGENT_MECHANICAL,
    STATUS_APPLIED,
    STATUS_PENDING,
    VERDICT_CONTRADICTED,
    VERDICT_GAP_FILLING,
    VERDICT_REINFORCED,
    VERDICT_UNCERTAIN,
)
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.temporal_revisions_repo import (
    SupersedeResult,
    _find_existing_revision,
    _split_id,
    supersede,
    supersede_from_llm_proposal,
    supersede_from_mechanical_revision,
)

# ---------------------------------------------------------------------------
# Mock-DB factory
# ---------------------------------------------------------------------------


def _mock_db(
    *,
    has_revision_meta: bool = True,
    prior_revisions: list[dict[str, Any]] | None = None,
    has_edge_collection: bool = True,
) -> tuple[MagicMock, MagicMock, MagicMock]:
    """Build a mock ``StandardDatabase`` with controllable behaviour.

    Returns ``(db, vertex_collection, edge_collection)``.
    """
    db = MagicMock()
    db.has_collection.side_effect = lambda name: (
        (name == "revision_meta" and has_revision_meta)
        or (name != "revision_meta" and has_edge_collection)
    )

    vertex_col = MagicMock()
    edge_col = MagicMock()

    def _collection(name: str) -> MagicMock:
        if name.startswith("ontology_") and "edges" not in name and "subclass" not in name:
            return vertex_col
        if "subclass" in name or "_edges" in name or name.endswith("_to"):
            return edge_col
        return vertex_col

    db.collection.side_effect = _collection

    return db, vertex_col, edge_col


def _patch_run_aql(prior_revisions: list[dict[str, Any]] | None):
    """Patch ``run_aql`` in the module under test to return canned rows."""
    return patch(
        "app.db.temporal_revisions_repo.run_aql",
        return_value=prior_revisions or [],
    )


# ---------------------------------------------------------------------------
# _split_id
# ---------------------------------------------------------------------------


class TestSplitId:
    def test_valid_id_splits(self) -> None:
        assert _split_id("ontology_classes/abc123") == ("ontology_classes", "abc123")

    def test_id_with_extra_slash_keeps_key(self) -> None:
        assert _split_id("col/key/with/slashes") == ("col", "key/with/slashes")

    @pytest.mark.parametrize("bad", ["", "no-slash", "/missing-col", "col/"])
    def test_invalid_id_raises(self, bad: str) -> None:
        with pytest.raises(ValueError):
            _split_id(bad)


# ---------------------------------------------------------------------------
# Idempotency probe
# ---------------------------------------------------------------------------


class TestFindExistingRevision:
    def test_no_revision_meta_collection_returns_none(self) -> None:
        db, *_ = _mock_db(has_revision_meta=False)
        with _patch_run_aql([]):
            assert (
                _find_existing_revision(
                    db,
                    triggering_doc_id="doc1",
                    existing_entity_id="ontology_classes/k",
                    action=ACTION_REINFORCE,
                )
                is None
            )

    def test_no_prior_returns_none(self) -> None:
        db, *_ = _mock_db()
        with _patch_run_aql([]):
            assert (
                _find_existing_revision(
                    db,
                    triggering_doc_id="doc1",
                    existing_entity_id="ontology_classes/k",
                    action=ACTION_REINFORCE,
                )
                is None
            )

    def test_prior_returns_doc(self) -> None:
        db, *_ = _mock_db()
        prior = {"_key": "rev1", "status": STATUS_APPLIED}
        with _patch_run_aql([prior]):
            assert (
                _find_existing_revision(
                    db,
                    triggering_doc_id="doc1",
                    existing_entity_id="ontology_classes/k",
                    action=ACTION_REINFORCE,
                )
                == prior
            )


# ---------------------------------------------------------------------------
# Idempotency in supersede
# ---------------------------------------------------------------------------


class TestSupersedeIdempotency:
    def test_idempotency_hit_returns_skipped_result_without_mutating(self) -> None:
        db, vertex, _ = _mock_db()
        prior = {
            "_key": "rev_existing",
            "status": STATUS_APPLIED,
            "new_version": "v2",
            "existing_version": "v1",
        }
        with _patch_run_aql([prior]), patch(
            "app.db.temporal_revisions_repo.record_revision"
        ) as record:
            result = supersede(
                ontology_id="ont1",
                existing_entity_id="ontology_classes/k1",
                verdict=VERDICT_REINFORCED,
                action=ACTION_REINFORCE,
                agent_type=AGENT_MECHANICAL,
                agent_version="v0.1",
                triggering_doc_id="doc1",
                db=db,
            )
        assert result.skipped is True
        assert result.revision_meta_key == "rev_existing"
        assert result.status == STATUS_APPLIED
        assert result.new_version_key == "v2"
        assert result.expired_version_key == "v1"
        record.assert_not_called()
        vertex.update.assert_not_called()
        vertex.insert.assert_not_called()

    def test_skip_idempotency_forces_application(self) -> None:
        db, vertex, _ = _mock_db()
        prior = {"_key": "rev_existing", "status": STATUS_APPLIED}
        vertex.update.return_value = {
            "new": {
                "_key": "k1",
                "evidence_count": 1,
                "current_confidence": 0.8,
            }
        }
        with patch(
            "app.db.temporal_revisions_repo.temporal.get_current",
            return_value={"_key": "k1", "evidence": []},
        ), _patch_run_aql([prior]), patch(
            "app.db.temporal_revisions_repo.record_revision",
            return_value={"_key": "rev_new", "status": STATUS_APPLIED},
        ):
            result = supersede(
                ontology_id="ont1",
                existing_entity_id="ontology_classes/k1",
                verdict=VERDICT_REINFORCED,
                action=ACTION_REINFORCE,
                agent_type=AGENT_MECHANICAL,
                agent_version="v0.1",
                triggering_doc_id="doc1",
                evidence_quotes=["quote A"],
                confidence_after=0.8,
                skip_idempotency=True,
                db=db,
            )
        assert result.skipped is False
        assert result.revision_meta_key == "rev_new"
        vertex.update.assert_called_once()


# ---------------------------------------------------------------------------
# REINFORCE
# ---------------------------------------------------------------------------


class TestSupersedeReinforce:
    def test_reinforce_appends_evidence_and_updates_confidence(self) -> None:
        db, vertex, _ = _mock_db()
        vertex.update.return_value = {
            "new": {
                "_key": "k1",
                "evidence_count": 2,
                "current_confidence": 0.85,
            }
        }
        with patch(
            "app.db.temporal_revisions_repo.temporal.get_current",
            return_value={"_key": "k1", "evidence": ["existing quote"]},
        ), _patch_run_aql([]), patch(
            "app.db.temporal_revisions_repo.record_revision",
            return_value={"_key": "rev_r1", "status": STATUS_APPLIED},
        ) as record:
            result = supersede(
                ontology_id="ont1",
                existing_entity_id="ontology_classes/k1",
                verdict=VERDICT_REINFORCED,
                action=ACTION_REINFORCE,
                agent_type=AGENT_LLM,
                agent_version="gpt-x@p1",
                triggering_doc_id="doc1",
                evidence_quotes=["new quote"],
                confidence_before=0.7,
                confidence_after=0.85,
                db=db,
            )
        update_args = vertex.update.call_args[0][0]
        assert update_args["_key"] == "k1"
        assert update_args["evidence"] == ["existing quote", "new quote"]
        assert update_args["evidence_count"] == 2
        assert update_args["current_confidence"] == 0.85
        assert "last_evidenced_at" in update_args
        assert result.action == ACTION_REINFORCE
        assert result.new_version_key == "k1"
        assert result.expired_version_key is None
        assert result.extra["evidence_count_after"] == 2
        record.assert_called_once()

    def test_reinforce_without_confidence_after_does_not_set_field(self) -> None:
        db, vertex, _ = _mock_db()
        vertex.update.return_value = {"new": {"_key": "k1", "evidence_count": 1}}
        with patch(
            "app.db.temporal_revisions_repo.temporal.get_current",
            return_value={"_key": "k1", "evidence": []},
        ), _patch_run_aql([]), patch(
            "app.db.temporal_revisions_repo.record_revision",
            return_value={"_key": "rev_r1", "status": STATUS_APPLIED},
        ):
            supersede(
                ontology_id="ont1",
                existing_entity_id="ontology_classes/k1",
                verdict=VERDICT_REINFORCED,
                action=ACTION_REINFORCE,
                agent_type=AGENT_LLM,
                agent_version="v",
                triggering_doc_id="doc1",
                evidence_quotes=["q"],
                db=db,
            )
        update_args = vertex.update.call_args[0][0]
        assert "current_confidence" not in update_args

    def test_reinforce_missing_current_raises(self) -> None:
        db, _vertex, _ = _mock_db()
        with patch(
            "app.db.temporal_revisions_repo.temporal.get_current",
            return_value=None,
        ), _patch_run_aql([]), pytest.raises(ValueError, match="no current version"):
            supersede(
                ontology_id="ont1",
                existing_entity_id="ontology_classes/k1",
                verdict=VERDICT_REINFORCED,
                action=ACTION_REINFORCE,
                agent_type=AGENT_LLM,
                agent_version="v",
                triggering_doc_id="doc1",
                evidence_quotes=["q"],
                db=db,
            )


# ---------------------------------------------------------------------------
# REVISE
# ---------------------------------------------------------------------------


class TestSupersedeRevise:
    def test_revise_calls_update_entity_and_records_audit(self) -> None:
        db, *_ = _mock_db()
        with patch(
            "app.db.temporal_revisions_repo.temporal.update_entity",
            return_value={"_key": "k1_v2", "_id": "ontology_classes/k1_v2"},
        ) as upd, _patch_run_aql([]), patch(
            "app.db.temporal_revisions_repo.record_revision",
            return_value={"_key": "rev_r2", "status": STATUS_APPLIED},
        ) as record:
            result = supersede(
                ontology_id="ont1",
                existing_entity_id="ontology_classes/k1",
                verdict=VERDICT_GAP_FILLING,
                action=ACTION_REVISE,
                agent_type=AGENT_LLM,
                agent_version="v",
                triggering_doc_id="doc1",
                new_vertex_data={"label": "NewLabel"},
                edge_collections=["subclass_of", "rdfs_domain"],
                change_summary="LLM revision: tightened label",
                db=db,
            )
        upd.assert_called_once()
        kwargs = upd.call_args.kwargs
        assert kwargs["collection"] == "ontology_classes"
        assert kwargs["key"] == "k1"
        assert kwargs["new_data"] == {"label": "NewLabel"}
        assert kwargs["change_type"] == "belief_revision"
        assert kwargs["edge_collections"] == ["subclass_of", "rdfs_domain"]
        assert result.expired_version_key == "k1"
        assert result.new_version_key == "k1_v2"
        assert result.extra["new_version_id"] == "ontology_classes/k1_v2"
        record_kwargs = record.call_args.kwargs
        assert record_kwargs["existing_version"] == "k1"
        assert record_kwargs["new_version"] == "k1_v2"

    def test_revise_without_new_vertex_data_raises(self) -> None:
        db, *_ = _mock_db()
        with _patch_run_aql([]), pytest.raises(ValueError, match="REVISE requires"):
            supersede(
                ontology_id="ont1",
                existing_entity_id="ontology_classes/k1",
                verdict=VERDICT_GAP_FILLING,
                action=ACTION_REVISE,
                agent_type=AGENT_LLM,
                agent_version="v",
                triggering_doc_id="doc1",
                db=db,
            )


# ---------------------------------------------------------------------------
# GAP_FILL
# ---------------------------------------------------------------------------


class TestSupersedeGapFill:
    def test_gap_fill_inserts_edge_with_temporal_stamps(self) -> None:
        db, _, edge = _mock_db()
        edge.insert.return_value = {
            "new": {
                "_key": "edge_xyz",
                "_id": "subclass_of/edge_xyz",
                "_from": "ontology_classes/child",
                "_to": "ontology_classes/parent",
                "ontology_id": "ont1",
            }
        }
        with _patch_run_aql([]), patch(
            "app.db.temporal_revisions_repo.record_revision",
            return_value={"_key": "rev_r3", "status": STATUS_APPLIED},
        ):
            result = supersede(
                ontology_id="ont1",
                existing_entity_id="ontology_classes/child",
                verdict=VERDICT_GAP_FILLING,
                action=ACTION_GAP_FILL,
                agent_type=AGENT_MECHANICAL,
                agent_version="v",
                triggering_doc_id="doc1",
                new_edge={
                    "_from": "ontology_classes/child",
                    "_to": "ontology_classes/parent",
                    "ontology_id": "ont1",
                },
                new_edge_collection="subclass_of",
                db=db,
            )
        edge.insert.assert_called_once()
        payload = edge.insert.call_args[0][0]
        assert payload["_from"] == "ontology_classes/child"
        assert payload["_to"] == "ontology_classes/parent"
        assert payload["expired"] == NEVER_EXPIRES
        assert payload["ttlExpireAt"] is None
        assert "created" in payload
        assert result.new_edge_key == "edge_xyz"
        assert result.expired_version_key is None

    def test_gap_fill_without_edge_raises(self) -> None:
        db, *_ = _mock_db()
        with _patch_run_aql([]), pytest.raises(ValueError, match="GAP_FILL requires"):
            supersede(
                ontology_id="ont1",
                existing_entity_id="ontology_classes/child",
                verdict=VERDICT_GAP_FILLING,
                action=ACTION_GAP_FILL,
                agent_type=AGENT_MECHANICAL,
                agent_version="v",
                triggering_doc_id="doc1",
                db=db,
            )

    def test_gap_fill_missing_edge_collection_raises(self) -> None:
        db, _, _ = _mock_db(has_edge_collection=False)
        with _patch_run_aql([]), patch(
            "app.db.temporal_revisions_repo.record_revision",
            return_value={"_key": "x", "status": STATUS_APPLIED},
        ), pytest.raises(ValueError, match="edge collection not found"):
            supersede(
                ontology_id="ont1",
                existing_entity_id="ontology_classes/child",
                verdict=VERDICT_GAP_FILLING,
                action=ACTION_GAP_FILL,
                agent_type=AGENT_MECHANICAL,
                agent_version="v",
                triggering_doc_id="doc1",
                new_edge={
                    "_from": "ontology_classes/child",
                    "_to": "ontology_classes/parent",
                },
                new_edge_collection="subclass_of",
                db=db,
            )

    def test_gap_fill_without_endpoints_raises(self) -> None:
        db, *_ = _mock_db()
        with _patch_run_aql([]), pytest.raises(ValueError, match="_from and _to"):
            supersede(
                ontology_id="ont1",
                existing_entity_id="ontology_classes/child",
                verdict=VERDICT_GAP_FILLING,
                action=ACTION_GAP_FILL,
                agent_type=AGENT_MECHANICAL,
                agent_version="v",
                triggering_doc_id="doc1",
                new_edge={"_from": "ontology_classes/child"},
                new_edge_collection="subclass_of",
                db=db,
            )


# ---------------------------------------------------------------------------
# RETRACT
# ---------------------------------------------------------------------------


class TestSupersedeRetract:
    def test_retract_calls_expire_entity(self) -> None:
        db, *_ = _mock_db()
        with patch(
            "app.db.temporal_revisions_repo.temporal.expire_entity",
            return_value={"_key": "k1", "expired": 1234.0},
        ) as expire, _patch_run_aql([]), patch(
            "app.db.temporal_revisions_repo.record_revision",
            return_value={"_key": "rev_r4", "status": STATUS_APPLIED},
        ):
            result = supersede(
                ontology_id="ont1",
                existing_entity_id="ontology_classes/k1",
                verdict=VERDICT_CONTRADICTED,
                action=ACTION_RETRACT,
                agent_type=AGENT_LLM,
                agent_version="v",
                triggering_doc_id="doc1",
                db=db,
            )
        expire.assert_called_once_with(db, collection="ontology_classes", key="k1")
        assert result.expired_version_key == "k1"
        assert result.new_version_key is None

    def test_retract_no_op_still_writes_audit(self) -> None:
        db, *_ = _mock_db()
        with patch(
            "app.db.temporal_revisions_repo.temporal.expire_entity",
            return_value=None,
        ), _patch_run_aql([]), patch(
            "app.db.temporal_revisions_repo.record_revision",
            return_value={"_key": "rev_r4", "status": STATUS_APPLIED},
        ) as record:
            result = supersede(
                ontology_id="ont1",
                existing_entity_id="ontology_classes/k1",
                verdict=VERDICT_CONTRADICTED,
                action=ACTION_RETRACT,
                agent_type=AGENT_LLM,
                agent_version="v",
                triggering_doc_id="doc1",
                db=db,
            )
        record.assert_called_once()
        assert result.revision_meta_key == "rev_r4"


# ---------------------------------------------------------------------------
# FLAG_FOR_CURATION
# ---------------------------------------------------------------------------


class TestSupersedeFlagForCuration:
    def test_flag_writes_audit_only_no_graph_change(self) -> None:
        db, vertex, edge = _mock_db()
        with _patch_run_aql([]), patch(
            "app.db.temporal_revisions_repo.record_revision",
            return_value={"_key": "rev_flag", "status": STATUS_PENDING},
        ) as record:
            result = supersede(
                ontology_id="ont1",
                existing_entity_id="ontology_classes/k1",
                verdict=VERDICT_UNCERTAIN,
                action=ACTION_FLAG_FOR_CURATION,
                agent_type=AGENT_LLM,
                agent_version="v",
                triggering_doc_id="doc1",
                reasoning="ambiguous suffix",
                db=db,
            )
        vertex.update.assert_not_called()
        vertex.insert.assert_not_called()
        edge.insert.assert_not_called()
        record.assert_called_once()
        assert result.action == ACTION_FLAG_FOR_CURATION
        assert result.status == STATUS_PENDING


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


class TestSupersedeValidation:
    def test_unknown_action_raises(self) -> None:
        db, *_ = _mock_db()
        with _patch_run_aql([]), pytest.raises(ValueError, match="unsupported action"):
            supersede(
                ontology_id="ont1",
                existing_entity_id="ontology_classes/k1",
                verdict=VERDICT_REINFORCED,
                action="WAT",
                agent_type=AGENT_LLM,
                agent_version="v",
                triggering_doc_id="doc1",
                db=db,
            )

    def test_invalid_existing_entity_id_for_non_gap_fill_raises(self) -> None:
        db, *_ = _mock_db()
        with _patch_run_aql([]), pytest.raises(ValueError, match="invalid entity"):
            supersede(
                ontology_id="ont1",
                existing_entity_id="not-a-valid-id",
                verdict=VERDICT_REINFORCED,
                action=ACTION_REINFORCE,
                agent_type=AGENT_LLM,
                agent_version="v",
                triggering_doc_id="doc1",
                db=db,
            )


# ---------------------------------------------------------------------------
# Audit-record contract
# ---------------------------------------------------------------------------


class TestAuditRecordContract:
    def test_record_revision_receives_all_fields(self) -> None:
        db, vertex, _ = _mock_db()
        vertex.update.return_value = {
            "new": {
                "_key": "k1",
                "evidence_count": 1,
                "current_confidence": 0.9,
            }
        }
        with patch(
            "app.db.temporal_revisions_repo.temporal.get_current",
            return_value={"_key": "k1", "evidence": []},
        ), _patch_run_aql([]), patch(
            "app.db.temporal_revisions_repo.record_revision",
            return_value={"_key": "rev1", "status": STATUS_APPLIED},
        ) as record:
            supersede(
                ontology_id="ont1",
                existing_entity_id="ontology_classes/k1",
                verdict=VERDICT_REINFORCED,
                action=ACTION_REINFORCE,
                agent_type=AGENT_LLM,
                agent_version="gpt-x@p1",
                triggering_doc_id="doc_abc",
                evidence_quotes=["quote"],
                reasoning="strong corroboration",
                confidence_before=0.6,
                confidence_after=0.9,
                db=db,
            )
        kw = record.call_args.kwargs
        assert kw["ontology_id"] == "ont1"
        assert kw["verdict"] == VERDICT_REINFORCED
        assert kw["action"] == ACTION_REINFORCE
        assert kw["agent_type"] == AGENT_LLM
        assert kw["agent_version"] == "gpt-x@p1"
        assert kw["triggering_doc_id"] == "doc_abc"
        assert kw["existing_entity_id"] == "ontology_classes/k1"
        assert kw["evidence_quotes"] == ["quote"]
        assert kw["reasoning"] == "strong corroboration"
        assert kw["confidence_before"] == 0.6
        assert kw["confidence_after"] == 0.9


# ---------------------------------------------------------------------------
# Convenience adapters
# ---------------------------------------------------------------------------


class _FakeTouchpoint:
    def __init__(self, existing_class_id: str) -> None:
        self.existing_class_id = existing_class_id


class _FakeMechanical:
    def __init__(
        self,
        *,
        verdict: str,
        action: str,
        rule_id: str,
        confidence: float,
        reasoning: str,
        existing_class_id: str = "ontology_classes/k1",
    ) -> None:
        self.verdict = verdict
        self.action = action
        self.rule_id = rule_id
        self.confidence = confidence
        self.reasoning = reasoning
        self.touchpoint = _FakeTouchpoint(existing_class_id)


class _FakeLLM:
    def __init__(
        self,
        *,
        action: str,
        evidence_quotes: list[str],
        reasoning: str,
        confidence: float,
    ) -> None:
        self.action = action
        self.evidence_quotes = evidence_quotes
        self.reasoning = reasoning
        self.confidence = confidence


class TestSupersedeFromMechanicalRevision:
    def test_mechanical_adapter_forwards_to_supersede(self) -> None:
        db, *_ = _mock_db()
        with patch(
            "app.db.temporal_revisions_repo.supersede",
            return_value=SupersedeResult(
                revision_meta_key="rev1",
                action=ACTION_REVISE,
                status=STATUS_APPLIED,
            ),
        ) as sup:
            result = supersede_from_mechanical_revision(
                _FakeMechanical(
                    verdict=VERDICT_GAP_FILLING,
                    action=ACTION_REVISE,
                    rule_id="R7_REFINED_NAMING",
                    confidence=0.72,
                    reasoning="strong fuzzy",
                ),
                ontology_id="ont1",
                triggering_doc_id="doc1",
                agent_version="rule-engine-1.0",
                new_vertex_data={"label": "X"},
                db=db,
            )
        sup.assert_called_once()
        kw = sup.call_args.kwargs
        assert kw["agent_type"] == AGENT_MECHANICAL
        assert kw["agent_version"] == "rule-engine-1.0+R7_REFINED_NAMING"
        assert kw["existing_entity_id"] == "ontology_classes/k1"
        assert kw["verdict"] == VERDICT_GAP_FILLING
        assert kw["action"] == ACTION_REVISE
        assert kw["confidence_after"] == 0.72
        assert result.revision_meta_key == "rev1"


class TestSupersedeFromLlmProposal:
    def test_llm_adapter_forwards_to_supersede(self) -> None:
        db, *_ = _mock_db()
        with patch(
            "app.db.temporal_revisions_repo.supersede",
            return_value=SupersedeResult(
                revision_meta_key="rev2",
                action=ACTION_RETRACT,
                status=STATUS_APPLIED,
            ),
        ) as sup:
            result = supersede_from_llm_proposal(
                _FakeLLM(
                    action=ACTION_RETRACT,
                    evidence_quotes=["q1"],
                    reasoning="contradicted",
                    confidence=0.91,
                ),
                ontology_id="ont1",
                existing_entity_id="ontology_classes/k1",
                verdict=VERDICT_CONTRADICTED,
                triggering_doc_id="doc1",
                agent_version="gpt-x@p1",
                db=db,
            )
        sup.assert_called_once()
        kw = sup.call_args.kwargs
        assert kw["agent_type"] == AGENT_LLM
        assert kw["agent_version"] == "gpt-x@p1"
        assert kw["evidence_quotes"] == ["q1"]
        assert kw["reasoning"] == "contradicted"
        assert kw["confidence_after"] == 0.91
        assert result.revision_meta_key == "rev2"


# ---------------------------------------------------------------------------
# SupersedeResult contract
# ---------------------------------------------------------------------------


class TestSupersedeResultContract:
    def test_to_dict_round_trips_all_fields(self) -> None:
        r = SupersedeResult(
            revision_meta_key="r",
            action=ACTION_REVISE,
            status=STATUS_APPLIED,
            new_version_key="v2",
            expired_version_key="v1",
            new_edge_key=None,
            skipped=False,
            skipped_reason="",
            extra={"foo": "bar"},
        )
        d = r.to_dict()
        assert d["revision_meta_key"] == "r"
        assert d["action"] == ACTION_REVISE
        assert d["status"] == STATUS_APPLIED
        assert d["new_version_key"] == "v2"
        assert d["expired_version_key"] == "v1"
        assert d["new_edge_key"] is None
        assert d["skipped"] is False
        assert d["extra"] == {"foo": "bar"}

    def test_result_is_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        r = SupersedeResult(
            revision_meta_key="r", action=ACTION_REINFORCE, status=STATUS_APPLIED
        )
        with pytest.raises(FrozenInstanceError):
            r.action = ACTION_REVISE  # type: ignore[misc]
