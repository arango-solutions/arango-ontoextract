"""Unit tests for ``app.services.edge_confidence``.

Both helpers are pure functions over edge/property documents -- exercised
directly with hand-built dicts, no fixtures or DB needed.
"""

from __future__ import annotations

import math

import pytest

from app.services.edge_confidence import (
    compute_edge_confidence,
    enrich_rdfs_range_class_edges,
)


class TestExplicitConfidenceWins:
    def test_explicit_top_level_confidence_used_verbatim(self):
        edge = {"confidence": 0.42, "evidence": [{"evidence_confidence": 0.9}]}
        assert compute_edge_confidence(edge) == pytest.approx(0.42)

    def test_explicit_zero_is_respected(self):
        edge = {"confidence": 0.0, "evidence": [{"evidence_confidence": 1.0}]}
        assert compute_edge_confidence(edge) == 0.0

    def test_explicit_above_one_is_clamped(self):
        edge = {"confidence": 1.5}
        assert compute_edge_confidence(edge) == 1.0

    def test_negative_explicit_falls_through_to_evidence(self):
        edge = {"confidence": -0.1, "evidence": [{"evidence_confidence": 0.7}]}
        assert compute_edge_confidence(edge) == pytest.approx(0.7)


class TestEvidenceMean:
    def test_single_evidence(self):
        edge = {"evidence": [{"evidence_confidence": 0.8}]}
        assert compute_edge_confidence(edge) == pytest.approx(0.8)

    def test_multi_evidence_returns_mean(self):
        edge = {
            "evidence": [
                {"evidence_confidence": 1.0},
                {"evidence_confidence": 0.5},
                {"evidence_confidence": 0.0},
            ]
        }
        assert compute_edge_confidence(edge) == pytest.approx(0.5)

    def test_evidence_above_one_is_clamped_per_item(self):
        edge = {
            "evidence": [
                {"evidence_confidence": 1.5},
                {"evidence_confidence": 0.5},
            ]
        }
        assert compute_edge_confidence(edge) == pytest.approx(0.75)

    def test_evidence_below_zero_is_clamped_per_item(self):
        edge = {
            "evidence": [
                {"evidence_confidence": -0.5},
                {"evidence_confidence": 0.6},
            ]
        }
        assert compute_edge_confidence(edge) == pytest.approx(0.3)


class TestMissingOrInvalid:
    def test_no_confidence_no_evidence_returns_none(self):
        assert compute_edge_confidence({}) is None

    def test_evidence_empty_list_returns_none(self):
        assert compute_edge_confidence({"evidence": []}) is None

    def test_evidence_not_a_list_returns_none(self):
        assert compute_edge_confidence({"evidence": "not-a-list"}) is None

    def test_evidence_items_without_evidence_confidence_skipped(self):
        edge = {
            "evidence": [
                {"source_chunk_ids": ["c1"]},
                {"evidence_confidence": 0.6},
            ]
        }
        assert compute_edge_confidence(edge) == pytest.approx(0.6)

    def test_all_invalid_evidence_returns_none(self):
        edge = {
            "evidence": [
                {"evidence_confidence": "high"},
                {"evidence_confidence": None},
                {"evidence_confidence": math.nan},
                {"evidence_confidence": True},  # bool must be rejected
            ]
        }
        assert compute_edge_confidence(edge) is None

    def test_non_numeric_explicit_falls_through_to_evidence(self):
        edge = {"confidence": "n/a", "evidence": [{"evidence_confidence": 0.4}]}
        assert compute_edge_confidence(edge) == pytest.approx(0.4)

    def test_bool_explicit_falls_through_to_evidence(self):
        edge = {"confidence": True, "evidence": [{"evidence_confidence": 0.4}]}
        assert compute_edge_confidence(edge) == pytest.approx(0.4)

    def test_non_dict_evidence_items_skipped(self):
        edge = {
            "evidence": [
                "string-evidence",
                None,
                {"evidence_confidence": 0.9},
            ]
        }
        assert compute_edge_confidence(edge) == pytest.approx(0.9)


class TestEnrichRdfsRangeClassEdges:
    """Verify the rdfs_range_class -> ontology_object_properties join.

    Without this join the canvas falls back to the structural label
    ``owl:ObjectProperty`` and shows no confidence for property-derived edges
    (e.g. CustomerRiskProfile -> KYCAssessment in Financial Services Domain).
    """

    def _props(self, **rest):
        return {
            "_id": "ontology_object_properties/KYCAssessment_generates_risk_profile",
            "_key": "KYCAssessment_generates_risk_profile",
            "label": "generates Risk Profile",
            "description": "Generates a risk profile that categorizes the customer.",
            "uri": "http://example.org/local#generatesRiskProfile",
            "confidence": 0.9,
            "evidence": [
                {"evidence_confidence": 0.9, "source_chunk_ids": ["c1"]}
            ],
            **rest,
        }

    def _edge(self, **overrides):
        edge = {
            "_key": "rdfs_range_class_KYC_to_CRP",
            "_id": "rdfs_range_class/rdfs_range_class_KYC_to_CRP",
            "_from": "ontology_object_properties/KYCAssessment_generates_risk_profile",
            "_to": "ontology_classes/CustomerRiskProfile",
            "edge_type": "rdfs_range_class",
            "ontology_id": "142130089",
        }
        edge.update(overrides)
        return edge

    def test_lifts_label_confidence_evidence_and_description(self):
        prop = self._props()
        edge = self._edge()
        edges = [edge]

        enrich_rdfs_range_class_edges(edges, {prop["_id"]: prop})

        assert edge["label"] == "generates Risk Profile"
        assert edge["confidence"] == 0.9
        assert edge["description"].startswith("Generates a risk profile")
        assert edge["uri"] == "http://example.org/local#generatesRiskProfile"
        assert isinstance(edge["evidence"], list) and len(edge["evidence"]) == 1
        assert edge["evidence"][0]["evidence_confidence"] == 0.9

    def test_compute_edge_confidence_now_works_after_enrichment(self):
        # End-to-end: enrichment + scoring is the actual pipeline used by the API.
        prop = self._props()
        edge = self._edge()
        edges = [edge]
        enrich_rdfs_range_class_edges(edges, {prop["_id"]: prop})
        assert compute_edge_confidence(edge) == pytest.approx(0.9)

    def test_preserves_edge_identity_fields(self):
        prop = self._props()
        edge = self._edge()
        original_key = edge["_key"]
        original_from = edge["_from"]
        original_to = edge["_to"]
        original_edge_type = edge["edge_type"]
        original_ontology_id = edge["ontology_id"]

        enrich_rdfs_range_class_edges([edge], {prop["_id"]: prop})

        assert edge["_key"] == original_key
        assert edge["_from"] == original_from
        assert edge["_to"] == original_to
        assert edge["edge_type"] == original_edge_type
        assert edge["ontology_id"] == original_ontology_id

    def test_does_not_overwrite_existing_non_empty_label(self):
        # Forward-compat: if a future writer already populated edge.label,
        # respect it.
        prop = self._props()
        edge = self._edge(label="existing custom label")
        enrich_rdfs_range_class_edges([edge], {prop["_id"]: prop})
        assert edge["label"] == "existing custom label"

    def test_overwrites_empty_string_label(self):
        prop = self._props()
        edge = self._edge(label="")
        enrich_rdfs_range_class_edges([edge], {prop["_id"]: prop})
        assert edge["label"] == "generates Risk Profile"

    def test_overwrites_none_label(self):
        prop = self._props()
        edge = self._edge(label=None)
        enrich_rdfs_range_class_edges([edge], {prop["_id"]: prop})
        assert edge["label"] == "generates Risk Profile"

    def test_skips_non_rdfs_range_class_edges(self):
        prop = self._props()
        edge = self._edge(edge_type="subclass_of")
        enrich_rdfs_range_class_edges([edge], {prop["_id"]: prop})
        assert "label" not in edge
        assert "confidence" not in edge

    def test_skips_when_property_not_in_map(self):
        edge = self._edge()
        enrich_rdfs_range_class_edges([edge], {})
        assert "label" not in edge
        assert "confidence" not in edge

    def test_skips_when_from_is_missing_or_non_string(self):
        prop = self._props()
        edge_no_from = self._edge()
        del edge_no_from["_from"]
        edge_int_from = self._edge(_from=123)

        enrich_rdfs_range_class_edges(
            [edge_no_from, edge_int_from], {prop["_id"]: prop}
        )

        assert "label" not in edge_no_from
        assert "label" not in edge_int_from

    def test_only_lifts_fields_present_on_property(self):
        # Property record missing description -- edge shouldn't gain a key for it.
        prop = self._props()
        del prop["description"]
        edge = self._edge()
        enrich_rdfs_range_class_edges([edge], {prop["_id"]: prop})
        assert "description" not in edge
        assert edge["label"] == "generates Risk Profile"

    def test_handles_multiple_edges_in_one_call(self):
        prop_a = self._props(
            _id="ontology_object_properties/A",
            _key="A",
            label="alpha",
            confidence=0.8,
        )
        prop_b = self._props(
            _id="ontology_object_properties/B",
            _key="B",
            label="beta",
            confidence=0.6,
        )
        edge_a = self._edge(
            _key="ea", _from="ontology_object_properties/A"
        )
        edge_b = self._edge(
            _key="eb", _from="ontology_object_properties/B"
        )
        enrich_rdfs_range_class_edges(
            [edge_a, edge_b], {prop_a["_id"]: prop_a, prop_b["_id"]: prop_b}
        )
        assert edge_a["label"] == "alpha" and edge_a["confidence"] == 0.8
        assert edge_b["label"] == "beta" and edge_b["confidence"] == 0.6
