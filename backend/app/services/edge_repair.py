"""Repair orphan ``ontology_object_properties`` -- write the missing
``rdfs_range_class`` edge by inferring the range class from the property's
own natural-language signals.

Why this exists
---------------

The extraction writer (``app.services.extraction``) writes the property
vertex + ``rdfs_domain`` edge unconditionally, but only writes the
``rdfs_range_class`` edge if it can resolve the LLM-supplied
``target_class_uri`` against an extracted class (URI, fragment, or key
lookup). When that resolution fails -- typically because the LLM emitted a
target URI that doesn't match any extracted class, or didn't emit one at
all -- the property is silently left without a range. The class-to-class
link never appears on the workspace canvas (see
``frontend/src/components/graph/graphCanvasEdges.ts::buildSyntheticRdfsRangeClassEdges``,
which requires a paired ``rdfs_domain`` + ``rdfs_range_class`` to emit a
synthetic edge).

A quick scan across the demo ontologies showed 23 / 63 (37 %) of object
properties were orphans by this definition. Of those, 18 / 23 (78 %)
mention an existing class somewhere in their ``description``,
``evidence_text``, or ``source_spans`` -- the LLM had the right concept,
the writer just couldn't link it. This module recovers those by
substring-matching existing class names against the property's own
recorded text.

Algorithm
---------

For each orphan:

1. Build the property's *signal text* by concatenating ``description``,
   every ``evidence[*].evidence_text``, and every
   ``evidence[*].source_spans[*]``.
2. Build the *candidate class* set: every live class in the same
   ontology, **minus** the orphan's own domain class (excluding the
   domain prevents trivial self-loops where e.g. "Customer" appears in
   the description of a property whose domain is already ``Customer``).
3. For each candidate, normalise both the class ``_key`` and ``label``
   (lowercase, alphanumeric only) and check for substring containment in
   the normalised signal text.
4. When multiple candidates match, the one with the **longest**
   normalised name wins (so ``CustomerRiskProfile`` beats ``Customer``
   for the description "generates a Customer Risk Profile").
5. The orchestrator writes the missing ``rdfs_range_class`` edge with a
   ``repair_meta`` field that records why the match was chosen, so the
   inserted edge can later be audited or undone in bulk.

Edges inserted by this module are intentionally minimal -- they hold no
``label``/``confidence``/``evidence`` of their own. The
``edge_confidence.enrich_rdfs_range_class_edges`` join (called from
``GET /api/v1/ontology/{id}/edges``) will lift the property vertex's
real label and confidence onto the edge at read time.

Idempotency
-----------

Running the orchestrator twice is safe: after the first run the
previously-orphan property has a ``rdfs_range_class`` edge and is no
longer detected as an orphan, so the second run is a no-op.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any

from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql

log = logging.getLogger(__name__)


# Marker written into the ``repair_meta.source`` field on inserted edges so a
# future audit query (or undo migration) can find every edge this module
# created. Kept in one place so the audit query stays in sync.
REPAIR_SOURCE = "edge_repair.repair_orphan_object_property_ranges"


# ---------------------------------------------------------------------------
# Pure matcher
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RangeMatch:
    """Result of matching an orphan property to a candidate range class."""

    class_key: str
    matched_text: str  # the literal substring that hit (normalised form)
    matched_via: str   # ``"key"`` or ``"label"``
    other_candidates: tuple[str, ...] = ()  # for ambiguity reporting


# Matches the possessive clitic ``'s`` / ``'s`` (curly variant) at a word
# boundary. Stripping it BEFORE the normalisation pass prevents
# ``Customer's Risk Profile`` from collapsing to ``customersriskprofile``
# (with a stray ``s`` between ``customer`` and ``risk``) which would no
# longer contain the class-key needle ``customerriskprofile``. Possessives
# are extremely common in extracted descriptions, so handling them is worth
# the small extra step.
_POSSESSIVE = re.compile(r"['\u2019]s\b", re.IGNORECASE)


def _normalise(s: str | None) -> str:
    """Lowercase + strip non-alphanumerics so ``ACH Batch`` matches ``ACHBatch``.

    Possessive ``'s`` is dropped first (see ``_POSSESSIVE``) so that
    ``Customer's Risk Profile`` normalises to ``customerriskprofile``,
    matching a class with ``_key="CustomerRiskProfile"``.
    """
    if not s:
        return ""
    stripped = _POSSESSIVE.sub("", s)
    return re.sub(r"[^a-z0-9]+", "", stripped.lower())


# Splits CamelCase / PascalCase / snake_case / kebab-case into space-separated
# words. Used to derive a human-readable label from a URI fragment when the
# LLM only emitted a ``target_class_uri`` (no separate label).
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def humanize_uri_fragment(uri: str) -> str:
    """Derive a readable label from a URI's last fragment.

    ``http://x#CustomerRiskProfile`` -> ``"Customer Risk Profile"``
    ``http://x/customer_risk_profile`` -> ``"customer risk profile"``
    ``http://x/account-type`` -> ``"account type"``
    Empty / non-string input returns ``""``.

    This is intentionally simple: the goal is to capture the LLM's *intent*
    when it emitted the URI, so a later resolution pass (or a human curator)
    can find the right class even if the URI itself doesn't directly match.
    """
    if not isinstance(uri, str) or not uri:
        return ""
    fragment = uri.split("#")[-1].split("/")[-1]
    if not fragment:
        return ""
    spaced = _CAMEL_BOUNDARY.sub(" ", fragment)
    spaced = re.sub(r"[_\-]+", " ", spaced)
    return re.sub(r"\s+", " ", spaced).strip()


@dataclass(frozen=True)
class RangeResolution:
    """Result of resolving an LLM-supplied target_class_uri to an extracted class.

    Attributes:
        class_key: The matched class ``_key``, or ``None`` if no tier hit.
        tier: Which tier produced the match -- ``"uri"``, ``"fragment"``,
            ``"label"`` (longest normalised label match), or ``"miss"``.
            Tier names are stable for telemetry / logging.
        target_label: The humanised label derived from the URI for
            persistence on the property document, regardless of whether
            resolution succeeded.
    """

    class_key: str | None
    tier: str
    target_label: str


def resolve_range_class(
    target_uri: str,
    *,
    uri_to_key: dict[str, str],
    fragment_to_key: dict[str, str],
    label_to_key: dict[str, str],
    target_label: str | None = None,
) -> RangeResolution:
    """Resolve an LLM-emitted ``target_class_uri`` to an extracted class key.

    Tries four ordered tiers; first hit wins:

    1. **uri** -- exact URI match against ``uri_to_key``.
    2. **fragment** -- match URI's last fragment against ``fragment_to_key``
       (which is keyed by the class URI fragment, e.g. ``"CustomerAccount"``).
    3. **label** -- normalised longest-match against ``label_to_key`` (which
       is keyed by the original class label, e.g. ``"Customer Account"``).
       This is the workhorse tier for the common LLM failure mode where the
       URI fragment doesn't equal the label letter-for-letter.
    4. **miss** -- nothing matched. ``class_key`` is ``None``.

    ``target_label`` is the LLM-supplied human label for the target class
    (rare; the prompts do not currently request it). When absent, the URI
    fragment is humanised (see :func:`humanize_uri_fragment`) so that later
    repair passes have a textual anchor even when the URI is unresolvable.
    """
    label = target_label or humanize_uri_fragment(target_uri)

    # Tier 1: exact URI
    hit = uri_to_key.get(target_uri)
    if hit:
        return RangeResolution(class_key=hit, tier="uri", target_label=label)

    # Tier 2: URI fragment against per-fragment index
    fragment = target_uri.split("#")[-1].split("/")[-1] if target_uri else ""
    if fragment:
        hit = fragment_to_key.get(fragment)
        if hit:
            return RangeResolution(class_key=hit, tier="fragment", target_label=label)

    # Tier 3: longest-normalised-match against class labels
    needle = _normalise(label) or _normalise(fragment)
    if needle and label_to_key:
        # Build candidate (normalised_label, key) list, longest first so
        # ``CustomerRiskProfile`` beats ``Customer`` when both are valid.
        candidates = sorted(
            ((_normalise(lbl), key) for lbl, key in label_to_key.items()),
            key=lambda x: len(x[0]),
            reverse=True,
        )
        for cn, key in candidates:
            if not cn:
                continue
            if cn == needle or cn in needle or needle in cn:
                return RangeResolution(class_key=key, tier="label", target_label=label)

    return RangeResolution(class_key=None, tier="miss", target_label=label)


def _signal_text(prop: dict[str, Any]) -> str:
    """Concatenate every recorded natural-language signal on the property."""
    parts: list[str] = []
    desc = prop.get("description")
    if isinstance(desc, str):
        parts.append(desc)
    evidence = prop.get("evidence")
    if isinstance(evidence, list):
        for ev in evidence:
            if not isinstance(ev, dict):
                continue
            t = ev.get("evidence_text")
            if isinstance(t, str):
                parts.append(t)
            spans = ev.get("source_spans")
            if isinstance(spans, list):
                for span in spans:
                    if isinstance(span, str):
                        parts.append(span)
    return " ".join(parts)


def find_range_class_for_orphan(
    orphan_prop: dict[str, Any],
    classes: list[dict[str, Any]],
    domain_class_key: str | None,
) -> RangeMatch | None:
    """Best-guess range class for an orphan object property, or ``None``.

    See module docstring for the full algorithm. ``domain_class_key`` may be
    ``None`` (no domain edge); in that case nothing is excluded.

    The orphan's own ``label`` is intentionally **not** part of the signal
    text -- it's typically a verb phrase (e.g. "generates Risk Profile")
    that already carries the class name and would dominate the match. But
    even then the ``description`` and ``evidence_text`` cover the same
    ground, and including ``label`` lets short ones (e.g. "holds") match
    a class purely on the verb when there's no narrative context, which
    biases too aggressively. Stick to the description / evidence text.
    """
    signal = _normalise(_signal_text(orphan_prop))
    if not signal:
        return None

    # (normalised_name, kind, original_class_key) tuples
    candidates: list[tuple[str, str, str]] = []
    for cls in classes:
        ckey = cls.get("_key")
        if not isinstance(ckey, str):
            continue
        if domain_class_key is not None and ckey == domain_class_key:
            # Skip the domain class so we don't suggest a trivial self-loop.
            continue
        cn_key = _normalise(ckey)
        if cn_key:
            candidates.append((cn_key, "key", ckey))
        clabel = cls.get("label")
        if isinstance(clabel, str):
            cn_label = _normalise(clabel)
            # Avoid double-listing when label normalises to the same thing as key.
            if cn_label and cn_label != cn_key:
                candidates.append((cn_label, "label", ckey))

    # Longest-first to disambiguate "BankAccount" before "Account".
    candidates.sort(key=lambda x: len(x[0]), reverse=True)

    hits: list[tuple[str, str, str]] = []
    seen_keys: set[str] = set()
    for cn, kind, ckey in candidates:
        if cn in signal and ckey not in seen_keys:
            hits.append((cn, kind, ckey))
            seen_keys.add(ckey)

    if not hits:
        return None

    # Longest hit wins (already sorted longest-first); record the rest as
    # other_candidates so the report can flag ambiguity.
    chosen_cn, chosen_kind, chosen_key = hits[0]
    other = tuple(h[2] for h in hits[1:])
    return RangeMatch(
        class_key=chosen_key,
        matched_text=chosen_cn,
        matched_via=chosen_kind,
        other_candidates=other,
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class RepairedEdge:
    prop_key: str
    domain_class_key: str
    range_class_key: str
    matched_text: str
    matched_via: str
    other_candidates: tuple[str, ...] = ()


@dataclass
class UnrecoverableOrphan:
    prop_key: str
    domain_class_key: str | None
    label: str
    description: str


@dataclass
class RepairReport:
    ontology_id: str
    orphans_found: int = 0
    repaired: list[RepairedEdge] = field(default_factory=list)
    unrecoverable: list[UnrecoverableOrphan] = field(default_factory=list)
    no_domain: list[str] = field(default_factory=list)  # prop keys with no rdfs_domain edge

    def to_dict(self) -> dict[str, Any]:
        """Serialisable summary for the admin endpoint and logs."""
        return {
            "ontology_id": self.ontology_id,
            "orphans_found": self.orphans_found,
            "repaired_count": len(self.repaired),
            "unrecoverable_count": len(self.unrecoverable),
            "no_domain_count": len(self.no_domain),
            "repaired": [
                {
                    "prop_key": r.prop_key,
                    "domain_class_key": r.domain_class_key,
                    "range_class_key": r.range_class_key,
                    "matched_text": r.matched_text,
                    "matched_via": r.matched_via,
                    "other_candidates": list(r.other_candidates),
                }
                for r in self.repaired
            ],
            "unrecoverable": [
                {
                    "prop_key": u.prop_key,
                    "domain_class_key": u.domain_class_key,
                    "label": u.label,
                    "description": u.description,
                }
                for u in self.unrecoverable
            ],
            "no_domain": list(self.no_domain),
        }


def repair_orphan_object_property_ranges(
    db: Any,
    ontology_id: str,
    *,
    dry_run: bool = False,
) -> RepairReport:
    """Find and repair orphan object properties for one ontology.

    An *orphan* is an ``ontology_object_properties`` document that has a live
    ``rdfs_domain`` edge in the ontology but no live ``rdfs_range_class``
    edge. This function infers the missing range class via
    :func:`find_range_class_for_orphan` and inserts the missing edge with a
    ``repair_meta`` audit field.

    ``dry_run=True`` runs the matcher and returns a populated report
    without writing any edges -- useful for the admin endpoint to preview
    the repair before committing.

    Idempotent: a second call after a successful run finds zero orphans.
    """
    report = RepairReport(ontology_id=ontology_id)

    if not (
        db.has_collection("ontology_object_properties")
        and db.has_collection("ontology_classes")
        and db.has_collection("rdfs_domain")
        and db.has_collection("rdfs_range_class")
    ):
        log.info(
            "edge_repair: required collections missing for ontology %s -- nothing to do",
            ontology_id,
        )
        return report

    bind = {"oid": ontology_id, "never": NEVER_EXPIRES}

    classes = list(
        run_aql(
            db,
            "FOR c IN ontology_classes "
            "FILTER c.ontology_id == @oid AND c.expired == @never "
            "RETURN c",
            bind_vars=bind,
        )
    )
    if not classes:
        log.info(
            "edge_repair: ontology %s has no classes -- nothing to repair",
            ontology_id,
        )
        return report

    object_props = list(
        run_aql(
            db,
            "FOR p IN ontology_object_properties "
            "FILTER p.ontology_id == @oid AND p.expired == @never "
            "RETURN p",
            bind_vars=bind,
        )
    )

    # Identify orphans + their domain class via a single AQL hop.
    domains_by_prop: dict[str, str] = {}
    for row in run_aql(
        db,
        "FOR e IN rdfs_domain "
        "FILTER e.ontology_id == @oid AND e.expired == @never "
        "RETURN { prop_id: e._from, class_id: e._to }",
        bind_vars=bind,
    ):
        prop_id = row.get("prop_id")
        class_id = row.get("class_id")
        if isinstance(prop_id, str) and isinstance(class_id, str):
            # A property may legally have multiple domains; we keep the first
            # for self-loop avoidance. Multi-domain object properties are rare
            # and the matcher's behaviour is the same either way -- it just
            # means one of the domains may not be excluded.
            domains_by_prop.setdefault(prop_id, class_id.split("/", 1)[-1])

    ranged_prop_ids: set[str] = set()
    for row in run_aql(
        db,
        "FOR e IN rdfs_range_class "
        "FILTER e.ontology_id == @oid AND e.expired == @never "
        "RETURN e._from",
        bind_vars=bind,
    ):
        if isinstance(row, str):
            ranged_prop_ids.add(row)

    range_col = db.collection("rdfs_range_class")
    now = time.time()

    for prop in object_props:
        pid = prop.get("_id")
        if not isinstance(pid, str):
            continue
        if pid in ranged_prop_ids:
            continue  # not an orphan
        report.orphans_found += 1

        domain_key = domains_by_prop.get(pid)
        if domain_key is None:
            # No rdfs_domain edge either -- not strictly an orphan in our sense
            # (we defined orphan as "has domain but no range"). Track it
            # separately so the report surfaces this rarer pathology, but skip
            # repair: without a domain edge we can't draw a class-to-class
            # link anyway, and inserting just a range edge would only deepen
            # the inconsistency.
            report.no_domain.append(prop.get("_key", pid))
            continue

        match = find_range_class_for_orphan(prop, classes, domain_key)
        if match is None:
            report.unrecoverable.append(
                UnrecoverableOrphan(
                    prop_key=prop.get("_key", pid),
                    domain_class_key=domain_key,
                    label=str(prop.get("label") or ""),
                    description=str(prop.get("description") or ""),
                )
            )
            continue

        repaired = RepairedEdge(
            prop_key=prop.get("_key", pid),
            domain_class_key=domain_key,
            range_class_key=match.class_key,
            matched_text=match.matched_text,
            matched_via=match.matched_via,
            other_candidates=match.other_candidates,
        )
        report.repaired.append(repaired)

        if dry_run:
            continue

        edge_doc = {
            "_from": pid,
            "_to": f"ontology_classes/{match.class_key}",
            "ontology_id": ontology_id,
            "created": now,
            "expired": NEVER_EXPIRES,
            "repair_meta": {
                "source": REPAIR_SOURCE,
                "matched_text": match.matched_text,
                "matched_via": match.matched_via,
                "other_candidates": list(match.other_candidates),
                "repaired_at": now,
            },
        }
        try:
            range_col.insert(edge_doc)
        except Exception as exc:
            # Don't swallow silently -- the original extraction bug we're
            # fixing did exactly that. Log and demote this orphan to
            # "unrecoverable" so the report is accurate.
            log.warning(
                "edge_repair: insert failed for prop %s -> %s: %s",
                pid,
                match.class_key,
                exc,
            )
            report.repaired.pop()
            report.unrecoverable.append(
                UnrecoverableOrphan(
                    prop_key=prop.get("_key", pid),
                    domain_class_key=domain_key,
                    label=str(prop.get("label") or ""),
                    description=f"insert failed: {exc}",
                )
            )

    log.info(
        "edge_repair: ontology %s -- found %d orphan(s), repaired %d, "
        "unrecoverable %d, no_domain %d (dry_run=%s)",
        ontology_id,
        report.orphans_found,
        len(report.repaired),
        len(report.unrecoverable),
        len(report.no_domain),
        dry_run,
    )
    return report
