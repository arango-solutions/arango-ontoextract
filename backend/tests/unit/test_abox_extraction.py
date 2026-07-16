"""Unit tests for schema-grounded A-box extraction (Stream 21 / AB-PR2)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from app.services import abox_extraction as ab


class TestRetrieveSchemaSlice:
    async def test_vector_path_filters_to_ontology(self) -> None:
        db = MagicMock()
        hits = [
            {"_key": "C1", "ontology_id": "ont1", "label": "Organization", "score": 0.9},
            {"_key": "Z9", "ontology_id": "other", "label": "Zebra", "score": 0.8},
        ]
        with (
            patch.object(ab, "embed_texts", new=AsyncMock(return_value=[[0.1, 0.2]])),
            patch.object(ab.ontology_embeddings, "search_similar", return_value=hits),
        ):
            out = await ab.retrieve_schema_slice(db, "ont1", "Acme is a company")
        assert out == [{"key": "C1", "label": "Organization"}]

    async def test_falls_back_to_all_classes(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [{"key": "C1", "label": "Organization"}, {"key": "C2", "label": "Person"}]
        with (
            patch.object(ab, "embed_texts", new=AsyncMock(return_value=[[]])),  # no embedding
            patch.object(ab, "run_aql", return_value=iter(rows)),
        ):
            out = await ab.retrieve_schema_slice(db, "ont1", "text")
        assert out == rows


class TestExtractAboxFromText:
    async def test_parses_individuals_and_assertions(self) -> None:
        llm = MagicMock()
        llm.ainvoke = AsyncMock(
            return_value=MagicMock(
                content=(
                    '{"individuals":[{"label":"Acme","class":"Organization"}],'
                    '"assertions":[{"subject":"Acme","predicate":"employs","object":"Bob"}]}'
                )
            )
        )
        with patch.object(ab, "_get_llm", return_value=llm):
            out = await ab.extract_abox_from_text("text", [{"key": "C1", "label": "Organization"}])
        assert out["individuals"][0]["label"] == "Acme"
        assert out["assertions"][0]["predicate"] == "employs"

    async def test_empty_slice_skips_llm(self) -> None:
        with patch.object(ab, "_get_llm") as mk:
            out = await ab.extract_abox_from_text("text", [])
        assert out == {"individuals": [], "assertions": []}
        mk.assert_not_called()

    async def test_llm_error_returns_empty(self) -> None:
        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
        with patch.object(ab, "_get_llm", return_value=llm):
            out = await ab.extract_abox_from_text("t", [{"key": "C1", "label": "Org"}])
        assert out == {"individuals": [], "assertions": []}


class TestExtractAndMaterialize:
    async def test_grounded_materialization_canonicalizes_and_asserts(self) -> None:
        db = MagicMock()
        chunks = [
            {"text": "Acme employs Bob.", "document_id": "d1", "_key": "ch1"},
            {"text": "Acme again.", "document_id": "d1", "_key": "ch2"},  # repeat mention
        ]
        slice_ = [{"key": "Org", "label": "Organization"}, {"key": "Per", "label": "Person"}]

        # chunk 1: Acme (Organization) + Bob (Person) + assertion; plus an
        # ungrounded "Ghost" (class not in slice) that must be dropped.
        # chunk 2: Acme again -> canonicalized to the same individual.
        extract_results = [
            {
                "individuals": [
                    {"label": "Acme", "class": "Organization"},
                    {"label": "Bob", "class": "Person"},
                    {"label": "Ghost", "class": "Spectre"},  # ungrounded -> dropped
                ],
                "assertions": [{"subject": "Acme", "predicate": "employs", "object": "Bob"}],
            },
            {"individuals": [{"label": "Acme", "class": "Organization"}], "assertions": []},
        ]

        created: list[str] = []

        def _create_individual(_db, **kwargs):
            iid = f"ontology_individuals/{kwargs['label']}"
            created.append(kwargs["label"])
            return {"_id": iid, "_key": kwargs["label"]}

        with (
            patch.object(ab, "retrieve_schema_slice", new=AsyncMock(return_value=slice_)),
            patch.object(ab, "extract_abox_from_text", new=AsyncMock(side_effect=extract_results)),
            patch.object(
                ab.individuals_repo, "create_individual", side_effect=_create_individual
            ) as mk_ind,
            patch.object(ab.individuals_repo, "add_assertion") as mk_assert,
        ):
            out = await ab.extract_and_materialize_abox(db, ontology_id="ont1", chunks=chunks)

        # Acme + Bob materialized once each; Ghost dropped (ungrounded); Acme not
        # re-created on the second chunk (canonicalized).
        assert out["individuals"] == 2
        assert sorted(created) == ["Acme", "Bob"]
        assert mk_ind.call_count == 2
        # one assertion Acme --employs--> Bob, with provenance
        assert out["assertions"] == 1
        akw = mk_assert.call_args.kwargs
        assert akw["predicate"] == "employs"
        assert akw["from_individual_id"] == "ontology_individuals/Acme"
        assert akw["to_id"] == "ontology_individuals/Bob"
        assert akw["provenance"][0]["chunk_id"] == "ch1"

    async def test_open_mode_keeps_ungrounded(self) -> None:
        db = MagicMock()
        chunks = [{"text": "X", "document_id": "d1", "_key": "ch1"}]
        with (
            patch.object(ab, "retrieve_schema_slice", new=AsyncMock(return_value=[])),
            patch.object(
                ab,
                "extract_abox_from_text",
                new=AsyncMock(
                    return_value={
                        "individuals": [{"label": "Thing", "class": "Unknown"}],
                        "assertions": [],
                    }
                ),
            ),
            patch.object(
                ab.individuals_repo,
                "create_individual",
                return_value={"_id": "ontology_individuals/Thing", "_key": "Thing"},
            ) as mk_ind,
            patch.object(ab.individuals_repo, "add_assertion"),
        ):
            out = await ab.extract_and_materialize_abox(
                db, ontology_id="ont1", chunks=chunks, mode="open"
            )
        assert out["individuals"] == 1
        assert mk_ind.call_args.kwargs["class_key"] == ""  # ungrounded, no T-box class
