"""Unit tests for ``GET /api/v1/ontology/library/{id}/constraints``.

Stream 3 PR 1. We exercise the route handler directly (no server,
no DB) so we can verify the join-on-class-and-property-label
enrichment + stable sort, without paying for ArangoDB IO.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.api.errors import NotFoundError, ValidationError
from app.api.ontology import (
    approve_constraint_endpoint,
    list_ontology_constraints,
    reject_constraint_endpoint,
    update_constraint_endpoint,
)
from app.models.ontology import UpdateConstraintRequest


def _registry_entry() -> dict[str, object]:
    return {"_key": "onto_1", "name": "Test Ontology"}


@pytest.mark.asyncio
async def test_returns_404_when_ontology_missing() -> None:
    with (
        patch("app.api.ontology._shared.registry_repo.get_registry_entry", return_value=None),
        pytest.raises(NotFoundError),
    ):
        await list_ontology_constraints("missing")


@pytest.mark.asyncio
async def test_empty_when_no_constraints() -> None:
    with (
        patch(
            "app.api.ontology._shared.registry_repo.get_registry_entry",
            return_value=_registry_entry(),
        ),
        patch("app.api.ontology._shared.get_db", return_value=object()),
        patch(
            "app.api.ontology._shared.constraints_repo.list_constraints_for_ontology",
            return_value=[],
        ),
    ):
        out = await list_ontology_constraints("onto_1")

    assert out == {"ontology_id": "onto_1", "constraints": [], "total": 0}


@pytest.mark.asyncio
async def test_enriches_with_class_and_property_labels_and_sorts() -> None:
    raw = [
        {
            "constraint_type": "owl:Restriction",
            "on_class": "ontology_classes/Account",
            "property_id": "ontology_object_properties/Account_holder",
            "property_uri": "http://ex.org/onto#holder",
            "restriction_type": "minCardinality",
            "restriction_value": 1,
            "ontology_id": "onto_1",
        },
        {
            "constraint_type": "owl:Restriction",
            "on_class": "ontology_classes/Customer",
            "property_id": "ontology_datatype_properties/Customer_email",
            "property_uri": "http://ex.org/onto#email",
            "restriction_type": "minCardinality",
            "restriction_value": 1,
            "ontology_id": "onto_1",
        },
        {
            "constraint_type": "owl:Restriction",
            "on_class": "ontology_classes/Account",
            "property_id": "ontology_object_properties/Account_holder",
            "property_uri": "http://ex.org/onto#holder",
            "restriction_type": "maxCardinality",
            "restriction_value": 1,
            "ontology_id": "onto_1",
        },
    ]

    label_rows_by_query: list[list[dict[str, str]]] = [
        # first run_aql call resolves class labels
        [
            {"id": "ontology_classes/Account", "label": "Account"},
            {"id": "ontology_classes/Customer", "label": "Customer"},
        ],
        # second run_aql call resolves property labels
        [
            {"id": "ontology_datatype_properties/Customer_email", "label": "email"},
            {"id": "ontology_object_properties/Account_holder", "label": "holder"},
        ],
    ]

    def fake_run_aql(_db, _query, bind_vars):  # type: ignore[no-untyped-def]
        return iter(label_rows_by_query.pop(0))

    with (
        patch(
            "app.api.ontology._shared.registry_repo.get_registry_entry",
            return_value=_registry_entry(),
        ),
        patch("app.api.ontology._shared.get_db", return_value=object()),
        patch(
            "app.api.ontology._shared.constraints_repo.list_constraints_for_ontology",
            return_value=raw,
        ),
        patch("app.api.ontology._shared.run_aql", side_effect=fake_run_aql),
    ):
        out = await list_ontology_constraints("onto_1")

    assert out["ontology_id"] == "onto_1"
    assert out["total"] == 3
    enriched = out["constraints"]
    # Stable sort: by class label, then property URI, then restriction type.
    # Account / holder / maxCardinality should come before Account / holder /
    # minCardinality, both before Customer / email / minCardinality.
    triples = [(c["class_label"], c["property_uri"], c["restriction_type"]) for c in enriched]
    assert triples == [
        ("Account", "http://ex.org/onto#holder", "maxCardinality"),
        ("Account", "http://ex.org/onto#holder", "minCardinality"),
        ("Customer", "http://ex.org/onto#email", "minCardinality"),
    ]
    # Property labels resolved.
    assert {c["property_label"] for c in enriched} == {"holder", "email"}


@pytest.mark.asyncio
async def test_unresolved_property_id_gets_empty_label() -> None:
    raw = [
        {
            "constraint_type": "owl:Restriction",
            "on_class": "ontology_classes/Account",
            "property_id": None,
            "property_uri": "http://ex.org/onto#missing",
            "restriction_type": "minCardinality",
            "restriction_value": 1,
            "ontology_id": "onto_1",
        }
    ]

    def fake_run_aql(_db, _query, bind_vars):  # type: ignore[no-untyped-def]
        # Only class-label query runs -- property_ids list is empty so the
        # second AQL is skipped.
        return iter([{"id": "ontology_classes/Account", "label": "Account"}])

    with (
        patch(
            "app.api.ontology._shared.registry_repo.get_registry_entry",
            return_value=_registry_entry(),
        ),
        patch("app.api.ontology._shared.get_db", return_value=object()),
        patch(
            "app.api.ontology._shared.constraints_repo.list_constraints_for_ontology",
            return_value=raw,
        ),
        patch("app.api.ontology._shared.run_aql", side_effect=fake_run_aql),
    ):
        out = await list_ontology_constraints("onto_1")

    assert out["total"] == 1
    c = out["constraints"][0]
    assert c["class_label"] == "Account"
    assert c["property_label"] == ""


@pytest.mark.asyncio
async def test_forwards_filter_kwargs_to_repo() -> None:
    with (
        patch(
            "app.api.ontology._shared.registry_repo.get_registry_entry",
            return_value=_registry_entry(),
        ),
        patch("app.api.ontology._shared.get_db", return_value=object()),
        patch(
            "app.api.ontology._shared.constraints_repo.list_constraints_for_ontology",
            return_value=[],
        ) as mock_repo,
    ):
        await list_ontology_constraints(
            "onto_1",
            constraint_type="owl:Restriction",
            include_unresolved=False,
        )

    kwargs = mock_repo.call_args.kwargs
    assert kwargs["ontology_id"] == "onto_1"
    assert kwargs["constraint_type"] == "owl:Restriction"
    assert kwargs["include_unresolved"] is False


@pytest.mark.asyncio
async def test_forwards_class_id_query_param_to_repo() -> None:
    """Stream 3 PR 4: the workspace FloatingDetailPanel passes
    ``?class_id=ontology_classes/Customer`` so the repo can scope its
    AQL to one class. The endpoint must forward it verbatim."""
    with (
        patch(
            "app.api.ontology._shared.registry_repo.get_registry_entry",
            return_value=_registry_entry(),
        ),
        patch("app.api.ontology._shared.get_db", return_value=object()),
        patch(
            "app.api.ontology._shared.constraints_repo.list_constraints_for_ontology",
            return_value=[],
        ) as mock_repo,
    ):
        await list_ontology_constraints(
            "onto_1",
            constraint_type=None,
            include_unresolved=True,
            class_id="ontology_classes/Customer",
        )

    kwargs = mock_repo.call_args.kwargs
    assert kwargs["on_class"] == "ontology_classes/Customer"
    # Other kwargs forwarded straight through unchanged.
    assert kwargs["ontology_id"] == "onto_1"
    assert kwargs["constraint_type"] is None
    assert kwargs["include_unresolved"] is True


# ---------------------------------------------------------------------------
# Constraint curation mutations (I.7)
# ---------------------------------------------------------------------------


def _live_constraint(ontology_id: str = "onto_1") -> dict[str, object]:
    return {
        "_key": "c1",
        "ontology_id": ontology_id,
        "constraint_type": "owl:Restriction",
        "on_class": "ontology_classes/Account",
        "restriction_type": "minCardinality",
        "restriction_value": 1,
    }


@pytest.mark.asyncio
async def test_approve_constraint_sets_status_approved() -> None:
    with (
        patch("app.api.ontology._shared.get_db", return_value=object()),
        patch(
            "app.api.ontology._shared.constraints_repo.get_constraint",
            return_value=_live_constraint(),
        ),
        patch(
            "app.api.ontology._shared.constraints_repo.update_constraint",
            return_value={"_key": "c2", "status": "approved", "version": 2},
        ) as mock_update,
    ):
        out = await approve_constraint_endpoint("onto_1", "c1")

    assert out["status"] == "approved"
    assert mock_update.call_args.kwargs["data"] == {"status": "approved"}
    assert mock_update.call_args.kwargs["key"] == "c1"


@pytest.mark.asyncio
async def test_approve_constraint_404_when_missing() -> None:
    with (
        patch("app.api.ontology._shared.get_db", return_value=object()),
        patch("app.api.ontology._shared.constraints_repo.get_constraint", return_value=None),
        pytest.raises(NotFoundError),
    ):
        await approve_constraint_endpoint("onto_1", "missing")


@pytest.mark.asyncio
async def test_approve_constraint_rejects_cross_ontology() -> None:
    with (
        patch("app.api.ontology._shared.get_db", return_value=object()),
        patch(
            "app.api.ontology._shared.constraints_repo.get_constraint",
            return_value=_live_constraint(ontology_id="other"),
        ),
        pytest.raises(ValidationError),
    ):
        await approve_constraint_endpoint("onto_1", "c1")


@pytest.mark.asyncio
async def test_reject_constraint_expires_it() -> None:
    with (
        patch("app.api.ontology._shared.get_db", return_value=object()),
        patch(
            "app.api.ontology._shared.constraints_repo.get_constraint",
            return_value=_live_constraint(),
        ),
        patch(
            "app.api.ontology._shared.constraints_repo.expire_constraint",
            return_value={"_key": "c1", "expired": 123.0},
        ) as mock_expire,
    ):
        out = await reject_constraint_endpoint("onto_1", "c1")

    assert out == {
        "status": "rejected",
        "constraint_key": "c1",
        "ontology_id": "onto_1",
    }
    assert mock_expire.call_args.kwargs["key"] == "c1"


@pytest.mark.asyncio
async def test_reject_constraint_404_when_already_gone() -> None:
    # get_constraint passes (race: still live at read) but expire returns None.
    with (
        patch("app.api.ontology._shared.get_db", return_value=object()),
        patch(
            "app.api.ontology._shared.constraints_repo.get_constraint",
            return_value=_live_constraint(),
        ),
        patch(
            "app.api.ontology._shared.constraints_repo.expire_constraint",
            return_value=None,
        ),
        pytest.raises(NotFoundError),
    ):
        await reject_constraint_endpoint("onto_1", "c1")


@pytest.mark.asyncio
async def test_update_constraint_edits_value_and_resets_status_to_pending() -> None:
    with (
        patch("app.api.ontology._shared.get_db", return_value=object()),
        patch(
            "app.api.ontology._shared.constraints_repo.get_constraint",
            return_value=_live_constraint(),
        ),
        patch(
            "app.api.ontology._shared.constraints_repo.update_constraint",
            return_value={"_key": "c2", "restriction_value": 5, "status": "pending"},
        ) as mock_update,
    ):
        out = await update_constraint_endpoint(
            "onto_1",
            "c1",
            UpdateConstraintRequest(restriction_value=5, description="loosened"),
        )

    assert out["restriction_value"] == 5
    data = mock_update.call_args.kwargs["data"]
    assert data["restriction_value"] == 5
    assert data["description"] == "loosened"
    # Editing a bound resets curation status so it is re-reviewed.
    assert data["status"] == "pending"


@pytest.mark.asyncio
async def test_update_constraint_requires_a_field() -> None:
    with (
        patch("app.api.ontology._shared.get_db", return_value=object()),
        patch(
            "app.api.ontology._shared.constraints_repo.get_constraint",
            return_value=_live_constraint(),
        ),
        pytest.raises(ValidationError),
    ):
        await update_constraint_endpoint("onto_1", "c1", UpdateConstraintRequest())
