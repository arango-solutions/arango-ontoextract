"""Unit tests for ``GET /api/v1/ontology/schema/diff``.

Stream 5 PR 3 sub-B -- S.5. We exercise the route handler directly
(no server, no DB) by mocking the underlying ``diff_ontologies``
service. The service has its own dedicated test module
(``test_schema_diff.py``); here we pin the API contract:

* query params land in the service call,
* service result is returned verbatim,
* ``ValueError`` -> 400 (caller mistake -- eg same ID for both sides).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.api.ontology import diff_schema_ontologies


@pytest.mark.asyncio
async def test_forwards_query_params_to_service_and_returns_result() -> None:
    """The endpoint must NOT massage the service result -- the
    workspace UI binds to the exact shape the service returns, and a
    surprise field rename in the API layer would break it silently.
    """
    expected = {
        "ontology_a": "left",
        "ontology_b": "right",
        "classes": {"added": [], "removed": [], "changed": []},
        "properties": {"added": [], "removed": [], "changed": []},
        "constraints": {"added": [], "removed": [], "changed": []},
        "summary": {
            "classes_added": 0,
            "classes_removed": 0,
            "classes_changed": 0,
            "properties_added": 0,
            "properties_removed": 0,
            "properties_changed": 0,
            "constraints_added": 0,
            "constraints_removed": 0,
            "constraints_changed": 0,
        },
        "provenance": {
            "a": {},
            "b": {},
            "compatible": False,
            "warning": "diff is between arbitrary ontologies",
        },
    }
    with patch(
        "app.api.ontology.schema_diff_svc.diff_ontologies",
        return_value=expected,
    ) as mock_svc:
        result = await diff_schema_ontologies(a="left", b="right")

    mock_svc.assert_called_once_with(ontology_a="left", ontology_b="right")
    assert result == expected


@pytest.mark.asyncio
async def test_self_diff_returns_400() -> None:
    """The service raises ``ValueError`` when the same id is passed
    twice; the API must convert that to a 400 (caller mistake) rather
    than letting it surface as a 500.
    """
    with (
        patch(
            "app.api.ontology.schema_diff_svc.diff_ontologies",
            side_effect=ValueError("Cannot diff an ontology against itself"),
        ),
        pytest.raises(HTTPException) as exc_info,
    ):
        await diff_schema_ontologies(a="same", b="same")

    assert exc_info.value.status_code == 400
    assert "itself" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_provenance_warning_passes_through_verbatim() -> None:
    """The warning string carries human-readable context (source DB
    names, hosts) that the curator needs to interpret the result.
    The API layer must not truncate or rewrite it.
    """
    warning = (
        "Ontologies target different source databases "
        "(prod@http://h1:8529 vs staging@http://h2:8529); "
        "diff is between unrelated schemas."
    )
    service_result = {
        "ontology_a": "x",
        "ontology_b": "y",
        "classes": {"added": [], "removed": [], "changed": []},
        "properties": {"added": [], "removed": [], "changed": []},
        "constraints": {"added": [], "removed": [], "changed": []},
        "summary": {
            k: 0
            for k in (
                "classes_added",
                "classes_removed",
                "classes_changed",
                "properties_added",
                "properties_removed",
                "properties_changed",
                "constraints_added",
                "constraints_removed",
                "constraints_changed",
            )
        },
        "provenance": {
            "a": {"source_db": "prod", "source_host": "http://h1:8529"},
            "b": {"source_db": "staging", "source_host": "http://h2:8529"},
            "compatible": False,
            "warning": warning,
        },
    }
    with patch(
        "app.api.ontology.schema_diff_svc.diff_ontologies",
        return_value=service_result,
    ):
        result = await diff_schema_ontologies(a="x", b="y")

    assert result["provenance"]["warning"] == warning
    assert result["provenance"]["compatible"] is False


@pytest.mark.asyncio
async def test_distinct_ids_passed_through_unchanged() -> None:
    """The router declared the query params as ``a`` and ``b`` (short
    so URLs stay tidy); they map to ``ontology_a`` / ``ontology_b``
    on the service. Pinning this lets a future contributor rename
    them without silently breaking the call site.
    """
    with patch(
        "app.api.ontology.schema_diff_svc.diff_ontologies",
        return_value={"ontology_a": "onto_x", "ontology_b": "onto_y"},
    ) as mock_svc:
        await diff_schema_ontologies(a="onto_x", b="onto_y")

    args, kwargs = mock_svc.call_args
    assert args == ()
    assert kwargs == {"ontology_a": "onto_x", "ontology_b": "onto_y"}
