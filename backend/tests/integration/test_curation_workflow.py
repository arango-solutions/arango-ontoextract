"""Integration test: curation workflow with real ArangoDB.

Tests the full path: record decision → verify in curation_decisions → promote → verify.
"""

from __future__ import annotations

import pytest

from app.db import curation_repo
from app.services import curation as curation_svc
from app.services import promotion as promotion_svc
from app.services.temporal import NEVER_EXPIRES, create_version


def _ensure_collections(db) -> None:
    for name in (
        "ontology_classes",
        "ontology_properties",
        "curation_decisions",
    ):
        if not db.has_collection(name):
            db.create_collection(name)
    for name in (
        "subclass_of",
        "has_property",
        "equivalent_class",
        "extends_domain",
        "related_to",
    ):
        if not db.has_collection(name):
            db.create_collection(name, edge=True)


def _seed_staging_class(db, *, run_id: str, label: str, uri: str) -> dict:
    """Create a staging-class entity for a given run."""
    return create_version(
        db,
        collection="ontology_classes",
        data={
            "uri": uri,
            "label": label,
            "ontology_id": f"extraction_{run_id}",
            "status": "draft",
            "tier": "domain",
        },
        created_by="test",
        change_type="initial",
    )


@pytest.mark.integration
class TestCurationWorkflow:
    """Full curation lifecycle against real ArangoDB."""

    def test_approve_creates_decision_and_temporal_version(self, test_db):
        _ensure_collections(test_db)

        entity = _seed_staging_class(
            test_db, run_id="wf_1", label="Approve Me", uri="http://ex.org#ApproveMe"
        )

        result = curation_svc.record_decision(
            test_db,
            run_id="wf_1",
            entity_key=entity["_key"],
            entity_type="class",
            action="approve",
            curator_id="curator_test",
            notes="Looks correct",
        )

        assert result["action"] == "approve"
        assert result["entity_key"] == entity["_key"]

        decision = curation_repo.get_decision(test_db, key=result["_key"])
        assert decision is not None
        assert decision["curator_id"] == "curator_test"

        old_entity = test_db.collection("ontology_classes").get(entity["_key"])
        assert old_entity["expired"] != NEVER_EXPIRES

    def test_reject_expires_entity(self, test_db):
        _ensure_collections(test_db)

        entity = _seed_staging_class(
            test_db, run_id="wf_2", label="Reject Me", uri="http://ex.org#RejectMe"
        )

        curation_svc.record_decision(
            test_db,
            run_id="wf_2",
            entity_key=entity["_key"],
            entity_type="class",
            action="reject",
            curator_id="curator_test",
        )

        old_entity = test_db.collection("ontology_classes").get(entity["_key"])
        assert old_entity["expired"] != NEVER_EXPIRES

    def test_edit_creates_new_version(self, test_db):
        _ensure_collections(test_db)

        entity = _seed_staging_class(
            test_db, run_id="wf_3", label="Edit Me", uri="http://ex.org#EditMe"
        )

        curation_svc.record_decision(
            test_db,
            run_id="wf_3",
            entity_key=entity["_key"],
            entity_type="class",
            action="edit",
            curator_id="curator_test",
            edited_data={"label": "Edited Label"},
        )

        old_entity = test_db.collection("ontology_classes").get(entity["_key"])
        assert old_entity["expired"] != NEVER_EXPIRES

        current = list(
            test_db.aql.execute(
                "FOR c IN ontology_classes "
                'FILTER c.uri == "http://ex.org#EditMe" '
                "FILTER c.expired == @never "
                "RETURN c",
                bind_vars={"never": NEVER_EXPIRES},
            )
        )
        assert len(current) == 1
        assert current[0]["label"] == "Edited Label"

    def test_batch_decide_processes_multiple(self, test_db):
        _ensure_collections(test_db)

        e1 = _seed_staging_class(
            test_db, run_id="wf_4", label="Batch A", uri="http://ex.org#BatchA"
        )
        e2 = _seed_staging_class(
            test_db, run_id="wf_4", label="Batch B", uri="http://ex.org#BatchB"
        )

        result = curation_svc.batch_decide(
            test_db,
            run_id="wf_4",
            decisions=[
                {
                    "entity_key": e1["_key"],
                    "entity_type": "class",
                    "action": "approve",
                    "curator_id": "curator_test",
                },
                {
                    "entity_key": e2["_key"],
                    "entity_type": "class",
                    "action": "reject",
                    "curator_id": "curator_test",
                },
            ],
        )

        assert result["processed"] == 2
        assert result["succeeded"] == 2
        assert result["failed"] == 0

    def test_merge_entities_expires_sources_and_updates_target(self, test_db):
        _ensure_collections(test_db)

        src = _seed_staging_class(
            test_db, run_id="wf_5", label="Source", uri="http://ex.org#Source"
        )
        tgt = _seed_staging_class(
            test_db, run_id="wf_5", label="Target", uri="http://ex.org#Target"
        )

        result = curation_svc.merge_entities(
            test_db,
            source_keys=[src["_key"]],
            target_key=tgt["_key"],
            merged_data={"label": "Merged Result"},
            curator_id="curator_test",
        )

        assert result["target_key"] == tgt["_key"]
        assert src["_key"] in result["expired_sources"]

        old_src = test_db.collection("ontology_classes").get(src["_key"])
        assert old_src["expired"] != NEVER_EXPIRES

    def test_promote_staging_to_production(self, test_db):
        _ensure_collections(test_db)

        entity = _seed_staging_class(
            test_db, run_id="wf_6", label="To Promote", uri="http://ex.org#ToPromote"
        )

        curation_svc.record_decision(
            test_db,
            run_id="wf_6",
            entity_key=entity["_key"],
            entity_type="class",
            action="approve",
            curator_id="curator_test",
        )

        report = promotion_svc.promote_staging(
            test_db,
            run_id="wf_6",
            ontology_id="prod_onto",
        )

        assert report["promoted_count"] >= 1
        assert report["status"] == "completed"

        promoted = list(
            test_db.aql.execute(
                "FOR c IN ontology_classes "
                'FILTER c.ontology_id == "prod_onto" '
                "FILTER c.expired == @never "
                "RETURN c",
                bind_vars={"never": NEVER_EXPIRES},
            )
        )
        assert len(promoted) >= 1
        assert any(p["label"] == "To Promote" for p in promoted)

    def test_decisions_audit_trail(self, test_db):
        _ensure_collections(test_db)

        entity = _seed_staging_class(
            test_db, run_id="wf_7", label="Audit", uri="http://ex.org#Audit"
        )
        curation_svc.record_decision(
            test_db,
            run_id="wf_7",
            entity_key=entity["_key"],
            entity_type="class",
            action="approve",
            curator_id="curator_test",
        )

        page = curation_repo.list_decisions(test_db, run_id="wf_7")
        assert page.total_count >= 1
        assert any(d["entity_key"] == entity["_key"] for d in page.data)
