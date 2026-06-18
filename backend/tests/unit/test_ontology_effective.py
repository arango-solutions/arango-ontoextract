"""Unit tests for ``app.services.ontology_effective`` (Stream 1 H.12 + H.13).

The service merges an ontology with its transitive ``owl:imports`` closure
and reports merge-induced conflicts. These tests pin the public contract:

* Self-only path returns at least the target's classes / edges / props.
* Transitive imports are walked OUTBOUND (ancestors), not INBOUND.
* Every entity is stamped with ``source_ontology_id`` /
  ``source_ontology_name`` / ``is_imported`` (boolean derived against
  the target id, not against any closure membership).
* ``conflicts`` detects duplicate URI / duplicate label / subclass
  cycle, but NEVER reports same-ontology duplicates (those are writer
  bugs, owned by per-ontology validation).
* The ETag depends on the closure's ``updated_at`` fingerprint AND on
  the include profile, so ``summary`` and ``full`` cannot collide and
  any source mutation busts the cache.
* Missing optional collections degrade gracefully (empty arrays, not
  exceptions), matching the per-ontology endpoints.

DB calls are mocked at the AQL dispatcher level, mirroring the H.4 / H.3
test pattern (see ``test_ontology_dependency.py`` /
``test_ontology_imports_graph.py``).
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.services.ontology_effective import (
    DEFAULT_MAX_DEPTH,
    compute_effective_ontology,
)

NEVER = sys.maxsize


# --- Fixtures --------------------------------------------------------------


def _make_db(
    *,
    registry_entries: dict[str, dict[str, Any]] | None = None,
    aql_responses: dict[str, list[Any]] | None = None,
    missing_collections: tuple[str, ...] = (),
    existing_collections: tuple[str, ...] = (
        "ontology_registry",
        "imports",
        "ontology_classes",
        "subclass_of",
        "rdfs_domain",
        "rdfs_range_class",
        "equivalent_class",
        "has_property",
        "related_to",
        "ontology_object_properties",
        "ontology_datatype_properties",
    ),
) -> MagicMock:
    """Build a MagicMock DB whose AQL dispatcher matches query substrings.

    The dispatcher returns the *first* matching response, which means
    callers can disambiguate edge vs property vs closure queries by
    using unique substrings as keys (``"FOR c IN ontology_classes"`` vs
    ``"FOR e IN subclass_of"``).
    """
    db = MagicMock()

    missing = set(missing_collections)
    existing = {name for name in existing_collections if name not in missing}

    db.has_collection.side_effect = lambda name: name in existing
    db.collections.return_value = [{"name": n} for n in existing]

    registry_entries = registry_entries or {}
    registry_collection = MagicMock()
    registry_collection.get.side_effect = lambda key: registry_entries.get(key)
    db.collection.return_value = registry_collection

    aql_responses = aql_responses or {}

    def _execute(query: str, bind_vars: dict[str, Any] | None = None) -> Any:
        for needle, rows in aql_responses.items():
            if needle in query:
                return iter(list(rows))
        return iter([])

    db.aql.execute = MagicMock(side_effect=_execute)
    return db


# --- Registry lookup -------------------------------------------------------


class TestRegistryLookup:
    def test_raises_when_registry_collection_missing(self) -> None:
        db = _make_db(missing_collections=("ontology_registry",))
        with pytest.raises(ValueError, match="ontology_registry"):
            compute_effective_ontology(db, ontology_id="anything")

    def test_raises_when_target_ontology_not_in_registry(self) -> None:
        db = _make_db(registry_entries={})
        with pytest.raises(ValueError, match="ont-missing"):
            compute_effective_ontology(db, ontology_id="ont-missing")

    def test_collection_metadata_is_probed_once_not_per_check(self) -> None:
        """Perf guardrail: python-arango's has_collection / collections each do
        a full WAN round-trip. compute_effective_ontology must snapshot the
        collection set ONCE (one collections() call, no has_collection calls),
        not re-probe per collection — this is what halves remote canvas latency.
        """
        db = _make_db(
            registry_entries={"ont-self": {"_key": "ont-self", "name": "Solo", "updated_at": 1}},
            aql_responses={},
        )
        compute_effective_ontology(db, ontology_id="ont-self")
        assert db.has_collection.call_count == 0
        assert db.collections.call_count == 1


# --- Self-only (no imports) -----------------------------------------------


class TestSelfOnlyClosure:
    def test_returns_self_in_sources_even_with_no_imports(self) -> None:
        db = _make_db(
            registry_entries={
                "ont-self": {
                    "_key": "ont-self",
                    "name": "Solo",
                    "tier": "user",
                    "updated_at": 42,
                }
            },
            aql_responses={},
        )

        result = compute_effective_ontology(db, ontology_id="ont-self")

        assert result["ontology_id"] == "ont-self"
        assert result["ontology_name"] == "Solo"
        assert len(result["sources"]) == 1
        assert result["sources"][0]["_key"] == "ont-self"
        assert result["sources"][0]["is_self"] is True
        assert result["sources"][0]["depth"] == 0
        assert result["classes"] == []
        assert result["edges"] == []
        assert result["properties"] == []
        assert result["conflicts"] == []
        assert result["truncated"] is False
        assert result["include"] == "summary"

    def test_classes_from_self_are_not_marked_imported(self) -> None:
        db = _make_db(
            registry_entries={"ont-self": {"_key": "ont-self", "name": "Solo", "updated_at": 1}},
            aql_responses={
                "FOR c IN ontology_classes": [
                    {
                        "_key": "C1",
                        "_id": "ontology_classes/C1",
                        "uri": "http://ex.org/C1",
                        "ontology_id": "ont-self",
                        "label": "Person",
                        "tier": "user",
                        "status": "approved",
                        "confidence": 0.9,
                    }
                ]
            },
        )

        result = compute_effective_ontology(db, ontology_id="ont-self")

        assert len(result["classes"]) == 1
        cls = result["classes"][0]
        assert cls["source_ontology_id"] == "ont-self"
        assert cls["source_ontology_name"] == "Solo"
        assert cls["is_imported"] is False


# --- Transitive imports ----------------------------------------------------


class TestTransitiveClosure:
    def test_imports_are_walked_outbound_and_annotated(self) -> None:
        db = _make_db(
            registry_entries={
                "ont-self": {"_key": "ont-self", "name": "Self", "updated_at": 10},
            },
            aql_responses={
                # The OUTBOUND imports traversal returns the ancestors.
                "OUTBOUND @target imports": [
                    {
                        "_key": "ont-base",
                        "name": "Base",
                        "tier": "library",
                        "updated_at": 5,
                        "depth": 1,
                    },
                    {
                        "_key": "ont-grand",
                        "name": "Grandparent",
                        "tier": "standard",
                        "updated_at": 1,
                        "depth": 2,
                    },
                ],
                "FOR c IN ontology_classes": [
                    {
                        "_key": "C-own",
                        "_id": "ontology_classes/C-own",
                        "uri": "http://ex.org/Own",
                        "ontology_id": "ont-self",
                        "label": "Local",
                    },
                    {
                        "_key": "C-base",
                        "_id": "ontology_classes/C-base",
                        "uri": "http://ex.org/Base",
                        "ontology_id": "ont-base",
                        "label": "BaseClass",
                    },
                ],
            },
        )

        result = compute_effective_ontology(db, ontology_id="ont-self")

        source_keys = {s["_key"] for s in result["sources"]}
        assert source_keys == {"ont-self", "ont-base", "ont-grand"}
        depth_by_key = {s["_key"]: s["depth"] for s in result["sources"]}
        assert depth_by_key == {"ont-self": 0, "ont-base": 1, "ont-grand": 2}

        # Sources are sorted by (depth ASC, name ASC).
        assert [s["_key"] for s in result["sources"]] == ["ont-self", "ont-base", "ont-grand"]

        own = next(c for c in result["classes"] if c["_key"] == "C-own")
        base = next(c for c in result["classes"] if c["_key"] == "C-base")
        assert own["is_imported"] is False
        assert own["source_ontology_id"] == "ont-self"
        assert base["is_imported"] is True
        assert base["source_ontology_id"] == "ont-base"
        assert base["source_ontology_name"] == "Base"

    def test_max_depth_is_clamped(self) -> None:
        db = _make_db(
            registry_entries={"ont-self": {"_key": "ont-self", "name": "Self"}},
            aql_responses={},
        )

        called_bind_vars: dict[str, Any] = {}

        def _execute(query: str, bind_vars: dict[str, Any] | None = None) -> Any:
            if "OUTBOUND @target imports" in query and bind_vars is not None:
                called_bind_vars.update(bind_vars)
            return iter([])

        db.aql.execute.side_effect = _execute

        compute_effective_ontology(db, ontology_id="ont-self", max_depth=999)
        assert called_bind_vars.get("max_depth") == 50

        called_bind_vars.clear()
        compute_effective_ontology(db, ontology_id="ont-self", max_depth=-3)
        assert called_bind_vars.get("max_depth") == 1


# --- Edges + projection ----------------------------------------------------


class TestEdgesAndProjection:
    def test_summary_profile_drops_evidence_and_keeps_annotation(self) -> None:
        db = _make_db(
            registry_entries={"ont-self": {"_key": "ont-self", "name": "Self"}},
            aql_responses={
                "FOR c IN ontology_classes": [
                    {
                        "_key": "C1",
                        "_id": "ontology_classes/C1",
                        "uri": "http://ex.org/C1",
                        "ontology_id": "ont-self",
                        "label": "Person",
                        "evidence": [{"long": "x" * 500}],
                    }
                ]
            },
        )

        result = compute_effective_ontology(db, ontology_id="ont-self", include="summary")

        cls = result["classes"][0]
        assert "evidence" not in cls
        assert cls["label"] == "Person"
        assert cls["source_ontology_id"] == "ont-self"
        assert cls["is_imported"] is False

    def test_full_profile_keeps_every_field_and_still_annotates(self) -> None:
        db = _make_db(
            registry_entries={"ont-self": {"_key": "ont-self", "name": "Self"}},
            aql_responses={
                "FOR c IN ontology_classes": [
                    {
                        "_key": "C1",
                        "_id": "ontology_classes/C1",
                        "uri": "http://ex.org/C1",
                        "ontology_id": "ont-self",
                        "label": "Person",
                        "evidence": [{"long": "kept"}],
                    }
                ]
            },
        )

        result = compute_effective_ontology(db, ontology_id="ont-self", include="full")

        cls = result["classes"][0]
        assert cls["evidence"] == [{"long": "kept"}]
        assert cls["source_ontology_id"] == "ont-self"
        assert result["include"] == "full"

    def test_edges_carry_edge_type_and_source_annotation(self) -> None:
        db = _make_db(
            registry_entries={
                "ont-self": {"_key": "ont-self", "name": "Self"},
                "ont-base": {"_key": "ont-base", "name": "Base"},
            },
            aql_responses={
                "OUTBOUND @target imports": [{"_key": "ont-base", "name": "Base", "depth": 1}],
                # The union-of-edges query is built dynamically; match on a
                # piece of the FLATTEN expression that will always be present.
                "LET edges = FLATTEN": [
                    [
                        {
                            "_key": "e1",
                            "_from": "ontology_classes/C-base",
                            "_to": "ontology_classes/C-root",
                            "ontology_id": "ont-base",
                            "edge_type": "subclass_of",
                        }
                    ]
                ],
            },
        )

        result = compute_effective_ontology(db, ontology_id="ont-self")

        assert len(result["edges"]) == 1
        edge = result["edges"][0]
        assert edge["edge_type"] == "subclass_of"
        assert edge["is_imported"] is True
        assert edge["source_ontology_id"] == "ont-base"
        assert edge["source_ontology_name"] == "Base"


# --- Conflict detection (H.13) --------------------------------------------


class TestConflictDetection:
    def _registry(self) -> dict[str, dict[str, Any]]:
        return {
            "ont-self": {"_key": "ont-self", "name": "Self", "updated_at": 1},
            "ont-a": {"_key": "ont-a", "name": "Alpha", "updated_at": 2},
            "ont-b": {"_key": "ont-b", "name": "Beta", "updated_at": 3},
        }

    def _two_imports(self) -> list[dict[str, Any]]:
        return [
            {"_key": "ont-a", "name": "Alpha", "depth": 1},
            {"_key": "ont-b", "name": "Beta", "depth": 1},
        ]

    def test_duplicate_uri_across_two_sources_is_flagged(self) -> None:
        db = _make_db(
            registry_entries=self._registry(),
            aql_responses={
                "OUTBOUND @target imports": self._two_imports(),
                "FOR c IN ontology_classes": [
                    {
                        "_key": "CA",
                        "_id": "ontology_classes/CA",
                        "uri": "http://ex.org/Person",
                        "ontology_id": "ont-a",
                        "label": "Person",
                    },
                    {
                        "_key": "CB",
                        "_id": "ontology_classes/CB",
                        "uri": "http://ex.org/Person",
                        "ontology_id": "ont-b",
                        "label": "Person",
                    },
                ],
            },
        )

        result = compute_effective_ontology(db, ontology_id="ont-self")

        uri_conflicts = [c for c in result["conflicts"] if c["kind"] == "duplicate_uri"]
        assert len(uri_conflicts) == 1
        c = uri_conflicts[0]
        assert c["key"] == "http://ex.org/Person"
        assert {s["ontology_id"] for s in c["sources"]} == {"ont-a", "ont-b"}

    def test_same_uri_within_one_source_is_not_a_merge_conflict(self) -> None:
        db = _make_db(
            registry_entries=self._registry(),
            aql_responses={
                "OUTBOUND @target imports": self._two_imports(),
                "FOR c IN ontology_classes": [
                    {
                        "_key": "C1",
                        "_id": "ontology_classes/C1",
                        "uri": "http://ex.org/X",
                        "ontology_id": "ont-a",
                        "label": "X",
                    },
                    {
                        "_key": "C2",
                        "_id": "ontology_classes/C2",
                        "uri": "http://ex.org/X",
                        "ontology_id": "ont-a",
                        "label": "X",
                    },
                ],
            },
        )

        result = compute_effective_ontology(db, ontology_id="ont-self")

        uri_conflicts = [c for c in result["conflicts"] if c["kind"] == "duplicate_uri"]
        assert uri_conflicts == []

    def test_duplicate_label_with_different_uris_is_flagged(self) -> None:
        db = _make_db(
            registry_entries=self._registry(),
            aql_responses={
                "OUTBOUND @target imports": self._two_imports(),
                "FOR c IN ontology_classes": [
                    {
                        "_key": "CA",
                        "_id": "ontology_classes/CA",
                        "uri": "http://a.org/Org",
                        "ontology_id": "ont-a",
                        "label": "Organization",
                    },
                    {
                        "_key": "CB",
                        "_id": "ontology_classes/CB",
                        "uri": "http://b.org/Org",
                        "ontology_id": "ont-b",
                        "label": "Organization",
                    },
                ],
            },
        )

        result = compute_effective_ontology(db, ontology_id="ont-self")

        label_conflicts = [c for c in result["conflicts"] if c["kind"] == "duplicate_label"]
        assert len(label_conflicts) == 1
        assert label_conflicts[0]["key"] == "organization"
        assert {s["ontology_id"] for s in label_conflicts[0]["sources"]} == {"ont-a", "ont-b"}

    def test_same_label_same_uri_is_not_double_reported(self) -> None:
        """Same URI + same label across sources surfaces ONLY as duplicate_uri."""
        db = _make_db(
            registry_entries=self._registry(),
            aql_responses={
                "OUTBOUND @target imports": self._two_imports(),
                "FOR c IN ontology_classes": [
                    {
                        "_key": "CA",
                        "_id": "ontology_classes/CA",
                        "uri": "http://shared.org/Person",
                        "ontology_id": "ont-a",
                        "label": "Person",
                    },
                    {
                        "_key": "CB",
                        "_id": "ontology_classes/CB",
                        "uri": "http://shared.org/Person",
                        "ontology_id": "ont-b",
                        "label": "Person",
                    },
                ],
            },
        )

        result = compute_effective_ontology(db, ontology_id="ont-self")

        kinds = [c["kind"] for c in result["conflicts"]]
        assert kinds.count("duplicate_uri") == 1
        assert kinds.count("duplicate_label") == 0

    def test_subclass_cycle_introduced_via_import_is_flagged(self) -> None:
        """Cycle A->B->A where one edge originates in an imported source."""
        db = _make_db(
            registry_entries=self._registry(),
            aql_responses={
                "OUTBOUND @target imports": self._two_imports(),
                "FOR c IN ontology_classes": [
                    {
                        "_key": "A",
                        "_id": "ontology_classes/A",
                        "uri": "http://ex/A",
                        "ontology_id": "ont-self",
                        "label": "A",
                    },
                    {
                        "_key": "B",
                        "_id": "ontology_classes/B",
                        "uri": "http://ex/B",
                        "ontology_id": "ont-a",
                        "label": "B",
                    },
                ],
                "LET edges = FLATTEN": [
                    [
                        # Local: A subclass_of B
                        {
                            "_key": "e1",
                            "_from": "ontology_classes/A",
                            "_to": "ontology_classes/B",
                            "ontology_id": "ont-self",
                            "edge_type": "subclass_of",
                        },
                        # Imported: B subclass_of A -> creates the cycle.
                        {
                            "_key": "e2",
                            "_from": "ontology_classes/B",
                            "_to": "ontology_classes/A",
                            "ontology_id": "ont-a",
                            "edge_type": "subclass_of",
                        },
                    ]
                ],
            },
        )

        result = compute_effective_ontology(db, ontology_id="ont-self")

        cycle_conflicts = [
            c for c in result["conflicts"] if c["kind"] == "subclass_cycle_via_import"
        ]
        assert len(cycle_conflicts) == 1
        # The same cycle should not be reported twice via different starting nodes.
        assert "ontology_classes/A" in cycle_conflicts[0]["key"]
        assert "ontology_classes/B" in cycle_conflicts[0]["key"]

    def test_cycle_entirely_within_self_is_not_flagged_as_merge_conflict(self) -> None:
        db = _make_db(
            registry_entries=self._registry(),
            aql_responses={
                "OUTBOUND @target imports": self._two_imports(),
                "FOR c IN ontology_classes": [
                    {
                        "_key": "A",
                        "_id": "ontology_classes/A",
                        "ontology_id": "ont-self",
                        "label": "A",
                    },
                    {
                        "_key": "B",
                        "_id": "ontology_classes/B",
                        "ontology_id": "ont-self",
                        "label": "B",
                    },
                ],
                "LET edges = FLATTEN": [
                    [
                        {
                            "_key": "e1",
                            "_from": "ontology_classes/A",
                            "_to": "ontology_classes/B",
                            "ontology_id": "ont-self",
                            "edge_type": "subclass_of",
                        },
                        {
                            "_key": "e2",
                            "_from": "ontology_classes/B",
                            "_to": "ontology_classes/A",
                            "ontology_id": "ont-self",
                            "edge_type": "subclass_of",
                        },
                    ]
                ],
            },
        )

        result = compute_effective_ontology(db, ontology_id="ont-self")

        cycle_conflicts = [
            c for c in result["conflicts"] if c["kind"] == "subclass_cycle_via_import"
        ]
        assert cycle_conflicts == []


# --- ETag semantics --------------------------------------------------------


class TestETag:
    def test_etag_changes_when_source_updated_at_changes(self) -> None:
        def _db(updated_at: int) -> MagicMock:
            return _make_db(
                registry_entries={
                    "ont-self": {
                        "_key": "ont-self",
                        "name": "Self",
                        "updated_at": updated_at,
                    }
                },
                aql_responses={},
            )

        e1 = compute_effective_ontology(_db(1), ontology_id="ont-self")["etag"]
        e2 = compute_effective_ontology(_db(2), ontology_id="ont-self")["etag"]
        assert e1 != e2
        # Stable for the same input.
        e1_again = compute_effective_ontology(_db(1), ontology_id="ont-self")["etag"]
        assert e1 == e1_again

    def test_etag_distinguishes_summary_from_full(self) -> None:
        db = _make_db(
            registry_entries={"ont-self": {"_key": "ont-self", "name": "Self", "updated_at": 1}},
            aql_responses={},
        )

        summary = compute_effective_ontology(db, ontology_id="ont-self", include="summary")["etag"]
        full = compute_effective_ontology(db, ontology_id="ont-self", include="full")["etag"]
        assert summary != full

    def test_etag_changes_when_imports_closure_grows(self) -> None:
        db_no_imports = _make_db(
            registry_entries={"ont-self": {"_key": "ont-self", "name": "Self", "updated_at": 1}},
            aql_responses={},
        )
        db_with_import = _make_db(
            registry_entries={
                "ont-self": {"_key": "ont-self", "name": "Self", "updated_at": 1},
                "ont-base": {"_key": "ont-base", "name": "Base", "updated_at": 9},
            },
            aql_responses={
                "OUTBOUND @target imports": [
                    {"_key": "ont-base", "name": "Base", "updated_at": 9, "depth": 1}
                ]
            },
        )

        e_alone = compute_effective_ontology(db_no_imports, ontology_id="ont-self")["etag"]
        e_with = compute_effective_ontology(db_with_import, ontology_id="ont-self")["etag"]
        assert e_alone != e_with

    def test_etag_format_is_weak_validator(self) -> None:
        db = _make_db(
            registry_entries={"ont-self": {"_key": "ont-self", "name": "Self", "updated_at": 1}},
            aql_responses={},
        )
        etag = compute_effective_ontology(db, ontology_id="ont-self")["etag"]
        # ``W/"..."`` per RFC 7232 -- weak because we hash registry metadata
        # rather than the byte-exact response body.
        assert etag.startswith('W/"') and etag.endswith('"')


# --- Missing collections ---------------------------------------------------


class TestMissingCollections:
    def test_missing_imports_collection_returns_self_only(self) -> None:
        db = _make_db(
            registry_entries={"ont-self": {"_key": "ont-self", "name": "Self"}},
            aql_responses={},
            missing_collections=("imports",),
        )
        result = compute_effective_ontology(db, ontology_id="ont-self")
        assert [s["_key"] for s in result["sources"]] == ["ont-self"]

    def test_missing_ontology_classes_returns_empty_classes(self) -> None:
        db = _make_db(
            registry_entries={"ont-self": {"_key": "ont-self", "name": "Self"}},
            aql_responses={},
            missing_collections=("ontology_classes",),
        )
        result = compute_effective_ontology(db, ontology_id="ont-self")
        assert result["classes"] == []

    def test_missing_all_edge_collections_returns_empty_edges(self) -> None:
        db = _make_db(
            registry_entries={"ont-self": {"_key": "ont-self", "name": "Self"}},
            aql_responses={},
            missing_collections=(
                "subclass_of",
                "rdfs_domain",
                "rdfs_range_class",
                "equivalent_class",
                "has_property",
                "related_to",
            ),
        )
        result = compute_effective_ontology(db, ontology_id="ont-self")
        assert result["edges"] == []

    def test_default_max_depth_is_module_constant(self) -> None:
        """Guardrail: keep the public constant at 10 unless deliberately raised."""
        assert DEFAULT_MAX_DEPTH == 10


# --- Telemetry (Stream 12 T6) ---------------------------------------------


class TestTimingTelemetry:
    """The canvas loads ``/effective``, so per-stage timing must surface here.

    Pins the Stream 12 T6 telemetry contract: one ``log.info`` line per
    computation, carrying every stage's ``ms_*`` field plus the entity
    counts in ``extra`` so production JSON loggers can index the breakdown.
    """

    def test_emits_one_per_stage_timing_log(self, caplog: pytest.LogCaptureFixture) -> None:
        db = _make_db(
            registry_entries={"ont-self": {"_key": "ont-self", "name": "Solo", "updated_at": 1}},
            aql_responses={
                "FOR c IN ontology_classes": [
                    {
                        "_key": "C1",
                        "_id": "ontology_classes/C1",
                        "uri": "http://ex.org/C1",
                        "ontology_id": "ont-self",
                        "label": "Person",
                    }
                ]
            },
        )

        with caplog.at_level("INFO", logger="app.services.ontology_effective"):
            compute_effective_ontology(db, ontology_id="ont-self")

        timing = [r for r in caplog.records if "compute_effective_ontology timing" in r.message]
        assert len(timing) == 1, "exactly one timing line per computation"

        rec = timing[0]
        # Every stage timer is present as a structured field for JSON loggers.
        for field in (
            "ms_meta_snapshot",
            "ms_closure_aql",
            "ms_fetch_aql",
            "ms_project",
            "ms_conflicts",
            "ms_etag",
            "ms_total_handler",
        ):
            assert isinstance(getattr(rec, field), float), field

        # Counts reflect the merged result, and the human-readable message
        # bakes them in (the dev log formatter shows only the message).
        assert rec.class_count == 1
        assert rec.source_count == 1
        assert rec.include == "summary"
        assert "TOTAL=" in rec.message and "classes=1" in rec.message
