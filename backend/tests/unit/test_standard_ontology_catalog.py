"""Unit tests for ``app.services.standard_ontology_catalog`` (Stream 1 H.5).

These tests cover the catalog loader, the bundled-vs-url dispatcher,
and the error-translation contract for the ``GET /catalog`` /
``POST /catalog/{id}/import`` endpoints. They do **not** spin up
ArangoDB: ``import_from_file`` / ``import_from_url`` are mocked at the
module boundary because their own logic is exercised by
``test_arangordf_bridge.py``.

The shipped catalog JSON is also smoke-tested for structural validity
so a malformed entry never escapes ``main``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services import standard_ontology_catalog as svc

# --- Loader ----------------------------------------------------------------


class TestLoadCatalog:
    def test_real_catalog_is_well_formed(self) -> None:
        """The shipped catalog must round-trip and conform to the schema.

        This is a packaging smoke test: a typo in the JSON or a missing
        field would otherwise only surface when a user hits
        ``GET /catalog`` in production.
        """
        entries = svc.load_catalog()

        assert isinstance(entries, list)
        assert len(entries) >= 1, "catalog should ship with at least one entry"

        seen_ids: set[str] = set()
        for entry in entries:
            for field in ("id", "name", "description", "uri", "tier", "source"):
                assert field in entry, f"entry {entry.get('id')!r} missing required field {field!r}"
            assert entry["id"] not in seen_ids, f"duplicate catalog id {entry['id']!r}"
            seen_ids.add(entry["id"])

            source = entry["source"]
            assert source["kind"] in ("bundled", "url"), (
                f"entry {entry['id']!r} has unknown source.kind={source.get('kind')!r}"
            )
            if source["kind"] == "bundled":
                assert source.get("path"), f"bundled entry {entry['id']!r} missing source.path"
            else:
                assert source.get("url"), f"url entry {entry['id']!r} missing source.url"

    def test_get_catalog_entry_hits(self) -> None:
        # dcterms is shipped as a bundled entry; it is the contractual
        # smoke-test entry for the bundled code path.
        entry = svc.get_catalog_entry("dcterms")
        assert entry is not None
        assert entry["id"] == "dcterms"
        assert entry["source"]["kind"] == "bundled"

    def test_get_catalog_entry_miss(self) -> None:
        assert svc.get_catalog_entry("does-not-exist") is None


# --- Import dispatch -------------------------------------------------------


@pytest.fixture()
def _fake_db() -> MagicMock:
    return MagicMock()


@pytest.fixture()
def _patch_registry_repo():
    with patch.object(svc, "registry_repo") as mock_repo:
        # By default no existing registry entry -> import proceeds.
        mock_repo.get_registry_entry.return_value = None
        yield mock_repo


class TestImportCatalogEntry:
    def test_unknown_catalog_id_raises_lookup_error(self, _fake_db, _patch_registry_repo) -> None:
        with pytest.raises(LookupError, match="ghost"):
            svc.import_catalog_entry("ghost", db=_fake_db)

    def test_existing_registry_entry_raises_conflict(self, _fake_db, _patch_registry_repo) -> None:
        from app.api.errors import ConflictError

        _patch_registry_repo.get_registry_entry.return_value = {"_key": "dcterms"}

        with pytest.raises(ConflictError):
            svc.import_catalog_entry("dcterms", db=_fake_db)

    def test_bundled_entry_delegates_to_import_from_file(
        self, _fake_db, _patch_registry_repo
    ) -> None:
        with patch.object(svc, "import_from_file") as mock_import:
            mock_import.return_value = {
                "registry_key": "dcterms",
                "triple_count": 42,
                "source": "file_import",
            }

            result = svc.import_catalog_entry("dcterms", db=_fake_db)

        # File path resolves to the bundled .ttl; bytes are non-empty.
        kwargs = mock_import.call_args.kwargs
        assert kwargs["ontology_id"] == "dcterms"
        assert kwargs["filename"] == "dcterms_minimal.ttl"
        assert isinstance(kwargs["file_content"], (bytes, bytearray))
        assert len(kwargs["file_content"]) > 100, "bundled DCMI file should be > 100 bytes"
        # The catalog wraps the bridge result with catalog-specific tags
        # so the workspace UI can render a "via catalog" badge.
        assert result["source"] == "catalog_import"
        assert result["catalog_id"] == "dcterms"
        assert result["catalog_name"] == "DCMI Metadata Terms"

    def test_url_entry_delegates_to_import_from_url(self, _fake_db, _patch_registry_repo) -> None:
        with patch.object(svc, "import_from_url") as mock_url:
            mock_url.return_value = {
                "registry_key": "foaf",
                "triple_count": 200,
                "source": "url_import",
            }

            result = svc.import_catalog_entry("foaf", db=_fake_db)

        kwargs = mock_url.call_args.kwargs
        assert kwargs["ontology_id"] == "foaf"
        assert kwargs["url"].startswith("http")
        assert result["source"] == "catalog_import"
        assert result["catalog_id"] == "foaf"

    def test_custom_ontology_id_overrides_catalog_id(self, _fake_db, _patch_registry_repo) -> None:
        with patch.object(svc, "import_from_file") as mock_import:
            mock_import.return_value = {"registry_key": "my_dc", "triple_count": 42}

            svc.import_catalog_entry("dcterms", db=_fake_db, ontology_id="my_dc")

        assert mock_import.call_args.kwargs["ontology_id"] == "my_dc"

    def test_missing_bundled_file_raises_runtime_error(
        self,
        _fake_db,
        _patch_registry_repo,
    ) -> None:
        """Defensive: a malformed catalog entry (path pointing at a file
        that's not actually packaged) should surface immediately rather
        than silently delegating to a confused import call.
        """
        with patch.object(svc, "load_catalog") as mock_load:
            mock_load.return_value = [
                {
                    "id": "ghost-bundle",
                    "name": "Phantom",
                    "description": "",
                    "uri": "http://example.org/ghost",
                    "tier": "core",
                    "source": {
                        "kind": "bundled",
                        "path": "does_not_exist.ttl",
                    },
                }
            ]
            with pytest.raises(RuntimeError, match=r"does_not_exist\.ttl"):
                svc.import_catalog_entry("ghost-bundle", db=_fake_db)

    def test_url_entry_without_url_raises_runtime_error(
        self,
        _fake_db,
        _patch_registry_repo,
    ) -> None:
        with patch.object(svc, "load_catalog") as mock_load:
            mock_load.return_value = [
                {
                    "id": "ghost-url",
                    "name": "Phantom URL",
                    "description": "",
                    "uri": "http://example.org/ghost-url",
                    "tier": "core",
                    "source": {"kind": "url"},  # missing url
                }
            ]
            with pytest.raises(RuntimeError, match=r"source\.url"):
                svc.import_catalog_entry("ghost-url", db=_fake_db)

    def test_unsupported_source_kind_raises_runtime_error(
        self,
        _fake_db,
        _patch_registry_repo,
    ) -> None:
        with patch.object(svc, "load_catalog") as mock_load:
            mock_load.return_value = [
                {
                    "id": "ghost-kind",
                    "name": "Phantom Kind",
                    "description": "",
                    "uri": "http://example.org/ghost-kind",
                    "tier": "core",
                    "source": {"kind": "magic"},
                }
            ]
            with pytest.raises(RuntimeError, match=r"unsupported source\.kind"):
                svc.import_catalog_entry("ghost-kind", db=_fake_db)


# --- Bundled file sanity ----------------------------------------------------


def test_bundled_dcterms_file_is_real_turtle() -> None:
    """The shipped DCMI bundle must actually parse as Turtle.

    A regression in the bundled file would otherwise only surface when
    a user attempts to import it. Parsing here is identical to what
    ``import_from_file`` will do downstream, just without the DB write.
    """
    import importlib.resources as _resources

    from rdflib import Graph as RDFGraph

    raw = _resources.files("app.data.ontologies").joinpath("dcterms_minimal.ttl").read_bytes()
    g = RDFGraph()
    g.parse(data=raw.decode("utf-8"), format="turtle")
    assert len(g) > 0, "bundled DCMI Turtle should produce at least one triple"


# --- HTTP layer ------------------------------------------------------------


@pytest.fixture()
def client_with_mocked_db():
    db = MagicMock()
    db.has_collection.return_value = True
    db.aql.execute = MagicMock(side_effect=lambda *a, **kw: iter([]))
    with (
        patch("app.db.client.get_db", return_value=db),
        patch("app.api.ontology._shared.get_db", return_value=db),
    ):
        from fastapi.testclient import TestClient

        from app.main import app

        yield TestClient(app), db


class TestCatalogHTTPEndpoints:
    def test_get_catalog_returns_entries(self, client_with_mocked_db) -> None:
        client, _ = client_with_mocked_db

        resp = client.get("/api/v1/ontology/catalog")

        assert resp.status_code == 200
        body = resp.json()
        assert "ontologies" in body
        assert body["count"] == len(body["ontologies"])
        # Bundled DCMI must always be present for the smoke-test path.
        ids = [e["id"] for e in body["ontologies"]]
        assert "dcterms" in ids

    def test_post_catalog_import_unknown_returns_404(self, client_with_mocked_db) -> None:
        client, _ = client_with_mocked_db

        resp = client.post("/api/v1/ontology/catalog/ghost/import")

        assert resp.status_code == 404

    def test_post_catalog_import_existing_returns_409(self, client_with_mocked_db) -> None:
        client, _ = client_with_mocked_db

        with patch(
            "app.db.registry_repo.get_registry_entry",
            return_value={"_key": "dcterms"},
        ):
            resp = client.post("/api/v1/ontology/catalog/dcterms/import")

        assert resp.status_code == 409

    def test_post_catalog_import_bundled_ok(self, client_with_mocked_db) -> None:
        client, _ = client_with_mocked_db

        def _fake_import_from_file(**kwargs: Any) -> dict[str, Any]:
            return {
                "registry_key": kwargs["ontology_id"],
                "triple_count": 18,
                "source": "file_import",
                "imports_sync": {"created": 0},
            }

        with (
            patch("app.db.registry_repo.get_registry_entry", return_value=None),
            patch(
                "app.services.standard_ontology_catalog.import_from_file",
                side_effect=_fake_import_from_file,
            ),
            # registry_repo is imported into the service module
            patch(
                "app.services.standard_ontology_catalog.registry_repo.get_registry_entry",
                return_value=None,
            ),
        ):
            resp = client.post("/api/v1/ontology/catalog/dcterms/import")

        assert resp.status_code == 201
        body = resp.json()
        assert body["source"] == "catalog_import"
        assert body["catalog_id"] == "dcterms"
        assert body["registry_key"] == "dcterms"

    def test_post_catalog_import_with_custom_id(self, client_with_mocked_db) -> None:
        client, _ = client_with_mocked_db

        captured: dict[str, Any] = {}

        def _fake_import_from_file(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {
                "registry_key": kwargs["ontology_id"],
                "triple_count": 1,
            }

        with (
            patch(
                "app.services.standard_ontology_catalog.registry_repo.get_registry_entry",
                return_value=None,
            ),
            patch(
                "app.services.standard_ontology_catalog.import_from_file",
                side_effect=_fake_import_from_file,
            ),
        ):
            resp = client.post(
                "/api/v1/ontology/catalog/dcterms/import",
                json={"ontology_id": "my_metadata_vocab"},
            )

        assert resp.status_code == 201
        assert captured["ontology_id"] == "my_metadata_vocab"
        assert resp.json()["registry_key"] == "my_metadata_vocab"
