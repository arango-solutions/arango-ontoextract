"""Schema-grounded assertion-graph (A-box) extraction (Stream 21 / AB-PR2, PRD §6.18).

EDC pattern (Extract-Define-Canonicalize, EMNLP 2024): for each chunk, a schema
retriever fetches the relevant T-box slice (via SF.1 vector search over class
embeddings, falling back to the ontology's full class list for small P1
ontologies), the LLM extracts individuals + relationships **grounded in that
slice**, and results are canonicalized + materialized as A-box individuals /
assertions with span provenance.

Grounding controls hallucination (FR-18.8): in ``schema_guided`` mode (default)
an individual whose class is not in the retrieved slice is dropped, and only
subject/object pairs that resolved to materialized individuals become assertions.

Multi-domain routing (FR-18.6) is the caller's boundary: pass the *domain*
``ontology_id`` and that domain's chunks. When a document set spans domains, the
caller (per the Stream 16 ``domain_tag``) invokes this once per domain ontology.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from arango.database import StandardDatabase
from langchain_core.messages import HumanMessage, SystemMessage

from app.db import individuals_repo
from app.db.client import get_db
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.extraction.agents.extractor import _get_llm
from app.services import ontology_embeddings
from app.services.embedding import embed_texts

log = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You extract a knowledge graph (A-box) from text, grounded in a given "
    "ontology. Only use the provided class labels; do not invent classes. "
    "Identify named individuals (instances) and their relationships. Respond "
    'ONLY with a JSON object: {"individuals": [{"label": "...", "class": '
    '"<one of the provided class labels>"}], "assertions": [{"subject": '
    '"<individual label>", "predicate": "...", "object": "<individual label>"}]}.'
)


async def retrieve_schema_slice(
    db: StandardDatabase,
    ontology_id: str,
    text: str,
    *,
    k: int = 15,
) -> list[dict[str, Any]]:
    """Return the T-box classes most relevant to ``text`` (EDC schema retriever).

    Uses SF.1 vector search over ``ontology_classes`` when embeddings/index exist;
    falls back to the ontology's full (small) class list otherwise. Each entry is
    ``{"key", "label"}``.
    """
    try:
        embeddings = await embed_texts([text])
        if embeddings and embeddings[0]:
            hits = ontology_embeddings.search_similar(
                db, "ontology_classes", embeddings[0], k=k * 3
            )
            slice_ = [
                {"key": h.get("_key"), "label": h.get("label")}
                for h in hits
                if h.get("ontology_id") == ontology_id and h.get("label")
            ]
            if slice_:
                return slice_[:k]
    except Exception:
        log.warning("schema retriever vector path failed; falling back", exc_info=True)

    if not db.has_collection("ontology_classes"):
        return []
    rows = run_aql(
        db,
        """
        FOR c IN ontology_classes
          FILTER c.ontology_id == @oid AND c.expired == @never AND c.label != null
          SORT c.label ASC
          LIMIT 500
          RETURN {key: c._key, label: c.label}
        """,
        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
    )
    return list(rows)


def _parse_abox(raw: str) -> dict[str, list[dict[str, Any]]]:
    text = raw.strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return {"individuals": [], "assertions": []}
    try:
        data = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return {"individuals": [], "assertions": []}
    inds = [i for i in data.get("individuals", []) if isinstance(i, dict)]
    asserts = [a for a in data.get("assertions", []) if isinstance(a, dict)]
    return {"individuals": inds, "assertions": asserts}


async def extract_abox_from_text(
    text: str,
    schema_slice: list[dict[str, Any]],
    *,
    model: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """LLM-extract individuals + assertions grounded in ``schema_slice``. Never raises."""
    labels = [str(s.get("label")) for s in schema_slice if s.get("label")]
    if not labels:
        return {"individuals": [], "assertions": []}
    try:
        llm = _get_llm(model or "")
        user = f"Ontology classes: {json.dumps(labels)}\n\nText:\n{text}"
        resp = await llm.ainvoke(
            [SystemMessage(content=_SYSTEM_PROMPT), HumanMessage(content=user)]
        )
        raw = resp.content if isinstance(resp.content, str) else str(resp.content)
        return _parse_abox(raw)
    except Exception:
        log.warning("A-box extraction LLM call failed; returning empty", exc_info=True)
        return {"individuals": [], "assertions": []}


async def extract_and_materialize_abox(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    chunks: list[dict[str, Any]],
    mode: str = "schema_guided",
    model: str | None = None,
) -> dict[str, Any]:
    """Extract + materialize the A-box for one domain ontology from its chunks.

    Canonicalizes coreferent mentions by (class, normalized label) across chunks
    (a lightweight stand-in for full ER canonicalization, AB-PR3), stamps span
    provenance on every individual + assertion, and — in ``schema_guided`` mode —
    drops individuals whose class is not in the retrieved slice. Returns counts.
    """
    if db is None:
        db = get_db()

    canon_to_id: dict[tuple[str, str], str] = {}
    ind_count = 0
    assert_count = 0

    for chunk in chunks:
        text = str(chunk.get("text") or chunk.get("content") or "")
        if not text.strip():
            continue
        prov = [
            {
                "doc_id": chunk.get("document_id") or chunk.get("doc_id"),
                "chunk_id": chunk.get("_key") or chunk.get("chunk_id"),
            }
        ]
        schema_slice = await retrieve_schema_slice(db, ontology_id, text)
        label_to_key = {str(s["label"]).lower(): s["key"] for s in schema_slice if s.get("label")}
        result = await extract_abox_from_text(text, schema_slice, model=model)

        local: dict[str, str] = {}  # individual label (lower) -> _id, for assertion resolution
        for ind in result["individuals"]:
            label = str(ind.get("label") or "").strip()
            cls = str(ind.get("class") or "").strip().lower()
            if not label:
                continue
            class_key = label_to_key.get(cls)
            if mode == "schema_guided" and class_key is None:
                continue  # grounded-only: skip ungrounded individuals
            canon = (class_key or "", label.lower())
            iid = canon_to_id.get(canon)
            if iid is None:
                individual = individuals_repo.create_individual(
                    db,
                    ontology_id=ontology_id,
                    class_key=class_key or "",
                    label=label,
                    provenance=prov,
                )
                iid = str(individual["_id"])
                canon_to_id[canon] = iid
                ind_count += 1
            local[label.lower()] = iid

        for a in result["assertions"]:
            subj = str(a.get("subject") or "").strip().lower()
            obj = str(a.get("object") or "").strip().lower()
            predicate = str(a.get("predicate") or "").strip()
            sid, oid_ = local.get(subj), local.get(obj)
            if sid and oid_ and predicate:
                individuals_repo.add_assertion(
                    db,
                    ontology_id=ontology_id,
                    from_individual_id=sid,
                    to_id=oid_,
                    predicate=predicate,
                    provenance=prov,
                )
                assert_count += 1

    log.info(
        "[abox] ontology %s: %d individuals, %d assertions from %d chunks",
        ontology_id,
        ind_count,
        assert_count,
        len(chunks),
    )
    return {
        "ontology_id": ontology_id,
        "individuals": ind_count,
        "assertions": assert_count,
        "chunks": len(chunks),
    }
