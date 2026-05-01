"""Unit tests for app.services.arangordf_bridge -- OWL/RDF import bridge."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.arangordf_bridge import (
    _detect_format,
    _ensure_named_graph,
    _find_registry_key_for_import_iri,
    _import_with_rdflib_fallback,
    _tag_documents_with_ontology_id,
    import_from_file,
    import_from_url,
    import_owl_to_graph,
    sync_owl_imports_edges,
)

# ---------------------------------------------------------------------------
# _detect_format
# ---------------------------------------------------------------------------


class TestDetectFormat:
    def test_turtle(self):
        assert _detect_format("ontology.ttl") == "turtle"

    def test_turtle_long(self):
        assert _detect_format("my.ontology.turtle") == "turtle"

    def test_rdf_xml(self):
        assert _detect_format("schema.rdf") == "xml"

    def test_owl_xml(self):
        assert _detect_format("schema.owl") == "xml"

    def test_jsonld(self):
        assert _detect_format("data.jsonld") == "json-ld"

    def test_json(self):
        assert _detect_format("data.json") == "json-ld"

    def test_n3(self):
        assert _detect_format("file.n3") == "n3"

    def test_ntriples(self):
        assert _detect_format("file.nt") == "nt"

    def test_unsupported_raises(self):
        with pytest.raises(ValueError, match="Unsupported file extension"):
            _detect_format("file.csv")

    def test_path_with_directory(self):
        assert _detect_format("path/to/onto.ttl") == "turtle"


# ---------------------------------------------------------------------------
# _tag_documents_with_ontology_id
# ---------------------------------------------------------------------------


class TestTagDocuments:
    @patch("app.services.arangordf_bridge.run_aql")
    def test_tags_existing_collections(self, mock_aql):
        db = MagicMock()
        db.has_collection.return_value = True
        mock_aql.return_value = [1, 1, 1]  # 3 docs tagged per collection

        count = _tag_documents_with_ontology_id(
            db, ontology_id="onto1", ontology_uri_prefix=None, graph_name="g1"
        )

        # 5 vertex collections x 3 docs each = 15
        assert count == 15
        assert mock_aql.call_count == 5

    @patch("app.services.arangordf_bridge.run_aql")
    def test_skips_missing_collections(self, mock_aql):
        db = MagicMock()
        db.has_collection.return_value = False

        count = _tag_documents_with_ontology_id(
            db, ontology_id="onto1", ontology_uri_prefix=None, graph_name="g1"
        )

        assert count == 0
        mock_aql.assert_not_called()

    @patch("app.services.arangordf_bridge.run_aql")
    def test_uri_prefix_filter_added(self, mock_aql):
        db = MagicMock()
        db.has_collection.side_effect = lambda name: name == "ontology_classes"
        mock_aql.return_value = [1]

        _tag_documents_with_ontology_id(
            db,
            ontology_id="onto1",
            ontology_uri_prefix="http://example.org/",
            graph_name="g1",
        )

        aql_call = mock_aql.call_args
        bind_vars = aql_call.kwargs.get("bind_vars") or aql_call[1].get("bind_vars")
        assert bind_vars["prefix"] == "http://example.org/"


# ---------------------------------------------------------------------------
# _ensure_named_graph
# ---------------------------------------------------------------------------


class TestEnsureNamedGraph:
    def test_skips_when_graph_exists(self):
        db = MagicMock()
        db.has_graph.return_value = True

        _ensure_named_graph(db, graph_name="ontology_test")

        db.create_graph.assert_not_called()

    def test_creates_graph_with_existing_edge_collections(self):
        db = MagicMock()
        db.has_graph.return_value = False
        db.collections.return_value = [
            {"name": "ontology_classes", "system": False},
            {"name": "ontology_properties", "system": False},
            {"name": "subclass_of", "system": False},
            {"name": "has_property", "system": False},
        ]

        _ensure_named_graph(db, graph_name="test_graph")

        db.create_graph.assert_called_once()
        call_kwargs = db.create_graph.call_args
        # Graph name should be prefixed with ontology_
        assert call_kwargs[0][0] == "ontology_test_graph"

    def test_already_prefixed_name_not_doubled(self):
        db = MagicMock()
        db.has_graph.return_value = False
        db.collections.return_value = []

        _ensure_named_graph(db, graph_name="ontology_already_prefixed")

        db.create_graph.assert_called_once()
        assert db.create_graph.call_args[0][0] == "ontology_already_prefixed"

    def test_handles_creation_error_gracefully(self):
        db = MagicMock()
        db.has_graph.return_value = False
        db.collections.return_value = []
        db.create_graph.side_effect = Exception("conflict")

        # Should not raise -- logs a warning instead
        _ensure_named_graph(db, graph_name="test")


# ---------------------------------------------------------------------------
# import_owl_to_graph
# ---------------------------------------------------------------------------


class TestImportOwlToGraph:
    @patch("app.services.arangordf_bridge._ensure_named_graph")
    @patch("app.services.arangordf_bridge._tag_documents_with_ontology_id")
    @patch("app.services.arangordf_bridge._ensure_arango_rdf")
    def test_full_pipeline(self, mock_ensure_rdf, mock_tag, mock_ensure_graph):
        db = MagicMock()
        mock_arango_rdf_cls = MagicMock()
        mock_ensure_rdf.return_value = mock_arango_rdf_cls
        mock_tag.return_value = 5

        ttl = """
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        <http://example.org/Person> a owl:Class ;
            rdfs:label "Person" .
        """

        result = import_owl_to_graph(
            db,
            ttl_content=ttl,
            graph_name="test_graph",
            ontology_id="onto1",
        )

        mock_arango_rdf_cls.assert_called_once_with(db)
        adb_rdf = mock_arango_rdf_cls.return_value
        adb_rdf.init_rdf_collections.assert_called_once()
        adb_rdf.rdf_to_arangodb_by_pgt.assert_called_once()
        mock_tag.assert_called_once()
        mock_ensure_graph.assert_called_once()

        assert result["graph_name"] == "test_graph"
        assert result["ontology_id"] == "onto1"
        assert result["imported"] is True
        assert result["triple_count"] > 0

    @patch("app.services.arangordf_bridge._ensure_named_graph")
    @patch("app.services.arangordf_bridge._tag_documents_with_ontology_id")
    @patch("app.services.arangordf_bridge._ensure_arango_rdf")
    def test_uses_get_db_when_none(self, mock_ensure_rdf, mock_tag, mock_ensure_graph):
        mock_ensure_rdf.return_value = MagicMock()
        mock_tag.return_value = 0

        ttl = "@prefix owl: <http://www.w3.org/2002/07/owl#> . <http://x> a owl:Class ."

        with patch("app.services.arangordf_bridge.get_db") as mock_get_db:
            mock_get_db.return_value = MagicMock()
            import_owl_to_graph(ttl_content=ttl, graph_name="g", ontology_id="o")

        mock_get_db.assert_called_once()

    @patch("app.services.arangordf_bridge._ensure_named_graph")
    @patch("app.services.arangordf_bridge._tag_documents_with_ontology_id")
    @patch("app.services.arangordf_bridge._import_with_rdflib_fallback")
    @patch("app.services.arangordf_bridge._ensure_arango_rdf")
    def test_falls_back_when_arango_rdf_missing(
        self,
        mock_ensure_rdf,
        mock_fallback,
        mock_tag,
        mock_ensure_graph,
    ):
        db = MagicMock()
        mock_ensure_rdf.side_effect = ImportError("missing")
        mock_tag.return_value = 0

        ttl = "@prefix owl: <http://www.w3.org/2002/07/owl#> . <http://x> a owl:Class ."

        result = import_owl_to_graph(
            db,
            ttl_content=ttl,
            graph_name="fallback_graph",
            ontology_id="onto_fallback",
        )

        mock_fallback.assert_called_once()
        mock_tag.assert_called_once()
        mock_ensure_graph.assert_called_once()
        assert result["imported"] is True


class TestFallbackImporter:
    @patch("app.services.arangordf_bridge.create_edge")
    @patch("app.services.arangordf_bridge.create_property")
    @patch("app.services.arangordf_bridge.create_class")
    def test_creates_classes_properties_and_edges(
        self,
        mock_create_class,
        mock_create_property,
        mock_create_edge,
    ):
        db = MagicMock()
        db.has_collection.return_value = False
        mock_create_class.side_effect = [
            {"_id": "ontology_classes/dept"},
            {"_id": "ontology_classes/org"},
        ]
        mock_create_property.side_effect = [
            {"_id": "ontology_object_properties/has_department"},
            {"_id": "ontology_datatype_properties/name"},
        ]

        ttl = """
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        @prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
        @prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
        @prefix ex: <http://example.org/> .

        ex:Organization a owl:Class ; rdfs:label "Organization" .
        ex:Department a owl:Class ;
            rdfs:subClassOf ex:Organization ;
            rdfs:comment "Department doc" .
        ex:hasDepartment a owl:ObjectProperty ;
            rdfs:domain ex:Organization ;
            rdfs:range ex:Department .
        ex:name a owl:DatatypeProperty ; rdfs:domain ex:Department ; rdfs:range xsd:string .
        """

        from rdflib import Graph as RDFGraph

        graph = RDFGraph()
        graph.parse(data=ttl, format="turtle")

        _import_with_rdflib_fallback(db, rdf_graph=graph, ontology_id="onto1")

        assert db.create_collection.call_count >= 4
        assert mock_create_class.call_count == 2
        assert mock_create_property.call_count == 2
        # 1 subclass_of + 2 rdfs_domain + 1 rdfs_range_class = 4
        assert mock_create_edge.call_count == 4

        first_class = mock_create_class.call_args_list[0].kwargs["data"]
        assert first_class["rdf_type"] == "owl:Class"

        obj_prop_call = mock_create_property.call_args_list[0]
        assert obj_prop_call.kwargs["data"]["property_type"] == "object"
        assert obj_prop_call.kwargs["collection"] == "ontology_object_properties"

        dt_prop_call = mock_create_property.call_args_list[1]
        assert dt_prop_call.kwargs["data"]["property_type"] == "datatype"
        assert dt_prop_call.kwargs["collection"] == "ontology_datatype_properties"

        edge_calls = [c.kwargs["edge_collection"] for c in mock_create_edge.call_args_list]
        assert "rdfs_domain" in edge_calls
        assert "rdfs_range_class" in edge_calls
        assert "subclass_of" in edge_calls


# ---------------------------------------------------------------------------
# sync_owl_imports_edges
# ---------------------------------------------------------------------------


class TestSyncOwlImportsEdges:
    def test_creates_imports_edge_when_target_in_registry(self):
        from rdflib import OWL, URIRef
        from rdflib import Graph as RDFGraph

        g = RDFGraph()
        g.add((URIRef("http://ex.org/A"), OWL.imports, URIRef("http://ex.org/B#Ont")))

        db = MagicMock()
        db.has_collection.return_value = True

        with (
            patch("app.services.arangordf_bridge.run_aql") as mock_aql,
            patch("app.services.arangordf_bridge.create_edge") as mock_edge,
        ):
            mock_aql.side_effect = [
                ["dep_onto"],
                [],
            ]
            out = sync_owl_imports_edges(db, g, "importer_onto")

        assert out["created"] == 1
        assert out["warnings"] == []
        mock_edge.assert_called_once()
        assert mock_edge.call_args.kwargs["from_id"] == "ontology_registry/importer_onto"
        assert mock_edge.call_args.kwargs["to_id"] == "ontology_registry/dep_onto"

    def test_warns_when_import_target_not_in_registry(self):
        from rdflib import OWL, URIRef
        from rdflib import Graph as RDFGraph

        g = RDFGraph()
        g.add((URIRef("http://ex.org/A"), OWL.imports, URIRef("http://missing.org/")))

        db = MagicMock()
        db.has_collection.return_value = True

        with patch("app.services.arangordf_bridge.run_aql", return_value=[]):
            out = sync_owl_imports_edges(db, g, "importer_onto")

        assert out["created"] == 0
        assert len(out["warnings"]) == 1


class TestFindRegistryKeyForImportIri:
    def test_returns_none_without_collection(self):
        db = MagicMock()
        db.has_collection.return_value = False
        assert _find_registry_key_for_import_iri(db, "http://x.org/") is None


# ---------------------------------------------------------------------------
# import_from_file
# ---------------------------------------------------------------------------


class TestImportFromFile:
    @patch("app.services.arangordf_bridge.sync_owl_imports_edges")
    @patch("app.services.arangordf_bridge.create_registry_entry")
    @patch("app.services.arangordf_bridge.import_owl_to_graph")
    def test_imports_turtle_file(self, mock_import, mock_registry, mock_sync_imports):
        db = MagicMock()
        mock_import.return_value = {
            "graph_name": "my_onto",
            "ontology_id": "my_onto",
            "triple_count": 3,
            "imported": True,
        }
        mock_registry.return_value = {"_key": "my_onto"}
        mock_sync_imports.return_value = {"created": 0, "skipped": 0, "warnings": []}

        ttl = (
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "<http://example.org/Person> a owl:Class .\n"
        )

        result = import_from_file(
            file_content=ttl.encode("utf-8"),
            filename="schema.ttl",
            ontology_id="my_onto",
            db=db,
            ontology_label="My Ontology",
        )

        assert result["source"] == "file_import"
        assert result["filename"] == "schema.ttl"
        assert result["format"] == "turtle"
        assert result["registry_key"] == "my_onto"
        assert result["imports_sync"] == mock_sync_imports.return_value
        mock_import.assert_called_once()
        mock_registry.assert_called_once()
        assert mock_registry.call_args.kwargs["db"] is db
        mock_sync_imports.assert_called_once()
        assert mock_sync_imports.call_args[0][0] is db
        assert mock_sync_imports.call_args[0][2] == "my_onto"
        reg_payload = mock_registry.call_args[0][0]
        assert reg_payload["name"] == "My Ontology"
        assert reg_payload["label"] == "My Ontology"
        assert reg_payload["tier"] == "local"
        assert "Imported from" in reg_payload["description"]

    @patch("app.services.arangordf_bridge.create_registry_entry")
    @patch("app.services.arangordf_bridge.import_owl_to_graph")
    def test_import_from_file_calls_sync_owl_imports(self, mock_import, mock_registry):
        """After registry entry, owl:imports is synced against ontology_registry."""
        db = MagicMock()
        mock_import.return_value = {"imported": True, "ontology_id": "a", "graph_name": "a"}
        mock_registry.return_value = {"_key": "a"}

        ttl = (
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix ex: <http://example.org/> .\n"
            "ex:MyOnto a owl:Ontology ; owl:imports ex:OtherOnto .\n"
            "ex:OtherOnto a owl:Ontology .\n"
        )

        with patch("app.services.arangordf_bridge.sync_owl_imports_edges") as mock_sync:
            mock_sync.return_value = {"created": 1, "skipped": 0, "warnings": []}
            result = import_from_file(
                file_content=ttl.encode("utf-8"),
                filename="schema.ttl",
                ontology_id="a",
                db=db,
            )

        assert result["imports_sync"]["created"] == 1
        mock_sync.assert_called_once()

    @patch("app.services.arangordf_bridge.create_registry_entry")
    @patch("app.services.arangordf_bridge.import_owl_to_graph")
    def test_empty_file_raises(self, mock_import, mock_registry):
        db = MagicMock()
        # Empty turtle file produces 0 triples
        with pytest.raises(ValueError, match="no RDF triples"):
            import_from_file(
                file_content=b"",
                filename="empty.ttl",
                ontology_id="x",
                db=db,
            )

    def test_unsupported_extension_raises(self):
        db = MagicMock()
        with pytest.raises(ValueError, match="Unsupported file extension"):
            import_from_file(
                file_content=b"data",
                filename="file.csv",
                ontology_id="x",
                db=db,
            )

    @patch("app.services.arangordf_bridge.sync_owl_imports_edges")
    @patch("app.services.arangordf_bridge.create_registry_entry")
    @patch("app.services.arangordf_bridge.import_owl_to_graph")
    def test_import_does_not_collide_with_reserved_logrecord_keys(
        self,
        mock_import,
        mock_registry,
        mock_sync_imports,
        caplog,
    ):
        """Regression: passing a reserved attribute name (e.g. 'filename') inside
        ``log.<level>(..., extra={...})`` raises ``KeyError: Attempt to overwrite
        'filename' in LogRecord`` and surfaces as a 500 at the API layer even
        though the import itself succeeded."""
        import logging

        db = MagicMock()
        mock_import.return_value = {"imported": True, "ontology_id": "x", "graph_name": "x"}
        mock_registry.return_value = {"_key": "x"}
        mock_sync_imports.return_value = {"created": 0, "skipped": 0, "warnings": []}

        ttl = (
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "<http://example.org/Person> a owl:Class .\n"
        )

        with caplog.at_level(logging.INFO, logger="app.services.arangordf_bridge"):
            import_from_file(
                file_content=ttl.encode("utf-8"),
                filename="schema.ttl",
                ontology_id="x",
                db=db,
            )

    @patch("app.services.arangordf_bridge.sync_owl_imports_edges")
    @patch("app.services.arangordf_bridge.create_registry_entry")
    @patch("app.services.arangordf_bridge.import_owl_to_graph")
    def test_import_uses_owl_ontology_rdfs_label_when_no_param_label(
        self,
        mock_import,
        mock_registry,
        mock_sync_imports,
    ):
        db = MagicMock()
        mock_import.return_value = {"imported": True, "ontology_id": "fin", "graph_name": "fin"}
        mock_registry.return_value = {"_key": "fin"}
        mock_sync_imports.return_value = {"created": 0, "skipped": 0, "warnings": []}

        ttl = (
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .\n"
            "@prefix ex: <http://example.org/> .\n"
            'ex:RootOnto a owl:Ontology ; rdfs:label "Finance Schema" .\n'
            "ex:Person a owl:Class .\n"
        )

        import_from_file(
            file_content=ttl.encode("utf-8"),
            filename="data.ttl",
            ontology_id="fin",
            db=db,
            ontology_label=None,
        )

        reg_payload = mock_registry.call_args[0][0]
        assert reg_payload["name"] == "Finance Schema"
        assert reg_payload["label"] == "Finance Schema"

    @patch("app.services.arangordf_bridge.sync_owl_imports_edges")
    @patch("app.services.arangordf_bridge.create_registry_entry")
    @patch("app.services.arangordf_bridge.import_owl_to_graph")
    def test_import_title_from_filename_when_no_ontology_label(
        self,
        mock_import,
        mock_registry,
        mock_sync_imports,
    ):
        db = MagicMock()
        mock_import.return_value = {"imported": True, "ontology_id": "x", "graph_name": "x"}
        mock_registry.return_value = {"_key": "x"}
        mock_sync_imports.return_value = {"created": 0, "skipped": 0, "warnings": []}

        ttl = (
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
            "<http://example.org/Person> a owl:Class .\n"
        )

        import_from_file(
            file_content=ttl.encode("utf-8"),
            filename="my_schema_file.ttl",
            ontology_id="x",
            db=db,
            ontology_label=None,
        )

        reg_payload = mock_registry.call_args[0][0]
        assert reg_payload["name"] == "My Schema File"


# ---------------------------------------------------------------------------
# import_from_url
# ---------------------------------------------------------------------------


class TestImportFromUrl:
    @patch("app.services.arangordf_bridge.import_from_file")
    @patch("app.services.arangordf_bridge.httpx")
    def test_downloads_and_delegates(self, mock_httpx, mock_import_file):
        db = MagicMock()
        response = MagicMock()
        response.content = b"@prefix owl: <http://www.w3.org/2002/07/owl#> ."
        mock_httpx.get.return_value = response
        mock_import_file.return_value = {
            "imported": True,
            "source": "file_import",
        }

        result = import_from_url(
            "http://example.org/schema.ttl",
            "onto1",
            db=db,
            ontology_label="Remote",
        )

        mock_httpx.get.assert_called_once_with(
            "http://example.org/schema.ttl", timeout=60, follow_redirects=True
        )
        response.raise_for_status.assert_called_once()
        mock_import_file.assert_called_once()
        assert result["source"] == "url_import"
        assert result["source_url"] == "http://example.org/schema.ttl"

    @patch("app.services.arangordf_bridge.import_from_file")
    @patch("app.services.arangordf_bridge.httpx")
    def test_url_without_extension_defaults_to_ttl(self, mock_httpx, mock_import_file):
        db = MagicMock()
        response = MagicMock()
        response.content = b"data"
        mock_httpx.get.return_value = response
        mock_import_file.return_value = {"imported": True, "source": "file_import"}

        import_from_url("http://example.org/", "onto1", db=db)

        # The filename parameter passed to import_from_file should be "ontology.ttl"
        call_kwargs = mock_import_file.call_args
        assert call_kwargs.kwargs.get("filename") == "ontology.ttl"


# ---------------------------------------------------------------------------
# _ensure_arango_rdf
# ---------------------------------------------------------------------------


class TestEnsureArangoRdf:
    def test_raises_import_error_when_missing(self):
        with patch.dict("sys.modules", {"arango_rdf": None}):
            from app.services.arangordf_bridge import _ensure_arango_rdf

            with pytest.raises(ImportError, match="arango_rdf is required"):
                _ensure_arango_rdf()
