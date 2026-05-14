"""Unit tests for the quality_recall service (Q.4).

The matching algorithm is deterministic given the inputs, so all tests
use small synthetic reference TTL strings and a mocked Arango database.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services import quality_recall as svc

# ---------------------------------------------------------------------------
# Label normalisation + similarity
# ---------------------------------------------------------------------------


class TestNormaliseLabel:
    def test_camel_case_split(self):
        assert svc.normalise_label("MortgageLoan") == "mortgage loan"

    def test_punctuation_and_whitespace_stripped(self):
        assert svc.normalise_label("  Mortgage-Loan!  ") == "mortgage loan"

    def test_pluralisation_removed(self):
        assert svc.normalise_label("Accounts") == "account"
        assert svc.normalise_label("Companies") == "company"
        assert svc.normalise_label("Boxes") == "box"

    def test_handles_acronyms(self):
        # "URI" should not split into 'u r i'; it stays as one token.
        assert svc.normalise_label("URIRef") == "uri ref"

    def test_empty_inputs(self):
        assert svc.normalise_label("") == ""
        assert svc.normalise_label(None) == ""


class TestLabelSimilarity:
    def test_exact_after_normalisation(self):
        assert svc.label_similarity("Person", "person") == 1.0
        assert svc.label_similarity("MortgageLoan", "mortgage_loan") == 1.0

    def test_close_match_returns_high_score(self):
        assert svc.label_similarity("Person", "Persons") == 1.0  # plural ≈ singular
        assert svc.label_similarity("Mortgage Loan", "MortgageLoans") == 1.0

    def test_unrelated_returns_low_score(self):
        assert svc.label_similarity("Person", "Account") < 0.5

    def test_empty_returns_zero(self):
        assert svc.label_similarity("", "Person") == 0.0
        assert svc.label_similarity("Person", None) == 0.0


# ---------------------------------------------------------------------------
# Reference parsing
# ---------------------------------------------------------------------------


_TURTLE_TAXONOMY = """
@prefix : <http://example.org/ref#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .

:Person a owl:Class ; rdfs:label "Person" .
:Account a owl:Class ; rdfs:label "Account" .
:CheckingAccount a owl:Class ; rdfs:label "Checking Account" ;
    rdfs:subClassOf :Account .
:owns a owl:ObjectProperty ; rdfs:label "owns" .
"""


class TestParseReferenceOntology:
    def test_extracts_classes_and_object_properties(self):
        concepts = svc.parse_reference_ontology(_TURTLE_TAXONOMY)
        kinds = {c.kind for c in concepts}
        assert kinds == {"class", "object_property"}
        labels = sorted(c.label for c in concepts)
        assert labels == ["Account", "Checking Account", "Person", "owns"]

    def test_falls_back_to_local_name_when_no_label(self):
        ttl = """
        @prefix : <http://example.org/ref#> .
        @prefix owl: <http://www.w3.org/2002/07/owl#> .
        :Vehicle a owl:Class .
        """
        concepts = svc.parse_reference_ontology(ttl)
        assert any(c.label == "Vehicle" for c in concepts)

    def test_skips_owl_built_ins(self):
        ttl = (
            _TURTLE_TAXONOMY
            + """
        owl:Thing a owl:Class .
        """
        )
        concepts = svc.parse_reference_ontology(ttl)
        assert all("owl#Thing" not in c.uri for c in concepts)

    def test_invalid_ttl_raises_value_error(self):
        with pytest.raises(ValueError, match="Failed to parse"):
            svc.parse_reference_ontology("this is not turtle <<<", rdf_format="turtle")


# ---------------------------------------------------------------------------
# Recall computation end-to-end
# ---------------------------------------------------------------------------


def _mock_db_with_classes(classes, object_properties=None):
    db = MagicMock()
    db.has_collection.side_effect = lambda name: True

    def fake_run_aql(_db, query, *, bind_vars):
        if "ontology_classes" in query:
            return iter(classes)
        if "ontology_object_properties" in query:
            return iter(object_properties or [])
        return iter([])

    return db, fake_run_aql


class TestComputeRecall:
    def test_perfect_match_returns_recall_one(self):
        extracted_classes = [
            {"uri": "http://x#Person", "label": "Person", "_key": "p1"},
            {"uri": "http://x#Account", "label": "Account", "_key": "a1"},
            {
                "uri": "http://x#CheckingAccount",
                "label": "Checking Account",
                "_key": "c1",
            },
        ]
        extracted_props = [
            {"uri": "http://x#owns", "label": "owns", "_key": "owns1"},
        ]
        db, run = _mock_db_with_classes(extracted_classes, extracted_props)

        with patch.object(svc, "run_aql", side_effect=run):
            report = svc.compute_recall(
                db,
                ontology_id="onto_1",
                reference_content=_TURTLE_TAXONOMY,
            )

        assert report["summary"]["recall"] == 1.0
        assert report["summary"]["precision"] == 1.0
        assert report["summary"]["f1"] == 1.0
        assert report["classes"]["summary"]["matched_count"] == 3
        assert report["object_properties"]["summary"]["matched_count"] == 1
        assert report["classes"]["missed"] == []
        assert report["classes"]["false_positives"] == []

    def test_partial_match_reports_missed_and_false_positives(self):
        # Reference has 3 classes; we extract 2 of them plus one extra.
        extracted_classes = [
            {"uri": "http://x#Person", "label": "Person", "_key": "p1"},
            {"uri": "http://x#Account", "label": "Account", "_key": "a1"},
            {"uri": "http://x#Vehicle", "label": "Vehicle", "_key": "v1"},
        ]
        db, run = _mock_db_with_classes(extracted_classes)

        with patch.object(svc, "run_aql", side_effect=run):
            report = svc.compute_recall(
                db,
                ontology_id="onto_1",
                reference_content=_TURTLE_TAXONOMY,
                include_object_properties=False,
            )

        cls = report["classes"]
        assert cls["summary"]["reference_count"] == 3
        assert cls["summary"]["matched_count"] == 2
        assert cls["summary"]["extracted_count"] == 3
        missed_labels = sorted(m["reference_label"] for m in cls["missed"])
        assert missed_labels == ["Checking Account"]
        fp_labels = sorted(f["extracted_label"] for f in cls["false_positives"])
        assert fp_labels == ["Vehicle"]
        # 2 / 3 ≈ 0.6667 recall, 2 / 3 ≈ 0.6667 precision
        assert report["summary"]["recall"] == pytest.approx(0.6667, abs=1e-3)
        assert report["summary"]["precision"] == pytest.approx(0.6667, abs=1e-3)

    def test_fuzzy_matching_handles_capitalisation_and_spaces(self):
        """Plural/case/space differences must still match at default threshold."""
        extracted_classes = [
            {"uri": "http://x#Persons", "label": "Persons", "_key": "p1"},
            {"uri": "http://x#Account", "label": "ACCOUNT", "_key": "a1"},
            {"uri": "http://x#chk", "label": "checking_accounts", "_key": "c1"},
        ]
        db, run = _mock_db_with_classes(extracted_classes)

        with patch.object(svc, "run_aql", side_effect=run):
            report = svc.compute_recall(
                db,
                ontology_id="onto_1",
                reference_content=_TURTLE_TAXONOMY,
                include_object_properties=False,
            )
        assert report["classes"]["summary"]["matched_count"] == 3
        assert report["summary"]["recall"] == 1.0

    def test_threshold_can_make_recall_strict(self):
        extracted_classes = [
            # Single token that only loosely matches "Checking Account".
            {"uri": "http://x#Acct", "label": "Acct", "_key": "a1"},
        ]
        db, run = _mock_db_with_classes(extracted_classes)
        with patch.object(svc, "run_aql", side_effect=run):
            strict = svc.compute_recall(
                db,
                ontology_id="onto_1",
                reference_content=_TURTLE_TAXONOMY,
                match_threshold=0.95,
                include_object_properties=False,
            )
        assert strict["classes"]["summary"]["matched_count"] == 0

    def test_invalid_threshold_raises(self):
        db = MagicMock()
        with pytest.raises(ValueError):
            svc.compute_recall(
                db,
                ontology_id="onto_1",
                reference_content=_TURTLE_TAXONOMY,
                match_threshold=1.5,
            )

    def test_no_extracted_data_returns_zero_recall(self):
        db, run = _mock_db_with_classes([])
        with patch.object(svc, "run_aql", side_effect=run):
            report = svc.compute_recall(
                db,
                ontology_id="onto_empty",
                reference_content=_TURTLE_TAXONOMY,
                include_object_properties=False,
            )
        assert report["summary"]["recall"] == 0.0
        assert report["summary"]["precision"] == 0.0
        assert report["summary"]["f1"] == 0.0
        # Missed concepts list should equal the full reference.
        assert len(report["classes"]["missed"]) == 3

    def test_reference_with_no_concepts_returns_zero_recall(self):
        """An empty reference should not blow up; recall is undefined so
        we report 0.0 (safer than NaN for downstream JSON serialisation)."""
        db, run = _mock_db_with_classes(
            [{"uri": "http://x#A", "label": "A", "_key": "a"}],
        )
        with patch.object(svc, "run_aql", side_effect=run):
            report = svc.compute_recall(
                db,
                ontology_id="onto_1",
                reference_content=(
                    "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n# no classes declared\n"
                ),
                include_object_properties=False,
            )
        assert report["summary"]["reference_count"] == 0
        assert report["summary"]["recall"] == 0.0
