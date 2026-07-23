"""Alignment evaluation harness (Stream 20 / AL-PR9, PRD §6.17 FR-17.11).

Scores a produced alignment against a reference (gold) alignment and reports
human-effort efficiency, over a seeded, deterministic fixture:

* Precision / recall / F1 of the auto-accept baseline (zero human interaction).
* The OAEI-Interactive interaction-count-vs-F-measure curve — how F1 rises as a
  human oracle confirms borderline correspondences in ranked order.
* The headline number: how many confirmations are needed to reach a target F1.

Run from the repo root::

    python -m benchmarks.operations.bench_alignment

The reusable metric functions live in ``app.services.alignment_eval`` (unit-tested
under the backend gate); this module supplies the fixture + report + CLI.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# Add the backend to sys.path so this script imports ``app.*`` when run as
# ``python -m benchmarks.operations.bench_alignment`` from the repo root without
# an editable install (mirrors bench_api_latency.py).
_REPO_ROOT = Path(__file__).resolve().parents[2]
_BACKEND = _REPO_ROOT / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from app.services.alignment_eval import (  # noqa: E402
    interaction_curve,
    interactions_to_target,
    pair_from_correspondence,
    prf1,
)

AUTO_ACCEPT_BAND = 0.9
TARGET_F1 = 0.9


def _corr(a_key: str, b_key: str, confidence: float) -> dict[str, Any]:
    return {
        "source_a": {"ontology_id": "onA", "entity_key": a_key},
        "source_b": {"ontology_id": "onB", "entity_key": b_key},
        "confidence": confidence,
    }


def seeded_fixture() -> tuple[list[dict[str, Any]], set[Any]]:
    """A deterministic 2-ontology fixture: candidate correspondences + gold set.

    Six true correspondences (R1..R6) plus two false positives. Confidences are
    laid out so two true matches and one false positive auto-accept (precision
    drag), and the remaining true matches sit in the borderline band where a human
    oracle confirms them — a realistic mix for the interaction curve.
    """
    candidates = [
        _corr("a1", "b1", 0.97),  # R1 — auto-accept, true
        _corr("a2", "b2", 0.95),  # R2 — auto-accept, true
        _corr("a9", "b9", 0.93),  # FP — auto-accept, false (caps precision)
        _corr("a3", "b3", 0.80),  # R3 — borderline, true
        _corr("a4", "b4", 0.75),  # R4 — borderline, true
        _corr("a8", "b8", 0.70),  # FP — borderline, false (oracle rejects)
        _corr("a5", "b5", 0.65),  # R5 — borderline, true
        _corr("a6", "b6", 0.55),  # R6 — borderline, true
    ]
    reference = {
        pair_from_correspondence(_corr(a, b, 1.0))
        for a, b in [
            ("a1", "b1"),
            ("a2", "b2"),
            ("a3", "b3"),
            ("a4", "b4"),
            ("a5", "b5"),
            ("a6", "b6"),
        ]
    }
    return candidates, reference


def run(
    *,
    auto_accept_band: float = AUTO_ACCEPT_BAND,
    target_f1: float = TARGET_F1,
) -> dict[str, Any]:
    """Compute the alignment evaluation report over the seeded fixture."""
    candidates, reference = seeded_fixture()
    eval_cands = [
        {"pair": pair_from_correspondence(c), "confidence": c["confidence"]}
        for c in candidates
    ]

    baseline = prf1(
        {c["pair"] for c in eval_cands if c["confidence"] >= auto_accept_band},
        reference,
    )
    curve = interaction_curve(eval_cands, reference, auto_accept_band=auto_accept_band)
    return {
        "auto_accept_band": auto_accept_band,
        "target_f1": target_f1,
        "reference_size": len(reference),
        "candidate_count": len(candidates),
        "baseline": baseline,  # 0 interactions
        "final": curve[-1],  # full human confirmation
        "curve": curve,
        "interactions_to_target": interactions_to_target(curve, target_f1),
        "max_interactions": curve[-1]["interactions"],
    }


def format_report(report: dict[str, Any]) -> str:
    lines = [
        "Alignment evaluation (AL-PR9)",
        "=" * 48,
        f"reference size:   {report['reference_size']} gold correspondences",
        f"candidates:       {report['candidate_count']}",
        f"auto-accept band: {report['auto_accept_band']}",
        "",
        "baseline (0 interactions): "
        f"P={report['baseline']['precision']} R={report['baseline']['recall']} "
        f"F1={report['baseline']['f1']}",
        "final (all confirmed):     "
        f"P={report['final']['precision']} R={report['final']['recall']} "
        f"F1={report['final']['f1']}",
        "",
        f"interactions to F1>={report['target_f1']}: {report['interactions_to_target']} "
        f"(of {report['max_interactions']} borderline)",
        "",
        "interaction curve (interactions -> F1):",
    ]
    lines += [f"  {p['interactions']:>2} -> {p['f1']:.3f}" for p in report["curve"]]
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover -- script entry point
    print(format_report(run()))
