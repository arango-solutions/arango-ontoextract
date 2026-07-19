"""Unit tests for LLM-assisted CQ->AQL formalization (Stream 22 / CQ-PR3)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import cq_formalize as cf

_READ_ONLY = "FOR c IN ontology_classes FILTER c.ontology_id==@ontology_id RETURN c"


def _llm_returning(content: str) -> MagicMock:
    llm = MagicMock()
    llm.ainvoke = AsyncMock(return_value=MagicMock(content=content))
    return llm


class TestFormalizeCq:
    async def test_returns_read_only_query(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        with (
            patch.object(cf, "run_aql", return_value=iter(["Account"])),
            patch.object(cf, "_get_llm", return_value=_llm_returning(_READ_ONLY)),
        ):
            out = await cf.formalize_cq(db, "o1", "Which accounts exist?")
        assert out == _READ_ONLY

    async def test_strips_code_fences(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        fenced = f"```aql\n{_READ_ONLY}\n```"
        with (
            patch.object(cf, "run_aql", return_value=iter([])),
            patch.object(cf, "_get_llm", return_value=_llm_returning(fenced)),
        ):
            out = await cf.formalize_cq(db, "o1", "q")
        assert out == _READ_ONLY

    async def test_rejects_write_query(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        with (
            patch.object(cf, "run_aql", return_value=iter([])),
            patch.object(cf, "_get_llm", return_value=_llm_returning("FOR c IN x REMOVE c IN x")),
        ):
            out = await cf.formalize_cq(db, "o1", "q")
        assert out == ""

    async def test_empty_text_skips_llm(self) -> None:
        db = MagicMock()
        with patch.object(cf, "_get_llm") as mk:
            out = await cf.formalize_cq(db, "o1", "   ")
        assert out == ""
        mk.assert_not_called()

    async def test_llm_error_returns_empty(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        llm = MagicMock()
        llm.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))
        with (
            patch.object(cf, "run_aql", return_value=iter([])),
            patch.object(cf, "_get_llm", return_value=llm),
        ):
            out = await cf.formalize_cq(db, "o1", "q")
        assert out == ""


class TestFormalizeSpec:
    async def test_missing_spec_raises(self) -> None:
        db = MagicMock()
        with (
            patch.object(cf.requirements_repo, "get_requirements", return_value=None),
            pytest.raises(ValueError, match="no requirements spec"),
        ):
            await cf.formalize_spec(db, ontology_id="o1")

    async def test_fills_only_unformalized_and_saves(self) -> None:
        db = MagicMock()
        spec = {
            "use_cases": [
                {
                    "competency_questions": [
                        {"text": "already", "query": "FOR c IN x RETURN c"},  # kept
                        {"text": "needs one"},  # formalized
                    ]
                }
            ]
        }
        with (
            patch.object(cf.requirements_repo, "get_requirements", return_value=spec),
            patch.object(cf, "formalize_cq", new=AsyncMock(return_value=_READ_ONLY)) as mk_f,
            patch.object(cf.requirements_repo, "upsert_requirements") as mk_up,
        ):
            out = await cf.formalize_spec(db, ontology_id="o1")
        assert out == {"ontology_id": "o1", "formalized": 1, "total": 2}
        mk_f.assert_awaited_once()  # only the un-formalized CQ
        # the generated query was written back before saving
        saved = mk_up.call_args.args[2]
        assert saved["use_cases"][0]["competency_questions"][1]["query"] == _READ_ONLY

    async def test_overwrite_reformalizes_all(self) -> None:
        db = MagicMock()
        spec = {"use_cases": [{"competency_questions": [{"text": "a", "query": "old"}]}]}
        with (
            patch.object(cf.requirements_repo, "get_requirements", return_value=spec),
            patch.object(cf, "formalize_cq", new=AsyncMock(return_value=_READ_ONLY)) as mk_f,
            patch.object(cf.requirements_repo, "upsert_requirements"),
        ):
            out = await cf.formalize_spec(db, ontology_id="o1", overwrite=True)
        assert out["formalized"] == 1
        mk_f.assert_awaited_once()
