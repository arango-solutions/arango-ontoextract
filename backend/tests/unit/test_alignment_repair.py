"""Unit tests for alignment incoherence repair (Stream 20 / AL-PR7)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import alignment_repair as rep


def _corr(key: str, a: tuple[str, str], b: tuple[str, str], conf: float) -> dict:
    return {
        "_key": key,
        "source_a": {"ontology_id": a[0], "entity_key": a[1]},
        "source_b": {"ontology_id": b[0], "entity_key": b[1]},
        "confidence": conf,
    }


class TestBuildDisjointPairs:
    def test_maps_edges_to_node_pairs(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        rows = [{"oid": "A", "from": "ontology_classes/X", "to": "ontology_classes/Z"}]
        with patch.object(rep, "run_aql", return_value=iter(rows)):
            pairs = rep.build_disjoint_pairs(db, ["A", "B"])
        assert pairs == {frozenset({("A", "X"), ("A", "Z")})}

    def test_empty_when_collection_missing(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        assert rep.build_disjoint_pairs(db, ["A"]) == set()

    def test_empty_when_no_ontologies(self) -> None:
        db = MagicMock()
        assert rep.build_disjoint_pairs(db, []) == set()


class TestRepairCorrespondences:
    def test_no_disjoint_pairs_keeps_everything(self) -> None:
        corrs = [_corr("c1", ("A", "X"), ("B", "Y"), 0.9)]
        kept, removals = rep.repair_correspondences(corrs, set())
        assert kept == corrs
        assert removals == []

    def test_removes_lowest_confidence_edge_on_conflict_path(self) -> None:
        # A.X and A.Z are disjoint; both aligned to B.Y -> one incoherent cluster.
        c1 = _corr("c1", ("A", "X"), ("B", "Y"), 0.9)  # keep (higher conf)
        c2 = _corr("c2", ("A", "Z"), ("B", "Y"), 0.6)  # drop (lower conf)
        disjoint = {frozenset({("A", "X"), ("A", "Z")})}

        kept, removals = rep.repair_correspondences([c1, c2], disjoint)

        assert [c["_key"] for c in kept] == ["c1"]  # only the low-conf edge removed
        assert len(removals) == 1
        assert removals[0]["correspondence_key"] == "c2"
        assert removals[0]["confidence"] == 0.6
        # the removal names the disjoint pair it resolved
        conflict = removals[0]["resolves_conflict"]
        assert {tuple(conflict["a"]), tuple(conflict["b"])} == {("A", "X"), ("A", "Z")}
        # after repair the disjoint pair no longer shares a cluster
        clusters = rep._clusters(kept)
        assert clusters.get(("A", "X")) != clusters.get(("A", "Z"))

    def test_minimal_no_removal_when_coherent(self) -> None:
        # X≡Y and P≡Q; disjoint pair (X, P) never merged -> coherent, no removals.
        c1 = _corr("c1", ("A", "X"), ("B", "Y"), 0.5)
        c2 = _corr("c2", ("A", "P"), ("B", "Q"), 0.5)
        disjoint = {frozenset({("A", "X"), ("A", "P")})}
        kept, removals = rep.repair_correspondences([c1, c2], disjoint)
        assert len(kept) == 2
        assert removals == []

    def test_iterates_over_multiple_conflicts(self) -> None:
        # Two independent incoherent clusters, each resolved by one removal.
        corrs = [
            _corr("c1", ("A", "X"), ("B", "Y"), 0.9),
            _corr("c2", ("A", "Z"), ("B", "Y"), 0.4),  # drop
            _corr("c3", ("A", "M"), ("B", "N"), 0.8),
            _corr("c4", ("A", "K"), ("B", "N"), 0.3),  # drop
        ]
        disjoint = {
            frozenset({("A", "X"), ("A", "Z")}),
            frozenset({("A", "M"), ("A", "K")}),
        }
        kept, removals = rep.repair_correspondences(corrs, disjoint)
        assert sorted(r["correspondence_key"] for r in removals) == ["c2", "c4"]
        assert sorted(c["_key"] for c in kept) == ["c1", "c3"]

    def test_tie_breaks_on_key(self) -> None:
        # Equal confidence -> lexicographically smallest key is the victim.
        c1 = _corr("c_a", ("A", "X"), ("B", "Y"), 0.5)
        c2 = _corr("c_b", ("A", "Z"), ("B", "Y"), 0.5)
        disjoint = {frozenset({("A", "X"), ("A", "Z")})}
        _, removals = rep.repair_correspondences([c1, c2], disjoint)
        assert removals[0]["correspondence_key"] == "c_a"


class TestCheckCoherence:
    def test_reports_incoherence_and_proposed_removals(self) -> None:
        db = MagicMock()
        c1 = _corr("c1", ("A", "X"), ("B", "Y"), 0.9)
        c2 = _corr("c2", ("A", "Z"), ("B", "Y"), 0.6)
        with patch.object(
            rep, "build_disjoint_pairs", return_value={frozenset({("A", "X"), ("A", "Z")})}
        ):
            report = rep.check_alignment_coherence(
                db, correspondences=[c1, c2], ontology_ids=["A", "B"]
            )
        assert report["coherent"] is False  # incoherent before repair
        assert report["removed_count"] == 1
        assert report["kept_count"] == 1
        assert report["disjoint_axioms"] == 1
