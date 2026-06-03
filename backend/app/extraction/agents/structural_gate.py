"""Structural Gate agent — deterministic, in-memory T-box health check + repair.

Inspired by the UPM "Self-Optimizing Ontology" Pipeline-2 quality-gate idea
(``docs/research/Ontologies_3_6 .pdf``): measure schema connectivity *before*
materialization and apply 100%-reliable deterministic repairs, rather than
persisting a disconnected schema and hoping a human notices the orphans.

This is the in-pipeline, pre-materialization sibling of the post-hoc DB
services ``app.services.edge_repair`` and ``app.services.ontology_rule_engine``.
It runs the *same* proven heuristics on the in-memory merged class list
(``state['consistency_result'].classes``) so broken relationship targets are
recovered — or at least surfaced in a health report — before the
human-in-the-loop curation breakpoint, instead of after they have already been
written to the graph.

Gated behind ``settings.structural_gate_enabled`` (default ON as of SO.2; the
repairs are provably faithfulness-neutral — see the guardrail test
``test_repairs_never_touch_faithfulness_inputs``). When disabled the node is a
transparent pass-through that records a single skipped step log, so the pipeline
topology is identical across deploys and flipping the flag is a config-only
rollout (no code deploy required to roll out or roll back).

Scope (Stream 15 SO.1) — two deterministic rules borrowed from the deck:

* **URI normalization** — a relationship whose ``target_class_uri`` matches a
  known class only by URI *fragment* or by *label* is rewritten to that class's
  canonical URI (the deck's "URI Normalization" A-box rule, applied to T-box
  object properties).
* **Link recovery** ("semantic re-typing") — a relationship whose target
  resolves to *no* known class is re-pointed at the class whose name appears in
  the relationship's own signal text (description + evidence), reusing
  ``edge_repair.find_range_class_for_orphan``'s longest-substring heuristic.

The iterative LLM "surgeon" loop (deck ``optimizer_surgeon``, Stream 15 SO.3)
and the A-box named-individual loop (deck Pipeline 3, Stream 15 SO.4) are
deliberately out of scope here — see ``docs/REMAINING_WORK_PLAN.md``.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.config import settings
from app.extraction.state import ExtractionPipelineState, StepLog
from app.models.ontology import ExtractedClass
from app.services.edge_repair import find_range_class_for_orphan, resolve_range_class

log = logging.getLogger(__name__)

#: Cap on the per-list detail arrays embedded in the health report / step log
#: metadata. The *counts* are always exact; only the enumerated examples are
#: truncated so a pathological extraction can't bloat the persisted run stats.
_MAX_REPORT_ITEMS = 50


# ---------------------------------------------------------------------------
# Class indexes + resolution (reuse edge_repair's proven 4-tier resolver)
# ---------------------------------------------------------------------------


class _ClassIndex:
    """Lookup tables over the in-memory class list, keyed for ``resolve_range_class``.

    ``edge_repair.resolve_range_class`` resolves an LLM-emitted target URI to a
    class *key* via four ordered tiers (uri → fragment → label → miss). We key
    every table by the class's canonical URI so a resolved "key" is exactly the
    URI we rewrite the relationship target to.
    """

    def __init__(self, classes: list[ExtractedClass]) -> None:
        self.uri_to_key: dict[str, str] = {}
        self.fragment_to_key: dict[str, str] = {}
        self.label_to_key: dict[str, str] = {}
        # Fragment-keyed views for the substring matcher (which compares against
        # ``_key`` and ``label``). Full URIs make poor needles — the scheme/host
        # ("httpexamplecom…") never appears in prose — so we feed the matcher the
        # short fragment and translate its answer back to the canonical URI.
        self.class_views: list[dict[str, Any]] = []
        self._fragment_to_uri: dict[str, str] = {}

        for cls in classes:
            uri = cls.uri
            self.uri_to_key[uri] = uri
            fragment = _fragment(uri)
            if fragment and fragment not in self.fragment_to_key:
                self.fragment_to_key[fragment] = uri
            if cls.label and cls.label not in self.label_to_key:
                self.label_to_key[cls.label] = uri
            view_key = fragment or uri
            self.class_views.append({"_key": view_key, "label": cls.label})
            self._fragment_to_uri.setdefault(view_key, uri)

    def resolve(self, target_uri: str) -> str | None:
        """Canonical URI for ``target_uri`` via uri/fragment/label tiers, else None."""
        if not target_uri:
            return None
        res = resolve_range_class(
            target_uri,
            uri_to_key=self.uri_to_key,
            fragment_to_key=self.fragment_to_key,
            label_to_key=self.label_to_key,
        )
        return res.class_key if res.tier != "miss" else None

    def resolution_tier(self, target_uri: str) -> tuple[str, str | None]:
        """``(tier, canonical_uri_or_None)`` — exposes the tier for repair classification."""
        if not target_uri:
            return "miss", None
        res = resolve_range_class(
            target_uri,
            uri_to_key=self.uri_to_key,
            fragment_to_key=self.fragment_to_key,
            label_to_key=self.label_to_key,
        )
        return res.tier, (res.class_key if res.tier != "miss" else None)

    def view_key_to_uri(self, view_key: str) -> str:
        """Translate a fragment-style matcher answer back to the canonical URI."""
        return self._fragment_to_uri.get(view_key, view_key)


def _fragment(uri: str) -> str:
    """Last ``#``/``/`` fragment of a URI (``http://x#Foo`` -> ``Foo``)."""
    if not uri:
        return ""
    return uri.split("#")[-1].split("/")[-1]


# ---------------------------------------------------------------------------
# Health report
# ---------------------------------------------------------------------------


def compute_health_report(classes: list[ExtractedClass], index: _ClassIndex) -> dict[str, Any]:
    """Structural health of the in-memory T-box.

    Metrics (counts are exact; enumerated lists are truncated to
    ``_MAX_REPORT_ITEMS``):

    * ``dangling_relationship_targets`` — relationships whose ``target_class_uri``
      resolves to no known class (broken links).
    * ``island_classes`` — zero-degree classes: no resolvable parent, not a
      parent of any class, no resolvable outgoing relationship, and never the
      resolvable target of another class's relationship.
    * ``classes_without_parent`` — the deck's ``orphan_class`` (no
      ``rdfs:subClassOf``).
    * ``classes_without_properties`` — neither attributes nor relationships.
    """
    is_target: set[str] = set()
    is_parent: set[str] = set()
    dangling: list[dict[str, str]] = []
    relationship_count = 0

    for cls in classes:
        parent = index.resolve(cls.parent_uri) if cls.parent_uri else None
        if parent:
            is_parent.add(parent)
        for rel in cls.relationships:
            relationship_count += 1
            resolved = index.resolve(rel.target_class_uri)
            if resolved:
                is_target.add(resolved)
            else:
                dangling.append(
                    {
                        "class_uri": cls.uri,
                        "relationship_uri": rel.uri,
                        "target_class_uri": rel.target_class_uri,
                    }
                )

    islands: list[str] = []
    classes_without_parent: list[str] = []
    classes_without_properties: list[str] = []

    for cls in classes:
        has_out = any(index.resolve(rel.target_class_uri) for rel in cls.relationships)
        has_parent = bool(cls.parent_uri and index.resolve(cls.parent_uri))
        if not (has_out or has_parent or cls.uri in is_parent or cls.uri in is_target):
            islands.append(cls.uri)
        if not cls.parent_uri:
            classes_without_parent.append(cls.uri)
        if not cls.attributes and not cls.relationships:
            classes_without_properties.append(cls.uri)

    return {
        "class_count": len(classes),
        "relationship_count": relationship_count,
        "dangling_relationship_target_count": len(dangling),
        "dangling_relationship_targets": dangling[:_MAX_REPORT_ITEMS],
        "island_class_count": len(islands),
        "island_classes": islands[:_MAX_REPORT_ITEMS],
        "classes_without_parent_count": len(classes_without_parent),
        "classes_without_properties_count": len(classes_without_properties),
    }


# ---------------------------------------------------------------------------
# Deterministic repair
# ---------------------------------------------------------------------------


def repair_relationship_targets(
    classes: list[ExtractedClass], index: _ClassIndex
) -> tuple[list[ExtractedClass], list[dict[str, Any]]]:
    """Rewrite resolvable-but-non-canonical and recoverable relationship targets.

    Returns ``(new_classes, repairs)``. Input classes are never mutated —
    repaired classes are produced via ``model_copy`` so the operation is pure
    and safe to call on shared state. Each repair record is auditable (rule,
    owning class, relationship, from → to, and how the target was matched).

    Two deterministic rules, in order, per relationship:

    1. Target resolves by exact URI → leave it (already canonical).
    2. Target resolves by *fragment*/*label* → **URI normalization**: rewrite to
       the canonical URI.
    3. Target resolves to nothing → **link recovery**: re-point at the class
       named in the relationship's own description/evidence text (excluding the
       owning class to avoid trivial self-loops); else leave it dangling.
    """
    repairs: list[dict[str, Any]] = []
    new_classes: list[ExtractedClass] = []

    for cls in classes:
        changed = False
        new_relationships = []
        for rel in cls.relationships:
            tier, canonical = index.resolution_tier(rel.target_class_uri)

            if tier == "uri":
                new_relationships.append(rel)
                continue

            if tier in ("fragment", "label") and canonical and canonical != rel.target_class_uri:
                repairs.append(
                    {
                        "rule": "uri_normalization",
                        "class_uri": cls.uri,
                        "relationship_uri": rel.uri,
                        "from_target": rel.target_class_uri,
                        "to_target": canonical,
                        "matched_via": tier,
                    }
                )
                new_relationships.append(rel.model_copy(update={"target_class_uri": canonical}))
                changed = True
                continue

            if tier == "miss":
                match = find_range_class_for_orphan(
                    {
                        "description": rel.description,
                        "evidence": [ev.model_dump() for ev in rel.evidence],
                    },
                    index.class_views,
                    _fragment(cls.uri) or cls.uri,
                )
                if match is not None:
                    recovered = index.view_key_to_uri(match.class_key)
                    if recovered and recovered != rel.target_class_uri:
                        repairs.append(
                            {
                                "rule": "link_recovery",
                                "class_uri": cls.uri,
                                "relationship_uri": rel.uri,
                                "from_target": rel.target_class_uri,
                                "to_target": recovered,
                                "matched_via": match.matched_via,
                                "matched_text": match.matched_text,
                            }
                        )
                        new_relationships.append(
                            rel.model_copy(update={"target_class_uri": recovered})
                        )
                        changed = True
                        continue

            # Resolvable-and-canonical (no-op) or unrecoverable dangling target.
            new_relationships.append(rel)

        if changed:
            new_classes.append(cls.model_copy(update={"relationships": new_relationships}))
        else:
            new_classes.append(cls)

    return new_classes, repairs


# ---------------------------------------------------------------------------
# LangGraph node
# ---------------------------------------------------------------------------


def structural_gate_node(state: ExtractionPipelineState) -> dict[str, Any]:
    """LangGraph node: pre-materialization structural gate + deterministic repair.

    Pass-through (records a single skipped step log) when
    ``settings.structural_gate_enabled`` is False or there is no input, so the
    pipeline topology is stable regardless of the flag.
    """
    start = time.time()
    run_id = state.get("run_id", "unknown")

    if not settings.structural_gate_enabled:
        return {"step_logs": [_skip_log(start, "disabled")]}

    consistency_result = state.get("consistency_result")
    if consistency_result is None or not consistency_result.classes:
        log.info("structural_gate skipped: no input", extra={"run_id": run_id})
        return {
            "structural_health": None,
            "step_logs": [_skip_log(start, "no_input")],
        }

    classes: list[ExtractedClass] = consistency_result.classes
    index = _ClassIndex(classes)

    before = compute_health_report(classes, index)
    repaired_classes, repairs = repair_relationship_targets(classes, index)
    after = compute_health_report(repaired_classes, index)

    updated_result = consistency_result.model_copy(update={"classes": repaired_classes})

    health: dict[str, Any] = {
        "status": "completed",
        "repair_count": len(repairs),
        "repairs": repairs[:_MAX_REPORT_ITEMS],
        "before": before,
        "after": after,
    }

    duration = time.time() - start
    step_log = StepLog(
        step="structural_gate",
        status="completed",
        started_at=start,
        completed_at=time.time(),
        duration_seconds=round(duration, 3),
        error=None,
        metadata={
            "repair_count": len(repairs),
            "dangling_before": before["dangling_relationship_target_count"],
            "dangling_after": after["dangling_relationship_target_count"],
            "islands_before": before["island_class_count"],
            "islands_after": after["island_class_count"],
        },
    )

    log.info(
        "structural_gate completed",
        extra={
            "run_id": run_id,
            "duration_seconds": round(duration, 3),
            "repair_count": len(repairs),
            "dangling_before": before["dangling_relationship_target_count"],
            "dangling_after": after["dangling_relationship_target_count"],
        },
    )

    return {
        "consistency_result": updated_result,
        "structural_health": health,
        "step_logs": [step_log],
    }


def _skip_log(start: float, reason: str) -> StepLog:
    return StepLog(
        step="structural_gate",
        status="skipped",
        started_at=start,
        completed_at=time.time(),
        duration_seconds=round(time.time() - start, 3),
        error=None,
        metadata={"reason": reason},
    )
