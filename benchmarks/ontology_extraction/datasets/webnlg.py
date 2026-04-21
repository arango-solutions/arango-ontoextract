"""WebNLG 2020 loader.

WebNLG distributes entries as XML. Each ``<entry>`` contains:

* a ``<modifiedtripleset>`` (or ``<originaltripleset>``) with one or more
  ``<mtriple>`` elements formatted as ``"subject | predicate | object"``;
* one or more ``<lex>`` natural-language realizations of those triples.

For our purposes, a single WebNLG *entry* is one ``GoldDocument``:

* ``text`` — the first lexicalisation (or all of them concatenated when
  multiple realizations exist, controlled by the ``merge_lex`` flag).
* ``gold_classes`` — DBpedia subjects and objects, typed generically as
  ``"entity"`` (WebNLG does not carry fine-grained NER types at triple level).
* ``gold_relations`` — the ``(subject, predicate, object)`` triples.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path

from benchmarks.ontology_extraction.datasets.base import GoldDocument
from benchmarks.ontology_extraction.metrics import ClassMention, Triple


def load(root: Path, limit: int | None = None, merge_lex: bool = False) -> Iterator[GoldDocument]:
    """Yield :class:`GoldDocument` instances from WebNLG fetched files.

    ``root`` should be ``samples/corpora/external/webnlg/``. The loader picks
    the first XML file matching ``rdf-to-text-test.xml``, then ``dev.xml``,
    then ``train.xml``.
    """
    root = Path(root)
    candidates = [
        root / "rdf-to-text-test.xml",
        root / "dev.xml",
        root / "train.xml",
    ]
    path = next((p for p in candidates if p.is_file()), None)
    if path is None:
        raise FileNotFoundError(
            f"no WebNLG XML found under {root}; run scripts/fetch-corpora.sh first"
        )

    tree = ET.parse(path)
    root_el = tree.getroot()
    entries = root_el.findall(".//entry")
    for i, entry in enumerate(entries):
        if limit is not None and i >= limit:
            return
        doc = _entry_to_gold_document(entry, fallback_id=f"webnlg-{i:06d}", merge_lex=merge_lex)
        if doc is not None:
            yield doc


def _entry_to_gold_document(
    entry: ET.Element, fallback_id: str, merge_lex: bool
) -> GoldDocument | None:
    entry_id = entry.attrib.get("eid") or fallback_id

    triples_el = entry.find("modifiedtripleset") or entry.find("originaltripleset")
    if triples_el is None:
        return None

    gold_classes: set[ClassMention] = set()
    gold_relations: set[Triple] = set()

    for mt in triples_el.findall("mtriple"):
        raw = (mt.text or "").strip()
        parts = [p.strip() for p in raw.split("|")]
        if len(parts) != 3 or not all(parts):
            continue
        subj, pred, obj = parts
        gold_classes.add(ClassMention.of(subj, "entity"))
        gold_classes.add(ClassMention.of(obj, "entity"))
        gold_relations.add(Triple.of(subj, pred, obj))

    lex_texts = [el.text.strip() for el in entry.findall("lex") if el.text and el.text.strip()]
    if not lex_texts:
        return None
    text = "\n\n".join(lex_texts) if merge_lex else lex_texts[0]

    return GoldDocument(
        id=entry_id,
        text=text,
        gold_classes=gold_classes,
        gold_relations=gold_relations,
        source_meta={"lex_count": len(lex_texts), "triple_count": len(gold_relations)},
    )
