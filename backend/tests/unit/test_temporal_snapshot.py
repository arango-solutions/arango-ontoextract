"""Unit tests for temporal snapshot, diff, timeline, and revert — all DB mocked."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.temporal import NEVER_EXPIRES


class TestGetSnapshot:
    def test_returns_classes_properties_edges_at_timestamp(self):
        from app.services.temporal import get_snapshot

        cls_doc = {
            "_key": "c1",
            "_id": "ontology_classes/c1",
            "uri": "http://ex.org#A",
            "label": "A",
            "ontology_id": "onto1",
            "created": 100.0,
            "expired": NEVER_EXPIRES,
        }
        prop_doc = {
            "_key": "p1",
            "_id": "ontology_properties/p1",
            "uri": "http://ex.org#prop1",
            "label": "prop1",
            "ontology_id": "onto1",
            "created": 100.0,
            "expired": NEVER_EXPIRES,
        }
        edge_doc = {
            "_from": "ontology_classes/c1",
            "_to": "ontology_properties/p1",
            "created": 100.0,
            "expired": NEVER_EXPIRES,
        }

        mock_db = MagicMock()
        mock_db.has_collection.return_value = True

        def mock_execute(query, bind_vars=None):
            col = bind_vars.get("@col", "")
            if col == "ontology_classes":
                return iter([cls_doc])
            if col == "ontology_properties":
                return iter([prop_doc])
            if col in ("ontology_object_properties", "ontology_datatype_properties"):
                return iter([])
            return iter([edge_doc])

        mock_db.aql.execute = mock_execute

        result = get_snapshot(mock_db, ontology_id="onto1", timestamp=200.0)

        assert result["ontology_id"] == "onto1"
        assert len(result["classes"]) == 1
        assert len(result["properties"]) == 1
        assert len(result["edges"]) >= 1

    def test_returns_empty_when_no_collections(self):
        from app.services.temporal import get_snapshot

        mock_db = MagicMock()
        mock_db.has_collection.return_value = False

        result = get_snapshot(mock_db, ontology_id="onto_missing", timestamp=200.0)

        assert result["classes"] == []
        assert result["properties"] == []
        assert result["edges"] == []


class TestGetEntityHistory:
    def test_returns_all_versions_sorted_desc(self):
        from app.services.temporal import get_entity_history

        v1 = {"_key": "k1", "uri": "http://ex.org#A", "label": "A v1", "created": 100.0}
        v2 = {"_key": "k2", "uri": "http://ex.org#A", "label": "A v2", "created": 200.0}

        mock_db = MagicMock()
        mock_db.has_collection.return_value = True

        call_count = [0]

        def mock_execute(query, bind_vars=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return iter(["http://ex.org#A"])
            return iter([v2, v1])

        mock_db.aql.execute = mock_execute

        result = get_entity_history(mock_db, collection="ontology_classes", key="k1")

        assert len(result) == 2
        assert result[0]["label"] == "A v2"

    def test_returns_empty_for_missing_collection(self):
        from app.services.temporal import get_entity_history

        mock_db = MagicMock()
        mock_db.has_collection.return_value = False

        result = get_entity_history(mock_db, collection="missing_col", key="k1")
        assert result == []

    def test_returns_empty_when_uri_not_found(self):
        from app.services.temporal import get_entity_history

        mock_db = MagicMock()
        mock_db.has_collection.return_value = True
        mock_db.aql.execute.return_value = iter([None])

        result = get_entity_history(mock_db, collection="ontology_classes", key="k1")
        assert result == []


class TestGetDiff:
    def test_detects_added_removed_changed(self):
        from app.services.temporal import get_diff

        doc_a = {
            "_key": "a",
            "uri": "http://ex.org#A",
            "label": "A",
            "ontology_id": "o1",
        }
        doc_b_v1 = {
            "_key": "b",
            "uri": "http://ex.org#B",
            "label": "B v1",
            "ontology_id": "o1",
        }
        doc_b_v2 = {
            "_key": "b2",
            "uri": "http://ex.org#B",
            "label": "B v2",
            "ontology_id": "o1",
        }
        doc_c = {
            "_key": "c",
            "uri": "http://ex.org#C",
            "label": "C",
            "ontology_id": "o1",
        }

        mock_db = MagicMock()
        mock_db.has_collection.return_value = True

        call_count = [0]

        def mock_execute(query, bind_vars=None):
            call_count[0] += 1
            ts = bind_vars.get("ts")
            col = bind_vars.get("@col", "")

            if col == "ontology_classes":
                if ts == 100.0:
                    return iter([doc_a, doc_b_v1])
                else:
                    return iter([doc_b_v2, doc_c])
            return iter([])

        mock_db.aql.execute = mock_execute

        result = get_diff(mock_db, ontology_id="o1", t1=100.0, t2=200.0)

        assert len(result["added"]) == 1
        assert result["added"][0]["uri"] == "http://ex.org#C"
        assert len(result["removed"]) == 1
        assert result["removed"][0]["uri"] == "http://ex.org#A"
        assert len(result["changed"]) == 1
        assert result["changed"][0]["after"]["label"] == "B v2"


class TestGetTimelineEvents:
    def test_returns_sorted_events(self):
        from app.services.temporal import get_timeline_events

        events_data = [
            {
                "timestamp": 200.0,
                "event_type": "edit",
                "entity_key": "k2",
                "entity_label": "B",
                "collection": "ontology_classes",
                "change_summary": "edited",
            },
            {
                "timestamp": 100.0,
                "event_type": "initial",
                "entity_key": "k1",
                "entity_label": "A",
                "collection": "ontology_classes",
                "change_summary": "created",
            },
        ]

        mock_db = MagicMock()
        mock_db.has_collection.return_value = True
        mock_db.aql.execute.return_value = iter(events_data)

        result = get_timeline_events(mock_db, ontology_id="o1")

        assert len(result) >= 1
        assert result[0]["timestamp"] <= result[-1]["timestamp"]


class TestRevertToVersion:
    @patch("app.services.temporal.update_entity")
    @patch("app.services.temporal._find_current_key")
    def test_creates_new_version_from_historical(self, mock_find_key, mock_update):
        from app.services.temporal import revert_to_version

        mock_db = MagicMock()
        mock_db.has_collection.return_value = True

        historical_doc = {
            "_key": "old_k",
            "_id": "ontology_classes/old_k",
            "uri": "http://ex.org#A",
            "label": "A original",
            "ontology_id": "o1",
            "created": 100.0,
            "expired": 200.0,
            "version": 1,
            "status": "approved",
            "created_by": "user_a",
            "change_type": "initial",
            "change_summary": "Created",
        }
        mock_db.aql.execute.return_value = iter([historical_doc])
        mock_find_key.return_value = "current_k"
        mock_update.return_value = {
            "_key": "reverted_k",
            "label": "A original",
            "version": 3,
            "change_type": "revert",
        }

        result = revert_to_version(
            mock_db,
            collection="ontology_classes",
            key="old_k",
            version_created_ts=100.0,
        )

        assert result["change_type"] == "revert"
        mock_update.assert_called_once()
        revert_data = mock_update.call_args.kwargs["new_data"]
        assert revert_data["label"] == "A original"
        assert "created" not in revert_data
        assert "_key" not in revert_data

    def test_raises_when_historical_version_not_found(self):
        from app.services.temporal import revert_to_version

        mock_db = MagicMock()
        mock_db.aql.execute.return_value = iter([])
        mock_db.has_collection.return_value = True

        uri_lookup = MagicMock()
        uri_lookup.return_value = iter([None])

        with (
            patch("app.services.temporal.get_entity_history", return_value=[]),
            pytest.raises(ValueError, match="No version found"),
        ):
            revert_to_version(
                mock_db,
                collection="ontology_classes",
                key="k1",
                version_created_ts=999.0,
            )


class TestHasDataChanged:
    def test_detects_label_change(self):
        from app.services.temporal import _has_data_changed

        old = {"_key": "k1", "label": "A", "uri": "http://ex.org#A"}
        new = {"_key": "k2", "label": "B", "uri": "http://ex.org#A"}
        assert _has_data_changed(old, new) is True

    def test_ignores_metadata_fields(self):
        from app.services.temporal import _has_data_changed

        old = {
            "_key": "k1",
            "label": "A",
            "created": 100.0,
            "expired": 200.0,
            "version": 1,
        }
        new = {
            "_key": "k2",
            "label": "A",
            "created": 200.0,
            "expired": NEVER_EXPIRES,
            "version": 2,
        }
        assert _has_data_changed(old, new) is False

    def test_same_data_returns_false(self):
        from app.services.temporal import _has_data_changed

        doc = {"label": "A", "uri": "http://ex.org#A", "ontology_id": "o1"}
        assert _has_data_changed(doc, dict(doc)) is False
