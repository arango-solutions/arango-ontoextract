"""Integration tests for temporal versioning — requires running ArangoDB."""

from __future__ import annotations

import time

import pytest

from app.services.temporal import (
    NEVER_EXPIRES,
    create_version,
    expire_entity,
    get_at_timestamp,
    get_current,
    get_diff,
    get_entity_history,
    get_snapshot,
    get_timeline_events,
    revert_to_version,
    update_entity,
)


def _ensure_collection(db, name: str, edge: bool = False) -> None:
    if not db.has_collection(name):
        db.create_collection(name, edge=edge)


@pytest.mark.integration
class TestTemporalVersioning:
    """Temporal versioning integration tests against real ArangoDB."""

    def test_create_version_inserts_with_temporal_fields(self, test_db):
        _ensure_collection(test_db, "ontology_classes")

        doc = create_version(
            test_db,
            collection="ontology_classes",
            data={
                "uri": "http://ex.org/test#ClassA",
                "label": "Class A",
                "description": "Test class A",
            },
            created_by="test_user",
            change_type="initial",
        )

        assert doc["expired"] == NEVER_EXPIRES
        assert doc["created"] > 0
        assert doc["created_by"] == "test_user"
        assert doc["change_type"] == "initial"
        assert doc["version"] == 1

    def test_expire_entity_sets_expired(self, test_db):
        _ensure_collection(test_db, "ontology_classes")

        doc = create_version(
            test_db,
            collection="ontology_classes",
            data={"uri": "http://ex.org/test#ToExpire", "label": "To Expire"},
        )

        expired = expire_entity(
            test_db,
            collection="ontology_classes",
            key=doc["_key"],
        )

        assert expired is not None
        assert expired["expired"] != NEVER_EXPIRES
        assert expired["expired"] > 0

    def test_get_current_returns_unexpired(self, test_db):
        _ensure_collection(test_db, "ontology_classes")

        doc = create_version(
            test_db,
            collection="ontology_classes",
            data={"uri": "http://ex.org/test#Current", "label": "Current"},
        )

        current = get_current(
            test_db,
            collection="ontology_classes",
            key=doc["_key"],
        )
        assert current is not None
        assert current["_key"] == doc["_key"]

    def test_get_current_returns_none_for_expired(self, test_db):
        _ensure_collection(test_db, "ontology_classes")

        doc = create_version(
            test_db,
            collection="ontology_classes",
            data={"uri": "http://ex.org/test#WillExpire", "label": "Will Expire"},
        )
        expire_entity(test_db, collection="ontology_classes", key=doc["_key"])

        current = get_current(
            test_db,
            collection="ontology_classes",
            key=doc["_key"],
        )
        assert current is None

    def test_update_entity_creates_new_version(self, test_db):
        _ensure_collection(test_db, "ontology_classes")

        doc = create_version(
            test_db,
            collection="ontology_classes",
            data={
                "uri": "http://ex.org/test#Updatable",
                "label": "Original Name",
            },
        )
        original_key = doc["_key"]

        time.sleep(0.01)

        new_doc = update_entity(
            test_db,
            collection="ontology_classes",
            key=original_key,
            new_data={"label": "Updated Name"},
            created_by="editor",
            change_type="edit",
            change_summary="Renamed from Original to Updated",
        )

        assert new_doc["label"] == "Updated Name"
        assert new_doc["version"] == 2
        assert new_doc["change_type"] == "edit"
        assert new_doc["_key"] != original_key

        old = get_current(test_db, collection="ontology_classes", key=original_key)
        assert old is None

    def test_point_in_time_query(self, test_db):
        _ensure_collection(test_db, "ontology_classes")

        t0 = time.time()
        time.sleep(0.01)

        v1 = create_version(
            test_db,
            collection="ontology_classes",
            data={
                "uri": "http://ex.org/test#TimeTravelClass",
                "label": "Version 1",
                "ontology_id": "time_test",
            },
        )

        t1 = time.time()
        time.sleep(0.01)

        expire_entity(test_db, collection="ontology_classes", key=v1["_key"])

        create_version(
            test_db,
            collection="ontology_classes",
            data={
                "uri": "http://ex.org/test#TimeTravelClass",
                "label": "Version 2",
                "ontology_id": "time_test",
            },
        )

        t2 = time.time()

        results_at_t0 = get_at_timestamp(
            test_db,
            collection="ontology_classes",
            timestamp=t0,
            filters={"ontology_id": "time_test"},
        )
        assert len(results_at_t0) == 0

        results_at_t1 = get_at_timestamp(
            test_db,
            collection="ontology_classes",
            timestamp=t1,
            filters={"ontology_id": "time_test"},
        )
        assert len(results_at_t1) == 1
        assert results_at_t1[0]["label"] == "Version 1"

        results_at_t2 = get_at_timestamp(
            test_db,
            collection="ontology_classes",
            timestamp=t2,
            filters={"ontology_id": "time_test"},
        )
        assert len(results_at_t2) == 1
        assert results_at_t2[0]["label"] == "Version 2"


@pytest.mark.integration
class TestTemporalSnapshot:
    """Snapshot, diff, timeline, and revert integration tests."""

    def test_snapshot_returns_active_entities(self, test_db):
        _ensure_collection(test_db, "ontology_classes")
        _ensure_collection(test_db, "ontology_properties")
        for edge_name in (
            "subclass_of", "has_property", "equivalent_class",
            "extends_domain", "related_to",
        ):
            _ensure_collection(test_db, edge_name, edge=True)

        t_before = time.time()
        time.sleep(0.01)

        create_version(
            test_db,
            collection="ontology_classes",
            data={
                "uri": "http://ex.org/snap#ClassA",
                "label": "Snap A",
                "ontology_id": "snap_test",
            },
        )
        create_version(
            test_db,
            collection="ontology_classes",
            data={
                "uri": "http://ex.org/snap#ClassB",
                "label": "Snap B",
                "ontology_id": "snap_test",
            },
        )
        t_after = time.time()

        snapshot = get_snapshot(test_db, ontology_id="snap_test", timestamp=t_after)
        assert len(snapshot["classes"]) == 2

        snapshot_before = get_snapshot(test_db, ontology_id="snap_test", timestamp=t_before)
        assert len(snapshot_before["classes"]) == 0

    def test_entity_history_returns_all_versions(self, test_db):
        _ensure_collection(test_db, "ontology_classes")

        v1 = create_version(
            test_db,
            collection="ontology_classes",
            data={
                "uri": "http://ex.org/hist#ClassH",
                "label": "V1",
                "ontology_id": "hist_test",
            },
        )
        time.sleep(0.01)

        expire_entity(test_db, collection="ontology_classes", key=v1["_key"])
        v2 = create_version(
            test_db,
            collection="ontology_classes",
            data={
                "uri": "http://ex.org/hist#ClassH",
                "label": "V2",
                "ontology_id": "hist_test",
            },
        )
        time.sleep(0.01)

        expire_entity(test_db, collection="ontology_classes", key=v2["_key"])
        create_version(
            test_db,
            collection="ontology_classes",
            data={
                "uri": "http://ex.org/hist#ClassH",
                "label": "V3",
                "ontology_id": "hist_test",
            },
        )

        history = get_entity_history(
            test_db, collection="ontology_classes", key=v1["_key"]
        )

        assert len(history) == 3
        assert history[0]["label"] == "V3"
        assert history[2]["label"] == "V1"

    def test_diff_detects_additions_and_removals(self, test_db):
        _ensure_collection(test_db, "ontology_classes")

        time.sleep(0.01)

        v1 = create_version(
            test_db,
            collection="ontology_classes",
            data={
                "uri": "http://ex.org/diff#OnlyT1",
                "label": "Only at t1",
                "ontology_id": "diff_test",
            },
        )

        t1 = time.time()
        time.sleep(0.01)

        expire_entity(test_db, collection="ontology_classes", key=v1["_key"])

        create_version(
            test_db,
            collection="ontology_classes",
            data={
                "uri": "http://ex.org/diff#OnlyT2",
                "label": "Only at t2",
                "ontology_id": "diff_test",
            },
        )

        t2 = time.time()

        diff = get_diff(test_db, ontology_id="diff_test", t1=t1, t2=t2)

        added_uris = [d["uri"] for d in diff["added"]]
        removed_uris = [d["uri"] for d in diff["removed"]]
        assert "http://ex.org/diff#OnlyT2" in added_uris
        assert "http://ex.org/diff#OnlyT1" in removed_uris

    def test_timeline_events_chronological(self, test_db):
        _ensure_collection(test_db, "ontology_classes")

        create_version(
            test_db,
            collection="ontology_classes",
            data={
                "uri": "http://ex.org/tl#First",
                "label": "First",
                "ontology_id": "tl_test",
            },
            change_type="initial",
        )
        time.sleep(0.01)
        create_version(
            test_db,
            collection="ontology_classes",
            data={
                "uri": "http://ex.org/tl#Second",
                "label": "Second",
                "ontology_id": "tl_test",
            },
            change_type="initial",
        )

        events = get_timeline_events(test_db, ontology_id="tl_test")

        tl_events = [e for e in events if e.get("collection") == "ontology_classes"
                      and "tl_test" in str(e)]
        assert len(tl_events) >= 2
        for i in range(len(tl_events) - 1):
            assert tl_events[i]["timestamp"] <= tl_events[i + 1]["timestamp"]

    def test_revert_creates_new_version_from_historical(self, test_db):
        _ensure_collection(test_db, "ontology_classes")

        v1 = create_version(
            test_db,
            collection="ontology_classes",
            data={
                "uri": "http://ex.org/revert#ClassR",
                "label": "Original",
                "ontology_id": "revert_test",
                "status": "approved",
            },
            created_by="user_1",
            change_type="initial",
        )
        v1_created = v1["created"]
        time.sleep(0.01)

        update_entity(
            test_db,
            collection="ontology_classes",
            key=v1["_key"],
            new_data={"label": "Modified"},
            created_by="user_2",
            change_type="edit",
        )
        time.sleep(0.01)

        reverted = revert_to_version(
            test_db,
            collection="ontology_classes",
            key=v1["_key"],
            version_created_ts=v1_created,
        )

        assert reverted["label"] == "Original"
        assert reverted["version"] == 3
        assert reverted["change_type"] == "revert"

        history = get_entity_history(
            test_db, collection="ontology_classes", key=v1["_key"]
        )
        assert len(history) == 3
