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
* **R4 -- Redundant Class.** Two or more classes whose labels (or
  ``_key`` fragments when label is missing) collapse to the same
  normalised form -- lowercase, alphanumeric only, possessive ``'s``
  stripped, plus a conservative singular/plural pass that only
  merges ``S`` with ``S+"s"`` / ``S+"es"`` / ``S[:-1]+"ies"`` when
  *both* forms exist in the data. Catches the silent-duplicate case
  R1 cannot see (R1 needs explicit ``equivalent_class`` /
  ``subclass_of`` edges already in place). Suggested action is
  ``REDUNDANT`` -- the merge target choice belongs to the curator.
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
RULE_R4_REDUNDANT_CLASS = "R4_redundant_class"
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
    documents written by Stream 3 PR 1 (LLM extraction) in the PRD
    §6.14 OWL-native shape, Stream 3 PR 2 (OWL import), AND Stream 3
    PR 3 (SHACL import). All three sources land rows with one
    restriction per row and the same on_class / property_uri fields;
    only ``constraint_type`` / ``restriction_type`` differ:

    * OWL (PR 1 & PR 2): ``constraint_type == "owl:Restriction"``,
      ``restriction_type in {"minCardinality","maxCardinality","cardinality"}``
      (``cardinality`` is the OWL "exactly N" sugar -- expanded here
      to min==max==N).
    * SHACL (PR 3): ``constraint_type == "sh:PropertyShape"``,
      ``restriction_type in {"sh:minCount","sh:maxCount"}``.

    A class that declares both an OWL ``minCardinality 1`` AND a SHACL
    ``sh:minCount 1`` on the same property arrives as two rows; both
    feed the same ``min`` slot in the grouped result so the
    intersection (i.e. the strictest bound) is what's enforced. This
    is the desired behaviour: redundant declarations don't trigger
    spurious violations, and stricter declarations win.

    No-op when the collection is missing or has no restrictions for
    this ontology.
    """
    if not (db.has_collection("ontology_constraints") and db.has_collection("rdfs_domain")):
        return []

    bind = {"oid": ontology_id, "never": NEVER_EXPIRES}
    rows = list(
        run_aql(
            db,
            "FOR c IN ontology_constraints "
            "FILTER c.ontology_id == @oid AND c.expired == @never "
            "  AND c.constraint_type IN ['owl:Restriction', 'sh:PropertyShape'] "
            "  AND c.restriction_type IN ["
            "    'minCardinality', 'maxCardinality', 'cardinality',"
            "    'sh:minCount', 'sh:maxCount'"
            "  ] "
            "RETURN c",
            bind_vars=bind,
        )
    )

    if not rows:
        return []

    # Group rows by (on_class, property_uri). A class with both
    # minCardinality=1 and maxCardinality=5 on the same property
    # arrives as two rows; we want to evaluate both bounds in one pass.
    # SHACL sh:minCount and OWL minCardinality on the same property
    # both write to slot["min"] -- if the values disagree the LATER
    # row wins for now; in practice they should match (the import is
    # deterministic). A future enhancement can take the strictest
    # (max of the two for min bounds, min of the two for max bounds).
    grouped: dict[tuple[str, str], dict[str, int]] = {}
    for c in rows:
        class_id = c.get("on_class")
        prop_uri = c.get("property_uri")
        if not isinstance(class_id, str) or not isinstance(prop_uri, str):
            continue
        rtype = c.get("restriction_type")
        rvalue = c.get("restriction_value")
        if not isinstance(rvalue, int):
            # Cardinality kinds REQUIRE an integer. A string here means
            # the LLM (or an importer) confused this with a value
            # restriction; skip with a warning -- the rule engine
            # should not crash the consolidation run on bad data.
            log.warning(
                "skipping cardinality restriction with non-int value: "
                "class=%s property=%s restriction_type=%s value=%r",
                class_id,
                prop_uri,
                rtype,
                rvalue,
            )
            continue
        slot = grouped.setdefault((class_id, prop_uri), {})
        if rtype in ("minCardinality", "sh:minCount"):
            slot["min"] = rvalue
        elif rtype in ("maxCardinality", "sh:maxCount"):
            slot["max"] = rvalue
        elif rtype == "cardinality":
            # owl:cardinality N is sugar for min==N AND max==N.
            slot["min"] = rvalue
            slot["max"] = rvalue

    violations: list[Violation] = []
    for (class_id, prop_uri), bounds in grouped.items():
        min_card = bounds.get("min")
        max_card = bounds.get("max")

        # Count rdfs_domain edges from properties with this URI to the class.
        count_rows = list(
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
        actual = count_rows[0] if count_rows else 0

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

    report = repair_orphan_object_property_ranges(db, ontology_id, dry_run=True)

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
            (u.prop_key,) if u.domain_class_key is None else (u.prop_key, u.domain_class_key)
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
# R4 -- Redundant class detector
# ---------------------------------------------------------------------------


def _r4_redundant_class(db: Any, ontology_id: str) -> list[Violation]:
    """Detect classes that look like silent duplicates of each other.

    Two classes are considered redundant when their labels (or, when
    the label is missing, their ``_key`` fragments) collapse to the
    same normalised form. Normalisation is the same one used by
    :mod:`app.services.edge_repair` -- lowercase + strip
    non-alphanumerics + drop possessive ``'s``. So
    ``"Customer's Risk Profile"`` and ``"CustomerRiskProfile"``
    both collapse to ``customerriskprofile``.

    On top of exact-form clustering, a conservative singular/plural
    pass merges any cluster whose normalised form ``S`` has another
    cluster whose form is one of ``S+"s"``, ``S+"es"``, or
    ``S[:-1]+"ies"`` -- but *only when both forms exist in the data*.
    This avoids over-aggressive stemming (``Address`` would otherwise
    incorrectly stem to ``Addres``) while still catching the common
    ``Employee/Employees``, ``Class/Classes``, ``Country/Countries``
    duplicates the user demo-flagged.

    Distinct from R1 (synonym triangle) -- R1 needs explicit
    ``equivalent_class`` / ``subclass_of`` edges already in place and
    detects inconsistencies in those triangles. R4 needs no edges and
    detects the class-was-extracted-twice case the LLM is prone to.

    Each cluster of size >= 2 emits one ``warning`` violation with
    ``suggested_action=REDUNDANT``. The merge target choice belongs
    to the curator (the rule has no opinion on which member to
    keep), so we do not pre-select one in the description.
    """
    if not db.has_collection("ontology_classes"):
        return []

    bind = {"oid": ontology_id, "never": NEVER_EXPIRES}
    rows = list(
        run_aql(
            db,
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id == @oid AND c.expired == @never "
            "RETURN { _key: c._key, label: c.label }",
            bind_vars=bind,
        )
    )
    if len(rows) < 2:
        return []

    # Step 1: bucket by exact normalised form.
    by_norm: dict[str, list[tuple[str, str]]] = {}
    for row in rows:
        key = str(row.get("_key") or "")
        if not key:
            continue
        label = row.get("label")
        # Fall back to the key (which is usually the URI fragment) when
        # the label is missing -- this matches edge_repair's behaviour
        # and means "Account" + an unlabeled "Account"-keyed class still
        # cluster together.
        canonical = _normalise_label_or_key(label, key)
        if not canonical:
            continue
        by_norm.setdefault(canonical, []).append((key, str(label or key)))

    # Step 2: conservative singular/plural pass. For each form S, check
    # whether S+"s", S+"es", or S[:-1]+"ies" is also a form. When found,
    # union the two buckets via a parent map (classic disjoint-set lite).
    parent: dict[str, str] = {form: form for form in by_norm}

    def _find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(a: str, b: str) -> None:
        ra, rb = _find(a), _find(b)
        if ra != rb:
            # Deterministic merge target so the description is stable
            # across runs (helps tests + makes the audit log diffable).
            parent[ra if ra < rb else rb] = ra if ra > rb else rb

    for form in list(by_norm):
        # Skip very short forms -- ``a`` -> ``as`` is just noise.
        if len(form) < 4:
            continue
        for plural in _plural_candidates(form):
            if plural in by_norm and plural != form:
                _union(form, plural)

    # Step 3: gather clusters keyed by their post-union root.
    clusters: dict[str, list[tuple[str, str]]] = {}
    for form, members in by_norm.items():
        root = _find(form)
        clusters.setdefault(root, []).extend(members)

    violations: list[Violation] = []
    for root, members in clusters.items():
        if len(members) < 2:
            continue
        # Sort for stable output (description + entity_ids order).
        members_sorted = sorted(members, key=lambda m: m[0])
        keys = tuple(k for k, _ in members_sorted)
        labels = [lbl for _, lbl in members_sorted]
        violations.append(
            Violation(
                rule_id=RULE_R4_REDUNDANT_CLASS,
                severity=SEVERITY_WARNING,
                entity_ids=keys,
                description=(
                    f"{len(members_sorted)} classes look redundant "
                    f"(normalised form '{root}'): "
                    + ", ".join(repr(lbl) for lbl in labels)
                    + ". Consider merging via curation."
                ),
                suggested_action=VERDICT_REDUNDANT,
            )
        )

    # Stable order across runs so the report is diffable.
    violations.sort(key=lambda v: v.entity_ids)
    return violations


def _normalise_label_or_key(label: Any, key: str) -> str:
    """Reuse ``edge_repair._normalise`` against label-then-key fallback.

    Imported lazily so the rule engine doesn't load ``edge_repair``
    unless R4 actually runs (matches the R3 lazy-import pattern).
    """
    from app.services.edge_repair import _normalise

    if isinstance(label, str) and label.strip():
        return _normalise(label)
    return _normalise(key)


def _plural_candidates(form: str) -> tuple[str, ...]:
    """Conservative plural variants for the singular/plural merge pass.

    Returns the candidate plural forms whose presence in the data
    would justify merging this singular cluster with the plural one.
    Intentionally narrow -- we only want high-precision matches
    (false positives turn into curator noise; false negatives just
    miss a duplicate, which the user can spot manually).
    """
    cands = [form + "s", form + "es"]
    if form.endswith("y") and len(form) > 2:
        # ``country`` -> ``countries``
        cands.append(form[:-1] + "ies")
    return tuple(cands)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


_DEFAULT_RULES: tuple[tuple[str, RuleFn], ...] = (
    (RULE_R1_SYNONYM_TRIANGLE, _r1_synonym_triangle),
    (RULE_R2_SUBCLASS_CYCLE, _r2_subclass_cycle),
    (RULE_R3_ORPHAN_RANGE, _r3_orphan_object_property_range),
    (RULE_R4_REDUNDANT_CLASS, _r4_redundant_class),
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
