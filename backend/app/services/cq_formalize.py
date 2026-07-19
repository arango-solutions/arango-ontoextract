"""LLM-assisted competency-question → AQL formalization (Stream 22 / CQ-PR3, §6.19).

Turns a competency question's natural-language ``text`` into a read-only AQL
query grounded in the ontology's schema, stored on the CQ's ``query`` field so
coverage validation (CQ-PR4/5) can run it. LLM-assisted but human-verified: the
generated query lands in the spec for a curator to review/edit in the
Requirements overlay before it's trusted.

Safety: the generated query is rejected unless it is read-only (same guard as
coverage) — the LLM is instructed to emit only reads, and we enforce it.
"""

from __future__ import annotations

import json
import logging

from arango.database import StandardDatabase

from app.db import requirements_repo
from app.db.client import get_db
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.extraction.agents.extractor import _get_llm
from app.services.cq_coverage import _is_read_only

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You translate a competency question into a single READ-ONLY ArangoDB AQL "
    "query that returns >=1 row if and only if the ontology can answer it. Use "
    "only these collections: ontology_classes (fields: label, ontology_id, "
    "expired) and ontology_individuals (fields: label, ontology_id, expired). "
    "ALWAYS filter `ontology_id == @ontology_id AND expired == @never`. NEVER use "
    "INSERT/UPDATE/REPLACE/REMOVE/UPSERT. Respond with ONLY the AQL query text — "
    "no prose, no code fences."
)


def _class_labels(db: StandardDatabase, ontology_id: str, limit: int = 200) -> list[str]:
    if not db.has_collection("ontology_classes"):
        return []
    return list(
        run_aql(
            db,
            """
            FOR c IN ontology_classes
              FILTER c.ontology_id == @oid AND c.expired == @never AND c.label != null
              SORT c.label ASC
              LIMIT @n
              RETURN c.label
            """,
            bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES, "n": limit},
        )
    )


def _clean_query(raw: str) -> str:
    """Strip code fences / surrounding prose from the LLM's AQL output."""
    text = raw.strip()
    if text.startswith("```"):
        # drop the opening fence line and any trailing fence
        lines = [ln for ln in text.splitlines() if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    return text


async def formalize_cq(
    db: StandardDatabase,
    ontology_id: str,
    cq_text: str,
    *,
    model: str | None = None,
) -> str:
    """Generate a read-only AQL query for one CQ. Returns "" on failure/unsafe."""
    if not cq_text.strip():
        return ""
    labels = _class_labels(db, ontology_id)
    try:
        llm = _get_llm(model or "")
        from langchain_core.messages import HumanMessage, SystemMessage

        user = f"Ontology classes: {json.dumps(labels)}\nCompetency question: {cq_text}"
        resp = await llm.ainvoke(
            [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user)]
        )
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
        query = _clean_query(raw)
        if not query or not _is_read_only(query):
            return ""
        return query
    except Exception:
        log.warning("CQ formalization failed for ontology %s", ontology_id, exc_info=True)
        return ""


async def formalize_spec(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    overwrite: bool = False,
    model: str | None = None,
) -> dict[str, int | str]:
    """Formalize the ontology's competency questions in place.

    Fills the ``query`` of each CQ that lacks one (or all CQs when
    ``overwrite``), saves the spec, and returns how many were formalized.
    Raises ``ValueError`` if the ontology has no requirements spec.
    """
    if db is None:
        db = get_db()
    spec = requirements_repo.get_requirements(db, ontology_id)
    if spec is None:
        raise ValueError(f"no requirements spec for ontology '{ontology_id}'")

    formalized = 0
    considered = 0
    for uc in spec.get("use_cases") or []:
        for cq in uc.get("competency_questions") or []:
            considered += 1
            if cq.get("query") and not overwrite:
                continue
            query = await formalize_cq(db, ontology_id, str(cq.get("text") or ""), model=model)
            if query:
                cq["query"] = query
                formalized += 1

    requirements_repo.upsert_requirements(db, ontology_id, spec)
    return {"ontology_id": ontology_id, "formalized": formalized, "total": considered}
