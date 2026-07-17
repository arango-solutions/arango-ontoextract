"""Unit tests for the A-box repo (Stream 21 / AB-PR1)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.db import individuals_repo as repo


class TestCreateIndividual:
    def test_creates_version_and_rdf_type_edge(self) -> None:
        db = MagicMock()
        individual = {"_key": "i1", "_id": "ontology_individuals/i1", "label": "Acme Corp"}
        with (
            patch.object(repo, "create_version", return_value=individual) as mk_ver,
            patch.object(repo, "create_edge") as mk_edge,
        ):
            out = repo.create_individual(
                db,
                ontology_id="ont1",
                class_key="Organization",
                label="Acme Corp",
                provenance=[{"doc_id": "d1", "chunk_id": "c1", "span": [0, 8]}],
            )
        assert out is individual
        # individual persisted to the A-box collection with provenance
        ver_kwargs = mk_ver.call_args.kwargs
        assert ver_kwargs["collection"] == "ontology_individuals"
        assert ver_kwargs["data"]["label"] == "Acme Corp"
        assert ver_kwargs["data"]["provenance"][0]["doc_id"] == "d1"
        # rdf:type edge -> the T-box class
        edge_kwargs = mk_edge.call_args.kwargs
        assert edge_kwargs["edge_collection"] == "rdf_type"
        assert edge_kwargs["from_id"] == "ontology_individuals/i1"
        assert edge_kwargs["to_id"] == "ontology_classes/Organization"


class TestAddAssertion:
    def test_creates_assertion_edge_with_predicate(self) -> None:
        db = MagicMock()
        with patch.object(repo, "create_edge", return_value={"_key": "e1"}) as mk_edge:
            repo.add_assertion(
                db,
                ontology_id="ont1",
                from_individual_id="ontology_individuals/i1",
                to_id="ontology_individuals/i2",
                predicate="employs",
                provenance=[{"doc_id": "d1"}],
            )
        kwargs = mk_edge.call_args.kwargs
        assert kwargs["edge_collection"] == "individual_assertion"
        assert kwargs["data"]["predicate"] == "employs"
        assert kwargs["data"]["ontology_id"] == "ont1"
        assert kwargs["data"]["provenance"] == [{"doc_id": "d1"}]


class TestListWithTypes:
    def test_missing_collection_is_empty(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        assert repo.list_individuals_with_types(db, "ont1") == []

    def test_returns_rows_and_threads_pagination(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [{"_key": "i1", "label": "Acme", "type_label": "Organization", "type_key": "Org"}]
        with patch.object(repo, "run_aql", return_value=iter(rows)) as raq:
            out = repo.list_individuals_with_types(db, "ont1", limit=25, offset=5)
        assert out == rows
        assert raq.call_args.kwargs["bind_vars"]["count"] == 25
        assert raq.call_args.kwargs["bind_vars"]["offset"] == 5


class TestQueries:
    def test_get_individual_returns_first_or_none(self) -> None:
        db = MagicMock()
        with patch.object(repo, "run_aql", return_value=iter([{"_key": "i1"}])):
            assert repo.get_individual(db, "i1") == {"_key": "i1"}
        with patch.object(repo, "run_aql", return_value=iter([])):
            assert repo.get_individual(db, "missing") is None

    def test_list_individuals_missing_collection_is_empty(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        assert repo.list_individuals(db, "ont1") == []

    def test_list_individuals_threads_pagination(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        with patch.object(repo, "run_aql", return_value=iter([{"_key": "i1"}])) as raq:
            out = repo.list_individuals(db, "ont1", limit=25, offset=50)
        assert out == [{"_key": "i1"}]
        assert raq.call_args.kwargs["bind_vars"]["count"] == 25
        assert raq.call_args.kwargs["bind_vars"]["offset"] == 50
