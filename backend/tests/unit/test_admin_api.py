"""Tests for admin API endpoints (admin.py)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.admin import _remove_ontology_graphs, _require_reset_enabled
from app.config import settings


class TestRequireResetEnabled:
    """Verify the reset gate respects ``settings.allow_system_reset``.

    The setting is loaded once at process start by pydantic-settings (env var
    ``ALLOW_SYSTEM_RESET``); individual test cases can flip it at runtime via
    ``patch.object(settings, ...)``.
    """

    def test_raises_403_when_disabled(self):
        with patch.object(settings, "allow_system_reset", False):
            with pytest.raises(HTTPException) as exc_info:
                _require_reset_enabled()
            assert exc_info.value.status_code == 403

    def test_passes_when_enabled(self):
        with patch.object(settings, "allow_system_reset", True):
            _require_reset_enabled()


class TestResetEndpoints:
    def test_remove_ontology_graphs_removes_only_prefixed_graphs(self):
        mock_db = MagicMock()
        mock_db.graphs.return_value = [
            {"name": "ontology_customer"},
            {"name": "other_graph"},
            "ontology_supplier",
        ]

        removed = _remove_ontology_graphs(mock_db)

        assert removed == ["ontology_customer", "ontology_supplier"]
        assert mock_db.delete_graph.call_count == 2

    def test_remove_ontology_graphs_handles_graph_listing_error(self):
        mock_db = MagicMock()
        mock_db.graphs.side_effect = RuntimeError("boom")

        removed = _remove_ontology_graphs(mock_db)

        assert removed == []
        mock_db.delete_graph.assert_not_called()

    @pytest.mark.asyncio
    async def test_reset_ontology_truncates_collections(self):
        mock_collection = MagicMock()
        mock_db = MagicMock()
        mock_db.has_collection.return_value = True
        mock_db.collection.return_value = mock_collection

        with (
            patch.object(settings, "allow_system_reset", True),
            patch("app.api.admin.get_db", return_value=mock_db),
        ):
            from app.api.admin import reset_ontology_data

            result = await reset_ontology_data()

        assert result["reset"] is True
        assert len(result["collections_truncated"]) > 0
        # Should NOT include documents/chunks
        assert "documents" not in result["collections_truncated"]
        assert "chunks" not in result["collections_truncated"]

    @pytest.mark.asyncio
    async def test_full_reset_includes_documents(self):
        mock_collection = MagicMock()
        mock_db = MagicMock()
        mock_db.has_collection.return_value = True
        mock_db.collection.return_value = mock_collection

        with (
            patch.object(settings, "allow_system_reset", True),
            patch("app.api.admin.get_db", return_value=mock_db),
        ):
            from app.api.admin import reset_all_data

            result = await reset_all_data()

        assert result["reset"] is True
        assert "documents" in result["collections_truncated"]
        assert "chunks" in result["collections_truncated"]

    @pytest.mark.asyncio
    async def test_reset_skips_missing_collections(self):
        mock_db = MagicMock()
        mock_db.has_collection.return_value = False

        with (
            patch.object(settings, "allow_system_reset", True),
            patch("app.api.admin.get_db", return_value=mock_db),
        ):
            from app.api.admin import reset_ontology_data

            result = await reset_ontology_data()

        assert result["reset"] is True
        assert result["collections_truncated"] == []
        mock_db.collection.assert_not_called()

    def test_settings_field_default_is_false(self, tmp_path, monkeypatch):
        """Regression: a fresh Settings with no env var and no .env must default
        to ``allow_system_reset=False`` so a new deployment isn't silently exposed
        to ``/admin/reset``.
        """
        monkeypatch.delenv("ALLOW_SYSTEM_RESET", raising=False)
        # Point pydantic-settings at an empty .env so the developer's repo-root
        # ``.env`` doesn't bleed into this assertion.
        empty_env = tmp_path / ".env.empty"
        empty_env.write_text("")

        from app.config import Settings

        fresh = Settings(_env_file=str(empty_env))
        assert fresh.allow_system_reset is False


class TestFeedbackLearningArtifacts:
    @pytest.mark.asyncio
    async def test_feedback_learning_artifacts_delegates_to_service(self):
        payload = {
            "status": "ready",
            "auto_apply": False,
            "summary": {"total_examples": 1},
            "examples": [{"decision_key": "d1"}],
            "regression_candidates": [],
        }

        with (
            patch("app.api.admin.get_db", return_value=MagicMock(name="db")) as mock_get_db,
            patch(
                "app.api.admin.build_feedback_learning_examples",
                return_value=payload,
            ) as mock_build,
        ):
            from app.api.admin import feedback_learning_artifacts

            result = await feedback_learning_artifacts(ontology_id="onto_1", limit=25)

        assert result == payload
        mock_build.assert_called_once_with(
            mock_get_db.return_value,
            ontology_id="onto_1",
            limit=25,
        )

    @pytest.mark.asyncio
    async def test_feedback_learning_artifacts_wraps_service_error(self):
        with (
            patch("app.api.admin.get_db", return_value=MagicMock()),
            patch(
                "app.api.admin.build_feedback_learning_examples",
                side_effect=RuntimeError("boom"),
            ),
        ):
            from app.api.admin import feedback_learning_artifacts

            with pytest.raises(HTTPException) as exc:
                await feedback_learning_artifacts(ontology_id=None, limit=100)

        assert exc.value.status_code == 500


class TestOntologyReflectionReport:
    """The reflection-report endpoint is the read-only path that the
    planned IBR.14 background-consolidation pass (and curators today)
    use to ask "what would a reflection cycle change?" without writing
    anything. Two contracts MUST hold:

    1. It composes ``evaluate_rules`` (rule violations) with
       ``apply_confidence_decay(..., dry_run=True)`` (decay preview)
       and never writes -- the dry-run flag must always be True.
    2. It returns a stable ``summary`` shape that future UIs and
       background jobs can consume without re-aggregating.
    """

    @staticmethod
    def _stub_rules_report(ontology_id: str = "wtw"):
        from app.services.ontology_rule_engine import (
            RULE_R1_SYNONYM_TRIANGLE,
            RULE_R2_SUBCLASS_CYCLE,
            SEVERITY_ERROR,
            SEVERITY_WARNING,
            RuleEngineReport,
            Violation,
        )

        return RuleEngineReport(
            ontology_id=ontology_id,
            rules_evaluated=[
                RULE_R1_SYNONYM_TRIANGLE,
                RULE_R2_SUBCLASS_CYCLE,
                "DISJOINT_violation",
            ],
            rules_skipped=["CARDINALITY_violation"],
            violations=[
                Violation(
                    rule_id=RULE_R1_SYNONYM_TRIANGLE,
                    severity=SEVERITY_WARNING,
                    entity_ids=("classes/A", "classes/B", "classes/C"),
                    description="A subClassOf B, B equiv C, but no A subClassOf C",
                    suggested_action="REFINED",
                ),
                Violation(
                    rule_id=RULE_R1_SYNONYM_TRIANGLE,
                    severity=SEVERITY_ERROR,
                    entity_ids=("classes/X", "classes/Y"),
                    description="Synonym cycle X subClassOf Y AND Y equiv X",
                    suggested_action="REDUNDANT",
                ),
                Violation(
                    rule_id=RULE_R2_SUBCLASS_CYCLE,
                    severity=SEVERITY_ERROR,
                    entity_ids=("classes/P", "classes/Q"),
                    description="Cycle P -> Q -> P in subclass_of",
                    suggested_action="CONTRADICTED",
                ),
            ],
        )

    @staticmethod
    def _stub_decay_report(ontology_id: str = "wtw"):
        from app.services.confidence_decay import DecayedClass, DecayReport

        return DecayReport(
            ontology_id=ontology_id,
            enabled=False,
            dry_run=True,
            half_life_days=90.0,
            floor=0.05,
            classes_examined=10,
            classes_decayed=2,
            decayed=[
                DecayedClass(
                    class_key="cls_old",
                    confidence_before=0.9,
                    confidence_after=0.55,
                    age_seconds=90 * 86400,
                ),
                DecayedClass(
                    class_key="cls_older",
                    confidence_before=0.7,
                    confidence_after=0.34,
                    age_seconds=120 * 86400,
                ),
            ],
            skipped_no_age=1,
        )

    @pytest.mark.asyncio
    async def test_endpoint_composes_rule_engine_and_dry_run_decay(self):
        rules_stub = self._stub_rules_report()
        decay_stub = self._stub_decay_report()

        with (
            patch("app.api.admin.get_db", return_value=MagicMock(name="db")) as mock_get_db,
            patch(
                "app.api.admin.evaluate_rules",
                return_value=rules_stub,
            ) as mock_rules,
            patch(
                "app.api.admin.apply_confidence_decay",
                return_value=decay_stub,
            ) as mock_decay,
        ):
            from app.api.admin import ontology_reflection_report

            result = await ontology_reflection_report(
                ontology_id="wtw",
                half_life_days=None,
                floor=None,
            )

        mock_rules.assert_called_once_with(mock_get_db.return_value, "wtw")
        # CRITICAL CONTRACT: dry_run MUST be True so the endpoint is
        # provably read-only. Asserted explicitly (not as default) so a
        # future refactor that drops the kwarg fails this test loudly.
        mock_decay.assert_called_once_with(
            mock_get_db.return_value,
            "wtw",
            dry_run=True,
            half_life_days=None,
            floor=None,
        )
        assert result["ontology_id"] == "wtw"
        assert result["rule_violations"] == rules_stub.to_dict()
        assert result["decay_preview"] == decay_stub.to_dict()
        assert isinstance(result["evaluated_at"], float)

    @pytest.mark.asyncio
    async def test_summary_aggregates_violations_correctly(self):
        rules_stub = self._stub_rules_report()
        decay_stub = self._stub_decay_report()

        with (
            patch("app.api.admin.get_db", return_value=MagicMock()),
            patch("app.api.admin.evaluate_rules", return_value=rules_stub),
            patch("app.api.admin.apply_confidence_decay", return_value=decay_stub),
        ):
            from app.api.admin import ontology_reflection_report

            result = await ontology_reflection_report(
                ontology_id="wtw",
                half_life_days=None,
                floor=None,
            )

        s = result["summary"]
        assert s["total_violations"] == 3
        assert s["violations_by_severity"] == {"warning": 1, "error": 2}
        assert s["violations_by_rule"] == {
            "R1_synonym_triangle": 2,
            "R2_subclass_cycle": 1,
        }
        assert s["rules_evaluated"] == [
            "R1_synonym_triangle",
            "R2_subclass_cycle",
            "DISJOINT_violation",
        ]
        assert s["rules_skipped"] == ["CARDINALITY_violation"]
        assert s["decay_classes_examined"] == 10
        assert s["decay_classes_would_change"] == 2
        assert s["decay_skipped_no_age"] == 1

    @pytest.mark.asyncio
    async def test_what_if_overrides_flow_through_to_decay(self):
        """``half_life_days`` and ``floor`` query params must reach the
        decay service so curators can preview tighter/looser settings.
        """
        with (
            patch("app.api.admin.get_db", return_value=MagicMock()),
            patch("app.api.admin.evaluate_rules", return_value=self._stub_rules_report()),
            patch(
                "app.api.admin.apply_confidence_decay",
                return_value=self._stub_decay_report(),
            ) as mock_decay,
        ):
            from app.api.admin import ontology_reflection_report

            await ontology_reflection_report(
                ontology_id="wtw",
                half_life_days=30.0,
                floor=0.10,
            )

        kwargs = mock_decay.call_args.kwargs
        assert kwargs["dry_run"] is True
        assert kwargs["half_life_days"] == 30.0
        assert kwargs["floor"] == 0.10

    @pytest.mark.asyncio
    async def test_handles_empty_ontology_with_zero_violations(self):
        from app.services.confidence_decay import DecayReport
        from app.services.ontology_rule_engine import RuleEngineReport

        empty_rules = RuleEngineReport(
            ontology_id="wtw",
            rules_evaluated=[],
            rules_skipped=[],
            violations=[],
        )
        empty_decay = DecayReport(
            ontology_id="wtw",
            enabled=False,
            dry_run=True,
            half_life_days=90.0,
            floor=0.05,
        )

        with (
            patch("app.api.admin.get_db", return_value=MagicMock()),
            patch("app.api.admin.evaluate_rules", return_value=empty_rules),
            patch("app.api.admin.apply_confidence_decay", return_value=empty_decay),
        ):
            from app.api.admin import ontology_reflection_report

            result = await ontology_reflection_report(
                ontology_id="wtw",
                half_life_days=None,
                floor=None,
            )

        # Stable shape MUST hold even when both services find nothing,
        # so the future UI / IBR.14 pass can render "all clean" without
        # special-casing missing keys.
        assert result["summary"]["total_violations"] == 0
        assert result["summary"]["violations_by_severity"] == {}
        assert result["summary"]["violations_by_rule"] == {}
        assert result["summary"]["decay_classes_examined"] == 0
        assert result["summary"]["decay_classes_would_change"] == 0

    @pytest.mark.asyncio
    async def test_wraps_service_error_in_500(self):
        with (
            patch("app.api.admin.get_db", return_value=MagicMock()),
            patch(
                "app.api.admin.evaluate_rules",
                side_effect=RuntimeError("AQL exploded"),
            ),
        ):
            from app.api.admin import ontology_reflection_report

            with pytest.raises(HTTPException) as exc:
                await ontology_reflection_report(
                    ontology_id="wtw",
                    half_life_days=None,
                    floor=None,
                )

        assert exc.value.status_code == 500
