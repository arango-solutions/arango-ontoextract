"""Unit tests for the requirements/CQ repo (Stream 22 / CQ-PR1)."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.db import requirements_repo as repo


class TestUpsert:
    def test_insert_when_absent(self) -> None:
        db = MagicMock()
        col = MagicMock()
        col.has.return_value = False
        db.collection.return_value = col
        out = repo.upsert_requirements(db, "ont1", {"purpose": "p", "use_cases": []})
        col.insert.assert_called_once()
        col.replace.assert_not_called()
        assert out["_key"] == "ont1"
        assert out["ontology_id"] == "ont1"
        assert "updated_at" in out

    def test_replace_when_present(self) -> None:
        db = MagicMock()
        col = MagicMock()
        col.has.return_value = True
        db.collection.return_value = col
        repo.upsert_requirements(db, "ont1", {"purpose": "p2"})
        col.replace.assert_called_once()
        col.insert.assert_not_called()


class TestGetDelete:
    def test_get_missing_collection(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = False
        assert repo.get_requirements(db, "ont1") is None

    def test_get_returns_doc(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        db.collection.return_value.get.return_value = {"_key": "ont1", "purpose": "p"}
        assert repo.get_requirements(db, "ont1")["purpose"] == "p"

    def test_delete_absent_is_false(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        db.collection.return_value.has.return_value = False
        assert repo.delete_requirements(db, "ont1") is False

    def test_delete_present_is_true(self) -> None:
        db = MagicMock()
        db.has_collection.return_value = True
        col = MagicMock()
        col.has.return_value = True
        db.collection.return_value = col
        assert repo.delete_requirements(db, "ont1") is True
        col.delete.assert_called_once_with("ont1")


class TestIterCompetencyQuestions:
    def test_flattens_and_annotates_use_case(self) -> None:
        spec = {
            "use_cases": [
                {
                    "name": "Fraud detection",
                    "competency_questions": [
                        {"text": "Which accounts are mule accounts?"},
                        {"text": "Who owns account X?"},
                    ],
                },
                {"name": "Empty UC", "competency_questions": []},
            ]
        }
        cqs = repo.iter_competency_questions(spec)
        assert len(cqs) == 2
        assert all(cq["use_case"] == "Fraud detection" for cq in cqs)

    def test_empty_spec(self) -> None:
        assert repo.iter_competency_questions({}) == []
