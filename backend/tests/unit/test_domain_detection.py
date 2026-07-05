"""Unit tests for the Stream 16 domain-detection helpers (DD.2 / DD.3).

Covers ``detected_domains_from_segments``, ``dominant_domain``,
``build_chunk_domain_map``, ``assign_domain_tags`` (Pydantic + dict paths),
and ``build_multi_domain_warning``.
"""

from __future__ import annotations

from app.models.ontology import ExtractedClass, SourceEvidence
from app.services.domain_detection import (
    assign_domain_tags,
    build_chunk_domain_map,
    build_multi_domain_warning,
    detected_domains_from_segments,
    domain_chunk_counts,
    dominant_domain,
)

_TWO_DOMAINS = [
    {"domain": "Finance", "chunk_ids": ["c1", "c2"], "confidence": 0.9},
    {"domain": "HR", "chunk_ids": ["c3"], "confidence": 0.8},
]


def _cls(uri: str, chunk_ids: list[str]) -> ExtractedClass:
    return ExtractedClass(
        uri=uri,
        label=uri.split("#")[-1],
        description="d",
        confidence=0.9,
        evidence=[SourceEvidence(source_chunk_ids=chunk_ids)] if chunk_ids else [],
    )


class TestDetectedDomains:
    def test_two_domains_sorted(self):
        assert detected_domains_from_segments(_TWO_DOMAINS, 0.6) == ["Finance", "HR"]

    def test_single_domain(self):
        segs = [{"domain": "Finance", "chunk_ids": ["c1", "c2"], "confidence": 0.95}]
        assert detected_domains_from_segments(segs, 0.6) == ["Finance"]

    def test_low_confidence_second_domain_folds_out(self):
        # HR at 0.5 is below the 0.6 bar -> only Finance qualifies.
        assert detected_domains_from_segments(_TWO_DOMAINS, 0.85) == ["Finance"]

    def test_all_below_threshold_collapses_to_dominant(self):
        segs = [
            {"domain": "Finance", "chunk_ids": ["c1", "c2"], "confidence": 0.2},
            {"domain": "HR", "chunk_ids": ["c3"], "confidence": 0.2},
        ]
        # Nothing clears the bar -> collapse to the single dominant domain.
        assert detected_domains_from_segments(segs, 0.6) == ["Finance"]

    def test_empty_segments(self):
        assert detected_domains_from_segments([], 0.6) == []


class TestDominantDomain:
    def test_most_chunks_wins(self):
        assert dominant_domain(_TWO_DOMAINS) == "Finance"

    def test_candidates_filter(self):
        assert dominant_domain(_TWO_DOMAINS, candidates=["HR"]) == "HR"

    def test_none_when_empty(self):
        assert dominant_domain([]) is None

    def test_domain_chunk_counts(self):
        assert domain_chunk_counts(_TWO_DOMAINS) == {"Finance": 2, "HR": 1}


class TestChunkDomainMap:
    def test_maps_each_chunk(self):
        mapping = build_chunk_domain_map(_TWO_DOMAINS, {"Finance", "HR"}, "Finance")
        assert mapping == {"c1": "Finance", "c2": "Finance", "c3": "HR"}

    def test_disallowed_domain_remaps_to_fallback(self):
        mapping = build_chunk_domain_map(_TWO_DOMAINS, {"Finance"}, "Finance")
        assert mapping["c3"] == "Finance"


class TestAssignDomainTags:
    def test_tags_by_majority_of_evidence(self):
        classes = [_cls("http://e#A", ["c1", "c2"]), _cls("http://e#B", ["c3"])]
        counts = assign_domain_tags(classes, _TWO_DOMAINS, min_confidence=0.6)
        assert classes[0].domain_tag == "Finance"
        assert classes[1].domain_tag == "HR"
        assert counts == {"Finance": 1, "HR": 1}

    def test_class_without_evidence_falls_back_to_dominant(self):
        classes = [_cls("http://e#Z", [])]
        assign_domain_tags(classes, _TWO_DOMAINS, min_confidence=0.6)
        assert classes[0].domain_tag == "Finance"

    def test_dict_classes_supported(self):
        classes = [{"evidence": [{"source_chunk_ids": ["c3"]}], "parent_evidence": []}]
        assign_domain_tags(classes, _TWO_DOMAINS, min_confidence=0.6)
        assert classes[0]["domain_tag"] == "HR"

    def test_no_detected_domains_is_noop(self):
        classes = [_cls("http://e#A", ["c1"])]
        counts = assign_domain_tags(classes, [], min_confidence=0.6)
        assert counts == {}
        assert classes[0].domain_tag is None


class TestMultiDomainWarning:
    def test_warning_for_multiple_domains(self):
        warning = build_multi_domain_warning(
            detected_domains=["Finance", "HR"],
            segments=_TWO_DOMAINS,
            class_domain_counts={"Finance": 2, "HR": 1},
        )
        assert warning is not None
        assert warning["type"] == "multi_domain"
        assert warning["severity"] == "warning"
        assert warning["detected_domains"] == ["Finance", "HR"]
        assert warning["domain_chunk_counts"] == {"Finance": 2, "HR": 1}
        assert warning["domain_class_counts"] == {"Finance": 2, "HR": 1}

    def test_no_warning_for_single_domain(self):
        assert (
            build_multi_domain_warning(detected_domains=["Finance"], segments=_TWO_DOMAINS) is None
        )

    def test_no_warning_for_empty(self):
        assert build_multi_domain_warning(detected_domains=[], segments=[]) is None
