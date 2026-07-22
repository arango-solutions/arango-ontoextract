"""A-box (instance) validation + hallucination control (Stream 21 / AB-PR5).

PRD §6.18 FR-18.7 (constraint validation) + FR-18.8 (hallucination control).

Built on the same rule-engine primitives as the T-box validator
(:mod:`app.services.ontology_rule_engine`) -- it reuses ``Violation`` /
``RuleEngineReport`` / the severity + verdict vocabulary -- but runs as a
*distinct instance-level pass* so it never perturbs the T-box consolidation run.
Every rule is self-contained: it checks for its prerequisite collections and
returns ``[]`` when they're missing, so the pass degrades gracefully on an
ontology that has no A-box yet.

Three rules:

* **Ungrounded individual** (FR-18.8): an individual none of whose provenance
  entries carries a ``char_span`` is not traceable to a source mention -- a
  hallucination candidate. Flagged (``UNCERTAIN``), never silently dropped.
* **Dangling type reference** (FR-18.8): an individual's ``rdf_type`` edge points
  at a class that does not exist (or is expired) in the T-box -- the extractor
  referenced a term that isn't in the ontology. Flagged as an error.
* **A-box cardinality** (FR-18.7): for each §6.14 cardinality restriction, count
  each individual's live outgoing assertions of the constrained property and flag
  individuals that fall below ``min`` or above ``max``. Violations are reported,
  not repaired -- curation decides.
"""

from __future__ import annotations

import logging
from typing import Any

from app.db.revision_meta_repo import VERDICT_CONTRADICTED, VERDICT_UNCERTAIN
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql
from app.services.ontology_rule_engine import (
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    RuleEngineReport,
    Violation,
)

log = logging.getLogger(__name__)

_INDIVIDUALS = "ontology_individuals"
_RDF_TYPE = "rdf_type"
_ASSERTION = "individual_assertion"
_CONSTRAINTS = "ontology_constraints"

RULE_ABOX_UNGROUNDED = "ABOX_ungrounded_individual"
RULE_ABOX_DANGLING_TYPE = "ABOX_dangling_type_reference"
RULE_ABOX_CARDINALITY = "ABOX_cardinality_violation"

_CARDINALITY_KINDS = (
    "minCardinality",
    "maxCardinality",
    "cardinality",
    "sh:minCount",
    "sh:maxCount",
)


def _ungrounded_individuals(db: Any, ontology_id: str) -> list[Violation]:
    """Individuals with no span-grounded provenance entry (FR-18.8)."""
    if not db.has_collection(_INDIVIDUALS):
        return []
    rows = run_aql(
        db,
        f"""
        FOR i IN {_INDIVIDUALS}
          FILTER i.ontology_id == @oid AND i.expired == @never
          LET grounded = LENGTH(
            FOR p IN (i.provenance == null ? [] : i.provenance)
              FILTER p.char_span != null
              RETURN 1
          )
          FILTER grounded == 0
          RETURN {{key: i._key, label: i.label}}
        """,
        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
    )
    return [
        Violation(
            rule_id=RULE_ABOX_UNGROUNDED,
            severity=SEVERITY_WARNING,
            entity_ids=(str(r.get("key")),),
            description=(
                f"Individual '{r.get('label') or r.get('key')}' has no span-grounded "
                f"provenance; it may be a hallucinated mention. Review or reject."
            ),
            suggested_action=VERDICT_UNCERTAIN,
        )
        for r in rows
    ]


def _dangling_type_references(db: Any, ontology_id: str) -> list[Violation]:
    """Individuals typed by a class absent/expired in the T-box (FR-18.8)."""
    if not (db.has_collection(_RDF_TYPE) and db.has_collection("ontology_classes")):
        return []
    rows = run_aql(
        db,
        f"""
        FOR e IN {_RDF_TYPE}
          FILTER e.ontology_id == @oid AND e.expired == @never
          LET cls = DOCUMENT(e._to)
          FILTER cls == null OR cls.expired != @never
          RETURN {{ind: e._from, cls: e._to}}
        """,
        bind_vars={"oid": ontology_id, "never": NEVER_EXPIRES},
    )
    return [
        Violation(
            rule_id=RULE_ABOX_DANGLING_TYPE,
            severity=SEVERITY_ERROR,
            entity_ids=(str(r.get("ind")), str(r.get("cls"))),
            description=(
                f"Individual '{r.get('ind')}' is typed by '{r.get('cls')}', which is not a "
                f"live class in the T-box; the extractor referenced a non-existent term."
            ),
            suggested_action=VERDICT_CONTRADICTED,
        )
        for r in rows
    ]


def _resolve_cardinality_bounds(db: Any, ontology_id: str) -> list[dict[str, Any]]:
    """Return ``[{class_id, predicate, min, max}]`` for §6.14 cardinality shapes.

    Resolves each constraint's ``property_uri`` to the property *label* (so it can
    be matched against an assertion's ``predicate``) via the object/data property
    collections.
    """
    bind = {"oid": ontology_id, "never": NEVER_EXPIRES}
    rows = list(
        run_aql(
            db,
            f"""
            FOR c IN {_CONSTRAINTS}
              FILTER c.ontology_id == @oid AND c.expired == @never
                AND c.restriction_type IN @kinds
              LET prop = FIRST(
                FOR p IN UNION(
                  (FOR x IN ontology_object_properties
                     FILTER x.ontology_id == @oid AND x.expired == @never
                       AND x.uri == c.property_uri RETURN x),
                  (FOR x IN ontology_properties
                     FILTER x.ontology_id == @oid AND x.expired == @never
                       AND x.uri == c.property_uri RETURN x)
                ) RETURN p
              )
              RETURN {{
                class_id: c.on_class, predicate: prop.label,
                rtype: c.restriction_type, value: c.restriction_value
              }}
            """,
            bind_vars={**bind, "kinds": list(_CARDINALITY_KINDS)},
        )
    )
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for r in rows:
        class_id, predicate = r.get("class_id"), r.get("predicate")
        value = r.get("value")
        if not (isinstance(class_id, str) and isinstance(predicate, str)):
            continue
        if not isinstance(value, int):
            continue
        slot = grouped.setdefault(
            (class_id, predicate), {"class_id": class_id, "predicate": predicate}
        )
        rtype = r.get("rtype")
        if rtype in ("minCardinality", "sh:minCount"):
            slot["min"] = value
        elif rtype in ("maxCardinality", "sh:maxCount"):
            slot["max"] = value
        elif rtype == "cardinality":
            slot["min"] = value
            slot["max"] = value
    return list(grouped.values())


def _cardinality_violations(db: Any, ontology_id: str) -> list[Violation]:
    """Per-individual assertion counts that breach a declared cardinality (FR-18.7)."""
    if not (
        db.has_collection(_CONSTRAINTS)
        and db.has_collection(_INDIVIDUALS)
        and db.has_collection(_ASSERTION)
        and db.has_collection(_RDF_TYPE)
    ):
        return []
    bounds = _resolve_cardinality_bounds(db, ontology_id)
    if not bounds:
        return []

    violations: list[Violation] = []
    for b in bounds:
        min_card, max_card = b.get("min"), b.get("max")
        counts = run_aql(
            db,
            f"""
            FOR t IN {_RDF_TYPE}
              FILTER t.ontology_id == @oid AND t.expired == @never AND t._to == @cid
              LET i = DOCUMENT(t._from)
              FILTER i != null AND i.expired == @never
              LET n = LENGTH(
                FOR a IN {_ASSERTION}
                  FILTER a._from == i._id AND a.expired == @never AND a.predicate == @pred
                  RETURN 1
              )
              RETURN {{key: i._key, label: i.label, n: n}}
            """,
            bind_vars={
                "oid": ontology_id,
                "never": NEVER_EXPIRES,
                "cid": b["class_id"],
                "pred": b["predicate"],
            },
        )
        for r in counts:
            n = int(r.get("n") or 0)
            if isinstance(min_card, int) and n < min_card:
                violations.append(_cardinality_violation(r, b["predicate"], f"< min {min_card}", n))
            if isinstance(max_card, int) and n > max_card:
                violations.append(_cardinality_violation(r, b["predicate"], f"> max {max_card}", n))
    return violations


def _cardinality_violation(row: dict[str, Any], predicate: str, bound: str, n: int) -> Violation:
    return Violation(
        rule_id=RULE_ABOX_CARDINALITY,
        severity=SEVERITY_ERROR,
        entity_ids=(str(row.get("key")), predicate),
        description=(
            f"Individual '{row.get('label') or row.get('key')}' has {n} '{predicate}' "
            f"assertion(s), which is {bound} declared cardinality."
        ),
        suggested_action=VERDICT_CONTRADICTED,
    )


def validate_abox(db: Any, ontology_id: str) -> RuleEngineReport:
    """Run every A-box rule against ``ontology_id`` and aggregate a report.

    Mirrors :func:`ontology_rule_engine.evaluate_rules`: a rule that raises is
    logged and recorded as skipped rather than aborting the pass. The rule list
    is resolved at call time (via the module-level rule functions) so tests can
    patch individual rules.
    """
    rules = (
        (RULE_ABOX_UNGROUNDED, _ungrounded_individuals),
        (RULE_ABOX_DANGLING_TYPE, _dangling_type_references),
        (RULE_ABOX_CARDINALITY, _cardinality_violations),
    )
    report = RuleEngineReport(ontology_id=ontology_id)
    for rule_id, fn in rules:
        try:
            results = fn(db, ontology_id)
        except Exception as exc:
            log.warning(
                "abox_validation: rule %s raised on %s -- skipping (%s)",
                rule_id,
                ontology_id,
                exc,
            )
            report.rules_skipped.append(rule_id)
            continue
        report.rules_evaluated.append(rule_id)
        report.violations.extend(results)
    log.info(
        "abox_validation: ontology=%s evaluated=%d skipped=%d violations=%d",
        ontology_id,
        len(report.rules_evaluated),
        len(report.rules_skipped),
        len(report.violations),
    )
    return report
