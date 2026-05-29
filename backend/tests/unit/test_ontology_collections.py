"""Tests for the canonical ontology collection-name allowlists (ADR-006).

Locks the property-vertex triple's contents/order and guards against the
duplication that this constant replaced: every module that used to declare
its own copy must now resolve to the same shared tuple.
"""

from __future__ import annotations

from app.db.ontology_collections import PROPERTY_VERTEX_COLLECTIONS


def test_property_triple_contents_and_order():
    # Legacy single collection first (pre-ADR-006), then the PGT split.
    assert PROPERTY_VERTEX_COLLECTIONS == (
        "ontology_properties",
        "ontology_object_properties",
        "ontology_datatype_properties",
    )


def test_consumers_resolve_to_the_shared_triple():
    """Regression guard: the modules that previously re-declared the triple
    inline must now derive from the canonical constant."""
    from app.db import ontology_repo
    from app.mcp.resources import ontology as mcp_resource_ontology
    from app.mcp.tools import ontology as mcp_tool_ontology
    from app.services import schema_diff, temporal

    expected = list(PROPERTY_VERTEX_COLLECTIONS)
    assert expected == ontology_repo._PROPERTY_COLLECTIONS
    assert expected == schema_diff._PROPERTY_COLLECTIONS
    assert expected == temporal._PROPERTY_VERTEX_COLLECTIONS
    assert tuple(mcp_tool_ontology._PROPERTY_VERTEX_COLLECTIONS) == PROPERTY_VERTEX_COLLECTIONS
    assert tuple(mcp_resource_ontology._PROPERTY_VERTEX_COLLECTIONS) == PROPERTY_VERTEX_COLLECTIONS


def test_vertex_supersets_embed_the_triple_in_order():
    """The classes+triple(+constraints) supersets must contain the triple
    contiguously and in the canonical order."""
    from app.services import ontology_dependency, promotion, temporal

    for superset in (
        temporal._ONTOLOGY_VERTEX_COLLECTIONS,
        ontology_dependency._VERTEX_COLLECTIONS,
        promotion._VERTEX_COLLECTIONS,
    ):
        seq = list(superset)
        start = seq.index("ontology_properties")
        assert (
            tuple(seq[start : start + len(PROPERTY_VERTEX_COLLECTIONS)])
            == PROPERTY_VERTEX_COLLECTIONS
        )
        assert seq[0] == "ontology_classes"
