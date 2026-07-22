"""Unit tests for A-box canonicalization (Stream 21 / AB-PR3)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import abox_canonicalize as canon


def _ind(key: str, label: str, type_: str, prov: int) -> dict:
    return {"key": key, "label": label, "type": type_, "prov": prov}


class TestFindDuplicates:
    def test_same_type_near_duplicates_detected_keep_more_prov(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [
            _ind("i1", "Acme Corporation", "ontology_classes/Org", prov=3),
            _ind("i2", "Acme Corporatoin", "ontology_classes/Org", prov=1),  # typo dup
            _ind("i3", "Zzz Ltd", "ontology_classes/Org", prov=1),  # dissimilar
        ]
        with patch.object(canon, "run_aql", return_value=iter(rows)):
            out = canon.find_individual_duplicates(db, "o1", min_score=0.85)
        assert len(out) == 1
        c = out[0]
        assert c["keep_key"] == "i1"  # more provenance survives
        assert c["drop_key"] == "i2"
        assert c["score"] >= 0.85

    def test_different_types_never_merge(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [
            _ind("i1", "Mercury", "ontology_classes/Planet", prov=1),
            _ind("i2", "Mercury", "ontology_classes/Element", prov=1),  # same name, other type
        ]
        with patch.object(canon, "run_aql", return_value=iter(rows)):
            out = canon.find_individual_duplicates(db, "o1", min_score=0.85)
        assert out == []

    def test_tie_on_provenance_keeps_smaller_key(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [
            _ind("b_key", "Acme", "ontology_classes/Org", prov=1),
            _ind("a_key", "Acme", "ontology_classes/Org", prov=1),
        ]
        with patch.object(canon, "run_aql", return_value=iter(rows)):
            out = canon.find_individual_duplicates(db, "o1", min_score=0.85)
        assert out[0]["keep_key"] == "a_key"
        assert out[0]["drop_key"] == "b_key"

    def test_missing_collection_is_empty(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        assert canon.find_individual_duplicates(db, "o1") == []


class TestMergeIndividuals:
    def test_reassigns_edges_unions_provenance_expires_drop(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        col.get.side_effect = lambda k: {
            "keep": {"_key": "keep", "provenance": [{"doc_id": "d1"}]},
            "drop": {"_key": "drop", "provenance": [{"doc_id": "d2"}]},
        }[k]
        db.collection.return_value = col

        assertion_edges = [
            # drop --employs--> X  -> recreate keep --employs--> X
            {
                "_key": "e1",
                "_from": "ontology_individuals/drop",
                "_to": "ontology_individuals/X",
                "predicate": "employs",
                "provenance": [{"doc_id": "d2"}],
            },
            # drop --self--> keep  -> becomes keep->keep self-loop, dropped
            {
                "_key": "e2",
                "_from": "ontology_individuals/drop",
                "_to": "ontology_individuals/keep",
                "predicate": "same",
            },
        ]

        def fake_run_aql(_db, query, bind_vars=None):
            if "individual_assertion" in query:
                return iter(assertion_edges)
            if "rdf_type" in query:
                return iter([{"_key": "t_drop"}])
            return iter([])

        with (
            patch.object(canon, "run_aql", side_effect=fake_run_aql),
            patch.object(canon.individuals_repo, "add_assertion") as mk_add,
            patch.object(canon, "expire_entity") as mk_expire,
        ):
            out = canon.merge_individuals(db, ontology_id="o1", keep_key="keep", drop_key="drop")

        assert out == {"keep": "keep", "drop": "drop", "reassigned": 1}
        # only the non-self-loop edge is recreated, pointed at keep
        mk_add.assert_called_once()
        akw = mk_add.call_args.kwargs
        assert akw["from_individual_id"] == "ontology_individuals/keep"
        assert akw["to_id"] == "ontology_individuals/X"
        # provenance unioned onto keep + merged_from recorded
        upd = col.update.call_args.args[0]
        assert upd["provenance"] == [{"doc_id": "d1"}, {"doc_id": "d2"}]
        assert upd["merged_from"] == ["drop"]
        # expired: both assertion edges + rdf_type edge + the drop individual
        expired = {(c.kwargs["collection"], c.kwargs["key"]) for c in mk_expire.call_args_list}
        assert ("individual_assertion", "e1") in expired
        assert ("individual_assertion", "e2") in expired
        assert ("rdf_type", "t_drop") in expired
        assert ("ontology_individuals", "drop") in expired


class TestCanonicalizeOntology:
    def test_auto_merge_skips_chained_and_counts(self) -> None:
        db = MagicMock()
        candidates = [
            {"keep_key": "a", "drop_key": "b", "score": 0.99},
            {"keep_key": "b", "drop_key": "c", "score": 0.9},  # b already dropped -> skip
            {"keep_key": "d", "drop_key": "e", "score": 0.88},
        ]
        with (
            patch.object(canon, "find_individual_duplicates", return_value=candidates),
            patch.object(canon, "merge_individuals") as mk_merge,
        ):
            out = canon.canonicalize_ontology(db, ontology_id="o1", auto_merge=True)
        assert out["merged"] == 2  # a<-b and d<-e; b<-c skipped (b was dropped)
        assert mk_merge.call_count == 2

    def test_detect_only_when_not_auto_merge(self) -> None:
        db = MagicMock()
        with (
            patch.object(
                canon,
                "find_individual_duplicates",
                return_value=[{"keep_key": "a", "drop_key": "b"}],
            ),
            patch.object(canon, "merge_individuals") as mk_merge,
        ):
            out = canon.canonicalize_ontology(db, ontology_id="o1", auto_merge=False)
        assert out["merged"] == 0
        assert len(out["candidates"]) == 1
        mk_merge.assert_not_called()
