"""Re-DocRED loader.

File format (upstream ``dev_revised.json`` / ``train_revised.json``): a JSON
array of documents. Each document object has:

* ``sents``: list of sentences, each a list of tokens.
* ``vertexSet``: list of entity clusters; each cluster is a list of mention
  dicts with ``name`` (surface form), ``type`` (coarse NER type), ``sent_id``,
  ``pos``.
* ``labels``: list of relation instances with integer head/tail indices into
  ``vertexSet``, a ``r`` relation code (Wikidata property id), and
  ``evidence`` sentence indices.

The loader flattens each document into:

* ``text`` — space-joined tokens across sentences, paragraph-broken on
  sentence boundaries.
* ``gold_classes`` — one :class:`ClassMention` per entity cluster, using the
  canonical first mention as the label and the NER type.
* ``gold_relations`` — one :class:`Triple` per ``labels`` entry, using the
  canonical labels of the head/tail clusters and the raw Wikidata property id.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from pathlib import Path

from benchmarks.ontology_extraction.datasets.base import GoldDocument
from benchmarks.ontology_extraction.metrics import ClassMention, Triple


def load(root: Path, limit: int | None = None) -> Iterator[GoldDocument]:
    """Yield :class:`GoldDocument` instances from the Re-DocRED fetch target.

    ``root`` should point at ``samples/corpora/external/redocred/`` (i.e. the
    directory populated by ``scripts/fetch-corpora.sh``). The loader looks for
    ``dev_revised.json`` first, then falls back to ``train_revised.json`` or
    ``test_revised.json``.
    """
    root = Path(root)
    candidates = [
        root / "dev_revised.json",
        root / "train_revised.json",
        root / "test_revised.json",
    ]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise FileNotFoundError(
            f"no Re-DocRED JSON found under {root}; run scripts/fetch-corpora.sh first"
        )

    with path.open("r", encoding="utf-8") as fh:
        docs = json.load(fh)

    if not isinstance(docs, list):
        raise ValueError(f"{path}: expected a JSON array at the top level")

    yield from _iter_docs(docs, limit, source_path=str(path))


def _iter_docs(
    docs: Iterable[dict], limit: int | None, source_path: str
) -> Iterator[GoldDocument]:
    for i, doc in enumerate(docs):
        if limit is not None and i >= limit:
            return
        yield _to_gold_document(doc, fallback_id=f"redocred-{i:06d}", source_path=source_path)


def _to_gold_document(doc: dict, fallback_id: str, source_path: str) -> GoldDocument:
    title = str(doc.get("title") or fallback_id)
    sents = doc.get("sents") or []
    text = "\n\n".join(" ".join(tokens) for tokens in sents if tokens)

    vertex_set = doc.get("vertexSet") or []
    canonical_labels: list[str] = []
    canonical_types: list[str] = []
    gold_classes: set[ClassMention] = set()

    for cluster in vertex_set:
        if not cluster:
            canonical_labels.append("")
            canonical_types.append("")
            continue
        first = cluster[0]
        label = str(first.get("name") or "").strip()
        type_ = str(first.get("type") or "").strip()
        canonical_labels.append(label)
        canonical_types.append(type_)
        if label:
            gold_classes.add(ClassMention.of(label, type_))

    gold_relations: set[Triple] = set()
    for rel in doc.get("labels") or []:
        h = rel.get("h")
        t = rel.get("t")
        r = rel.get("r")
        if (
            h is None
            or t is None
            or r is None
            or h >= len(canonical_labels)
            or t >= len(canonical_labels)
        ):
            continue
        head_label = canonical_labels[h]
        tail_label = canonical_labels[t]
        if not head_label or not tail_label:
            continue
        gold_relations.add(Triple.of(head_label, str(r), tail_label))

    return GoldDocument(
        id=title,
        text=text,
        gold_classes=gold_classes,
        gold_relations=gold_relations,
        source_meta={"source": source_path, "vertex_count": len(vertex_set)},
    )
