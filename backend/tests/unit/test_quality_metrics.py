"""Unit tests for quality_metrics service — all DB operations mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _mock_db(aql_results: dict | None = None):
    """Create a mock StandardDatabase with configurable AQL results."""
    db = MagicMock()
    db.has_collection.return_value = True

    _results = aql_results or {}
    call_count = {"n": 0}

    def execute_side_effect(query, bind_vars=None, **kwargs):
        key = call_count["n"]
        call_count["n"] += 1
        if key in _results:
            return iter(_results[key])
        return iter([])

    db.aql.execute.side_effect = execute_side_effect
    return db


class TestComputeOntologyQuality:
    """Tests for compute_ontology_quality."""

    def test_returns_metrics_for_populated_ontology(self):
        from app.services.quality_metrics import compute_ontology_quality

        db = _mock_db({
            0: [{"cnt": 5, "avg_conf": 0.85, "avg_faith": 0.8, "avg_sem": 0.9}],  # class stats
            1: [3],                                 # property count
            2: [4],                                 # classes with props
            3: [0],                                 # orphan query
            4: [],                                  # cycle check 1
            5: [],                                  # cycle check 2
            6: [2],                                 # related_to count
            7: [3],                                 # classes_with_relationships
            8: [2],                                 # chunk count
            9: [0],                                 # _count_edges (subclass_of)
            # _compute_schema_metrics queries follow (all default to 0/empty)
        })

        result = compute_ontology_quality(db, "onto_1")

        assert result["ontology_id"] == "onto_1"
        assert result["avg_confidence"] == 0.85
        assert result["class_count"] == 5
        assert result["property_count"] == 3
        assert result["completeness"] == 80.0
        assert result["classes_without_properties"] == 1
        assert result["connectivity"] == 60.0  # 3/5 * 100
        assert result["schema_metrics"] is not None
        assert result["health_score"] is not None
        assert 0 <= result["health_score"] <= 100

    def test_empty_ontology(self):
        from app.services.quality_metrics import compute_ontology_quality

        db = MagicMock()
        db.has_collection.return_value = False

        result = compute_ontology_quality(db, "empty")

        assert result["class_count"] == 0
        assert result["property_count"] == 0
        assert result["avg_confidence"] is None
        assert result["completeness"] == 0.0
        assert result["orphan_count"] == 0
        assert result["has_cycles"] is False
        assert result["health_score"] is None

    def test_handles_missing_collections_gracefully(self):
        from app.services.quality_metrics import compute_ontology_quality

        db = MagicMock()
        db.has_collection.side_effect = lambda name: name == "ontology_classes"
        db.aql.execute.return_value = iter([{"cnt": 2, "avg_conf": 0.6}])

        result = compute_ontology_quality(db, "partial")

        assert result["class_count"] == 2
        assert result["property_count"] == 0

    @patch("app.services.extraction.get_run_cost", return_value={"estimated_cost": 1.234567})
    def test_cost_lookup_skips_quality_enrichment(self, mock_get_run_cost):
        from app.services.quality_metrics import compute_ontology_quality

        db = _mock_db({
            0: [{"cnt": 0, "avg_conf": None, "avg_faith": None, "avg_sem": None}],
            1: [0],
            2: [0],
            3: [],
            4: [],
            5: [0],
            6: [0],   # _count_edges (subclass_of)
            7: [{"run_id": "run_1", "name": "Ontology 1", "tier": "domain"}],
        })

        result = compute_ontology_quality(db, "onto_1")

        assert result["estimated_cost"] == 1.234567
        mock_get_run_cost.assert_called_once_with(
            db,
            run_id="run_1",
            include_quality_metrics=False,
        )


class TestComputeExtractionQuality:
    """Tests for compute_extraction_quality."""

    def test_returns_acceptance_rate(self):
        from app.services.quality_metrics import compute_extraction_quality

        db = _mock_db({
            0: [{"accepted": 8, "rejected": 1, "edited": 1}],  # curation_decisions
            1: [{"completed_at": 1000.5, "uploaded_at": 999.0}],  # time_to_ontology
        })

        result = compute_extraction_quality(db, "onto_1")

        assert result["acceptance_rate"] == 0.8
        assert result["time_to_ontology_ms"] == 1500

    def test_null_when_no_decisions(self):
        from app.services.quality_metrics import compute_extraction_quality

        db = _mock_db({
            0: [{"accepted": 0, "rejected": 0, "edited": 0}],
            1: [{}],
        })

        result = compute_extraction_quality(db, "onto_1")

        assert result["acceptance_rate"] is None
        assert result["time_to_ontology_ms"] is None

    def test_missing_curation_collection(self):
        from app.services.quality_metrics import compute_extraction_quality

        db = MagicMock()
        db.has_collection.return_value = False

        result = compute_extraction_quality(db, "onto_1")

        assert result["acceptance_rate"] is None
        assert result["time_to_ontology_ms"] is None


class TestComputeQualitySummary:
    """Tests for compute_quality_summary."""

    @patch("app.services.quality_metrics.compute_ontology_quality")
    def test_aggregates_across_ontologies(self, mock_oq):
        from app.services.quality_metrics import compute_quality_summary

        mock_oq.side_effect = [
            {
                "ontology_id": "a",
                "avg_confidence": 0.8,
                "avg_faithfulness": 0.9,
                "avg_semantic_validity": 0.85,
                "class_count": 10,
                "property_count": 5,
                "completeness": 80.0,
                "connectivity": 60.0,
                "relationship_count": 3,
                "orphan_count": 1,
                "has_cycles": False,
                "classes_without_properties": 2,
                "health_score": 75,
                "schema_metrics": {},
            },
            {
                "ontology_id": "b",
                "avg_confidence": 0.6,
                "avg_faithfulness": 0.7,
                "avg_semantic_validity": 0.65,
                "class_count": 4,
                "property_count": 2,
                "completeness": 50.0,
                "connectivity": 25.0,
                "relationship_count": 1,
                "orphan_count": 0,
                "has_cycles": True,
                "classes_without_properties": 2,
                "health_score": 45,
                "schema_metrics": {},
            },
        ]

        db = MagicMock()
        db.has_collection.return_value = True
        db.aql.execute.return_value = iter(["a", "b"])

        result = compute_quality_summary(db)

        assert result["ontology_count"] == 2
        assert result["total_classes"] == 14
        assert result["total_properties"] == 7
        assert result["avg_confidence"] == 0.7
        assert result["avg_faithfulness"] == 0.8
        assert result["avg_semantic_validity"] == 0.75
        assert result["avg_completeness"] == 65.0
        assert result["avg_health_score"] == 60
        assert result["ontologies_with_cycles"] == 1
        assert result["total_orphans"] == 1

    def test_empty_summary(self):
        from app.services.quality_metrics import compute_quality_summary

        db = MagicMock()
        db.has_collection.return_value = False

        result = compute_quality_summary(db)

        assert result["ontology_count"] == 0
        assert result["total_classes"] == 0
        assert result["avg_confidence"] is None


class TestCountOrphans:
    """Tests for _count_orphans."""

    def test_all_connected_returns_zero(self):
        from app.services.quality_metrics import _count_orphans

        db = _mock_db({
            0: [0],  # orphan count query returns 0
        })

        assert _count_orphans(db, "onto_1") == 0

    def test_no_subclass_of_collection(self):
        from app.services.quality_metrics import _count_orphans

        db = MagicMock()
        db.has_collection.side_effect = lambda n: n == "ontology_classes"
        db.aql.execute.return_value = iter([3])

        result = _count_orphans(db, "onto_1")

        assert result == 3


class TestDetectCycles:
    """Tests for _detect_cycles."""

    def test_no_cycle(self):
        from app.services.quality_metrics import _detect_cycles

        db = _mock_db({0: [], 1: []})

        assert _detect_cycles(db, "onto_1") is False

    def test_cycle_detected(self):
        from app.services.quality_metrics import _detect_cycles

        db = _mock_db({0: [True]})

        assert _detect_cycles(db, "onto_1") is True

    def test_missing_collections(self):
        from app.services.quality_metrics import _detect_cycles

        db = MagicMock()
        db.has_collection.return_value = False

        assert _detect_cycles(db, "onto_1") is False


class TestComputeHealthScore:
    """Tests for compute_health_score."""

    def test_perfect_ontology(self):
        from app.services.quality_metrics import compute_health_score

        score = compute_health_score(
            completeness=1.0,
            has_cycles=False,
            orphan_count=0,
            total_classes=10,
            avg_confidence=0.9,
            total_properties=30,
            chunk_count=5,
            connectivity=0.8,
        )
        assert score >= 80

    def test_poor_ontology(self):
        from app.services.quality_metrics import compute_health_score

        score = compute_health_score(
            completeness=0.1,
            has_cycles=True,
            orphan_count=8,
            total_classes=10,
            avg_confidence=0.2,
            total_properties=1,
            chunk_count=0,
            connectivity=0.0,
        )
        assert score < 30

    def test_score_bounded_0_to_100(self):
        from app.services.quality_metrics import compute_health_score

        score_max = compute_health_score(
            completeness=1.0,
            has_cycles=False,
            orphan_count=0,
            total_classes=10,
            avg_confidence=1.0,
            total_properties=50,
            chunk_count=100,
            connectivity=1.0,
        )
        assert 0 <= score_max <= 100

        score_min = compute_health_score(
            completeness=0.0,
            has_cycles=True,
            orphan_count=10,
            total_classes=10,
            avg_confidence=0.0,
            total_properties=0,
            chunk_count=0,
            connectivity=0.0,
        )
        assert 0 <= score_min <= 100

    def test_cycles_penalize_score(self):
        from app.services.quality_metrics import compute_health_score

        score_no_cycle = compute_health_score(
            completeness=0.8,
            has_cycles=False,
            orphan_count=0,
            total_classes=10,
            avg_confidence=0.7,
            total_properties=15,
            chunk_count=3,
            connectivity=0.5,
        )
        score_with_cycle = compute_health_score(
            completeness=0.8,
            has_cycles=True,
            orphan_count=0,
            total_classes=10,
            avg_confidence=0.7,
            total_properties=15,
            chunk_count=3,
            connectivity=0.5,
        )
        assert score_no_cycle > score_with_cycle

    def test_orphans_penalize_score(self):
        from app.services.quality_metrics import compute_health_score

        score_connected = compute_health_score(
            completeness=0.8,
            has_cycles=False,
            orphan_count=0,
            total_classes=10,
            avg_confidence=0.7,
            total_properties=15,
            chunk_count=3,
            connectivity=0.5,
        )
        score_orphans = compute_health_score(
            completeness=0.8,
            has_cycles=False,
            orphan_count=5,
            total_classes=10,
            avg_confidence=0.7,
            total_properties=15,
            chunk_count=3,
            connectivity=0.5,
        )
        assert score_connected > score_orphans

    def test_completeness_as_percentage_handled(self):
        """completeness > 1.0 is treated as percentage (e.g. 80.0 = 80%)."""
        from app.services.quality_metrics import compute_health_score

        score = compute_health_score(
            completeness=80.0,
            has_cycles=False,
            orphan_count=0,
            total_classes=10,
            avg_confidence=0.7,
            total_properties=15,
            chunk_count=3,
            connectivity=0.5,
        )
        assert 50 <= score <= 100

    def test_connectivity_improves_score(self):
        from app.services.quality_metrics import compute_health_score

        score_no_conn = compute_health_score(
            completeness=0.8,
            has_cycles=False,
            orphan_count=0,
            total_classes=10,
            avg_confidence=0.7,
            total_properties=15,
            chunk_count=3,
            connectivity=0.0,
        )
        score_with_conn = compute_health_score(
            completeness=0.8,
            has_cycles=False,
            orphan_count=0,
            total_classes=10,
            avg_confidence=0.7,
            total_properties=15,
            chunk_count=3,
            connectivity=0.8,
        )
        assert score_with_conn > score_no_conn
