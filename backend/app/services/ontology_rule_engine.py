"""Ontology rule engine for the belief-revision pipeline (Stream 11 IBR.4).

Implements PRD §6.16 / FR-16.7: a single AQL pass per ontology that
detects violations of four rule families, each registered as an
independent ``Rule`` function so new rules can be added without
touching the orchestrator.

Built-in rules
--------------

* **R1 -- Synonym Triangle.** If A ``subClassOf`` B and either
  A ``equivalent_class`` C or B ``equivalent_class`` C, the system
  expects the triangle to close: A should also be subClassOf C
  (or its synonym closure should). When the inferred edge is
  *missing*, the rule emits an ``inferred-missing`` violation;
  when the inferred edge would create a cycle (A subClassOf B and
  B equivalent A), it emits a ``synonym-cycle`` violation
  signalling a likely merge candidate.
* **R2 -- subClassOf Transitivity (Cycle Detection).** subClassOf
  must be a strict partial order. Any cycle (``A -> B -> A`` or
  longer) is a hard violation: the LLM extracted contradictory
  hierarchy. Detected via WCC on the ``subclass_of`` edge set.
* **R3 -- Orphan Object Property Range.** Object properties whose
  ``rdfs_domain`` edge is present but ``rdfs_range_class`` edge is
  missing are invisible on the workspace canvas (the synthetic-edge
  builder requires both endpoints). Wraps
  :func:`app.services.edge_repair.repair_orphan_object_property_ranges`
  in dry-run mode to surface every orphan along with its inferred
  range candidate (when the matcher finds one). Always
  ``GAP_FILLING`` -- the action is the same regardless of whether the
  matcher had a candidate; the difference is whether a curator can
  one-click apply or has to source new evidence.
* **Disjointness.** When ``disjoint_with`` edges exist, any class C
  that is subClassOf both A and B (where A ``disjoint_with`` B) is
  a violation.
* **Cardinality.** When ``ontology_constraints`` documents declare
  cardinality bounds for a property, count actual occurrences and
  flag any class outside ``[min, max]``.

Output
------

``evaluate_rules`` returns a :class:`RuleEngineReport` containing a
list of :class:`Violation` records. Each violation has a stable
``rule_id``, a ``severity`` (``"warning"`` or ``"error"``), the
``entity_ids`` involved, a human-readable ``description``, and an
optional ``suggested_action`` (one of the belief-revision verdicts
from :mod:`app.db.revision_meta_repo`) so Phase 2's mechanical
classifier can read this directly.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.db.revision_meta_repo import (
    VERDICT_CONTRADICTED,
    VERDICT_GAP_FILLING,
    VERDICT_REDUNDANT,
    VERDICT_REFINED,
)
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql

log = logging.getLogger(__name__)


SEVERITY_WARNING = "warning"
SEVERITY_ERROR = "error"

RULE_R1_SYNONYM_TRIANGLE = "R1_synonym_triangle"
RULE_R2_SUBCLASS_CYCLE = "R2_subclass_cycle"
RULE_R3_ORPHAN_RANGE = "R3_orphan_object_property_range"
RULE_DISJOINT_VIOLATION = "DISJOINT_violation"
RULE_CARDINALITY_VIOLATION = "CARDINALITY_violation"


@dataclass(frozen=True)
class Violation:
    rule_id: str
    severity: str
    entity_ids: tuple[str, ...]
    description: str
    suggested_action: str | None = None  # One of revision_meta_repo.VERDICT_* or None.


@dataclass
class RuleEngineReport:
    ontology_id: str
    rules_evaluated: list[str] = field(default_factory=list)
    rules_skipped: list[str] = field(default_factory=list)  # missing collection etc.
    violations: list[Violation] = field(default_factory=list)

    def by_rule(self, rule_id: str) -> list[Violation]:
        return [v for v in self.violations if v.rule_id == rule_id]

    def to_dict(self) -> dict[str, Any]:
        """Serialisable summary for the admin endpoint and logs."""
        return {
            "ontology_id": self.ontology_id,
            "rules_evaluated": list(self.rules_evaluated),
            "rules_skipped": list(self.rules_skipped),
            "violation_count": len(self.violations),
            "violations": [
                {
                    "rule_id": v.rule_id,
                    "severity": v.severity,
                    "entity_ids": list(v.entity_ids),
                    "description": v.description,
                    "suggested_action": v.suggested_action,
                }
                for v in self.violations
            ],
        }


# Type alias for a rule: takes (db, ontology_id) and returns violations.
# Each rule MUST be self-contained -- it must check for required
# collections and silently return ``[]`` when they're missing, so the
# engine can degrade gracefully on partially-populated ontologies.
RuleFn = Callable[[Any, str], list[Violation]]


# ---------------------------------------------------------------------------
# R1 -- Synonym Triangle
# ---------------------------------------------------------------------------


def _r1_synonym_triangle(db: Any, ontology_id: str) -> list[Violation]:
    """Detect synonym-triangle violations (closure failures + cycles).

    For every (A subclass_of B, B equivalent C) pair, C is the
    canonical name for B, so A subclass_of C should also hold.
    Two failure modes:

    * **Missing inferred edge** (``severity=warning``): no edge
      A subclass_of C even though A subclass_of B and B equivalent C.
      Suggests REFINE -- the canonical name ought to be linked.
    * **Synonym cycle** (``severity=error``): A subclass_of B AND
      B equivalent A (or transitively). Suggests REDUNDANT -- the
      LLM almost certainly extracted the same concept twice with
      different labels.
    """
    if not (db.has_collection("subclass_of") and db.has_collection("equivalent_class")):
        return []

    bind = {"oid": ontology_id, "never": NEVER_EXPIRES}

    # Collect live subclass_of and equivalent_class edges in one pass each.
    sub_edges = list(
        run_aql(
            db,
            "FOR e IN subclass_of "
            "FILTER e.ontology_id == @oid AND e.expired == @never "
            "RETURN { from: e._from, to: e._to }",
            bind_vars=bind,
        )
    )
    equiv_edges = list(
        run_aql(
            db,
            "FOR e IN equivalent_class "
            "FILTER e.ontology_id == @oid AND e.expired == @never "
            "RETURN { from: e._from, to: e._to }",
            bind_vars=bind,
        )
    )

    sub_pairs: set[tuple[str, str]] = {(e["from"], e["to"]) for e in sub_edges}
    # Treat equivalent_class as undirected for triangle reasoning (it is
    # symmetric semantically, even when only one direction is materialised).
    equivalents: dict[str, set[str]] = {}
    for e in equiv_edges:
        a, b = e["from"], e["to"]
        equivalents.setdefault(a, set()).add(b)
        equivalents.setdefault(b, set()).add(a)

    violations: list[Violation] = []
    for a, b in sub_pairs:
        # Cycle: A subclass_of B and B equivalent A -- LLM extracted
        # the same concept under two names.
        if a in equivalents.get(b, set()):
            violations.append(
                Violation(
                    rule_id=RULE_R1_SYNONYM_TRIANGLE,
                    severity=SEVERITY_ERROR,
                    entity_ids=(a, b),
                    description=(
                        f"{a} is subClassOf {b} but also equivalent to it -- "
                        "likely duplicate extraction."
                    ),
                    suggested_action=VERDICT_REDUNDANT,
                )
            )
            continue
        # Triangle closure: A subclass_of B and B equivalent C should
        # imply A subclass_of C. Emit one warning per unmaterialised
        # edge so the report has a clean structure.
        for c in equivalents.get(b, set()):
            if c == a:
                continue  # the cycle case already handled
            if (a, c) in sub_pairs:
                continue  # already materialised
            violations.append(
                Violation(
                    rule_id=RULE_R1_SYNONYM_TRIANGLE,
                    severity=SEVERITY_WARNING,
                    entity_ids=(a, b, c),
                    description=(
                        f"{a} is subClassOf {b}, and {b} is equivalent to {c}, "
                        f"but {a} subClassOf {c} is not asserted."
                    ),
                    suggested_action=VERDICT_REFINED,
                )
            )
    return violations


# ---------------------------------------------------------------------------
# R2 -- subClassOf Cycle Detection
# ---------------------------------------------------------------------------


def _r2_subclass_cycle(db: Any, ontology_id: str) -> list[Violation]:
    """Detect cycles in the subclass_of graph (transitivity violation).

    A subclass_of relation must be a strict partial order; any cycle is
    a hard contradiction (at minimum the LLM extracted incompatible
    hierarchy). Detected by tarjan-style SCC: any SCC of size > 1, or
    any self-loop, is a cycle.
    """
    if not db.has_collection("subclass_of"):
        return []

    bind = {"oid": ontology_id, "never": NEVER_EXPIRES}
    edges = list(
        run_aql(
            db,
            "FOR e IN subclass_of "
            "FILTER e.ontology_id == @oid AND e.expired == @never "
            "RETURN { from: e._from, to: e._to }",
            bind_vars=bind,
        )
    )

    adj: dict[str, list[str]] = {}
    nodes: set[str] = set()
    for e in edges:
        a, b = e["from"], e["to"]
        adj.setdefault(a, []).append(b)
        nodes.add(a)
        nodes.add(b)

    # Self-loops first -- cheap and unambiguous.
    violations: list[Violation] = []
    for n, succs in adj.items():
        if n in succs:
            violations.append(
                Violation(
                    rule_id=RULE_R2_SUBCLASS_CYCLE,
                    severity=SEVERITY_ERROR,
                    entity_ids=(n,),
                    description=f"{n} is subClassOf itself.",
                    suggested_action=VERDICT_CONTRADICTED,
                )
            )

    # Tarjan's SCC. Only emit one violation per SCC of size > 1 to
    # avoid quadratic-blowup duplicates.
    index_counter = [0]
    stack: list[str] = []
    on_stack: set[str] = set()
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    sccs: list[list[str]] = []

    def _strongconnect(v: str) -> None:
        indices[v] = index_counter[0]
        lowlinks[v] = index_counter[0]
        index_counter[0] += 1
        stack.append(v)
        on_stack.add(v)
        for w in adj.get(v, ()):
            if w not in indices:
                _strongconnect(w)
                lowlinks[v] = min(lowlinks[v], lowlinks[w])
            elif w in on_stack:
                lowlinks[v] = min(lowlinks[v], indices[w])
        if lowlinks[v] == indices[v]:
            component: list[str] = []
            while True:
                w = stack.pop()
                on_stack.remove(w)
                component.append(w)
                if w == v:
                    break
            if len(component) > 1:
                sccs.append(component)

    for v in nodes:
        if v not in indices:
            _strongconnect(v)

    for component in sccs:
        violations.append(
            Violation(
                rule_id=RULE_R2_SUBCLASS_CYCLE,
                severity=SEVERITY_ERROR,
                entity_ids=tuple(sorted(component)),
                description=(
                    f"subClassOf cycle among {len(component)} classes: "
                    + " -> ".join(sorted(component))
                ),
                suggested_action=VERDICT_CONTRADICTED,
            )
        )
    return violations


# ---------------------------------------------------------------------------
# Disjointness violation
# ---------------------------------------------------------------------------


def _disjoint_violation(db: Any, ontology_id: str) -> list[Violation]:
    """Flag classes that are subClassOf two disjoint parents.

    The ``disjoint_with`` collection isn't materialised by the current
    extraction pipeline (the LLM-as-Judge calls disjointness mismatches
    out as a confidence penalty rather than as edges), so this rule is
    a no-op on most ontologies. Once Phase 2 starts emitting
    ``disjoint_with`` edges as part of REFINED revisions, the rule will
    activate without code changes.
    """
    if not (db.has_collection("subclass_of") and db.has_collection("disjoint_with")):
        return []

    bind = {"oid": ontology_id, "never": NEVER_EXPIRES}
    rows = list(
        run_aql(
            db,
            "FOR sub1 IN subclass_of "
            "  FILTER sub1.ontology_id == @oid AND sub1.expired == @never "
            "  FOR sub2 IN subclass_of "
            "    FILTER sub2.ontology_id == @oid AND sub2.expired == @never "
            "      AND sub2._from == sub1._from AND sub2._to != sub1._to "
            "    FOR dw IN disjoint_with "
            "      FILTER dw.ontology_id == @oid AND dw.expired == @never "
            "        AND ((dw._from == sub1._to AND dw._to == sub2._to) OR "
            "             (dw._from == sub2._to AND dw._to == sub1._to)) "
            "      RETURN { child: sub1._from, p1: sub1._to, p2: sub2._to }",
            bind_vars=bind,
        )
    )

    violations: list[Violation] = []
    seen: set[tuple[str, str, str]] = set()
    for row in rows:
        # Normalise the parent pair so we don't emit two violations for
        # the same triple under different orderings.
        child = row["child"]
        parents = tuple(sorted([row["p1"], row["p2"]]))
        key = (child, parents[0], parents[1])
        if key in seen:
            continue
        seen.add(key)
        violations.append(
            Violation(
                rule_id=RULE_DISJOINT_VIOLATION,
                severity=SEVERITY_ERROR,
                entity_ids=(child, parents[0], parents[1]),
                description=(
                    f"{child} is subClassOf both {parents[0]} and {parents[1]}, "
                    "which are declared disjoint."
                ),
                suggested_action=VERDICT_CONTRADICTED,
            )
        )
    return violations


# ---------------------------------------------------------------------------
# Cardinality violation
# ---------------------------------------------------------------------------


def _cardinality_violation(db: Any, ontology_id: str) -> list[Violation]:
    """Detect properties that violate declared min/max cardinality.

    Reads cardinality declarations from ``ontology_constraints``
    documents of ``constraint_type == "cardinality"`` (per PRD §5.1).
    A constraint document is expected to have:

    * ``class_id``: the class the constraint applies to
    * ``property_uri``: the property URI being constrained
    * ``min_cardinality``: int (optional)
    * ``max_cardinality``: int (optional)

    No-op when ``ontology_constraints`` is missing or when no
    documents of ``constraint_type=="cardinality"`` exist for this
    ontology.
    """
    if not (
        db.has_collection("ontology_constraints")
        and db.has_collection("rdfs_domain")
    ):
        return []

    bind = {"oid": ontology_id, "never": NEVER_EXPIRES}
    constraints = list(
        run_aql(
            db,
            "FOR c IN ontology_constraints "
            "FILTER c.ontology_id == @oid AND c.expired == @never "
            "  AND c.constraint_type == 'cardinality' "
            "RETURN c",
            bind_vars=bind,
        )
    )

    if not constraints:
        return []

    violations: list[Violation] = []
    for c in constraints:
        class_id = c.get("class_id")
        prop_uri = c.get("property_uri")
        if not isinstance(class_id, str) or not isinstance(prop_uri, str):
            continue
        min_card = c.get("min_cardinality")
        max_card = c.get("max_cardinality")

        # Count rdfs_domain edges from properties with this URI to the class.
        rows = list(
            run_aql(
                db,
                "FOR e IN rdfs_domain "
                "FILTER e.ontology_id == @oid AND e.expired == @never "
                "  AND e._to == @cid "
                "LET prop = DOCUMENT(e._from) "
                "FILTER prop != null AND prop.uri == @puri "
                "COLLECT WITH COUNT INTO n "
                "RETURN n",
                bind_vars={**bind, "cid": class_id, "puri": prop_uri},
            )
        )
        actual = rows[0] if rows else 0

        if isinstance(min_card, int) and actual < min_card:
            violations.append(
                Violation(
                    rule_id=RULE_CARDINALITY_VIOLATION,
                    severity=SEVERITY_ERROR,
                    entity_ids=(class_id, prop_uri),
                    description=(
                        f"{class_id} has {actual} occurrences of {prop_uri}, "
                        f"below declared min cardinality {min_card}."
                    ),
                    suggested_action=VERDICT_CONTRADICTED,
                )
            )
        if isinstance(max_card, int) and actual > max_card:
            violations.append(
                Violation(
                    rule_id=RULE_CARDINALITY_VIOLATION,
                    severity=SEVERITY_ERROR,
                    entity_ids=(class_id, prop_uri),
                    description=(
                        f"{class_id} has {actual} occurrences of {prop_uri}, "
                        f"above declared max cardinality {max_card}."
                    ),
                    suggested_action=VERDICT_CONTRADICTED,
                )
            )
    return violations


# ---------------------------------------------------------------------------
# R3 -- Orphan object property range
# ---------------------------------------------------------------------------


def _r3_orphan_object_property_range(db: Any, ontology_id: str) -> list[Violation]:
    """Detect object properties missing their ``rdfs_range_class`` edge.

    An *orphan* object property has a live ``rdfs_domain`` edge but no
    live ``rdfs_range_class`` edge (or, in the worst case, has neither).
    Such properties are invisible on the workspace canvas because the
    synthetic-edge builder
    (``frontend/src/components/graph/graphCanvasEdges.ts::buildSyntheticRdfsRangeClassEdges``)
    requires both endpoints to emit a class-to-class edge.

    Wraps :func:`app.services.edge_repair.repair_orphan_object_property_ranges`
    in dry-run mode and converts each item in the report into a
    :class:`Violation`. Three cases:

    * **Repairable orphan** (``severity=warning``,
      ``suggested_action=GAP-FILLING``): the matcher inferred a range
      class candidate from the property's own description / evidence
      text. A curator can one-click apply via
      ``POST /admin/ontology/{id}/repair-edges``.
    * **Unrecoverable orphan** (``severity=warning``,
      ``suggested_action=GAP-FILLING``): no candidate was found; the
      gap requires either new evidence or human curation.
    * **Structurally broken** (``severity=error``,
      ``suggested_action=GAP-FILLING``): the property has neither
      domain nor range; it is unusable as currently extracted.

    Reuses ``edge_repair`` instead of re-implementing the AQL so the
    "what counts as an orphan" definition stays in one place; if it
    ever changes (e.g. to allow data-property ranges), only one
    module needs to update.
    """
    if not (
        db.has_collection("ontology_object_properties")
        and db.has_collection("ontology_classes")
        and db.has_collection("rdfs_domain")
        and db.has_collection("rdfs_range_class")
    ):
        return []

    # Local import: ``edge_repair`` is a higher-level service that
    # already imports things from ``app.db``; importing it at module
    # top would force every consumer of the rule engine to pull in
    # edge_repair's transitive deps. Keeping it local also makes it
    # easier to mock in tests via ``monkeypatch.setattr(engine, ...)``.
    from app.services.edge_repair import repair_orphan_object_property_ranges

    report = repair_orphan_object_property_ranges(
        db, ontology_id, dry_run=True
    )

    violations: list[Violation] = []

    for r in report.repaired:
        violations.append(
            Violation(
                rule_id=RULE_R3_ORPHAN_RANGE,
                severity=SEVERITY_WARNING,
                entity_ids=(r.prop_key, r.domain_class_key, r.range_class_key),
                description=(
                    f"Orphan object property '{r.prop_key}' "
                    f"(domain={r.domain_class_key}) missing rdfs_range_class. "
                    f"Inferred range='{r.range_class_key}' via "
                    f"{r.matched_via}. One-click apply via "
                    f"POST /api/v1/admin/ontology/{ontology_id}/repair-edges."
                ),
                suggested_action=VERDICT_GAP_FILLING,
            )
        )

    for u in report.unrecoverable:
        entity_ids: tuple[str, ...] = (
            (u.prop_key,)
            if u.domain_class_key is None
            else (u.prop_key, u.domain_class_key)
        )
        violations.append(
            Violation(
                rule_id=RULE_R3_ORPHAN_RANGE,
                severity=SEVERITY_WARNING,
                entity_ids=entity_ids,
                description=(
                    f"Orphan object property '{u.prop_key}' "
                    f"(label={u.label!r}, domain={u.domain_class_key}) "
                    f"missing rdfs_range_class. No candidate range class "
                    f"matched the property's description or evidence text; "
                    f"likely requires new evidence or human curation."
                ),
                suggested_action=VERDICT_GAP_FILLING,
            )
        )

    for prop_key in report.no_domain:
        violations.append(
            Violation(
                rule_id=RULE_R3_ORPHAN_RANGE,
                severity=SEVERITY_ERROR,
                entity_ids=(prop_key,),
                description=(
                    f"Object property '{prop_key}' has neither rdfs_domain "
                    f"nor rdfs_range_class. Property is structurally broken "
                    f"and cannot appear on the canvas."
                ),
                suggested_action=VERDICT_GAP_FILLING,
            )
        )

    return violations


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


_DEFAULT_RULES: tuple[tuple[str, RuleFn], ...] = (
    (RULE_R1_SYNONYM_TRIANGLE, _r1_synonym_triangle),
    (RULE_R2_SUBCLASS_CYCLE, _r2_subclass_cycle),
    (RULE_R3_ORPHAN_RANGE, _r3_orphan_object_property_range),
    (RULE_DISJOINT_VIOLATION, _disjoint_violation),
    (RULE_CARDINALITY_VIOLATION, _cardinality_violation),
)


def evaluate_rules(
    db: Any,
    ontology_id: str,
    *,
    rules: tuple[tuple[str, RuleFn], ...] | None = None,
) -> RuleEngineReport:
    """Run every registered rule against an ontology, return aggregated report.

    A rule function that raises an exception is logged and treated as
    "skipped" rather than aborting the whole pass -- one bad rule must
    not block the others (Phase 4 consolidation depends on this for
    safety).

    Pass ``rules`` to run a custom subset (testing, ad-hoc audits).
    """
    rules = rules if rules is not None else _DEFAULT_RULES
    report = RuleEngineReport(ontology_id=ontology_id)
    for rule_id, fn in rules:
        try:
            results = fn(db, ontology_id)
        except Exception as exc:
            log.warning(
                "ontology_rule_engine: rule %s raised on ontology %s -- skipping (%s)",
                rule_id,
                ontology_id,
                exc,
            )
            report.rules_skipped.append(rule_id)
            continue
        if not results:
            # Distinguish "ran with no violations" from "skipped due to
            # missing prerequisites" by sentinel: rules return [] in
            # both cases, so we just record evaluation. The cardinality /
            # disjointness rules degrade gracefully on missing
            # collections and that's reported as evaluated-with-zero,
            # which is an honest summary.
            report.rules_evaluated.append(rule_id)
            continue
        report.rules_evaluated.append(rule_id)
        report.violations.extend(results)
    log.info(
        "ontology_rule_engine: ontology=%s evaluated=%d skipped=%d violations=%d",
        ontology_id,
        len(report.rules_evaluated),
        len(report.rules_skipped),
        len(report.violations),
    )
    return report
