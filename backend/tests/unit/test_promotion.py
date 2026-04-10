"""Unit tests for promotion service — all DB operations mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.temporal import NEVER_EXPIRES


class TestPromoteStaging:
    """Tests for promotion_svc.promote_staging."""

    @patch("app.services.promotion._promote_edges")
    @patch("app.services.promotion._promote_entity")
    @patch("app.services.promotion._get_non_approved_staging_entities")
    @patch("app.services.promotion._get_approved_staging_entities")
    def test_promotes_approved_entities(
        self, mock_approved, mock_non_approved, mock_promote_entity, mock_promote_edges
    ):
        from app.services.promotion import promote_staging

        approved_class = {
            "_key": "cls1",
            "_id": "ontology_classes/cls1",
            "label": "ClassA",
            "status": "approved",
            "ontology_id": "extraction_run_1",
        }
        # One entry per vertex collection in promote_staging (classes + 3 property cols)
        mock_approved.side_effect = [
            [approved_class],
            [],
            [],
            [],
        ]
        mock_non_approved.side_effect = [[], [], [], []]
        mock_promote_entity.return_value = {
            "_key": "prod_cls1",
            "_id": "ontology_classes/prod_cls1",
        }
        mock_promote_edges.return_value = 0

        mock_db = MagicMock()
        mock_db.has_collection.return_value = True

        report = promote_staging(mock_db, run_id="run_1")

        assert report["promoted_count"] == 1
        assert report["skipped_count"] == 0
        assert report["error_count"] == 0
        assert report["status"] == "completed"
        mock_promote_entity.assert_called_once()

    @patch("app.services.promotion._promote_edges")
    @patch("app.services.promotion._promote_entity")
    @patch("app.services.promotion._get_non_approved_staging_entities")
    @patch("app.services.promotion._get_approved_staging_entities")
    def test_counts_skipped_non_approved(
        self, mock_approved, mock_non_approved, mock_promote_entity, mock_promote_edges
    ):
        from app.services.promotion import promote_staging

        mock_approved.side_effect = [[], [], [], []]
        mock_non_approved.side_effect = [
            [
                {"_key": "cls_draft", "status": "draft"},
                {"_key": "cls_rejected", "status": "rejected"},
            ],
            [],
            [],
            [],
        ]
        mock_promote_edges.return_value = 0

        mock_db = MagicMock()
        mock_db.has_collection.return_value = True

        report = promote_staging(mock_db, run_id="run_2")

        assert report["promoted_count"] == 0
        assert report["skipped_count"] == 2
        assert report["error_count"] == 0

    @patch("app.services.promotion._promote_edges")
    @patch("app.services.promotion._promote_entity")
    @patch("app.services.promotion._get_non_approved_staging_entities")
    @patch("app.services.promotion._get_approved_staging_entities")
    def test_captures_promotion_errors(
        self, mock_approved, mock_non_approved, mock_promote_entity, mock_promote_edges
    ):
        from app.services.promotion import promote_staging

        mock_approved.side_effect = [
            [{"_key": "bad_cls", "_id": "ontology_classes/bad_cls", "status": "approved"}],
            [],
            [],
            [],
        ]
        mock_non_approved.side_effect = [[], [], [], []]
        mock_promote_entity.side_effect = Exception("DB write failure")
        mock_promote_edges.return_value = 0

        mock_db = MagicMock()
        mock_db.has_collection.return_value = True

        report = promote_staging(mock_db, run_id="run_3")

        assert report["promoted_count"] == 0
        assert report["error_count"] == 1
        assert len(report["errors"]) == 1

    @patch("app.services.promotion._promote_edges")
    @patch("app.services.promotion._promote_entity")
    @patch("app.services.promotion._get_non_approved_staging_entities")
    @patch("app.services.promotion._get_approved_staging_entities")
    def test_uses_custom_ontology_id(
        self, mock_approved, mock_non_approved, mock_promote_entity, mock_promote_edges
    ):
        from app.services.promotion import promote_staging

        mock_approved.side_effect = [[], [], [], []]
        mock_non_approved.side_effect = [[], [], [], []]
        mock_promote_edges.return_value = 0

        mock_db = MagicMock()
        mock_db.has_collection.return_value = True

        report = promote_staging(mock_db, run_id="run_4", ontology_id="custom_onto")

        assert report["ontology_id"] == "custom_onto"


class TestGetPromotionStatus:
    def test_returns_none_when_not_run(self):
        from app.services.promotion import get_promotion_status

        assert get_promotion_status("nonexistent_run") is None


class TestPromoteEntity:
    @patch("app.services.promotion.create_version")
    def test_creates_production_version(self, mock_create):
        from app.services.promotion import _promote_entity

        mock_create.return_value = {
            "_key": "prod_1",
            "_id": "ontology_classes/prod_1",
            "ontology_id": "target_onto",
            "status": "approved",
        }

        mock_db = MagicMock()
        entity = {
            "_key": "stg_1",
            "_id": "ontology_classes/stg_1",
            "_rev": "rev1",
            "uri": "http://ex.org#ClassA",
            "label": "Class A",
            "ontology_id": "extraction_run_1",
            "status": "approved",
            "created": 1700000000.0,
            "expired": NEVER_EXPIRES,
            "version": 2,
            "ttlExpireAt": None,
        }

        result = _promote_entity(
            mock_db,
            collection="ontology_classes",
            entity=entity,
            target_ontology_id="target_onto",
        )

        assert result["_key"] == "prod_1"
        create_call_data = mock_create.call_args.kwargs["data"]
        assert create_call_data["ontology_id"] == "target_onto"
        assert create_call_data["status"] == "approved"
        assert "_key" not in create_call_data
        assert "created" not in create_call_data


class TestPromoteEdges:
    def test_skips_edges_with_no_promoted_endpoints(self):
        from app.services.promotion import _promote_edges

        mock_db = MagicMock()
        mock_db.has_collection.return_value = True
        mock_db.aql.execute.return_value = iter(
            [
                {
                    "_from": "ontology_classes/unknown",
                    "_to": "ontology_classes/other",
                    "created": 1700000000.0,
                    "expired": NEVER_EXPIRES,
                }
            ]
        )

        count = _promote_edges(mock_db, key_map={})
        assert count == 0

    def test_returns_zero_for_empty_key_map(self):
        from app.services.promotion import _promote_edges

        mock_db = MagicMock()
        count = _promote_edges(mock_db, key_map={})
        assert count == 0
