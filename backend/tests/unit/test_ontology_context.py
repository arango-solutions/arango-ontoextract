"""Unit tests for ontology context serialization."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.ontology_context import (
    CQ_SCOPE_CONTEXT_HEADER,
    EFFECTIVE_CONTEXT_HEADER,
    get_domain_ontology_for_org,
    serialize_cq_scope_context,
    serialize_domain_context,
    serialize_effective_ontology_context,
    serialize_multi_domain_context,
    set_domain_ontology_for_org,
)


def _mock_db(
    *,
    classes: list[dict] | None = None,
    edges: list[dict] | None = None,
    properties: list[dict] | None = None,
    rdfs_domain_rows: list[dict] | None = None,
    registry_name: str | None = None,
    org_ontologies: list[str] | None = None,
):
    """Create a mock ArangoDB database with configurable query results.

    ``has_collection`` reflects which collections exist: by default registry,
    classes, subclass_of, and ontology_properties (no ``rdfs_domain``).
    Pass ``rdfs_domain_rows`` to simulate PGT: adds ``rdfs_domain`` and an
    extra AQL result row after subclass edges.
    """
    db = MagicMock()

    present_cols = {
        "ontology_registry",
        "ontology_classes",
        "subclass_of",
        "ontology_properties",
    }
    if rdfs_domain_rows is not None:
        present_cols.add("rdfs_domain")
    if properties is None and rdfs_domain_rows is not None:
        present_cols.discard("ontology_properties")

    db.has_collection.side_effect = lambda name: name in present_cols

    call_count = {"n": 0}
    query_results = []

    if registry_name is not None:
        query_results.append(iter([registry_name]))
    else:
        query_results.append(iter(["test_ontology"]))

    if classes is not None:
        query_results.append(iter(classes))
    else:
        query_results.append(iter([]))

    if edges is not None:
        query_results.append(iter(edges))
    else:
        query_results.append(iter([]))

    if rdfs_domain_rows is not None:
        query_results.append(iter(rdfs_domain_rows))

    if properties is not None:
        query_results.append(iter(properties))
    elif rdfs_domain_rows is None:
        query_results.append(iter([]))

    def execute_side_effect(query, bind_vars=None):
        idx = call_count["n"]
        call_count["n"] += 1
        if idx < len(query_results):
            return query_results[idx]
        return iter([])

    db.aql.execute.side_effect = execute_side_effect
    return db


class TestSerializeDomainContext:
    def test_empty_ontology_returns_none_marker(self):
        db = _mock_db(classes=[])
        result = serialize_domain_context(db, ontology_id="test")
        assert "Domain: test_ontology" in result
        assert "(none)" in result

    def test_single_root_class(self):
        classes = [
            {
                "_id": "ontology_classes/1",
                "_key": "1",
                "uri": "http://ex.org#Vehicle",
                "label": "Vehicle",
                "ontology_id": "test",
            }
        ]
        db = _mock_db(classes=classes)
        result = serialize_domain_context(db, ontology_id="test")
        assert "Vehicle" in result
        assert "Domain:" in result

    def test_hierarchy_with_children(self):
        classes = [
            {
                "_id": "ontology_classes/1",
                "_key": "1",
                "uri": "http://ex.org#Vehicle",
                "label": "Vehicle",
                "ontology_id": "test",
            },
            {
                "_id": "ontology_classes/2",
                "_key": "2",
                "uri": "http://ex.org#Car",
                "label": "Car",
                "ontology_id": "test",
            },
        ]
        edges = [
            {
                "_from": "ontology_classes/2",
                "_to": "ontology_classes/1",
            }
        ]
        db = _mock_db(classes=classes, edges=edges)
        result = serialize_domain_context(db, ontology_id="test")
        assert "Vehicle" in result
        assert "Car" in result

    def test_with_properties(self):
        classes = [
            {
                "_id": "ontology_classes/1",
                "_key": "1",
                "uri": "http://ex.org#Person",
                "label": "Person",
                "ontology_id": "test",
            }
        ]
        properties = [
            {
                "domain_class_id": "ontology_classes/1",
                "label": "name",
                "uri": "http://ex.org#name",
            },
            {
                "domain_class_id": "ontology_classes/1",
                "label": "age",
                "uri": "http://ex.org#age",
            },
        ]
        db = _mock_db(classes=classes, properties=properties)
        result = serialize_domain_context(db, ontology_id="test")
        assert "Person" in result
        assert "props:" in result

    def test_pgt_property_labels_via_rdfs_domain(self):
        classes = [
            {
                "_id": "ontology_classes/1",
                "_key": "1",
                "uri": "http://ex.org#Person",
                "label": "Person",
                "ontology_id": "test",
            }
        ]
        rdfs_rows = [
            {"class_id": "ontology_classes/1", "label": "fullName"},
            {"class_id": "ontology_classes/1", "label": "age"},
        ]
        db = _mock_db(
            classes=classes,
            edges=[],
            rdfs_domain_rows=rdfs_rows,
        )
        result = serialize_domain_context(db, ontology_id="test")
        assert "Person" in result
        assert "fullName" in result
        assert "age" in result
        assert "props:" in result


class TestGetDomainOntologyForOrg:
    def test_returns_empty_when_no_collection(self):
        db = MagicMock()
        db.has_collection.return_value = False
        result = get_domain_ontology_for_org(db, org_id="org1")
        assert result == []

    def test_returns_empty_when_no_org(self):
        db = MagicMock()
        db.has_collection.return_value = True
        db.aql.execute.return_value = iter([None])
        result = get_domain_ontology_for_org(db, org_id="org1")
        assert result == []

    def test_returns_ontology_ids(self):
        db = MagicMock()
        db.has_collection.return_value = True
        db.aql.execute.return_value = iter([["onto_1", "onto_2"]])
        result = get_domain_ontology_for_org(db, org_id="org1")
        assert result == ["onto_1", "onto_2"]


class TestSetDomainOntologyForOrg:
    def test_validates_ontology_ids_exist(self):
        db = MagicMock()
        db.has_collection.return_value = True
        db.aql.execute.return_value = iter([])

        with pytest.raises(ValueError, match="not found in registry"):
            set_domain_ontology_for_org(db, org_id="org1", ontology_ids=["bad_id"])

    def test_creates_org_if_not_exists(self):
        db = MagicMock()
        db.has_collection.side_effect = lambda col: col != "organizations"

        call_count = {"n": 0}

        def execute_side(query, bind_vars=None):
            call_count["n"] += 1
            return iter([])

        db.aql.execute.side_effect = execute_side
        col_mock = MagicMock()
        col_mock.insert.return_value = {"new": {"_key": "org1", "selected_ontologies": []}}
        db.collection.return_value = col_mock
        db.create_collection.return_value = None

        result = set_domain_ontology_for_org(db, org_id="org1", ontology_ids=[])
        assert result["_key"] == "org1"


class TestSerializeMultiDomainContext:
    def test_empty_ontology_ids(self):
        db = MagicMock()
        result = serialize_multi_domain_context(db, ontology_ids=[])
        assert result == ""


# ---------------------------------------------------------------------------
# H.17: serialize_effective_ontology_context
# ---------------------------------------------------------------------------


def _effective_payload(
    *,
    ontology_id: str = "wtw",
    ontology_name: str = "WTW Ontology",
    classes: list[dict] | None = None,
    edges: list[dict] | None = None,
    sources: list[dict] | None = None,
):
    """Build the dict shape that ``compute_effective_ontology`` returns.

    The serializer reads ``ontology_id``, ``ontology_name``, ``classes``,
    ``edges``, and ``sources``; ``conflicts`` / ``etag`` / ``truncated``
    are passed through unread so we leave them out of the fixture to
    keep the test signal-to-noise high.
    """
    return {
        "ontology_id": ontology_id,
        "ontology_name": ontology_name,
        "classes": classes or [],
        "edges": edges or [],
        "sources": sources
        or [{"_key": ontology_id, "name": ontology_name, "is_self": True, "depth": 0}],
        "conflicts": [],
        "etag": "etag-test",
        "truncated": False,
    }


def _mock_effective_db():
    """Minimal ``has_collection``-aware mock; the serializer does not
    issue AQL itself (it goes through ``compute_effective_ontology``
    which we patch), so we don't need to script query results."""
    db = MagicMock()
    db.has_collection.return_value = True
    return db


class TestSerializeEffectiveOntologyContext:
    """H.17 import-aware extraction context.

    The serializer is the single point of LLM-facing serialization for
    the effective ontology, so each branch of the output format gets a
    dedicated test:

      * empty target with no imports -> empty string (don't waste tokens)
      * non-empty self, no imports   -> own section + footer, no "Imported"
      * non-empty self, with imports -> own + per-source imported sections
      * tree nesting under subclass_of edges
      * source name fallback to ``_key`` when the registry row lacks ``name``
      * URI-not-found in registry -> empty string (no crash)
    """

    def _patched(self, payload):
        return patch(
            "app.services.ontology_effective.compute_effective_ontology",
            return_value=payload,
        )

    def test_empty_target_with_no_imports_returns_empty(self):
        # Greenfield ontology with nothing in it. We expect "" so the
        # prompt stays unchanged for first-run extractions.
        with self._patched(_effective_payload(classes=[])):
            db = _mock_effective_db()
            result = serialize_effective_ontology_context(db, ontology_id="wtw")
        assert result == ""

    def test_owned_only_renders_self_section_and_footer(self):
        # ``compute_effective_ontology`` annotates each class with
        # ``source_ontology_id`` -- when it equals the target, the class
        # belongs to "Your ontology (<name>)".
        payload = _effective_payload(
            classes=[
                {
                    "_id": "ontology_classes/wtw_person",
                    "_key": "wtw_person",
                    "label": "Person",
                    "uri": "http://example.org/wtw#Person",
                    "source_ontology_id": "wtw",
                    "source_ontology_name": "WTW Ontology",
                    "is_imported": False,
                },
            ],
        )
        with self._patched(payload):
            db = _mock_effective_db()
            result = serialize_effective_ontology_context(db, ontology_id="wtw")

        assert EFFECTIVE_CONTEXT_HEADER in result
        assert "Your ontology (WTW Ontology):" in result
        assert "- Person [http://example.org/wtw#Person]" in result
        # No imports -> no "Imported from" section.
        assert "Imported from" not in result
        # Footer guidelines always present so the LLM has the reuse rules.
        assert "Guidelines:" in result
        assert "REUSE its URI" in result

    def test_imports_render_per_source_section_with_depth(self):
        # Target imports FOAF (depth 1). Each class carries its source
        # annotation; the renderer groups by ``source_ontology_id``.
        payload = _effective_payload(
            classes=[
                {
                    "_id": "ontology_classes/wtw_person",
                    "_key": "wtw_person",
                    "label": "WTW Person",
                    "uri": "http://example.org/wtw#Person",
                    "source_ontology_id": "wtw",
                    "source_ontology_name": "WTW Ontology",
                    "is_imported": False,
                },
                {
                    "_id": "ontology_classes/foaf_agent",
                    "_key": "foaf_agent",
                    "label": "Agent",
                    "uri": "http://xmlns.com/foaf/0.1/Agent",
                    "source_ontology_id": "foaf",
                    "source_ontology_name": "FOAF",
                    "is_imported": True,
                },
            ],
            sources=[
                {"_key": "wtw", "name": "WTW Ontology", "is_self": True, "depth": 0},
                {"_key": "foaf", "name": "FOAF", "is_self": False, "depth": 1},
            ],
        )
        with self._patched(payload):
            db = _mock_effective_db()
            result = serialize_effective_ontology_context(db, ontology_id="wtw")

        # Self always renders first (depth 0) -- pinning order matters
        # because the LLM tends to weight earlier sections more.
        self_idx = result.index("Your ontology (WTW Ontology):")
        imported_idx = result.index("Imported from FOAF (depth 1):")
        assert self_idx < imported_idx
        assert "- WTW Person [http://example.org/wtw#Person]" in result
        assert "- Agent [http://xmlns.com/foaf/0.1/Agent]" in result

    def test_subclass_edges_produce_nested_tree(self):
        # Person rdfs:subClassOf Agent (both in self). The renderer must
        # nest Agent's children -- two-space indent per depth.
        payload = _effective_payload(
            classes=[
                {
                    "_id": "ontology_classes/agent",
                    "_key": "agent",
                    "label": "Agent",
                    "uri": "ex:Agent",
                    "source_ontology_id": "wtw",
                    "source_ontology_name": "WTW",
                    "is_imported": False,
                },
                {
                    "_id": "ontology_classes/person",
                    "_key": "person",
                    "label": "Person",
                    "uri": "ex:Person",
                    "source_ontology_id": "wtw",
                    "source_ontology_name": "WTW",
                    "is_imported": False,
                },
            ],
            edges=[
                {
                    "_from": "ontology_classes/person",
                    "_to": "ontology_classes/agent",
                    "edge_type": "subclass_of",
                    "source_ontology_id": "wtw",
                },
            ],
        )
        with self._patched(payload):
            db = _mock_effective_db()
            result = serialize_effective_ontology_context(db, ontology_id="wtw")

        # Agent is root (no incoming subclass_of as child); Person nested.
        assert "- Agent [ex:Agent]" in result
        assert "  - Person [ex:Person]" in result
        # Person should NOT appear as a root (no leading "- Person" at
        # zero indent) -- catches a regression where children leak to
        # the root list.
        for line in result.splitlines():
            if line.startswith("- Person"):
                pytest.fail(f"Person should be nested under Agent, got root line: {line!r}")

    def test_falls_back_to_source_key_when_name_missing(self):
        # Defensive: registry rows historically lacked ``name`` for some
        # ontologies. The header must still read "Imported from <key>"
        # rather than "Imported from None".
        payload = _effective_payload(
            classes=[
                {
                    "_id": "ontology_classes/wtw_x",
                    "_key": "wtw_x",
                    "label": "X",
                    "uri": "ex:X",
                    "source_ontology_id": "wtw",
                    "source_ontology_name": "WTW",
                    "is_imported": False,
                },
                {
                    "_id": "ontology_classes/foo_y",
                    "_key": "foo_y",
                    "label": "Y",
                    "uri": "ex:Y",
                    "source_ontology_id": "foo",
                    "source_ontology_name": None,
                    "is_imported": True,
                },
            ],
            sources=[
                {"_key": "wtw", "name": "WTW", "is_self": True, "depth": 0},
                {"_key": "foo", "name": None, "is_self": False, "depth": 1},
            ],
        )
        with self._patched(payload):
            db = _mock_effective_db()
            result = serialize_effective_ontology_context(db, ontology_id="wtw")

        assert "Imported from foo (depth 1):" in result
        assert "Imported from None" not in result

    def test_unknown_target_returns_empty(self):
        # ``compute_effective_ontology`` raises ``ValueError`` when the
        # registry has no row for the target. The serializer swallows it
        # so the extraction prompt is unchanged rather than poisoned
        # with an exception message.
        with patch(
            "app.services.ontology_effective.compute_effective_ontology",
            side_effect=ValueError("ontology not found"),
        ):
            db = _mock_effective_db()
            result = serialize_effective_ontology_context(db, ontology_id="ghost")
        assert result == ""


_CQ_SPEC = {
    "purpose": "Answer supply-chain questions",
    "scope": "Automotive parts",
    "use_cases": [
        {
            "name": "Sourcing",
            "competency_questions": [
                {"id": "q2", "text": "Which parts are low priority?", "priority": "P3"},
                {
                    "id": "q1",
                    "text": "Who supplies part X?",
                    "priority": "P1",
                    "expected_answer_shape": "list of Supplier",
                },
            ],
        }
    ],
}


class TestSerializeCqScopeContext:
    def test_returns_empty_when_no_spec(self):
        db = MagicMock()
        with patch("app.db.requirements_repo.get_requirements", return_value=None):
            assert serialize_cq_scope_context(db, ontology_id="o1") == ""

    def test_returns_empty_when_no_cqs(self):
        db = MagicMock()
        with patch(
            "app.db.requirements_repo.get_requirements",
            return_value={"purpose": "x", "use_cases": []},
        ):
            assert serialize_cq_scope_context(db, ontology_id="o1") == ""

    def test_renders_header_purpose_and_priority_ordered_cqs(self):
        db = MagicMock()
        with patch("app.db.requirements_repo.get_requirements", return_value=_CQ_SPEC):
            out = serialize_cq_scope_context(db, ontology_id="o1")
        assert CQ_SCOPE_CONTEXT_HEADER in out
        assert "Purpose: Answer supply-chain questions" in out
        assert "Scope: Automotive parts" in out
        assert "Use case: Sourcing" in out
        # P1 CQ must render before the P3 CQ (priority ordering)
        assert out.index("Who supplies part X?") < out.index("Which parts are low priority?")
        # expected-answer hint surfaced
        assert "expected answer: list of Supplier" in out
        # priority label shown
        assert "[P1]" in out and "[P3]" in out
