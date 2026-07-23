"""Unit tests for alignment evaluation metrics (Stream 20 / AL-PR9)."""

from __future__ import annotations

from app.services import alignment_eval as ev


class TestNormPair:
    def test_order_independent(self) -> None:
        p1 = ev.norm_pair("A", "x", "B", "y")
        p2 = ev.norm_pair("B", "y", "A", "x")
        assert p1 == p2

    def test_from_correspondence(self) -> None:
        c = {
            "source_a": {"ontology_id": "A", "entity_key": "x"},
            "source_b": {"ontology_id": "B", "entity_key": "y"},
        }
        assert ev.pair_from_correspondence(c) == ev.norm_pair("A", "x", "B", "y")


class TestPrf1:
    def test_perfect(self) -> None:
        ref = {("a",), ("b",)}  # opaque hashable pairs are fine for prf1
        out = ev.prf1({("a",), ("b",)}, ref)
        assert out["precision"] == 1.0
        assert out["recall"] == 1.0
        assert out["f1"] == 1.0

    def test_partial(self) -> None:
        ref = {1, 2, 3, 4}
        pred = {1, 2, 99}  # 2 tp, 1 fp, 2 fn
        out = ev.prf1(pred, ref)
        assert out["tp"] == 2 and out["fp"] == 1 and out["fn"] == 2
        assert out["precision"] == round(2 / 3, 4)
        assert out["recall"] == 0.5
        assert out["f1"] == round(2 * (2 / 3) * 0.5 / ((2 / 3) + 0.5), 4)

    def test_empty_prediction(self) -> None:
        out = ev.prf1(set(), {1, 2})
        assert out == {"precision": 0.0, "recall": 0.0, "f1": 0.0, "tp": 0, "fp": 0, "fn": 2}


def _cand(pair: int, conf: float) -> dict:
    return {"pair": pair, "confidence": conf}


class TestInteractionCurve:
    def test_baseline_and_rising_curve(self) -> None:
        # reference = {1,2,3}. auto (>=0.9): pair 1 (tp), pair 9 (fp).
        # borderline: pair 2 (tp, .8), pair 8 (fp, .7), pair 3 (tp, .6).
        reference = {1, 2, 3}
        cands = [
            _cand(1, 0.95),
            _cand(9, 0.92),
            _cand(2, 0.80),
            _cand(8, 0.70),
            _cand(3, 0.60),
        ]
        curve = ev.interaction_curve(cands, reference, auto_accept_band=0.9)
        # 0 interactions: aligned={1,9} -> tp1 fp1 fn2
        assert curve[0]["interactions"] == 0
        assert curve[0]["tp"] == 1 and curve[0]["fp"] == 1 and curve[0]["fn"] == 2
        # confirmations happen in confidence order: 2 (tp), 8 (fp reject), 3 (tp)
        assert curve[1]["tp"] == 2  # pair 2 added
        assert curve[2]["tp"] == 2  # pair 8 rejected -> unchanged
        assert curve[3]["tp"] == 3 and curve[3]["fn"] == 0  # pair 3 added
        # precision capped by the auto-accepted false positive (pair 9)
        assert curve[3]["precision"] == 0.75  # 3 tp / 4 predicted

    def test_ranking_respects_priority_key(self) -> None:
        reference = {2}
        cands = [_cand(1, 0.8), _cand(2, 0.5)]  # pair1 fp higher conf, pair2 tp lower
        # default (confidence desc): pair1 first (reject), then pair2 (accept)
        default = ev.interaction_curve(cands, reference, auto_accept_band=0.9)
        assert default[1]["tp"] == 0 and default[2]["tp"] == 1
        # priority key that surfaces the true match first
        pri = ev.interaction_curve(
            cands,
            reference,
            auto_accept_band=0.9,
            priority_key=lambda c: 0 if c["pair"] == 2 else 1,
        )
        assert pri[1]["tp"] == 1  # pair 2 confirmed on the first interaction


class TestInteractionsToTarget:
    def test_returns_first_reaching_interaction(self) -> None:
        curve = [
            {"interactions": 0, "f1": 0.4},
            {"interactions": 1, "f1": 0.7},
            {"interactions": 2, "f1": 0.91},
        ]
        assert ev.interactions_to_target(curve, 0.9) == 2

    def test_none_when_never_reached(self) -> None:
        curve = [{"interactions": 0, "f1": 0.4}, {"interactions": 1, "f1": 0.6}]
        assert ev.interactions_to_target(curve, 0.9) is None


class TestBenchFixture:
    def test_bench_run_is_deterministic_and_reaches_target(self) -> None:
        # The bench module lives at the repo root (outside the backend package);
        # put the repo root on sys.path so it is importable from the backend tests.
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))
        from benchmarks.operations.bench_alignment import run

        report = run()
        assert report["reference_size"] == 6
        assert report["baseline"]["f1"] == 0.4444
        assert report["final"]["f1"] == 0.9231
        assert report["interactions_to_target"] == 5
        # curve is monotonic non-decreasing in F1
        f1s = [p["f1"] for p in report["curve"]]
        assert f1s == sorted(f1s)
