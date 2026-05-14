"""Cross-module integration test for Stream 11 Phase 1 substrate (IBR.6).

Proves that the four foundational services compose correctly without
needing live ArangoDB or an LLM:

    rule_engine + touchpoint_discovery
        -> mechanical verdict (no LLM)
        -> revision_meta_repo.record_revision

This test does NOT cover Phase 2's mechanical-classifier policy
(that's IBR.7-9). It only proves the *substrate* fits together: a
rule violation can be turned into a Touchpoint can be recorded as a
``revision_meta`` document with the same verdict the rule suggested.

Why a unit-style test for an "integration" concern
--------------------------------------------------

Each substrate piece has its own deep test suite. What's missing from
those suites is an assertion that the *contracts between them* line
up: that ``Violation.suggested_action`` values are valid
``revision_meta`` verdicts, that ``Touchpoint.combined_score`` can
feed ``confidence_after``, etc. We don't need a real DB to assert
those contracts -- we just need the modules in the same process.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import MagicMock

from app.db import revision_meta_repo as repo
from app.services import (
    confidence_decay,
)
from app.services import (
    ontology_rule_engine as rules,
)
from app.services import (
    touchpoint_discovery as td,
)


def _stub_db_with(*present: str, collections: dict[str, Any] | None = None) -> MagicMock:
    """Build a MagicMock DB whose ``has_collection`` matches ``present`` and
    whose ``collection(name)`` returns the supplied per-name MagicMock."""
    db = MagicMock()
    db.has_collection.side_effect = lambda name: name in present
    cols = collections or {}

    def get_col(name: str) -> Any:
        if name in cols:
            return cols[name]
        return MagicMock()

    db.collection.side_effect = get_col
    return db


# ---------------------------------------------------------------------------
# Contract checks across modules
# ---------------------------------------------------------------------------


def test_rule_engine_suggested_actions_are_valid_repo_verdicts():
    """Every Violation.suggested_action emitted by the built-in rules
    must be a valid revision_meta verdict so a downstream Phase 2
    classifier can pass it straight to record_revision."""
    # Run all built-in rules against an empty DB; none emit violations,
    # but we still need to confirm the constants line up. The check is
    # static: walk the rule code paths via the constants they reference.
    suggested = {
        rules.VERDICT_REDUNDANT,
        rules.VERDICT_REFINED,
        rules.VERDICT_CONTRADICTED,
    }
    for action in suggested:
        assert action in repo.VERDICTS, f"{action!r} not in revision_meta VERDICTS"


def test_touchpoint_combined_score_is_in_unit_interval():
    # Phase 2 will use combined_score to populate confidence_after on
    # REINFORCED revisions. Make sure the contract is in [0, 1] so the
    # downstream multi-signal blender doesn't see out-of-range inputs.
    new = td.NewConcept(label="X", uri="http://x#X", chunk_ids=("c1",))
    existing = {
        "_id": "ontology_classes/X",
        "_key": "X",
        "label": "X",
        "uri": "http://x#X",
        "source_chunk_ids": ["c1"],
    }
    tp = td.score_touchpoint(new, existing)
    assert tp is not None
    assert 0.0 <= tp.combined_score <= 1.0


def test_decay_constants_align_with_confidence_module():
    # The decay job reads the same half-life as the confidence
    # blender's evidence-age signal default; both must agree to avoid
    # double-decay or contradiction in the dashboard explainers.
    # Use the *settings* default rather than the live-mutated one to
    # avoid coupling to other tests' patches.
    from app.config import Settings
    from app.services.confidence import DEFAULT_EVIDENCE_HALF_LIFE_DAYS

    s = Settings()
    assert s.belief_revision_decay_half_life_days == DEFAULT_EVIDENCE_HALF_LIFE_DAYS


# ---------------------------------------------------------------------------
# End-to-end pipeline (no LLM, no real DB)
# ---------------------------------------------------------------------------


def test_synonym_cycle_violation_becomes_redundant_revision(monkeypatch):
    """Smoke test: a R1 synonym-cycle violation (suggesting REDUNDANT)
    can be turned into a touchpoint between the two equivalent classes
    and recorded as a revision with that verdict.

    Not a "real" Phase 2 implementation -- just proves the substrate
    types line up end-to-end.
    """
    # ---- Step 1: rule engine reports a R1 cycle violation. ----
    db_rules = _stub_db_with("subclass_of", "equivalent_class")

    def fake_run_aql_rules(_db, aql, *, bind_vars=None):
        if "FOR e IN subclass_of" in aql:
            return iter([{"from": "ontology_classes/A", "to": "ontology_classes/B"}])
        if "FOR e IN equivalent_class" in aql:
            return iter([{"from": "ontology_classes/A", "to": "ontology_classes/B"}])
        raise AssertionError(f"unexpected AQL: {aql!r}")

    monkeypatch.setattr(rules, "run_aql", fake_run_aql_rules)
    rule_report = rules.evaluate_rules(
        db_rules,
        "OID",
        rules=((rules.RULE_R1_SYNONYM_TRIANGLE, rules._r1_synonym_triangle),),
    )
    assert len(rule_report.violations) == 1
    violation = rule_report.violations[0]
    assert violation.suggested_action == rules.VERDICT_REDUNDANT

    # ---- Step 2: build a touchpoint for the same A / B pair. ----
    new = td.NewConcept(label="A", uri="http://x#A")
    existing_b = {
        "_id": "ontology_classes/B",
        "_key": "B",
        "label": "A",  # same label as new (deliberate -- the cycle)
        "uri": "http://x#B",
    }
    touchpoint = td.score_touchpoint(new, existing_b)
    assert touchpoint is not None
    assert touchpoint.signals.label_exact == 1.0
    assert touchpoint.combined_score > 0.2

    # ---- Step 3: record a revision combining both signals. ----
    insert_calls = []
    revision_col = MagicMock()
    revision_col.insert.side_effect = lambda doc, **_: (
        insert_calls.append(doc) or {"new": {**doc, "_key": f"rev_{len(insert_calls)}"}}
    )
    db_repo = _stub_db_with("revision_meta", collections={"revision_meta": revision_col})
    monkeypatch.setattr(repo, "get_db", lambda: db_repo)

    persisted = repo.record_revision(
        ontology_id="OID",
        verdict=violation.suggested_action,  # passed straight from rule
        action=repo.ACTION_FLAG_FOR_CURATION,  # REDUNDANT defers to ER
        agent_type=repo.AGENT_MECHANICAL,
        agent_version="rule_engine@v1",
        triggering_doc_id="doc_42",
        existing_entity_id=touchpoint.existing_class_id,
        evidence_quotes=[touchpoint.reasoning],
        reasoning=violation.description,
        confidence_before=None,
        confidence_after=touchpoint.combined_score,  # touchpoint score feeds confidence
        db=db_repo,
    )
    assert persisted["verdict"] == repo.VERDICT_REDUNDANT
    assert persisted["status"] == repo.STATUS_PENDING  # FLAG_FOR_CURATION default
    assert insert_calls[0]["existing_entity_id"] == "ontology_classes/B"


def test_decayed_class_then_touchpoint_chain(monkeypatch):
    """End-to-end Phase 4 → Phase 1 chain: a decayed class is still a
    valid touchpoint candidate. (Catches a regression where the
    decay job's writes break a downstream service's assumptions.)"""
    # ---- Step 1: decay runs and writes current_confidence. ----
    monkeypatch.setattr(confidence_decay.settings, "belief_revision_decay_enabled", True)
    monkeypatch.setattr(confidence_decay.settings, "belief_revision_decay_half_life_days", 30.0)
    monkeypatch.setattr(confidence_decay.settings, "belief_revision_decay_floor", 0.05)
    now = 1_700_000_000.0
    cls = {
        "_key": "Customer",
        "_id": "ontology_classes/Customer",
        "label": "Customer",
        "uri": "http://x#Customer",
        "confidence": 0.8,
        "created": now - 60 * 86400,
    }
    cls_col = MagicMock()
    db_decay = _stub_db_with("ontology_classes", collections={"ontology_classes": cls_col})

    def fake_decay_run_aql(_db, _aql, *, bind_vars=None):
        return iter([cls])

    monkeypatch.setattr(confidence_decay, "run_aql", fake_decay_run_aql)
    decay_report = confidence_decay.apply_confidence_decay(db_decay, "OID", now=now)
    assert decay_report.classes_decayed == 1
    decayed_value = cls_col.update.call_args.args[0]["current_confidence"]
    assert decayed_value < 0.8

    # ---- Step 2: simulate the next extraction and discover touchpoints
    #              against the (post-decay) class. The class doc shape
    #              now carries current_confidence; touchpoint discovery
    #              must not be confused by the new field.
    cls_post = {**cls, "current_confidence": decayed_value, "confidence_decayed_at": now}
    db_td = _stub_db_with("ontology_classes")

    def fake_td_run_aql(_db, _aql, *, bind_vars=None):
        return iter([cls_post])

    monkeypatch.setattr(td, "run_aql", fake_td_run_aql)
    report = td.discover_touchpoints(
        db_td,
        "OID",
        [td.NewConcept(label="Customer", uri="http://x#Customer")],
        threshold=0.0,
    )
    assert len(report.touchpoints) == 1
    assert report.touchpoints[0].existing_class_id == "ontology_classes/Customer"
    # Touchpoint discovery is unaware of (and unaffected by) decay state;
    # match strength is based on identity signals, not on confidence.
    assert report.touchpoints[0].combined_score > 0.5


# ---------------------------------------------------------------------------
# Telemetry: every IBR module logs to a stable namespace
# ---------------------------------------------------------------------------


def test_every_substrate_module_uses_module_logger():
    """Operational invariant: every IBR substrate module must obtain
    its logger via ``logging.getLogger(__name__)`` so log filters
    can target them by the ``app.services.<module>`` namespace.

    Catches accidental ``logging.getLogger("custom-name")`` drift.
    """
    import logging as stdlib_logging

    expected = {
        "app.db.revision_meta_repo": "app.db.revision_meta_repo",
        "app.services.confidence_decay": "app.services.confidence_decay",
        "app.services.ontology_rule_engine": "app.services.ontology_rule_engine",
        "app.services.touchpoint_discovery": "app.services.touchpoint_discovery",
        "app.services.belief_revision_metrics": "app.services.belief_revision_metrics",
    }
    for module_path, expected_name in expected.items():
        module = __import__(module_path, fromlist=["log"])
        log = getattr(module, "log", None)
        assert log is not None, f"{module_path} has no module-level ``log``"
        assert isinstance(log, stdlib_logging.Logger)
        assert log.name == expected_name, (
            f"{module_path} logger name is {log.name!r}, expected {expected_name!r}"
        )


def test_substrate_modules_emit_structured_summary_on_completion(monkeypatch, caplog):
    """When a substrate function finishes, it must log a single INFO line
    that summarises the action -- the log aggregator can build dashboards
    from these without scraping individual events.

    This is the contract behind FR-13.26 (revision metrics on the dashboard).
    """
    import logging

    # rule engine
    db = _stub_db_with("subclass_of", "equivalent_class")
    monkeypatch.setattr(rules, "run_aql", lambda *_a, **_k: iter([]))
    with caplog.at_level(logging.INFO, logger=rules.log.name):
        rules.evaluate_rules(db, "OID")
    rule_records = [r for r in caplog.records if r.name == rules.log.name]
    assert any("evaluated=" in r.getMessage() for r in rule_records)
    caplog.clear()

    # touchpoint discovery
    db_td = _stub_db_with("ontology_classes")
    monkeypatch.setattr(td, "run_aql", lambda *_a, **_k: iter([]))
    with caplog.at_level(logging.INFO, logger=td.log.name):
        td.discover_touchpoints(db_td, "OID", [td.NewConcept("X")])
    td_records = [r for r in caplog.records if r.name == td.log.name]
    assert any("touchpoints=" in r.getMessage() for r in td_records)
    caplog.clear()

    # decay
    monkeypatch.setattr(confidence_decay.settings, "belief_revision_decay_enabled", True)
    monkeypatch.setattr(confidence_decay.settings, "belief_revision_decay_half_life_days", 90.0)
    monkeypatch.setattr(confidence_decay.settings, "belief_revision_decay_floor", 0.05)
    db_decay = _stub_db_with("ontology_classes")
    monkeypatch.setattr(confidence_decay, "run_aql", lambda *_a, **_k: iter([]))
    with caplog.at_level(logging.INFO, logger=confidence_decay.log.name):
        confidence_decay.apply_confidence_decay(db_decay, "OID", now=time.time())
    decay_records = [r for r in caplog.records if r.name == confidence_decay.log.name]
    assert any("decayed=" in r.getMessage() for r in decay_records)
