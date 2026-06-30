"""Unit tests for ``GET /api/v1/ontology/{id}/classes`` (Stream 12 T10).

T10 adds **opt-in keyset pagination** to the classes list endpoint without
changing the legacy full-list contract. The criteria these tests pin:

1. **Back-compat:** with no ``limit`` the endpoint returns the full class
   list (``{data: [...]}``) via the original single AQL, and the shared
   :func:`paginate` helper is NOT invoked.
2. **Paginated:** with ``limit`` set the response is a bounded page plus
   ``next_cursor`` / ``has_more`` / ``total_count``, delegating to
   :func:`app.db.pagination.paginate` with the right collection / sort /
   filters.
3. **Summary projection** still applies on the paginated path (evidence
   stripped) and is applied in Python after the page is fetched.
4. **Invalid cursor** surfaces as ``400`` (not a 500), including when the
   real :func:`decode_cursor` rejects a corrupt token.
5. A **real keyset round-trip** through ``paginate`` produces a decodable
   ``next_cursor`` ordered by ``(label, _key)``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.db.pagination import decode_cursor
from app.models.common import PaginatedResponse


def _make_db(has_classes: bool = True) -> MagicMock:
    db = MagicMock()
    db.has_collection.return_value = has_classes
    return db


def _client(db: MagicMock) -> TestClient:
    patcher = patch("app.api.ontology._shared.get_db", return_value=db)
    patcher.start()
    from app.main import app

    client = TestClient(app)
    client._patcher = patcher  # type: ignore[attr-defined]
    return client


# ---------------------------------------------------------------------------
# Back-compat: no limit -> full list, paginate untouched
# ---------------------------------------------------------------------------


class TestFullListBackCompat:
    def test_no_limit_returns_full_list_via_single_aql(self):
        db = _make_db()
        docs = [
            {"_key": "c1", "label": "Account", "ontology_id": "ont1"},
            {"_key": "c2", "label": "Bond", "ontology_id": "ont1"},
        ]
        with (
            patch("app.api.ontology._shared.run_aql", return_value=docs) as run_aql_mock,
            patch("app.api.ontology._shared.paginate") as paginate_mock,
        ):
            client = _client(db)
            try:
                r = client.get("/api/v1/ontology/ont1/classes")
            finally:
                client._patcher.stop()  # type: ignore[attr-defined]

        assert r.status_code == 200
        assert r.json() == {"data": docs}
        # Legacy shape: no pagination envelope fields.
        assert "next_cursor" not in r.json()
        # The shared keyset helper must NOT be touched on the full path.
        paginate_mock.assert_not_called()
        assert run_aql_mock.call_count == 1

    def test_missing_collection_returns_empty_full_shape(self):
        db = _make_db(has_classes=False)
        with patch("app.api.ontology._shared.run_aql") as run_aql_mock:
            client = _client(db)
            try:
                r = client.get("/api/v1/ontology/ont1/classes")
            finally:
                client._patcher.stop()  # type: ignore[attr-defined]
            run_aql_mock.assert_not_called()
        assert r.status_code == 200
        assert r.json() == {"data": []}


# ---------------------------------------------------------------------------
# Paginated path
# ---------------------------------------------------------------------------


class TestPaginatedPath:
    def test_limit_delegates_to_paginate_with_label_keyset(self):
        db = _make_db()
        page = PaginatedResponse(
            data=[
                {"_key": "c1", "label": "Account", "ontology_id": "ont1"},
                {"_key": "c2", "label": "Bond", "ontology_id": "ont1"},
            ],
            cursor="CURSOR_ABC",
            has_more=True,
            total_count=10,
        )
        with patch("app.api.ontology._shared.paginate", return_value=page) as paginate_mock:
            client = _client(db)
            try:
                r = client.get("/api/v1/ontology/ont1/classes?limit=2")
            finally:
                client._patcher.stop()  # type: ignore[attr-defined]

        assert r.status_code == 200
        body = r.json()
        assert [c["_key"] for c in body["data"]] == ["c1", "c2"]
        assert body["next_cursor"] == "CURSOR_ABC"
        assert body["has_more"] is True
        assert body["total_count"] == 10

        kwargs = paginate_mock.call_args.kwargs
        assert kwargs["collection"] == "ontology_classes"
        assert kwargs["sort_field"] == "label"
        assert kwargs["sort_order"] == "asc"
        assert kwargs["limit"] == 2
        assert kwargs["cursor"] is None
        assert kwargs["filters"]["ontology_id"] == "ont1"
        # The temporal "live only" filter must be threaded through.
        assert "expired" in kwargs["filters"]

    def test_cursor_is_forwarded_to_paginate(self):
        db = _make_db()
        page = PaginatedResponse(data=[], cursor=None, has_more=False, total_count=0)
        with patch("app.api.ontology._shared.paginate", return_value=page) as paginate_mock:
            client = _client(db)
            try:
                r = client.get("/api/v1/ontology/ont1/classes?limit=5&cursor=PREV")
            finally:
                client._patcher.stop()  # type: ignore[attr-defined]
        assert r.status_code == 200
        assert paginate_mock.call_args.kwargs["cursor"] == "PREV"

    def test_last_page_has_null_next_cursor(self):
        db = _make_db()
        page = PaginatedResponse(
            data=[{"_key": "c9", "label": "Zeta", "ontology_id": "ont1"}],
            cursor=None,
            has_more=False,
            total_count=1,
        )
        with patch("app.api.ontology._shared.paginate", return_value=page):
            client = _client(db)
            try:
                r = client.get("/api/v1/ontology/ont1/classes?limit=25")
            finally:
                client._patcher.stop()  # type: ignore[attr-defined]
        body = r.json()
        assert body["next_cursor"] is None
        assert body["has_more"] is False

    def test_summary_profile_strips_evidence_on_paginated_path(self):
        db = _make_db()
        heavy = {
            "_key": "c1",
            "label": "Account",
            "ontology_id": "ont1",
            "uri": "http://x/Account",
            "status": "approved",
            "evidence": [{"text": "x" * 5000, "evidence_confidence": 0.9}],
        }
        page = PaginatedResponse(data=[heavy], cursor=None, has_more=False, total_count=1)
        with patch("app.api.ontology._shared.paginate", return_value=page):
            client = _client(db)
            try:
                r = client.get("/api/v1/ontology/ont1/classes?limit=10&include=summary")
            finally:
                client._patcher.stop()  # type: ignore[attr-defined]
        cls = r.json()["data"][0]
        assert "evidence" not in cls
        assert cls["label"] == "Account"

    def test_missing_collection_returns_empty_paginated_shape(self):
        db = _make_db(has_classes=False)
        client = _client(db)
        try:
            r = client.get("/api/v1/ontology/ont1/classes?limit=10")
        finally:
            client._patcher.stop()  # type: ignore[attr-defined]
        assert r.status_code == 200
        assert r.json() == {
            "data": [],
            "next_cursor": None,
            "has_more": False,
            "total_count": 0,
        }


# ---------------------------------------------------------------------------
# Invalid cursor handling
# ---------------------------------------------------------------------------


class TestInvalidCursor:
    def test_paginate_value_error_becomes_400(self):
        db = _make_db()
        with patch("app.api.ontology._shared.paginate", side_effect=ValueError("bad cursor")):
            client = _client(db)
            try:
                r = client.get("/api/v1/ontology/ont1/classes?limit=5&cursor=garbage")
            finally:
                client._patcher.stop()  # type: ignore[attr-defined]
        assert r.status_code == 400
        assert "cursor" in r.json()["detail"].lower()

    def test_real_decode_cursor_rejects_corrupt_token_with_400(self):
        # Exercise the genuine decode path: a non-base64 cursor makes the
        # real ``paginate`` -> ``decode_cursor`` raise, which the route must
        # translate to 400 rather than letting it 500.
        db = _make_db()
        with patch("app.db.pagination.run_aql") as inner_run_aql:
            client = _client(db)
            try:
                r = client.get("/api/v1/ontology/ont1/classes?limit=5&cursor=not!base64!!")
            finally:
                client._patcher.stop()  # type: ignore[attr-defined]
            # Decoding fails before any AQL is issued.
            inner_run_aql.assert_not_called()
        assert r.status_code == 400


# ---------------------------------------------------------------------------
# Real keyset round-trip through paginate
# ---------------------------------------------------------------------------


class TestRealKeysetRoundTrip:
    def test_next_cursor_decodes_to_last_row_label_and_key(self):
        db = _make_db()
        # limit=2 -> paginate fetches lim=3 to detect has_more.
        data_rows = [
            {"_key": "c1", "label": "Account", "ontology_id": "ont1"},
            {"_key": "c2", "label": "Bond", "ontology_id": "ont1"},
            {"_key": "c3", "label": "Cash", "ontology_id": "ont1"},
        ]
        # paginate issues the data query then a COLLECT WITH COUNT query.
        with patch(
            "app.db.pagination.run_aql",
            side_effect=[data_rows, iter([7])],
        ) as inner_run_aql:
            client = _client(db)
            try:
                r = client.get("/api/v1/ontology/ont1/classes?limit=2")
            finally:
                client._patcher.stop()  # type: ignore[attr-defined]

        assert r.status_code == 200
        body = r.json()
        assert [c["_key"] for c in body["data"]] == ["c1", "c2"]
        assert body["has_more"] is True
        assert body["total_count"] == 7
        # The cursor must point at the last returned row, ordered by label.
        sort_value, key = decode_cursor(body["next_cursor"])
        assert sort_value == "Bond"
        assert key == "c2"
        # Data query + count query == 2 AQL calls.
        assert inner_run_aql.call_count == 2
