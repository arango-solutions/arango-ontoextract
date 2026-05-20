"""Unit tests for app.services.schema_extraction.

Covers Stream 5 PR 1 additions:
  * SchemaExtractionConfig new fields (graph_names, include_loose,
    sample_fields, field_sample_limit, imports)
  * list_named_graphs (S.6) -- topology discovery
  * _direct_extract_schema (S.7 + S.8) -- named-graph-aware OWL emission
    with field sampling + provenance annotations
  * _infer_xsd_type + _sample_collection_fields -- type inference
  * _stamp_per_class_provenance (S.4) -- post-import stamping
  * Auto-imports embedding (S.10) -- owl:imports triples in generated TTL
  * extract_schema orchestrator -- pipeline integration

Tests mock python-arango at the boundary (no live ArangoDB connection).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.schema_extraction import (
    ExtractionStatus,
    SchemaExtractionConfig,
    _direct_extract_schema,
    _infer_xsd_type,
    _runs,
    _sample_collection_fields,
    _stamp_per_class_provenance,
    _stub_extract_schema,
    extract_schema,
    get_extraction_status,
    list_named_graphs,
)


@pytest.fixture(autouse=True)
def _clear_runs():
    """Clear the module-level _runs dict before each test."""
    _runs.clear()
    yield
    _runs.clear()


def _make_config(**overrides) -> SchemaExtractionConfig:
    defaults = {
        "target_host": "http://localhost:8529",
        "target_db": "test_db",
        "target_user": "root",
        "target_password": "pass",
    }
    defaults.update(overrides)
    return SchemaExtractionConfig(**defaults)


def _mock_db(graphs=None, collections=None, sample_docs=None):
    """Build a ``MagicMock`` shaped like ``python-arango``'s ``StandardDatabase``.

    ``graphs`` = list[dict] for ``db.graphs()``
    ``collections`` = list[dict] for ``db.collections()``
    ``sample_docs`` = ``dict[col_name, list[doc]]`` returned by the
    sample-fields AQL query (matched in order of calls).
    """
    db = MagicMock()
    db.graphs.return_value = graphs or []
    db.collections.return_value = collections or []
    db.has_collection.return_value = True

    # ``_sample_collection_fields`` calls ``run_aql`` (not a ``db.``
    # method), so the sample data is patched separately via patch().

    # collection(name).count() — used by list_named_graphs for loose
    # collection counts.
    def _collection(name):
        col_mock = MagicMock()
        col_mock.count.return_value = 0
        return col_mock

    db.collection.side_effect = _collection
    return db


# ---------------------------------------------------------------------------
# SchemaExtractionConfig
# ---------------------------------------------------------------------------


class TestSchemaExtractionConfig:
    def test_defaults(self):
        cfg = SchemaExtractionConfig(target_host="http://h:8529", target_db="db1")
        assert cfg.target_user == "root"
        assert cfg.target_password == ""
        assert cfg.use_llm_inference is False
        assert cfg.ontology_id is None
        assert cfg.extraction_source == "arango_graph_schema"
        assert cfg.verify_tls is True
        # Stream 5 PR 1 additions
        assert cfg.graph_names is None
        assert cfg.include_loose is True
        assert cfg.sample_fields is True
        assert cfg.field_sample_limit == 10
        assert cfg.imports == []

    def test_custom_values(self):
        cfg = _make_config(
            ontology_id="custom",
            ontology_label="My Schema",
            graph_names=["g1", "g2"],
            include_loose=False,
            sample_fields=False,
            field_sample_limit=50,
            imports=["foaf", "schema_org"],
        )
        assert cfg.ontology_id == "custom"
        assert cfg.ontology_label == "My Schema"
        assert cfg.graph_names == ["g1", "g2"]
        assert cfg.include_loose is False
        assert cfg.sample_fields is False
        assert cfg.field_sample_limit == 50
        assert cfg.imports == ["foaf", "schema_org"]

    def test_field_sample_limit_bounds(self):
        # Lower bound: 0 is allowed (means "no sampling even if
        # sample_fields=True"); negative is not. Upper bound: 1000 is
        # the cap to avoid accidental full-collection scans against
        # production ArangoDB. Use ``ValidationError`` (the pydantic
        # exception) so ruff B017 doesn't flag a bare ``Exception``
        # match and so a non-pydantic crash surfaces as a real failure.
        from pydantic import ValidationError

        SchemaExtractionConfig(target_host="h", target_db="d", field_sample_limit=0)
        with pytest.raises(ValidationError):
            SchemaExtractionConfig(target_host="h", target_db="d", field_sample_limit=-1)
        with pytest.raises(ValidationError):
            SchemaExtractionConfig(target_host="h", target_db="d", field_sample_limit=10000)


# ---------------------------------------------------------------------------
# _infer_xsd_type — type inference (S.8)
# ---------------------------------------------------------------------------


class TestInferXsdType:
    def test_bool_before_int(self):
        # CRITICAL: bool is a subclass of int in Python. If the isinstance
        # check ordering ever regresses, ``True`` would be tagged as
        # xsd:integer and the ontology would lie. Pin the order.
        assert _infer_xsd_type(True).endswith("#boolean")
        assert _infer_xsd_type(False).endswith("#boolean")

    def test_int_and_float(self):
        assert _infer_xsd_type(42).endswith("#integer")
        assert _infer_xsd_type(0).endswith("#integer")
        assert _infer_xsd_type(3.14).endswith("#decimal")

    def test_plain_string(self):
        assert _infer_xsd_type("hello").endswith("#string")
        assert _infer_xsd_type("").endswith("#string")

    def test_iso_date_string(self):
        # Strict ISO 8601 -- date with no time component should map to
        # xsd:date (not xsd:dateTime).
        assert _infer_xsd_type("2026-05-19").endswith("#date")

    def test_iso_datetime_string(self):
        assert _infer_xsd_type("2026-05-19T12:34:56").endswith("#dateTime")
        # With tz offset
        assert _infer_xsd_type("2026-05-19T12:34:56+00:00").endswith("#dateTime")

    def test_ambiguous_strings_are_string(self):
        # Permissive date parsers misclassify these; we should not.
        assert _infer_xsd_type("Jan").endswith("#string")
        assert _infer_xsd_type("1.0").endswith("#string")  # float-looking string
        assert _infer_xsd_type("yesterday").endswith("#string")

    def test_none_lists_dicts_return_none(self):
        assert _infer_xsd_type(None) is None
        assert _infer_xsd_type([1, 2, 3]) is None
        assert _infer_xsd_type({"nested": "obj"}) is None


# ---------------------------------------------------------------------------
# _sample_collection_fields
# ---------------------------------------------------------------------------


class TestSampleCollectionFields:
    def test_sample_limit_zero_short_circuits(self):
        db = MagicMock()
        # Should not even call run_aql when limit is 0.
        with patch("app.services.schema_extraction.run_aql") as mock_aql:
            result = _sample_collection_fields(db, "users", 0)
        assert result == {}
        mock_aql.assert_not_called()

    def test_homogeneous_types_inferred(self):
        with patch(
            "app.services.schema_extraction.run_aql",
            return_value=[
                {"name": "alice", "age": 30, "active": True},
                {"name": "bob", "age": 25, "active": False},
            ],
        ):
            result = _sample_collection_fields(MagicMock(), "users", 5)
        assert result["name"].endswith("#string")
        assert result["age"].endswith("#integer")
        assert result["active"].endswith("#boolean")

    def test_heterogeneous_types_fallback_to_string(self):
        # Mixed int + string for the same field -> xsd:string (the safe
        # superset). The curator will see "heterogeneous" and can refine.
        with patch(
            "app.services.schema_extraction.run_aql",
            return_value=[
                {"count": 3},
                {"count": "n/a"},
            ],
        ):
            result = _sample_collection_fields(MagicMock(), "items", 5)
        assert result["count"].endswith("#string")

    def test_null_values_do_not_contribute(self):
        # A field that is null in every sampled doc has no inferable type
        # and should NOT be emitted as a datatype property.
        with patch(
            "app.services.schema_extraction.run_aql",
            return_value=[
                {"name": "alice", "deleted_at": None},
                {"name": "bob", "deleted_at": None},
            ],
        ):
            result = _sample_collection_fields(MagicMock(), "users", 5)
        assert "deleted_at" not in result
        assert "name" in result


# ---------------------------------------------------------------------------
# list_named_graphs (S.6) — topology discovery
# ---------------------------------------------------------------------------


class TestListNamedGraphs:
    @patch("arango.client.ArangoClient")
    def test_collects_graphs_with_edge_definitions(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        db = _mock_db(
            graphs=[
                {
                    "name": "social_graph",
                    "edge_definitions": [
                        {
                            "edge_collection": "follows",
                            "from_vertex_collections": ["users"],
                            "to_vertex_collections": ["users"],
                        },
                        {
                            "edge_collection": "posted",
                            "from_vertex_collections": ["users"],
                            "to_vertex_collections": ["posts"],
                        },
                    ],
                    "orphan_collections": ["tags"],
                }
            ],
            collections=[
                {"name": "users", "system": False, "type": 2},
                {"name": "posts", "system": False, "type": 2},
                {"name": "tags", "system": False, "type": 2},
                {"name": "follows", "system": False, "type": 3},
                {"name": "posted", "system": False, "type": 3},
                # Loose: not in any graph
                {"name": "audit_log", "system": False, "type": 2},
                # System: must be skipped
                {"name": "_system_col", "system": True, "type": 2},
            ],
        )
        mock_client.db.return_value = db

        result = list_named_graphs(_make_config())
        assert result["target_db"] == "test_db"
        assert len(result["graphs"]) == 1
        g = result["graphs"][0]
        assert g["name"] == "social_graph"
        assert {ed["edge_collection"] for ed in g["edge_definitions"]} == {
            "follows",
            "posted",
        }
        # Vertex cols = union of all (from + to + orphan)
        assert set(g["vertex_collections"]) == {"users", "posts", "tags"}
        assert g["orphan_collections"] == ["tags"]

        # Loose collection surfaced separately
        assert len(result["loose_collections"]) == 1
        assert result["loose_collections"][0]["name"] == "audit_log"
        assert result["loose_collections"][0]["type"] == "document"

        mock_client.close.assert_called_once()

    @patch("arango.client.ArangoClient")
    def test_loose_edge_collection_typed_correctly(self, mock_client_cls):
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        db = _mock_db(
            graphs=[],
            collections=[
                {"name": "loose_edges", "system": False, "type": 3},
                {"name": "loose_docs", "system": False, "type": 2},
            ],
        )
        mock_client.db.return_value = db

        result = list_named_graphs(_make_config())
        loose = {c["name"]: c["type"] for c in result["loose_collections"]}
        assert loose == {"loose_edges": "edge", "loose_docs": "document"}

    @patch("arango.client.ArangoClient")
    def test_count_failure_surfaced_as_none(self, mock_client_cls):
        # A per-collection count() crash must not abort discovery -- the
        # UI shows "unknown" for that one row.
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        db = _mock_db(
            graphs=[],
            collections=[{"name": "broken", "system": False, "type": 2}],
        )

        def _bad_collection(name):
            col = MagicMock()
            col.count.side_effect = RuntimeError("permission denied")
            return col

        db.collection.side_effect = _bad_collection
        mock_client.db.return_value = db

        result = list_named_graphs(_make_config())
        assert result["loose_collections"] == [
            {"name": "broken", "type": "document", "count": None}
        ]


# ---------------------------------------------------------------------------
# _direct_extract_schema (S.7 + S.8)
# ---------------------------------------------------------------------------


class TestDirectExtractSchema:
    def test_named_graph_emits_object_properties_with_domain_range(self):
        db = _mock_db(
            graphs=[
                {
                    "name": "social",
                    "edge_definitions": [
                        {
                            "edge_collection": "follows",
                            "from_vertex_collections": ["users"],
                            "to_vertex_collections": ["users"],
                        }
                    ],
                    "orphan_collections": [],
                }
            ],
            collections=[
                {"name": "users", "system": False, "type": 2},
                {"name": "follows", "system": False, "type": 3},
            ],
        )
        # No field sampling so we don't need to patch run_aql.
        cfg = _make_config(sample_fields=False)
        ttl, uri_map = _direct_extract_schema(cfg, db=db)

        assert "users" in ttl
        assert "follows" in ttl
        # ObjectProperty with rdfs:domain + rdfs:range. Don't pin exact
        # wire format -- rdflib's Turtle output uses CURIEs.
        assert "owl:ObjectProperty" in ttl
        assert "rdfs:domain" in ttl
        assert "rdfs:range" in ttl
        # Per-class provenance annotation present
        assert "aoe:sourceCollection" in ttl
        assert '"users"' in ttl
        # URI -> source collection map populated for both class + edge
        users_uri = "http://aoe.example.org/schema/test_db#users"
        follows_uri = "http://aoe.example.org/schema/test_db#follows"
        assert uri_map[users_uri] == "users"
        assert uri_map[follows_uri] == "follows"

    def test_graph_names_filter_restricts_walk(self):
        db = _mock_db(
            graphs=[
                {
                    "name": "wanted",
                    "edge_definitions": [
                        {
                            "edge_collection": "rel_wanted",
                            "from_vertex_collections": ["a"],
                            "to_vertex_collections": ["b"],
                        }
                    ],
                    "orphan_collections": [],
                },
                {
                    "name": "unwanted",
                    "edge_definitions": [
                        {
                            "edge_collection": "rel_unwanted",
                            "from_vertex_collections": ["x"],
                            "to_vertex_collections": ["y"],
                        }
                    ],
                    "orphan_collections": [],
                },
            ],
            collections=[
                {"name": "a", "system": False, "type": 2},
                {"name": "b", "system": False, "type": 2},
                {"name": "x", "system": False, "type": 2},
                {"name": "y", "system": False, "type": 2},
                {"name": "rel_wanted", "system": False, "type": 3},
                {"name": "rel_unwanted", "system": False, "type": 3},
            ],
        )
        # include_loose=False so collections from the unwanted graph
        # do NOT leak in as loose -- pure filter behaviour test.
        cfg = _make_config(graph_names=["wanted"], include_loose=False, sample_fields=False)
        ttl, uri_map = _direct_extract_schema(cfg, db=db)
        assert "rel_wanted" in ttl
        assert "rel_unwanted" not in ttl
        assert "<http://aoe.example.org/schema/test_db#rel_wanted>" not in uri_map  # CURIE
        assert "http://aoe.example.org/schema/test_db#rel_unwanted" not in uri_map

    def test_loose_collections_included_by_default(self):
        db = _mock_db(
            graphs=[],
            collections=[
                {"name": "audit_log", "system": False, "type": 2},
                {"name": "loose_edge", "system": False, "type": 3},
            ],
        )
        cfg = _make_config(sample_fields=False)
        ttl, _ = _direct_extract_schema(cfg, db=db)
        assert "audit_log" in ttl
        assert "loose_edge" in ttl
        # Loose edge collection -> ObjectProperty without domain/range
        assert "Loose edge collection" in ttl

    def test_include_loose_false_skips_them(self):
        db = _mock_db(
            graphs=[],
            collections=[
                {"name": "audit_log", "system": False, "type": 2},
            ],
        )
        cfg = _make_config(sample_fields=False, include_loose=False)
        ttl, uri_map = _direct_extract_schema(cfg, db=db)
        # Only the ontology resource + bindings -- no class for audit_log
        assert "audit_log" not in ttl
        assert uri_map == {}

    def test_field_sampling_emits_datatype_properties(self):
        db = _mock_db(
            graphs=[],
            collections=[{"name": "users", "system": False, "type": 2}],
        )
        # Patch run_aql so the field sample returns deterministic types.
        with patch(
            "app.services.schema_extraction.run_aql",
            return_value=[{"name": "alice", "age": 30, "active": True, "score": 1.5}],
        ):
            cfg = _make_config(sample_fields=True, field_sample_limit=1)
            ttl, _ = _direct_extract_schema(cfg, db=db)

        # DatatypeProperty triples for each sampled scalar field. URIs
        # are scoped to the collection (users.name vs other_col.name).
        assert "owl:DatatypeProperty" in ttl
        assert "users.name" in ttl
        assert "users.age" in ttl
        assert "users.active" in ttl
        assert "users.score" in ttl
        # rdflib's Turtle serializer always emits the xsd: CURIE (bound
        # in the graph at extraction time), not the full IRI -- so we
        # assert on the prefixed form. The full IRI is verifiable via
        # the @prefix declaration which is also in the output.
        assert "xsd:string" in ttl
        assert "xsd:integer" in ttl
        assert "xsd:boolean" in ttl
        assert "xsd:decimal" in ttl
        assert "@prefix xsd: <http://www.w3.org/2001/XMLSchema#>" in ttl

    def test_field_sampling_failure_does_not_abort_extraction(self):
        db = _mock_db(
            graphs=[],
            collections=[
                {"name": "good", "system": False, "type": 2},
                {"name": "bad", "system": False, "type": 2},
            ],
        )
        # First call (good) succeeds, second call (bad) raises
        with patch(
            "app.services.schema_extraction.run_aql",
            side_effect=[[{"x": 1}], RuntimeError("boom")],
        ):
            cfg = _make_config(sample_fields=True)
            ttl, _ = _direct_extract_schema(cfg, db=db)
        # Good collection's property still emitted; extraction not crashed
        assert "good.x" in ttl

    def test_auto_imports_embedded(self):
        db = _mock_db(graphs=[], collections=[])
        cfg = _make_config(sample_fields=False, imports=["foaf", "schema_org"])
        ttl, _ = _direct_extract_schema(cfg, db=db)
        # owl:imports triples present
        assert "owl:imports" in ttl
        # The imported URIs follow the standard AOE ontology URI scheme
        # used by sync_owl_imports_edges
        assert "http://example.org/ontology/foaf" in ttl
        assert "http://example.org/ontology/schema_org" in ttl


# ---------------------------------------------------------------------------
# _stub_extract_schema — back-compat alias
# ---------------------------------------------------------------------------


class TestStubExtractSchema:
    def test_delegates_to_direct_extract(self):
        # The alias must produce the same TTL as the canonical call.
        with patch(
            "app.services.schema_extraction._direct_extract_schema",
            return_value=("@prefix x: <> .", {"u1": "c1"}),
        ) as mock_direct:
            ttl = _stub_extract_schema(_make_config())
        assert ttl == "@prefix x: <> ."
        mock_direct.assert_called_once()


# ---------------------------------------------------------------------------
# _stamp_per_class_provenance (S.4)
# ---------------------------------------------------------------------------


class TestStampPerClassProvenance:
    def test_skipped_when_collection_missing(self):
        db = MagicMock()
        db.has_collection.return_value = False
        # No run_aql call should fire when the collection is absent.
        with patch("app.services.schema_extraction.run_aql") as mock_aql:
            stamped = _stamp_per_class_provenance(
                db,
                ontology_id="oid",
                source_db="sdb",
                source_host="http://h",
                uri_to_collection={"u": "c"},
            )
        assert stamped == 0
        mock_aql.assert_not_called()

    def test_stamps_matched_classes(self):
        db = MagicMock()
        db.has_collection.return_value = True
        with patch(
            "app.services.schema_extraction.run_aql",
            return_value=[1, 1, 1],  # AQL returned 3 update rows
        ) as mock_aql:
            stamped = _stamp_per_class_provenance(
                db,
                ontology_id="oid_x",
                source_db="src_db",
                source_host="http://h:8529",
                uri_to_collection={
                    "http://ex/u1": "users",
                    "http://ex/u2": "posts",
                },
            )
        assert stamped == 3
        # Verify the bind_vars carried both the map and the source meta
        kwargs = mock_aql.call_args.kwargs
        bind = kwargs["bind_vars"]
        assert bind["oid"] == "oid_x"
        assert bind["sdb"] == "src_db"
        assert bind["shost"] == "http://h:8529"
        assert bind["uri_map"] == {
            "http://ex/u1": "users",
            "http://ex/u2": "posts",
        }

    def test_failure_is_swallowed(self):
        # A provenance bug must NEVER break the extraction write path.
        db = MagicMock()
        db.has_collection.return_value = True
        with patch(
            "app.services.schema_extraction.run_aql",
            side_effect=RuntimeError("AQL exploded"),
        ):
            stamped = _stamp_per_class_provenance(
                db,
                ontology_id="oid",
                source_db="db",
                source_host="h",
                uri_to_collection={"u": "c"},
            )
        assert stamped == 0  # Returns 0, no re-raise


# ---------------------------------------------------------------------------
# extract_schema orchestrator
# ---------------------------------------------------------------------------


class TestExtractSchema:
    @patch("app.services.schema_extraction._stamp_per_class_provenance", return_value=2)
    @patch("app.services.schema_extraction.import_from_file")
    @patch("app.services.schema_extraction._try_import_schema_mapper", return_value=None)
    @patch("app.services.schema_extraction._direct_extract_schema")
    @patch("app.services.schema_extraction.get_db")
    def test_direct_path_calls_provenance_stamping(
        self,
        mock_get_db,
        mock_direct,
        mock_mapper,
        mock_import,
        mock_stamp,
    ):
        mock_get_db.return_value = MagicMock()
        mock_direct.return_value = (
            "@prefix owl: <http://www.w3.org/2002/07/owl#> .",
            {"http://ex/users": "users", "http://ex/posts": "posts"},
        )
        mock_import.return_value = {"triple_count": 10, "imported": True}

        cfg = _make_config()
        result = extract_schema(cfg)

        assert result["status"] == "completed"
        assert result["provenance"]["mode"] == "direct"
        assert result["provenance_stamped"] == 2
        # Provenance stamping was called with the URI map from the direct path
        kwargs = mock_stamp.call_args.kwargs
        assert kwargs["ontology_id"] == result["ontology_id"]
        assert kwargs["source_db"] == "test_db"
        assert kwargs["source_host"] == "http://localhost:8529"
        assert kwargs["uri_to_collection"] == {
            "http://ex/users": "users",
            "http://ex/posts": "posts",
        }

    @patch("app.services.schema_extraction._stamp_per_class_provenance")
    @patch("app.services.schema_extraction.import_from_file")
    @patch("app.services.schema_extraction._run_schema_mapper_extract")
    @patch("app.services.schema_extraction._try_import_schema_mapper")
    @patch("app.services.schema_extraction.get_db")
    def test_mapper_path_skips_provenance_stamping(
        self,
        mock_get_db,
        mock_try_mapper,
        mock_run_extract,
        mock_import,
        mock_stamp,
    ):
        # When schema_analyzer is installed, the mapper path runs. It
        # doesn't surface a URI -> collection map, so per-class stamping
        # is a no-op (mock_stamp must NOT be called).
        mock_get_db.return_value = MagicMock()
        mock_try_mapper.return_value = (object(), object(), object(), object())
        mock_run_extract.return_value = (
            "@prefix owl: <> .",
            {"physical_schema_fingerprint": "fp1"},
        )
        mock_import.return_value = {"imported": True}

        cfg = _make_config()
        result = extract_schema(cfg)
        assert result["status"] == "completed"
        assert result["provenance"]["physical_schema_fingerprint"] == "fp1"
        assert result["provenance_stamped"] == 0
        mock_stamp.assert_not_called()

    @patch("app.services.schema_extraction._stamp_per_class_provenance", return_value=0)
    @patch("app.services.schema_extraction.import_from_file")
    @patch("app.services.schema_extraction._try_import_schema_mapper", return_value=None)
    @patch("app.services.schema_extraction._direct_extract_schema")
    @patch("app.services.schema_extraction.get_db")
    def test_custom_ontology_id(
        self, mock_get_db, mock_direct, mock_mapper, mock_import, mock_stamp
    ):
        mock_get_db.return_value = MagicMock()
        mock_direct.return_value = ("ttl", {})
        mock_import.return_value = {"imported": True}

        cfg = _make_config(ontology_id="my_custom_id")
        result = extract_schema(cfg)
        assert result["ontology_id"] == "my_custom_id"

    @patch("app.services.schema_extraction._try_import_schema_mapper", return_value=None)
    @patch(
        "app.services.schema_extraction._direct_extract_schema",
        side_effect=ConnectionError("nope"),
    )
    @patch("app.services.schema_extraction.get_db")
    def test_failure_sets_error(self, mock_get_db, mock_direct, mock_mapper):
        mock_get_db.return_value = MagicMock()
        cfg = _make_config()

        with pytest.raises(ConnectionError):
            extract_schema(cfg)

        assert len(_runs) == 1
        run = next(iter(_runs.values()))
        assert run.status == ExtractionStatus.FAILED
        assert run.error == "nope"

    @patch("app.services.schema_extraction._stamp_per_class_provenance", return_value=0)
    @patch("app.services.schema_extraction.import_from_file")
    @patch("app.services.schema_extraction._try_import_schema_mapper", return_value=None)
    @patch("app.services.schema_extraction._direct_extract_schema")
    @patch("app.services.schema_extraction.get_db")
    def test_provenance_includes_config_metadata(
        self, mock_get_db, mock_direct, mock_mapper, mock_import, mock_stamp
    ):
        mock_get_db.return_value = MagicMock()
        mock_direct.return_value = ("ttl", {"u": "c"})
        mock_import.return_value = {"imported": True}

        cfg = _make_config(
            graph_names=["g1"],
            include_loose=False,
            sample_fields=True,
            imports=["foaf"],
        )
        result = extract_schema(cfg)
        prov = result["provenance"]
        # Stream 5 PR 1: provenance now records the config knobs so a
        # downstream consumer can tell "this was a partial extraction
        # of 1 graph with auto-imports" vs "this was a full topology".
        assert prov["mode"] == "direct"
        assert prov["graphs_filter"] == ["g1"]
        assert prov["include_loose"] is False
        assert prov["auto_imports"] == ["foaf"]
        assert prov["field_sampling"] is True


# ---------------------------------------------------------------------------
# get_extraction_status — unchanged from v0.3 but pinned here for coverage
# ---------------------------------------------------------------------------


class TestGetExtractionStatus:
    def test_raises_for_unknown_run(self):
        with pytest.raises(ValueError, match="not found"):
            get_extraction_status("nonexistent")

    @patch("app.services.schema_extraction._stamp_per_class_provenance", return_value=0)
    @patch("app.services.schema_extraction.import_from_file")
    @patch("app.services.schema_extraction._try_import_schema_mapper", return_value=None)
    @patch("app.services.schema_extraction._direct_extract_schema")
    @patch("app.services.schema_extraction.get_db")
    def test_completed_run_includes_stats(
        self, mock_get_db, mock_direct, mock_mapper, mock_import, mock_stamp
    ):
        mock_get_db.return_value = MagicMock()
        mock_direct.return_value = ("@prefix owl: <> .", {})
        mock_import.return_value = {"triple_count": 5, "imported": True}

        config = _make_config()
        result = extract_schema(config)
        run_id = result["run_id"]

        status = get_extraction_status(run_id)
        assert status["status"] == "completed"
        assert "import_stats" in status
        assert status["target_db"] == "test_db"
