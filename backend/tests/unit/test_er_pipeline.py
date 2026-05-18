"""Unit tests for the ER pipeline configuration and orchestration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.models.ontology import ExtractedClass
from app.services.er import (
    ERFieldConfig,
    ERPipelineConfig,
    ERRunStatus,
    _blocking_tokens,
    _execute_blocking,
    _execute_scoring,
    _jaro_winkler_sim,
    _token_overlap,
    configure_blocking,
    configure_scoring,
    explain_match,
    get_config,
    run_er_pipeline,
    score_existing_class_vs_extracted,
    update_config,
)


class TestERPipelineConfig:
    def test_default_config(self):
        config = ERPipelineConfig()
        assert config.collection == "ontology_classes"
        assert len(config.field_configs) == 3
        assert config.topological_weight == 0.1

    def test_to_dict_roundtrip(self):
        config = ERPipelineConfig(
            ontology_id="test_onto",
            similarity_threshold=0.8,
        )
        d = config.to_dict()
        restored = ERPipelineConfig.from_dict(d)
        assert restored.ontology_id == "test_onto"
        assert restored.similarity_threshold == 0.8

    def test_from_dict_with_defaults(self):
        config = ERPipelineConfig.from_dict({})
        assert config.collection == "ontology_classes"
        assert len(config.blocking_strategies) == 2

    def test_custom_field_configs(self):
        config = ERPipelineConfig(
            field_configs=[
                ERFieldConfig("label", 0.5, "jaro_winkler"),
                ERFieldConfig("uri", 0.5, "exact"),
            ]
        )
        assert len(config.field_configs) == 2
        total_weight = sum(fc.weight for fc in config.field_configs)
        assert total_weight == 1.0


class TestConfigureBlocking:
    def test_bm25_strategy(self):
        config = ERPipelineConfig(blocking_strategies=["bm25"])
        result = configure_blocking(config)
        assert len(result["strategies"]) == 1
        assert result["strategies"][0]["type"] == "BM25BlockingStrategy"

    def test_vector_strategy(self):
        config = ERPipelineConfig(blocking_strategies=["vector"])
        result = configure_blocking(config)
        assert result["strategies"][0]["type"] == "VectorBlockingStrategy"

    def test_multi_strategy(self):
        config = ERPipelineConfig(blocking_strategies=["bm25", "vector"])
        result = configure_blocking(config)
        assert len(result["strategies"]) == 2
        assert result["orchestrator"] == "MultiStrategyOrchestrator"


class TestConfigureScoring:
    def test_default_scoring(self):
        config = ERPipelineConfig()
        result = configure_scoring(config)
        assert result["type"] == "WeightedFieldSimilarity"
        assert len(result["fields"]) == 3
        assert result["topological_weight"] == 0.1

    def test_custom_threshold(self):
        config = ERPipelineConfig(similarity_threshold=0.9)
        result = configure_scoring(config)
        assert result["threshold"] == 0.9


class TestJaroWinklerSim:
    def test_identical_strings(self):
        assert _jaro_winkler_sim("hello", "hello") == 1.0

    def test_empty_strings(self):
        assert _jaro_winkler_sim("", "") == 0.0
        assert _jaro_winkler_sim("hello", "") == 0.0

    def test_similar_strings(self):
        sim = _jaro_winkler_sim("Customer", "Customers")
        assert sim > 0.9

    def test_different_strings(self):
        sim = _jaro_winkler_sim("apple", "orange")
        assert sim < 0.7

    def test_case_insensitive(self):
        assert _jaro_winkler_sim("Vehicle", "vehicle") == 1.0


class TestTokenOverlap:
    def test_identical_texts(self):
        assert _token_overlap("hello world", "hello world") == 1.0

    def test_empty_texts(self):
        assert _token_overlap("", "") == 0.0

    def test_partial_overlap(self):
        sim = _token_overlap("red car fast", "red truck slow")
        assert 0.0 < sim < 1.0

    def test_no_overlap(self):
        sim = _token_overlap("apple banana", "orange grape")
        assert sim == 0.0


class TestRunERPipeline:
    def test_pipeline_with_no_collection(self):
        db = MagicMock()
        db.has_collection.return_value = False

        result = run_er_pipeline(db, ontology_id="test")
        assert result.status == ERRunStatus.COMPLETE
        assert result.candidate_count == 0

    def test_pipeline_stores_run_status(self):
        db = MagicMock()
        db.has_collection.return_value = False

        result = run_er_pipeline(db, ontology_id="test")
        from app.services.er import get_run_status

        stored = get_run_status(result.run_id)
        assert stored is not None
        assert stored.run_id == result.run_id

    @patch("app.services.er.run_aql")
    def test_blocking_normalizes_plural_and_camelcase(self, mock_run_aql):
        db = MagicMock()
        db.has_collection.return_value = True
        mock_run_aql.return_value = [
            {"key": "c1", "label": "Customer", "uri": "http://ex#Customer"},
            {"key": "c2", "label": "Customers", "uri": "http://ex#Customers"},
            {"key": "c3", "label": "CustomerAccount", "uri": "http://ex#CustomerAccount"},
            {"key": "c4", "label": "Customer_Account", "uri": "http://ex#Customer_Account"},
        ]

        pairs = _execute_blocking(db, "onto1", ERPipelineConfig())

        assert ("c1", "c2") in pairs
        assert ("c3", "c4") in pairs

    @patch("app.services.er.compute_topological_similarity", return_value=0.0)
    @patch("app.services.er._get_class_doc")
    def test_scoring_does_not_penalize_nonmatching_exact_uri(
        self,
        mock_get_class_doc,
        mock_topology,
    ):
        db = MagicMock()
        db.has_collection.return_value = False
        mock_get_class_doc.side_effect = [
            {
                "_key": "c1",
                "label": "Customer",
                "description": "A customer account",
                "uri": "http://ex#Customer",
            },
            {
                "_key": "c2",
                "label": "Customers",
                "description": "Customer account records",
                "uri": "http://ex#Customers",
            },
        ]

        scored = _execute_scoring(
            db,
            [("c1", "c2")],
            ERPipelineConfig(similarity_threshold=0.6, topological_weight=0.0),
        )

        assert len(scored) == 1
        assert scored[0]["combined_score"] >= 0.6


class TestBlockingTokens:
    def test_splits_camelcase_and_singularizes(self):
        tokens = _blocking_tokens("CustomerAccounts")

        assert "customer" in tokens
        assert "accounts" in tokens
        assert "account" in tokens


class TestScoreExistingClassVsExtracted:
    def test_high_score_when_label_uri_match(self):
        db = MagicMock()
        db.has_collection.return_value = True
        ext = ExtractedClass(
            uri="http://ex.org#Customer",
            label="Customer",
            description="A customer entity",
            confidence=0.9,
        )
        with patch("app.services.er._get_class_doc") as mock_get:
            mock_get.return_value = {
                "_key": "c1",
                "label": "Customer",
                "description": "A customer entity",
                "uri": "http://ex.org#Customer",
            }
            result = score_existing_class_vs_extracted(db, existing_class_key="c1", extracted=ext)
        assert result["combined_score"] >= 0.85
        assert "field_scores" in result

    def test_missing_existing_returns_zero(self):
        db = MagicMock()
        with patch("app.services.er._get_class_doc", return_value=None):
            result = score_existing_class_vs_extracted(
                db,
                existing_class_key="missing",
                extracted=ExtractedClass(uri="u", label="L", description="d", confidence=0.5),
            )
        assert result["combined_score"] == 0.0
        assert result.get("error") == "existing_class_not_found"


class TestExplainMatch:
    def test_missing_classes(self):
        db = MagicMock()
        db.has_collection.return_value = True
        db.aql.execute.return_value = iter([])

        result = explain_match(db, key1="k1", key2="k2")
        assert "error" in result

    def test_explain_with_classes(self):
        db = MagicMock()
        db.has_collection.return_value = True

        call_count = {"n": 0}

        def execute_side(query, bind_vars=None):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                return iter(
                    [
                        {
                            "_key": f"k{call_count['n']}",
                            "_id": f"ontology_classes/k{call_count['n']}",
                            "label": f"Label{call_count['n']}",
                            "description": f"Description of entity {call_count['n']}",
                            "uri": f"http://ex.org#Entity{call_count['n']}",
                        }
                    ]
                )
            return iter([])

        db.aql.execute.side_effect = execute_side

        with patch("app.services.er.compute_topological_similarity", return_value=0.5):
            result = explain_match(db, key1="k1", key2="k2")

        assert "field_scores" in result
        assert "combined_score" in result
        assert result["combined_score"] > 0


class TestUpdateConfig:
    def test_update_preserves_defaults(self):
        updated = update_config({"similarity_threshold": 0.9})
        assert updated.similarity_threshold == 0.9
        assert updated.collection == "ontology_classes"

    def test_get_config_returns_current(self):
        update_config({"similarity_threshold": 0.75})
        config = get_config()
        assert config.similarity_threshold == 0.75
        update_config({"similarity_threshold": 0.7})


# ---------------------------------------------------------------------------
# Stream 2 PR 1 -- accept / reject / explain by pair_id.
#
# These tests pin the contract the workspace MergeCandidatesOverlay
# binds to. The decision shape (`status: accepted | already_accepted |
# rejected | already_rejected`, `pair_id`, timestamps) is part of the
# wire contract -- changing it will silently break the overlay.
# ---------------------------------------------------------------------------


def _stub_similar_to_collection(edges: dict[str, dict[str, object]]) -> tuple[MagicMock, dict]:
    """Build a MagicMock that behaves like a ``similarTo`` collection
    over an in-memory dict of edges keyed by pair_id. Returns (db_mock,
    recorded_updates) so tests can assert what got patched."""
    collection = MagicMock()
    recorded_updates: dict[str, dict[str, object]] = {}

    def _get(pair_id: str) -> dict[str, object] | None:
        return edges.get(pair_id)

    def _update(payload: dict[str, object]) -> dict[str, object]:
        pid = str(payload["_key"])
        recorded_updates[pid] = payload
        if pid in edges:
            edges[pid] = {**edges[pid], **payload}
        return {"_key": pid}

    collection.get.side_effect = _get
    collection.update.side_effect = _update

    db = MagicMock()
    db.has_collection.return_value = True
    db.collection.return_value = collection
    return db, recorded_updates


class TestAcceptCandidate:
    def test_accept_runs_merge_and_stamps_edge(self):
        from app.services import er as er_mod

        edges = {
            "p1": {
                "_key": "p1",
                "_from": "ontology_classes/src",
                "_to": "ontology_classes/tgt",
                "combined_score": 0.92,
            }
        }
        db, updates = _stub_similar_to_collection(edges)

        with patch.object(
            er_mod,
            "execute_merge",
            return_value={"target_key": "tgt", "source_key": "src"},
        ) as mock_merge:
            result = er_mod.accept_candidate(db, pair_id="p1", strategy="most_complete")

        mock_merge.assert_called_once_with(
            db, source_key="src", target_key="tgt", strategy="most_complete"
        )
        assert result["pair_id"] == "p1"
        assert result["status"] == "accepted"
        assert isinstance(result["accepted_at"], float)
        # similarTo edge was stamped so a second call short-circuits.
        assert "accepted_at" in updates["p1"]

    def test_accept_is_idempotent(self):
        from app.services import er as er_mod

        edges = {
            "p1": {
                "_key": "p1",
                "_from": "ontology_classes/src",
                "_to": "ontology_classes/tgt",
                "combined_score": 0.92,
                "accepted_at": 1000.0,
            }
        }
        db, _ = _stub_similar_to_collection(edges)

        with patch.object(er_mod, "execute_merge") as mock_merge:
            result = er_mod.accept_candidate(db, pair_id="p1")

        # No second merge -- the already-accepted edge was returned
        # as-is. Crucial: re-running execute_merge on an
        # already-expired source would crash.
        mock_merge.assert_not_called()
        assert result["status"] == "already_accepted"
        assert result["accepted_at"] == 1000.0

    def test_accept_after_reject_raises(self):
        from app.services import er as er_mod

        edges = {
            "p1": {
                "_key": "p1",
                "_from": "ontology_classes/src",
                "_to": "ontology_classes/tgt",
                "rejected_at": 500.0,
            }
        }
        db, _ = _stub_similar_to_collection(edges)

        import pytest

        with pytest.raises(ValueError, match="already rejected"):
            er_mod.accept_candidate(db, pair_id="p1")

    def test_accept_missing_pair_raises(self):
        from app.services import er as er_mod

        db, _ = _stub_similar_to_collection({})
        import pytest

        with pytest.raises(ValueError, match="not found"):
            er_mod.accept_candidate(db, pair_id="ghost")

    def test_accept_missing_collection_raises(self):
        from app.services import er as er_mod

        db = MagicMock()
        db.has_collection.return_value = False
        import pytest

        with pytest.raises(ValueError, match="similarTo collection not found"):
            er_mod.accept_candidate(db, pair_id="p1")


class TestRejectCandidate:
    def test_reject_stamps_edge(self):
        from app.services import er as er_mod

        edges = {
            "p1": {
                "_key": "p1",
                "_from": "ontology_classes/src",
                "_to": "ontology_classes/tgt",
            }
        }
        db, updates = _stub_similar_to_collection(edges)

        result = er_mod.reject_candidate(db, pair_id="p1")

        assert result["pair_id"] == "p1"
        assert result["status"] == "rejected"
        assert isinstance(result["rejected_at"], float)
        assert "rejected_at" in updates["p1"]

    def test_reject_is_idempotent(self):
        from app.services import er as er_mod

        edges = {
            "p1": {
                "_key": "p1",
                "_from": "ontology_classes/src",
                "_to": "ontology_classes/tgt",
                "rejected_at": 777.0,
            }
        }
        db, updates = _stub_similar_to_collection(edges)

        result = er_mod.reject_candidate(db, pair_id="p1")

        assert result["status"] == "already_rejected"
        assert result["rejected_at"] == 777.0
        # No second stamp -- already-rejected edge returned as-is.
        assert "p1" not in updates

    def test_reject_after_accept_raises(self):
        from app.services import er as er_mod

        edges = {
            "p1": {
                "_key": "p1",
                "_from": "ontology_classes/src",
                "_to": "ontology_classes/tgt",
                "accepted_at": 200.0,
            }
        }
        db, _ = _stub_similar_to_collection(edges)
        import pytest

        with pytest.raises(ValueError, match="already accepted"):
            er_mod.reject_candidate(db, pair_id="p1")

    def test_reject_missing_pair_raises(self):
        from app.services import er as er_mod

        db, _ = _stub_similar_to_collection({})
        import pytest

        with pytest.raises(ValueError, match="not found"):
            er_mod.reject_candidate(db, pair_id="ghost")


class TestExplainCandidate:
    def test_explain_by_pair_id_resolves_keys(self):
        from app.services import er as er_mod

        edges = {
            "p1": {
                "_key": "p1",
                "_from": "ontology_classes/src",
                "_to": "ontology_classes/tgt",
            }
        }
        db, _ = _stub_similar_to_collection(edges)

        with patch.object(
            er_mod,
            "explain_match",
            return_value={"combined_score": 0.91, "field_scores": {}},
        ) as mock_explain:
            result = er_mod.explain_candidate(db, pair_id="p1")

        mock_explain.assert_called_once_with(db, key1="src", key2="tgt")
        assert result["pair_id"] == "p1"
        assert result["combined_score"] == 0.91

    def test_explain_missing_pair_raises(self):
        from app.services import er as er_mod

        db, _ = _stub_similar_to_collection({})
        import pytest

        with pytest.raises(ValueError, match="not found"):
            er_mod.explain_candidate(db, pair_id="ghost")


class TestGetCandidatesIncludeResolved:
    def test_include_resolved_passed_through(self):
        """Pin that the new ``include_resolved`` flag actually makes
        it into the AQL bind vars -- otherwise the inbox would
        re-surface decisions the user already made."""
        from app.services import er as er_mod

        db = MagicMock()
        db.has_collection.return_value = True

        captured: list[dict] = []

        def fake_run_aql(_db, _query, bind_vars=None):
            captured.append(dict(bind_vars or {}))
            return iter([])

        with patch.object(er_mod, "run_aql", side_effect=fake_run_aql):
            er_mod.get_candidates(db, ontology_id="o1", include_resolved=True)
            er_mod.get_candidates(db, ontology_id="o1")  # default = False

        assert captured[0]["include_resolved"] is True
        assert captured[1]["include_resolved"] is False
