"""Unit tests for migration 026 (TTL indexes on PGT split + new edge collections).

Stream 7 PR 1 -- E.3. Migration 006 created TTL indexes on the
original versioned collections; 026 closes the gap for collections
added afterwards (the PGT object/datatype property split + the
``rdfs_domain`` / ``rdfs_range_class`` edge collections). These unit
tests pin the defensive paths a live ArangoDB integration test
cannot exercise cheaply:

* the migration declares the right set of collections,
* missing collections are skipped (not raised),
* duplicate runs are no-ops (idempotency),
* ``IndexCreateError`` (concurrent runner race) is swallowed.
"""

from __future__ import annotations

import importlib
from unittest.mock import MagicMock

import pytest
from arango.exceptions import IndexCreateError


@pytest.fixture()
def mod026():
    return importlib.import_module("migrations.026_ttl_indexes_extended")


def test_targets_the_four_collections_added_after_migration_006(mod026) -> None:
    """Drift detector: the collection list IS the contract. If a future
    PR adds a fifth temporal collection (eg ``sh_node_shapes``), this
    test will keep failing until the migration is extended to cover it.
    The reverse is also true -- if a collection is removed entirely,
    the test fails to remind the author to drop the row here too.
    """
    assert set(mod026.EXTENDED_VERSIONED_COLLECTIONS) == {
        "ontology_object_properties",
        "ontology_datatype_properties",
        "rdfs_domain",
        "rdfs_range_class",
    }


def test_creates_ttl_index_on_every_present_collection(mod026) -> None:
    db = MagicMock()
    db.has_collection.return_value = True

    col = MagicMock()
    col.indexes.return_value = []
    db.collection.return_value = col

    mod026.up(db)

    # 4 collections, each should get one add_ttl_index call.
    assert col.add_ttl_index.call_count == len(mod026.EXTENDED_VERSIONED_COLLECTIONS)
    for call in col.add_ttl_index.call_args_list:
        kwargs = call.kwargs
        assert kwargs["fields"] == ["ttlExpireAt"]
        assert kwargs["expiry_time"] == 0
        # in_background=True so a slow live database doesn't block the
        # migration runner during an upgrade.
        assert kwargs["in_background"] is True


def test_skips_missing_collections_without_raising(mod026) -> None:
    """Some deployments may have never used PGT object/datatype
    properties (eg a fresh dev DB that only imported flat ontologies).
    The migration must degrade gracefully -- the worst-case is that
    the index doesn't get created, which is exactly what the operator
    wants when the underlying collection doesn't exist.
    """
    db = MagicMock()
    db.has_collection.return_value = False  # nothing exists

    # Should NOT raise even though every collection is missing.
    mod026.up(db)
    db.collection.assert_not_called()


def test_partial_collection_presence_processes_only_present_ones(mod026) -> None:
    db = MagicMock()
    present = {"ontology_object_properties", "rdfs_range_class"}
    db.has_collection.side_effect = lambda name: name in present

    col = MagicMock()
    col.indexes.return_value = []
    db.collection.return_value = col

    mod026.up(db)

    # Only the two present collections should be touched.
    assert col.add_ttl_index.call_count == 2
    called_collection_names = [c[0][0] for c in db.collection.call_args_list]
    assert set(called_collection_names) == present


def test_idempotent_when_index_already_exists(mod026) -> None:
    """Re-running the migration must NOT call ``add_ttl_index`` again --
    the index name lookup short-circuits the call. This mirrors the
    same defence migration 006 carries; replicate the test so a future
    refactor that loses the loop guard fails loudly here.
    """
    db = MagicMock()
    db.has_collection.return_value = True

    col = MagicMock()
    col.indexes.return_value = [
        {"name": "idx_ontology_object_properties_ttl"},
        {"name": "idx_ontology_datatype_properties_ttl"},
        {"name": "idx_rdfs_domain_ttl"},
        {"name": "idx_rdfs_range_class_ttl"},
    ]
    db.collection.return_value = col

    mod026.up(db)

    col.add_ttl_index.assert_not_called()


def test_concurrent_runner_race_does_not_raise(mod026) -> None:
    """Two migration runners hitting the same database concurrently
    can both see ``col.indexes()`` empty, both call ``add_ttl_index``,
    and one will lose the race with ``IndexCreateError``. The
    migration must swallow that -- otherwise an upgrade triggered
    by two pods at once would fail.
    """
    db = MagicMock()
    db.has_collection.return_value = True

    col = MagicMock()
    col.indexes.return_value = []
    col.add_ttl_index.side_effect = IndexCreateError(
        resp=MagicMock(status_code=409, body={}),
        request=MagicMock(),
    )
    db.collection.return_value = col

    # MUST NOT raise.
    mod026.up(db)
    # Still attempted (we don't pre-suppress -- we tolerate the
    # specific exception from the create call).
    assert col.add_ttl_index.call_count == len(mod026.EXTENDED_VERSIONED_COLLECTIONS)
