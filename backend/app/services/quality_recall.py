"""Quality recall service — gold-standard comparison (Q.4, PRD §6.13).

Compares the classes (and optionally object properties) of an ontology
already in ArangoDB against a reference OWL/TTL document supplied by
the caller, using fuzzy label matching so superficial differences
(``Person`` vs ``person``, ``Mortgage Loan`` vs ``MortgageLoan``,
extra punctuation, plural / singular variants) do not artificially
lower recall.

Outputs precision, recall, F1, plus per-class match details so the
operator can inspect which gold-standard concepts are missing and
which extracted concepts have no counterpart.

The label normalisation here is intentionally simple (lowercase +
strip non-alnum + de-pluralise + camelCase split). The point is not
to ship a thesaurus; it is to give a useful "the pipeline missed
*these* concepts" report without forcing the user to clean their
gold standard.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from arango.database import StandardDatabase
from rdflib import OWL, RDF, RDFS, Graph as RDFGraph, URIRef
from rdflib.term import Literal

from app.db.client import get_db
from app.db.utils import run_aql

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Label normalisation
# ---------------------------------------------------------------------------

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _split_camel(value: str) -> str:
    return _CAMEL_BOUNDARY.sub(" ", value)


def _depluralise(token: str) -> str:
    """Cheap singularisation. Handles the common s / ies / es endings.

    Intentionally conservative — we don't try to invert "data → datum"
    or "indices → index"; matchers should fall back to fuzzy similarity
    for those.
    """
    if len(token) <= 3:
        return token
    if token.endswith("ies"):
        return token[:-3] + "y"
    if token.endswith("ses") or token.endswith("xes") or token.endswith("zes"):
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def normalise_label(value: str | None) -> str:
    """Normalise a label for fuzzy matching.

    Splits ``camelCase`` / ``PascalCase``, lowercases, strips
    non-alphanumerics, then de-pluralises each token. Empty / ``None``
    inputs return ``""`` so callers can treat "no label" as a sentinel.
    """
    if not value:
        return ""
    value = _split_camel(value)
    value = value.lower()
    value = _NON_ALNUM.sub(" ", value).strip()
    if not value:
        return ""
    tokens = [_depluralise(tok) for tok in value.split() if tok]
    return " ".join(tokens)


def label_similarity(a: str | None, b: str | None) -> float:
    """Fuzzy similarity ``[0, 1]`` between two labels after normalisation.

    Returns ``0.0`` when either side normalises to empty so that
    "no label" never scores as a match. Exact (post-normalisation)
    matches return ``1.0`` without invoking the more expensive
    SequenceMatcher.
    """
    na = normalise_label(a)
    nb = normalise_label(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


# ---------------------------------------------------------------------------
# Reference parsing
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RefConcept:
    uri: str
    label: str
    kind: str  # "class" | "object_property"


def _local_name(uri: URIRef | str) -> str:
    """Extract the local part of a URI (after ``#`` or last ``/``).

    Used as a fallback label when the reference document does not carry
    an ``rdfs:label`` for a concept.
    """
    s = str(uri)
    if "#" in s:
        return s.rsplit("#", 1)[-1]
    if "/" in s:
        return s.rsplit("/", 1)[-1]
    return s


def _label_for(graph: RDFGraph, subject: URIRef) -> str:
    for _, _, obj in graph.triples((subject, RDFS.label, None)):
        if isinstance(obj, Literal):
            return str(obj)
    return _local_name(subject)


def parse_reference_ontology(
    content: str,
    *,
    rdf_format: str = "turtle",
) -> list[_RefConcept]:
    """Parse the user-supplied reference OWL/TTL into concepts.

    Returns a flat list of classes + object properties so the caller
    (or test) can group as needed. Anonymous nodes (blank nodes) and
    OWL built-ins (``owl:Thing``, ``owl:topObjectProperty``, …) are
    excluded.

    ``rdf_format`` is forwarded to ``rdflib.Graph.parse``; common values:
    ``"turtle"``, ``"xml"`` (RDF/XML), ``"nt"``, ``"json-ld"``.
    """
    graph = RDFGraph()
    try:
        graph.parse(data=content, format=rdf_format)
    except Exception as exc:
        raise ValueError(f"Failed to parse reference ontology as {rdf_format}: {exc}") from exc

    concepts: list[_RefConcept] = []
    seen: set[str] = set()

    def _emit(subject: URIRef, kind: str) -> None:
        # Skip blank nodes and OWL built-in vocabulary.
        if not isinstance(subject, URIRef):
            return
        uri = str(subject)
        if uri.startswith(str(OWL)) or uri.startswith(str(RDFS)):
            return
        if uri in seen:
            return
        seen.add(uri)
        concepts.append(_RefConcept(uri=uri, label=_label_for(graph, subject), kind=kind))

    for cls, _, _ in graph.triples((None, RDF.type, OWL.Class)):
        if isinstance(cls, URIRef):
            _emit(cls, "class")
    for cls, _, _ in graph.triples((None, RDF.type, RDFS.Class)):
        if isinstance(cls, URIRef):
            _emit(cls, "class")
    for prop, _, _ in graph.triples((None, RDF.type, OWL.ObjectProperty)):
        if isinstance(prop, URIRef):
            _emit(prop, "object_property")

    return concepts


# ---------------------------------------------------------------------------
# Recall computation
# ---------------------------------------------------------------------------


def _load_extracted_classes(
    db: StandardDatabase,
    ontology_id: str,
) -> list[dict[str, Any]]:
    if not db.has_collection("ontology_classes"):
        return []
    rows = run_aql(
        db,
        "FOR c IN ontology_classes "
        "FILTER c.ontology_id == @oid "
        "FILTER c.expired == 9223372036854775807 "  # NEVER_EXPIRES
        "RETURN { uri: c.uri, label: c.label, _key: c._key }",
        bind_vars={"oid": ontology_id},
    )
    return [r for r in rows if r and r.get("label")]


def _load_extracted_object_properties(
    db: StandardDatabase,
    ontology_id: str,
) -> list[dict[str, Any]]:
    if not db.has_collection("ontology_object_properties"):
        return []
    rows = run_aql(
        db,
        "FOR p IN ontology_object_properties "
        "FILTER p.ontology_id == @oid "
        "FILTER p.expired == 9223372036854775807 "
        "RETURN { uri: p.uri, label: p.label, _key: p._key }",
        bind_vars={"oid": ontology_id},
    )
    return [r for r in rows if r and r.get("label")]


@dataclass
class _MatchPair:
    reference_uri: str
    reference_label: str
    extracted_uri: str | None
    extracted_label: str | None
    extracted_key: str | None
    similarity: float


def _greedy_match(
    reference: list[_RefConcept],
    extracted: list[dict[str, Any]],
    *,
    threshold: float,
) -> tuple[list[_MatchPair], list[_RefConcept], list[dict[str, Any]]]:
    """Greedy 1-to-1 best-match assignment.

    For each reference concept, find the highest-scoring extracted
    concept (above ``threshold``) that has not yet been claimed by an
    earlier reference. Returns ``(matches, missed, false_positives)``.

    Greedy is sufficient at this scale (≤ a few hundred concepts) and
    avoids the complexity of the Hungarian algorithm. If two reference
    concepts both prefer the same extracted concept, the first one wins
    — which is fine because reference order is itself arbitrary; what
    matters is the count, not which side of a tie gets credit.
    """
    matches: list[_MatchPair] = []
    missed: list[_RefConcept] = []
    claimed: set[str] = set()

    extracted_by_uri = {row.get("uri") or row.get("_key"): row for row in extracted}

    for ref in reference:
        best_uri: str | None = None
        best_label: str | None = None
        best_key: str | None = None
        best_sim = 0.0
        for row in extracted:
            uri = row.get("uri") or row.get("_key")
            if uri in claimed:
                continue
            sim = label_similarity(ref.label, row.get("label"))
            if sim > best_sim:
                best_sim = sim
                best_uri = uri
                best_label = row.get("label")
                best_key = row.get("_key")
        if best_sim >= threshold and best_uri is not None:
            claimed.add(best_uri)
            matches.append(
                _MatchPair(
                    reference_uri=ref.uri,
                    reference_label=ref.label,
                    extracted_uri=best_uri,
                    extracted_label=best_label,
                    extracted_key=best_key,
                    similarity=round(best_sim, 4),
                )
            )
        else:
            missed.append(ref)

    false_positives = [
        row
        for uri, row in extracted_by_uri.items()
        if uri not in claimed
    ]
    return matches, missed, false_positives


def _f1(precision: float, recall: float) -> float:
    if precision + recall <= 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def compute_recall(
    db: StandardDatabase | None = None,
    *,
    ontology_id: str,
    reference_content: str,
    rdf_format: str = "turtle",
    match_threshold: float = 0.85,
    include_object_properties: bool = True,
) -> dict[str, Any]:
    """Compare an extracted ontology to a reference OWL/TTL document.

    Returns a structured report::

        {
          "ontology_id": "...",
          "match_threshold": 0.85,
          "rdf_format": "turtle",
          "summary": {
            "reference_count": int,
            "extracted_count": int,
            "matched_count": int,
            "recall": float,        # |matched| / |reference|
            "precision": float,     # |matched| / |extracted|
            "f1": float,
          },
          "classes": {summary, matched, missed, false_positives},
          "object_properties": {summary, matched, missed, false_positives}
              # only present when include_object_properties=True
        }
    """
    if db is None:
        db = get_db()
    if not 0.0 <= match_threshold <= 1.0:
        raise ValueError("match_threshold must be in [0, 1]")

    reference = parse_reference_ontology(reference_content, rdf_format=rdf_format)
    ref_classes = [c for c in reference if c.kind == "class"]
    ref_props = [c for c in reference if c.kind == "object_property"]

    extracted_classes = _load_extracted_classes(db, ontology_id)
    classes_report = _build_section(
        ref_classes,
        extracted_classes,
        threshold=match_threshold,
    )

    payload: dict[str, Any] = {
        "ontology_id": ontology_id,
        "match_threshold": match_threshold,
        "rdf_format": rdf_format,
        "classes": classes_report,
    }

    summary_ref = classes_report["summary"]["reference_count"]
    summary_ext = classes_report["summary"]["extracted_count"]
    summary_matched = classes_report["summary"]["matched_count"]

    if include_object_properties:
        extracted_props = _load_extracted_object_properties(db, ontology_id)
        props_report = _build_section(
            ref_props,
            extracted_props,
            threshold=match_threshold,
        )
        payload["object_properties"] = props_report
        summary_ref += props_report["summary"]["reference_count"]
        summary_ext += props_report["summary"]["extracted_count"]
        summary_matched += props_report["summary"]["matched_count"]

    recall = summary_matched / summary_ref if summary_ref > 0 else 0.0
    precision = summary_matched / summary_ext if summary_ext > 0 else 0.0
    payload["summary"] = {
        "reference_count": summary_ref,
        "extracted_count": summary_ext,
        "matched_count": summary_matched,
        "recall": round(recall, 4),
        "precision": round(precision, 4),
        "f1": round(_f1(precision, recall), 4),
    }
    log.info(
        "computed quality recall",
        extra={
            "ontology_id": ontology_id,
            "reference_count": summary_ref,
            "extracted_count": summary_ext,
            "matched_count": summary_matched,
        },
    )
    return payload


def _build_section(
    reference: list[_RefConcept],
    extracted: list[dict[str, Any]],
    *,
    threshold: float,
) -> dict[str, Any]:
    matches, missed, false_positives = _greedy_match(
        reference,
        extracted,
        threshold=threshold,
    )
    matched_count = len(matches)
    return {
        "summary": {
            "reference_count": len(reference),
            "extracted_count": len(extracted),
            "matched_count": matched_count,
        },
        "matched": [
            {
                "reference_uri": m.reference_uri,
                "reference_label": m.reference_label,
                "extracted_uri": m.extracted_uri,
                "extracted_label": m.extracted_label,
                "extracted_key": m.extracted_key,
                "similarity": m.similarity,
            }
            for m in matches
        ],
        "missed": [
            {"reference_uri": ref.uri, "reference_label": ref.label}
            for ref in missed
        ],
        "false_positives": [
            {
                "extracted_uri": row.get("uri"),
                "extracted_label": row.get("label"),
                "extracted_key": row.get("_key"),
            }
            for row in false_positives
        ],
    }


__all__ = [
    "compute_recall",
    "label_similarity",
    "normalise_label",
    "parse_reference_ontology",
]
