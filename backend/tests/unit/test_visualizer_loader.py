"""Regression tests for ``_load_visualizer_installer`` CWD-independence.

``make backend`` launches the dev server with ``cd backend && uvicorn
app.main:app``, so the process CWD is ``backend/`` and the repo root that
holds the top-level ``scripts`` package is NOT on ``sys.path``. Before the
fix, ``_load_visualizer_installer`` did a bare ``from scripts.setup.
install_visualizer import ...`` which blew up with
``ModuleNotFoundError: No module named 'scripts'`` on every post-extraction
visualizer auto-install (Tim Darr's traceback).

These tests are deliberately isolated in their own module (the big
``test_extraction_service.py`` autouse-mocks ``_load_visualizer_installer``
to keep the real import from polluting ``sys.modules``), and they fully
save/restore ``sys.path`` + ``scripts*`` modules so they don't leak that
state into sibling tests.
"""

from __future__ import annotations

import sys
from pathlib import Path

import app.services.extraction as extraction_mod
from app.services.extraction import _load_visualizer_installer

_REPO_ROOT = str(Path(extraction_mod.__file__).resolve().parents[3])


def _snapshot_import_state() -> tuple[list[str], dict]:
    return list(sys.path), {k: v for k, v in sys.modules.items() if k.split(".")[0] == "scripts"}


def _restore_import_state(saved_path: list[str], saved_scripts: dict) -> None:
    sys.path[:] = saved_path
    for key in [k for k in sys.modules if k.split(".")[0] == "scripts"]:
        if key not in saved_scripts:
            del sys.modules[key]
    sys.modules.update(saved_scripts)


def test_repo_root_resolution_points_at_scripts_package() -> None:
    # parents[3] of backend/app/services/extraction.py is the repo root,
    # which must actually contain the script we import.
    assert Path(_REPO_ROOT, "scripts", "setup", "install_visualizer.py").is_file()


def test_loader_imports_even_when_repo_root_missing_from_syspath() -> None:
    saved_path, saved_scripts = _snapshot_import_state()
    try:
        # Simulate the ``cd backend && uvicorn`` launch: repo root absent
        # from sys.path and no cached ``scripts`` modules.
        sys.path[:] = [p for p in sys.path if Path(p).resolve() != Path(_REPO_ROOT).resolve()]
        for key in [k for k in sys.modules if k.split(".")[0] == "scripts"]:
            del sys.modules[key]
        assert _REPO_ROOT not in sys.path

        installer = _load_visualizer_installer()

        assert callable(installer)
        assert installer.__name__ == "install_for_ontology_graph"
        # The loader put the repo root back so the import could resolve.
        assert _REPO_ROOT in sys.path
    finally:
        _restore_import_state(saved_path, saved_scripts)


def test_loader_is_idempotent_and_does_not_duplicate_syspath_entries() -> None:
    saved_path, saved_scripts = _snapshot_import_state()
    try:
        _load_visualizer_installer()
        _load_visualizer_installer()
        assert sys.path.count(_REPO_ROOT) == 1
    finally:
        _restore_import_state(saved_path, saved_scripts)
