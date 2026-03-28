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

        v2 = create_version(
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
