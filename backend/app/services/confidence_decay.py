"""Confidence decay over time for live ontology classes (Stream 11 IBR.3).

Why this exists
---------------

Per PRD §6.16 / ADR-008, a class's confidence should drift downward when
no new evidence arrives -- a stale belief that hasn't been re-affirmed
in months is less credible than a freshly-corroborated one, even if
both were extracted with identical agreement and faithfulness scores.

This is *separate from* the multi-signal blender in
:mod:`app.services.confidence`. The blender computes the *extraction
confidence* (signal 9 includes evidence age, but contributes only ~5%
of the weight). Decay is a post-hoc pure age-based dampener that runs
periodically as part of Phase 4 background consolidation.

Output contract
---------------

The decay job writes ``current_confidence`` (the decayed value) and
``confidence_decayed_at`` (the timestamp of this decay run) onto each
class. The original ``confidence`` field is left intact -- it remains
the immutable extraction confidence. UI / API consumers should prefer
``current_confidence`` when present, falling back to ``confidence``.

Feature flag
------------

Decay is gated behind ``settings.belief_revision_decay_enabled``
(default ``False``). When the flag is off:

* ``dry_run=True`` calls still compute and report what decay *would*
  do -- useful for previewing before enabling.
* ``dry_run=False`` returns ``DecayReport(enabled=False, ...)`` with
  zero writes.

This matches the safety-hardened pattern from
Graph-Native Cognitive Memory (admin-triggered first; scheduled second).
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field
from typing import Any

from app.config import settings
from app.db.temporal_constants import NEVER_EXPIRES
from app.db.utils import run_aql

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pure decay calculation
# ---------------------------------------------------------------------------


def compute_decayed_confidence(
    current_confidence: float,
    age_seconds: float,
    *,
    half_life_days: float,
    floor: float,
) -> float:
    """Apply exponential decay with a floor; pure function, fully testable.

    Returns ``current_confidence`` unchanged when ``age_seconds <= 0``
    (just-touched / clock skew). The decay curve is the standard
    half-life form: ``conf * 2^(-age / half_life)``. The result is
    clamped to ``[floor, current_confidence]`` -- decay never increases
    confidence and never drops below the floor.
    """
    if age_seconds <= 0:
        return current_confidence
    half_life_seconds = max(half_life_days * 86400.0, 1.0)
    decayed = current_confidence * math.exp(-age_seconds * math.log(2) / half_life_seconds)
    # Two-step clamp so the result is never *raised* by the floor:
    # 1. Floor the decay output (decayed value can't drop below floor).
    # 2. Cap at current_confidence (decay can't increase a value, even
    #    when the input was already below the floor -- the floor is
    #    descriptive of "how low decay is allowed to drag a value",
    #    not a target the function pushes everything up to).
    return min(current_confidence, max(floor, decayed))


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class DecayedClass:
    class_key: str
    confidence_before: float
    confidence_after: float
    age_seconds: float


@dataclass
class DecayReport:
    ontology_id: str
    enabled: bool
    dry_run: bool
    half_life_days: float
    floor: float
    classes_examined: int = 0
    classes_decayed: int = 0
    decayed: list[DecayedClass] = field(default_factory=list)
    skipped_no_age: int = 0  # classes with no usable ``created`` timestamp

    def to_dict(self) -> dict[str, Any]:
        """Serialisable summary for the admin endpoint and logs."""
        return {
            "ontology_id": self.ontology_id,
            "enabled": self.enabled,
            "dry_run": self.dry_run,
            "half_life_days": self.half_life_days,
            "floor": self.floor,
            "classes_examined": self.classes_examined,
            "classes_decayed": self.classes_decayed,
            "skipped_no_age": self.skipped_no_age,
            "decayed": [
                {
                    "class_key": d.class_key,
                    "confidence_before": d.confidence_before,
                    "confidence_after": d.confidence_after,
                    "age_seconds": d.age_seconds,
                }
                for d in self.decayed
            ],
        }


def _resolve_class_age(class_doc: dict[str, Any], now: float) -> float | None:
    """Best-effort age-of-evidence estimate for one class, in seconds.

    Preference order:

    1. ``last_evidenced_at`` -- written by the belief-revision pipeline
       (IBR.5 +) when new evidence reinforces a class. This is the
       cleanest signal but is not present on legacy ontologies.
    2. ``created`` -- the temporal interval start. Always present on
       versioned vertices; means "we haven't touched this class
       since it was first extracted".

    Returns ``None`` when neither field is a usable Unix timestamp,
    so the orchestrator can ``skipped_no_age``-track the class.
    """
    for field_name in ("last_evidenced_at", "created"):
        value = class_doc.get(field_name)
        if isinstance(value, (int, float)) and value > 0:
            return max(0.0, now - float(value))
    return None


def apply_confidence_decay(
    db: Any,
    ontology_id: str,
    *,
    dry_run: bool = False,
    now: float | None = None,
    half_life_days: float | None = None,
    floor: float | None = None,
    force: bool = False,
) -> DecayReport:
    """Apply confidence decay to every live class in an ontology.

    Parameters
    ----------
    db:
        ArangoDB ``StandardDatabase`` (or duck-typed mock for tests).
    ontology_id:
        Scope.
    dry_run:
        If ``True``, compute and report decay without writing. Always
        permitted, even when the feature flag is off.
    now:
        Override the wall-clock (defaults to ``time.time()``). For tests.
    half_life_days, floor:
        Override the configured defaults. For per-ontology tuning.
    force:
        If ``True``, ignore ``settings.belief_revision_decay_enabled``
        and run live writes anyway. Reserved for the admin endpoint /
        runbook; *not* used by the scheduled job.

    Returns
    -------
    DecayReport
        Always populated. When the feature flag is off and ``dry_run``
        and ``force`` are both ``False``, ``enabled=False`` and
        ``classes_examined=0``.
    """
    enabled = bool(settings.belief_revision_decay_enabled)
    half_life = (
        half_life_days
        if half_life_days is not None
        else float(settings.belief_revision_decay_half_life_days)
    )
    decay_floor = floor if floor is not None else float(settings.belief_revision_decay_floor)
    report = DecayReport(
        ontology_id=ontology_id,
        enabled=enabled,
        dry_run=dry_run,
        half_life_days=half_life,
        floor=decay_floor,
    )

    # Disabled and not previewing -> early return; no DB work.
    if not enabled and not dry_run and not force:
        log.info(
            "confidence_decay: feature flag is off and not dry-running -- "
            "ontology %s skipped (set belief_revision_decay_enabled=True or "
            "pass dry_run=True to preview)",
            ontology_id,
        )
        return report

    if not db.has_collection("ontology_classes"):
        log.info("confidence_decay: ontology_classes collection missing -- nothing to do")
        return report

    if now is None:
        now = time.time()

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

    cls_col = db.collection("ontology_classes")
    write_live = (enabled or force) and not dry_run

    for cls in classes:
        report.classes_examined += 1
        ckey = cls.get("_key")
        if not isinstance(ckey, str):
            continue
        current_conf = cls.get("current_confidence")
        if not isinstance(current_conf, (int, float)):
            current_conf = cls.get("confidence")
        if not isinstance(current_conf, (int, float)):
            # No confidence to decay -- skip without inflating no-age count.
            continue

        age = _resolve_class_age(cls, now)
        if age is None:
            report.skipped_no_age += 1
            continue

        decayed = compute_decayed_confidence(
            float(current_conf),
            age,
            half_life_days=half_life,
            floor=decay_floor,
        )
        # Only record / write when decay actually moved the value. Saves
        # noise in the report and avoids gratuitous writes when most
        # classes are well within the first half-life.
        if decayed >= float(current_conf):
            continue

        report.classes_decayed += 1
        report.decayed.append(
            DecayedClass(
                class_key=ckey,
                confidence_before=float(current_conf),
                confidence_after=decayed,
                age_seconds=age,
            )
        )
        if write_live:
            try:
                cls_col.update(
                    {
                        "_key": ckey,
                        "current_confidence": decayed,
                        "confidence_decayed_at": now,
                    }
                )
            except Exception as exc:
                log.warning(
                    "confidence_decay: write failed for class %s: %s",
                    ckey,
                    exc,
                )
                # Roll back this entry from the report so the report
                # accurately reflects what's persisted.
                report.classes_decayed -= 1
                report.decayed.pop()

    log.info(
        "confidence_decay: ontology=%s enabled=%s dry_run=%s "
        "examined=%d decayed=%d skipped_no_age=%d (half_life=%.1fd, floor=%.3f)",
        ontology_id,
        enabled,
        dry_run,
        report.classes_examined,
        report.classes_decayed,
        report.skipped_no_age,
        half_life,
        decay_floor,
    )
    return report
