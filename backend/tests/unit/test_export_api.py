"""Unit tests for ``GET /api/v1/ontology/{id}/export``.

Stream 3 PR 5 added a fourth format (``shacl``) so the endpoint now
routes ``turtle`` / ``jsonld`` / ``csv`` / ``shacl`` to four different
service helpers. We exercise the route handler directly (no server,
no DB) to pin the routing contract and the filename / media-type
conventions for each format.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.ontology import export_ontology_endpoint


def _registry_entry() -> dict[str, object]:
    return {"_key": "onto_1", "name": "Test Ontology"}


@pytest.mark.asyncio
async def test_returns_404_when_ontology_missing() -> None:
    with (
        patch("app.api.ontology.registry_repo.get_registry_entry", return_value=None),
        pytest.raises(HTTPException) as excinfo,
    ):
        await export_ontology_endpoint("missing", format="turtle")
    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_turtle_format_calls_export_ontology_with_turtle() -> None:
    with (
        patch(
            "app.api.ontology.registry_repo.get_registry_entry",
            return_value=_registry_entry(),
        ),
        patch(
            "app.api.ontology.export_svc.export_ontology",
            return_value="@prefix : <ex#> .",
        ) as mock_owl,
    ):
        resp = await export_ontology_endpoint("onto_1", format="turtle")
    mock_owl.assert_called_once_with("onto_1", fmt="turtle")
    assert resp.media_type == "text/turtle"
    assert 'filename="onto_1.ttl"' in resp.headers["Content-Disposition"]


@pytest.mark.asyncio
async def test_shacl_format_calls_export_shacl_with_shapes_filename() -> None:
    """Stream 3 PR 5 -- the new ``shacl`` format must hit
    ``export_shacl``, NOT ``export_ontology``. Filename convention is
    ``.shapes.ttl`` so a downstream parser picks up the shapes graph
    next to the main ontology Turtle."""
    with (
        patch(
            "app.api.ontology.registry_repo.get_registry_entry",
            return_value=_registry_entry(),
        ),
        patch(
            "app.api.ontology.export_svc.export_shacl",
            return_value="@prefix sh: <http://www.w3.org/ns/shacl#> .",
        ) as mock_shacl,
        # If routing accidentally falls through to the turtle branch
        # we want a hard failure, not a passing test.
        patch(
            "app.api.ontology.export_svc.export_ontology",
            side_effect=AssertionError("must not call export_ontology for format=shacl"),
        ),
    ):
        resp = await export_ontology_endpoint("onto_1", format="shacl")
    mock_shacl.assert_called_once_with("onto_1")
    assert resp.media_type == "text/turtle"
    assert 'filename="onto_1.shapes.ttl"' in resp.headers["Content-Disposition"]


@pytest.mark.asyncio
async def test_unknown_format_falls_through_to_turtle_default() -> None:
    """The handler treats anything not in {jsonld, csv, shacl} as
    turtle. Pin the fall-through so a typo (``?format=tuttle``) still
    returns useful output rather than 500."""
    with (
        patch(
            "app.api.ontology.registry_repo.get_registry_entry",
            return_value=_registry_entry(),
        ),
        patch(
            "app.api.ontology.export_svc.export_ontology",
            return_value="@prefix : <ex#> .",
        ) as mock_owl,
    ):
        resp = await export_ontology_endpoint("onto_1", format="tuttle")  # typo
    mock_owl.assert_called_once()
    assert resp.media_type == "text/turtle"
