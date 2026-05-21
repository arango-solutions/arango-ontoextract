"""Unit tests for ``app.db.constraints_repo``.

Stream 3 PR 1. AQL execution is patched at the module boundary; we only
want to verify the repo (a) returns ``[]`` when the collection is
missing, (b) emits the right filter clauses based on optional kwargs,
and (c) preserves row order.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.db import constraints_repo
from app.db.temporal_constants import NEVER_EXPIRES


def _db_with(has_collection: bool) -> MagicMock:
    db = MagicMock()
    db.has_collection.return_value = has_collection
    return db


# ---------------------------------------------------------------------------
# list_constraints_for_ontology
# ---------------------------------------------------------------------------


def test_list_constraints_returns_empty_when_collection_missing() -> None:
    db = _db_with(False)
    assert constraints_repo.list_constraints_for_ontology(db, ontology_id="o1") == []


@patch("app.db.constraints_repo.run_aql")
def test_list_constraints_filters_by_ontology(mock_run_aql: MagicMock) -> None:
    db = _db_with(True)
    mock_run_aql.return_value = iter(
        [
            {
                "constraint_type": "owl:Restriction",
                "on_class": "ontology_classes/Customer",
                "property_uri": "http://ex.org#hasName",
                "restriction_type": "minCardinality",
                "restriction_value": 1,
                "ontology_id": "o1",
            }
        ]
    )

    result = constraints_repo.list_constraints_for_ontology(db, ontology_id="o1")

    assert len(result) == 1
    assert mock_run_aql.call_count == 1
    args, kwargs = mock_run_aql.call_args
    query = args[1]
    bind = kwargs["bind_vars"]
    assert "ontology_constraints" in query
    assert "c.ontology_id == @ontology_id" in query
    assert "c.expired == @never" in query
    assert "@ctype" not in query  # no type filter unless requested
    assert bind == {"ontology_id": "o1", "never": NEVER_EXPIRES}


@patch("app.db.constraints_repo.run_aql")
def test_list_constraints_adds_type_filter_when_requested(
    mock_run_aql: MagicMock,
) -> None:
    db = _db_with(True)
    mock_run_aql.return_value = iter([])

    constraints_repo.list_constraints_for_ontology(
        db,
        ontology_id="o1",
        constraint_type="owl:Restriction",
    )

    args, kwargs = mock_run_aql.call_args
    query = args[1]
    bind = kwargs["bind_vars"]
    assert "c.constraint_type == @ctype" in query
    assert bind["ctype"] == "owl:Restriction"


@patch("app.db.constraints_repo.run_aql")
def test_list_constraints_can_filter_out_unresolved(mock_run_aql: MagicMock) -> None:
    db = _db_with(True)
    mock_run_aql.return_value = iter([])

    constraints_repo.list_constraints_for_ontology(
        db,
        ontology_id="o1",
        include_unresolved=False,
    )

    query = mock_run_aql.call_args[0][1]
    assert "c.property_id != null" in query


@patch("app.db.constraints_repo.run_aql")
def test_list_constraints_filters_by_on_class_when_provided(
    mock_run_aql: MagicMock,
) -> None:
    """Stream 3 PR 4: the workspace FloatingDetailPanel fetches the
    constraints for ONE class per click. The repo accepts an
    ``on_class`` kwarg so this hot-path query is a single round-trip,
    not a full ontology scan + client-side filter."""
    db = _db_with(True)
    mock_run_aql.return_value = iter([])

    constraints_repo.list_constraints_for_ontology(
        db,
        ontology_id="o1",
        on_class="ontology_classes/Customer",
    )

    args, kwargs = mock_run_aql.call_args
    query = args[1]
    bind = kwargs["bind_vars"]
    assert "c.on_class == @on_class" in query
    assert bind["on_class"] == "ontology_classes/Customer"


@patch("app.db.constraints_repo.run_aql")
def test_list_constraints_combines_all_filters(mock_run_aql: MagicMock) -> None:
    """All four optional filters can be combined; each adds its own
    FILTER clause without conflicting."""
    db = _db_with(True)
    mock_run_aql.return_value = iter([])

    constraints_repo.list_constraints_for_ontology(
        db,
        ontology_id="o1",
        constraint_type="sh:PropertyShape",
        include_unresolved=False,
        on_class="ontology_classes/Customer",
    )

    args, kwargs = mock_run_aql.call_args
    query = args[1]
    bind = kwargs["bind_vars"]
    assert "c.constraint_type == @ctype" in query
    assert "c.property_id != null" in query
    assert "c.on_class == @on_class" in query
    assert bind["ctype"] == "sh:PropertyShape"
    assert bind["on_class"] == "ontology_classes/Customer"


# ---------------------------------------------------------------------------
# list_constraints_for_class
# ---------------------------------------------------------------------------


def test_list_class_constraints_empty_when_collection_missing() -> None:
    db = _db_with(False)
    assert (
        constraints_repo.list_constraints_for_class(db, class_id="ontology_classes/Customer") == []
    )


@patch("app.db.constraints_repo.run_aql")
def test_list_class_constraints_filters_by_full_class_id(
    mock_run_aql: MagicMock,
) -> None:
    db = _db_with(True)
    mock_run_aql.return_value = iter([{"on_class": "ontology_classes/Customer"}])

    rows = constraints_repo.list_constraints_for_class(db, class_id="ontology_classes/Customer")

    assert rows == [{"on_class": "ontology_classes/Customer"}]
    args, kwargs = mock_run_aql.call_args
    query = args[1]
    bind = kwargs["bind_vars"]
    assert "c.on_class == @class_id" in query
    assert bind == {"class_id": "ontology_classes/Customer", "never": NEVER_EXPIRES}


# ---------------------------------------------------------------------------
# count_constraints_for_ontology
# ---------------------------------------------------------------------------


def test_count_constraints_zero_when_collection_missing() -> None:
    db = _db_with(False)
    assert constraints_repo.count_constraints_for_ontology(db, ontology_id="o1") == 0


@patch("app.db.constraints_repo.run_aql")
def test_count_constraints_returns_integer(mock_run_aql: MagicMock) -> None:
    db = _db_with(True)
    mock_run_aql.return_value = iter([7])

    assert constraints_repo.count_constraints_for_ontology(db, ontology_id="o1") == 7


@patch("app.db.constraints_repo.run_aql")
def test_count_constraints_zero_when_empty(mock_run_aql: MagicMock) -> None:
    db = _db_with(True)
    mock_run_aql.return_value = iter([])

    assert constraints_repo.count_constraints_for_ontology(db, ontology_id="o1") == 0
