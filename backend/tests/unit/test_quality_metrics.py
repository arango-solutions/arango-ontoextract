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


def _mock_db_selective(collections: set[str], aql_results: dict | None = None):
    """Create a mock DB where only *collections* exist."""
    db = MagicMock()
    db.has_collection.side_effect = lambda name: name in collections

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

    def test_returns_metrics_for_populated_ontology_pgt(self):
        """PGT path: uses rdfs_domain / rdfs_range_class / split property collections."""
        from app.services.quality_metrics import compute_ontology_quality

        # Query order with PGT (all collections present):
        # 0: class stats
        # 1: datatype property count
        # 2: object property count
        # 3: completeness (rdfs_domain distinct _to classes)
        # 4: orphan count
        # 5: cycle check
        # 6: relationship count (rdfs_range_class)
        # 7: classes with relationships (UNION_DISTINCT)
        # 8: chunk count
        # 9: subclass_of edge count
        db = _mock_db({
            0: [{"cnt": 5, "avg_conf": 0.85, "avg_faith": 0.8, "avg_sem": 0.9}],
            1: [2],     # datatype properties
            2: [1],     # object properties
            3: [4],     # classes with ≥1 rdfs_domain edge
            4: [0],     # orphan count
            5: [],      # cycle check (no cycles)
            6: [2],     # rdfs_range_class edges
            7: [3],     # classes involved in relationships
            8: [2],     # chunk count
            9: [0],     # subclass_of edge count
        })

        result = compute_ontology_quality(db, "onto_1")

        assert result["ontology_id"] == "onto_1"
        assert result["avg_confidence"] == 0.85
        assert result["class_count"] == 5
        assert result["property_count"] == 3   # 2 dt + 1 obj
        assert result["completeness"] == 80.0   # 4/5 * 100
        assert result["classes_without_properties"] == 1
        assert result["connectivity"] == 60.0   # 3/5 * 100
        assert result["schema_metrics"] is not None
        assert result["health_score"] is not None
        assert 0 <= result["health_score"] <= 100

    def test_backward_compat_uses_old_collections(self):
        """When PGT collections are absent, falls back to has_property / related_to."""
        from app.services.quality_metrics import compute_ontology_quality

        old_collections = {
            "ontology_classes", "ontology_properties",
            "has_property", "related_to",
            "subclass_of", "has_chunk",
            "ontology_registry", "extraction_runs",
        }
        # Query order for legacy path:
        # 0: class stats
        # 1: property count (ontology_properties)
        # 2: classes with props (has_property)
        # 3: orphan count
        # 4: cycle check
        # 5: related_to count
        # 6: classes_with_relationships
        # 7: chunk count
        # 8: subclass_of edge count
        db = _mock_db_selective(old_collections, {
            0: [{"cnt": 5, "avg_conf": 0.85, "avg_faith": 0.8, "avg_sem": 0.9}],
            1: [3],     # property count
            2: [4],     # classes with props
            3: [0],     # orphan count
            4: [],      # cycle check
            5: [2],     # related_to count
            6: [3],     # classes_with_relationships
            7: [2],     # chunk count
            8: [0],     # subclass_of edge count
        })

        result = compute_ontology_quality(db, "onto_1")

        assert result["class_count"] == 5
        assert result["property_count"] == 3
        assert result["completeness"] == 80.0
        assert result["connectivity"] == 60.0

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

    def test_cost_lookup_skips_quality_enrichment(self):
        from app.services.quality_metrics import compute_ontology_quality

        mock_get_run_cost = MagicMock(return_value={"estimated_cost": 1.234567})

        # PGT path, class_count=0 → completeness/connectivity skipped
        # 0: class stats (cnt=0)
        # 1: dt prop count
        # 2: obj prop count
        # 3: orphan query
        # 4: cycle check
        # 5: chunk count
        # 6: subclass_of edge count
        # 7: registry lookup
        db = _mock_db({
            0: [{"cnt": 0, "avg_conf": None, "avg_faith": None, "avg_sem": None}],
            1: [0],     # dt prop count
            2: [0],     # obj prop count
            3: [0],     # orphan count
            4: [],      # cycle check
            5: [0],     # chunk count
            6: [0],     # subclass_of edge count
            7: [{"run_id": "run_1", "name": "Ontology 1", "tier": "domain"}],
        })

        import sys
        fake_extraction = MagicMock()
        fake_extraction.get_run_cost = mock_get_run_cost
        with patch.dict(sys.modules, {"app.services.extraction": fake_extraction}):
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


class TestQualityReportHistory:
    def test_compute_quality_report_records_snapshot(self):
        from app.services import quality_metrics

        db = MagicMock()
        with (
            patch.object(
                quality_metrics,
                "compute_ontology_quality",
                return_value={"ontology_id": "onto_1", "health_score": 82},
            ) as mock_ontology,
            patch.object(
                quality_metrics,
                "compute_extraction_quality",
                return_value={"acceptance_rate": 0.75},
            ) as mock_extraction,
            patch.object(
                quality_metrics.quality_history_repo,
                "save_quality_snapshot",
                return_value={"_key": "snap1"},
            ) as mock_save,
        ):
            result = quality_metrics.compute_quality_report(db, "onto_1")

        assert result == {
            "ontology_id": "onto_1",
            "health_score": 82,
            "acceptance_rate": 0.75,
        }
        mock_ontology.assert_called_once_with(db, "onto_1")
        mock_extraction.assert_called_once_with(db, "onto_1")
        mock_save.assert_called_once_with("onto_1", result, db=db)

    def test_get_quality_history_delegates_to_repository(self):
        from app.services import quality_metrics

        db = MagicMock()
        snapshots = [{"timestamp": "2026-04-28T00:00:00+00:00", "health_score": 80}]
        with patch.object(
            quality_metrics.quality_history_repo,
            "list_quality_history",
            return_value=snapshots,
        ) as mock_list:
            result = quality_metrics.get_quality_history(db, "onto_1", limit=10)

        assert result == {
            "ontology_id": "onto_1",
            "count": 1,
            "snapshots": snapshots,
        }
        mock_list.assert_called_once_with("onto_1", limit=10, db=db)


class TestComputeAssertionEvidenceMetrics:
    """Tests for assertion-level evidence coverage metrics."""

    def test_returns_evidence_coverage_by_assertion_type(self):
        from app.services.quality_metrics import compute_assertion_evidence_metrics

        db = _mock_db({
            0: [{"total": 4, "evidenced": 3}],  # classes
            1: [{"total": 2, "evidenced": 1}],  # attributes
            2: [{"total": 1, "evidenced": 1}],  # relationships
            3: [{"total": 3, "evidenced": 0}],  # subclass links
        })

        result = compute_assertion_evidence_metrics(db, "onto_1")

        assert result["total_assertions"] == 10
        assert result["evidenced_assertions"] == 5
        assert result["unsupported_assertions"] == 5
        assert result["evidence_coverage"] == 0.5
        assert result["by_type"]["classes"] == {
            "total": 4,
            "evidenced": 3,
            "coverage": 0.75,
        }
        assert result["by_type"]["subclass_links"] == {
            "total": 3,
            "evidenced": 0,
            "coverage": 0.0,
        }

    def test_handles_missing_assertion_collections(self):
        from app.services.quality_metrics import compute_assertion_evidence_metrics

        db = _mock_db_selective({"ontology_classes"}, {
            0: [{"total": 1, "evidenced": 0}],
        })

        result = compute_assertion_evidence_metrics(db, "onto_1")

        assert result["total_assertions"] == 1
        assert result["evidence_coverage"] == 0.0
        assert result["by_type"]["attributes"] == {
            "total": 0,
            "evidenced": 0,
            "coverage": None,
        }


class TestComputeConfidenceCalibrationMetrics:
    """Tests for confidence calibration from HITL decisions."""

    def test_returns_bucketed_calibration_metrics(self):
        from app.services.quality_metrics import compute_confidence_calibration_metrics

        db = _mock_db({
            0: [
                {
                    "bucket_id": 8,
                    "total": 10,
                    "accepted": 8,
                    "edited": 1,
                    "rejected": 1,
                    "avg_confidence": 0.82,
                },
                {
                    "bucket_id": 4,
                    "total": 5,
                    "accepted": 1,
                    "edited": 1,
                    "rejected": 3,
                    "avg_confidence": 0.45,
                },
            ],
        })

        result = compute_confidence_calibration_metrics(db, "onto_1")

        assert result["bucket_count"] == 2
        assert result["total_decisions"] == 15
        assert result["expected_calibration_error"] == 0.0967
        high_bucket = result["buckets"][1]
        assert high_bucket["bucket_min"] == 0.8
        assert high_bucket["bucket_max"] == 0.9
        assert high_bucket["acceptance_rate"] == 0.8
        assert high_bucket["calibration_error"] == 0.02

    def test_returns_empty_when_required_collections_missing(self):
        from app.services.quality_metrics import compute_confidence_calibration_metrics

        db = _mock_db_selective({"ontology_classes"})

        result = compute_confidence_calibration_metrics(db, "onto_1")

        assert result == {
            "bucket_count": 0,
            "total_decisions": 0,
            "expected_calibration_error": None,
            "buckets": [],
        }


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

        db = _mock_db({0: []})

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

    def test_completeness_clamped_to_1(self):
        """Values above 1.0 are clamped, not treated as percentages."""
        from app.services.quality_metrics import compute_health_score

        score_normal = compute_health_score(
            completeness=0.8,
            has_cycles=False,
            orphan_count=0,
            total_classes=10,
            avg_confidence=0.7,
            total_properties=15,
            chunk_count=3,
            connectivity=0.5,
        )
        score_over = compute_health_score(
            completeness=1.5,
            has_cycles=False,
            orphan_count=0,
            total_classes=10,
            avg_confidence=0.7,
            total_properties=15,
            chunk_count=3,
            connectivity=0.5,
        )
        score_at_1 = compute_health_score(
            completeness=1.0,
            has_cycles=False,
            orphan_count=0,
            total_classes=10,
            avg_confidence=0.7,
            total_properties=15,
            chunk_count=3,
            connectivity=0.5,
        )
        # Over-1.0 is clamped to 1.0, so same as completeness=1.0
        assert score_over == score_at_1
        assert score_at_1 >= score_normal

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
