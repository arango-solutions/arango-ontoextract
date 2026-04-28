"""Unit tests for gated HITL feedback learning artifacts."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _mock_db(*, has_decisions: bool = True) -> MagicMock:
    db = MagicMock()
    db.has_collection.side_effect = lambda name: name == "curation_decisions" and has_decisions
    return db


class TestBuildFeedbackLearningExamples:
    def test_returns_empty_payload_when_decisions_collection_missing(self):
        from app.services.feedback_learning import build_feedback_learning_examples

        result = build_feedback_learning_examples(_mock_db(has_decisions=False), ontology_id="o1")

        assert result["status"] == "not_available"
        assert result["auto_apply"] is False
        assert result["summary"]["total_examples"] == 0
        assert result["examples"] == []

    @patch("app.services.feedback_learning.run_aql")
    def test_builds_prompt_examples_and_summary(self, mock_run_aql):
        from app.services.feedback_learning import build_feedback_learning_examples

        mock_run_aql.return_value = [
            {
                "_key": "d_edit",
                "run_id": "run_1",
                "entity_key": "Customer",
                "entity_type": "class",
                "action": "edit",
                "issue_reasons": ["bad_label"],
                "notes": "Use business terminology",
                "edit_diff": {
                    "changed_fields": ["label"],
                    "before": {"label": "Client Entity"},
                    "after": {"label": "Customer"},
                },
            },
            {
                "_key": "d_reject",
                "run_id": "run_1",
                "entity_key": "Ghost",
                "entity_type": "class",
                "action": "reject",
                "issue_reasons": ["hallucinated", "missing_evidence"],
                "notes": "No source support",
            },
        ]

        result = build_feedback_learning_examples(_mock_db(), ontology_id="onto_1")

        assert result["status"] == "ready"
        assert result["auto_apply"] is False
        assert result["summary"] == {
            "total_examples": 2,
            "regression_candidates": 1,
            "by_action": {"edit": 1, "reject": 1},
            "by_issue_reason": {
                "bad_label": 1,
                "hallucinated": 1,
                "missing_evidence": 1,
            },
        }
        edit_example = result["examples"][0]
        assert edit_example["prompt_guidance"] == (
            "For future class extraction, prefer the curated correction "
            "(label: 'Client Entity' -> 'Customer') when similar source evidence appears."
        )
        reject_example = result["regression_candidates"][0]
        assert reject_example["decision_key"] == "d_reject"
        assert "source_chunk_id" in reject_example["prompt_guidance"]
        fixture = result["benchmark_fixture"]
        assert fixture["schema_version"] == "hitl-regression-v1"
        assert fixture["summary"]["documents"] == 1
        assert fixture["documents"][0]["negative_classes"] == [
            {"label": "Ghost", "type": ""}
        ]

    @patch("app.services.feedback_learning.run_aql", return_value=[])
    def test_clamps_limit_and_filters_by_ontology(self, mock_run_aql):
        from app.services.feedback_learning import build_feedback_learning_examples

        build_feedback_learning_examples(_mock_db(), ontology_id="onto_2", limit=5000)

        bind_vars = mock_run_aql.call_args.kwargs["bind_vars"]
        assert bind_vars == {"ontology_id": "onto_2", "limit": 1000}


class TestBuildHitlRegressionFixture:
    def test_exports_positive_edit_and_negative_reject_documents(self):
        from app.services.feedback_learning import build_hitl_regression_fixture

        result = build_hitl_regression_fixture(
            [
                {
                    "decision_key": "edit1",
                    "entity_key": "Client",
                    "entity_type": "class",
                    "action": "edit",
                    "issue_reasons": ["bad_label"],
                    "source_text": "A customer opens an account.",
                    "after": {"label": "Customer", "type": "DomainClass"},
                    "prompt_guidance": "Prefer Customer.",
                },
                {
                    "decision_key": "reject1",
                    "entity_key": "Ghost",
                    "entity_type": "class",
                    "action": "reject",
                    "issue_reasons": ["hallucinated"],
                    "notes": "No source support.",
                    "prompt_guidance": "Do not extract unsupported classes.",
                },
            ],
            ontology_id="onto_1",
        )

        assert result["ontology_id"] == "onto_1"
        assert result["summary"] == {
            "documents": 2,
            "negative_examples": 1,
            "positive_classes": 1,
            "positive_relations": 0,
        }
        assert result["documents"][0]["gold_classes"] == [
            {"label": "Customer", "type": "DomainClass"}
        ]
        assert result["documents"][1]["negative_classes"] == [
            {"label": "Ghost", "type": ""}
        ]
