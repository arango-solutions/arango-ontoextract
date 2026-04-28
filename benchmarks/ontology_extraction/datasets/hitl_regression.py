"""HITL regression fixture loader.

The fixture is generated from curated feedback-learning artifacts. Positive
assertions are scored by the existing benchmark harness; negative assertions are
retained in ``source_meta`` for review and future negative-example scoring.
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

from benchmarks.ontology_extraction.datasets.base import GoldDocument
from benchmarks.ontology_extraction.metrics import ClassMention, Triple


def load(root: Path, limit: int | None = None) -> Iterator[GoldDocument]:
    """Yield benchmark documents from ``hitl-regression-v1`` fixture JSON."""
    path = _fixture_path(Path(root))
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)

    if payload.get("schema_version") != "hitl-regression-v1":
        raise ValueError(f"{path}: expected schema_version='hitl-regression-v1'")

    documents = payload.get("documents") or []
    if not isinstance(documents, list):
        raise ValueError(f"{path}: expected documents to be a JSON array")

    for i, doc in enumerate(documents):
        if limit is not None and i >= limit:
            return
        yield _to_gold_document(doc, fallback_id=f"hitl-{i:06d}", source_path=str(path))


def _fixture_path(root: Path) -> Path:
    if root.is_file():
        return root
    candidates = [
        root / "hitl_regression.json",
        root / "regression_fixture.json",
        root / "feedback_learning_fixture.json",
    ]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise FileNotFoundError(
            f"no HITL regression fixture found under {root}; expected hitl_regression.json"
        )
    return path


def _to_gold_document(doc: dict, fallback_id: str, source_path: str) -> GoldDocument:
    gold_classes = {
        ClassMention.of(str(item.get("label") or ""), str(item.get("type") or ""))
        for item in doc.get("gold_classes") or []
        if item.get("label")
    }
    gold_relations = {
        Triple.of(
            str(item.get("head") or ""),
            str(item.get("relation") or ""),
            str(item.get("tail") or ""),
        )
        for item in doc.get("gold_relations") or []
        if item.get("head") and item.get("relation") and item.get("tail")
    }
    source_meta = {
        **(doc.get("source_meta") or {}),
        "source": source_path,
        "negative_classes": doc.get("negative_classes") or [],
        "negative_relations": doc.get("negative_relations") or [],
    }
    return GoldDocument(
        id=str(doc.get("id") or fallback_id),
        text=str(doc.get("text") or ""),
        gold_classes=gold_classes,
        gold_relations=gold_relations,
        source_meta=source_meta,
    )
