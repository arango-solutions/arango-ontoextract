"""Unit tests for app.services.arangordf_bridge -- OWL/RDF import bridge."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.arangordf_bridge import (
    _detect_format,
    _ensure_named_graph,
    _import_with_rdflib_fallback,
    _tag_documents_with_ontology_id,
    import_from_file,
    import_from_url,
    import_owl_to_graph,
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

        # 3 vertex collections x 3 docs each = 9
        assert count == 9
        assert mock_aql.call_count == 3

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

        ttl = '@prefix owl: <http://www.w3.org/2002/07/owl#> . <http://x> a owl:Class .'

        with patch("app.services.arangordf_bridge.get_db") as mock_get_db:
            mock_get_db.return_value = MagicMock()
            import_owl_to_graph(
                ttl_content=ttl, graph_name="g", ontology_id="o"
            )

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

        ttl = '@prefix owl: <http://www.w3.org/2002/07/owl#> . <http://x> a owl:Class .'

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
            {"_id": "ontology_classes/org"},
            {"_id": "ontology_classes/dept"},
        ]
        mock_create_property.side_effect = [
            {"_id": "ontology_properties/has_department"},
            {"_id": "ontology_properties/name"},
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
        assert mock_create_edge.call_count == 3

        first_class = mock_create_class.call_args_list[0].kwargs["data"]
        assert first_class["rdf_type"] == "owl:Class"

        first_property = mock_create_property.call_args_list[0].kwargs["data"]
        assert first_property["property_type"] == "object"
        assert first_property["domain_class"] == "http://example.org/Organization"


# ---------------------------------------------------------------------------
# import_from_file
# ---------------------------------------------------------------------------


class TestImportFromFile:
    @patch("app.services.arangordf_bridge.create_registry_entry")
    @patch("app.services.arangordf_bridge.import_owl_to_graph")
    def test_imports_turtle_file(self, mock_import, mock_registry):
        db = MagicMock()
        mock_import.return_value = {
            "graph_name": "my_onto",
            "ontology_id": "my_onto",
            "triple_count": 3,
            "imported": True,
        }
        mock_registry.return_value = {"_key": "my_onto"}

        ttl = (
            '@prefix owl: <http://www.w3.org/2002/07/owl#> .\n'
            '<http://example.org/Person> a owl:Class .\n'
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
        mock_import.assert_called_once()
        mock_registry.assert_called_once()
        assert mock_registry.call_args.kwargs["db"] is db

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
