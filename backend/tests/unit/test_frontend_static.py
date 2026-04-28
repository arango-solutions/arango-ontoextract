"""Tests for ``app.frontend_static.resolve_frontend_out_dir``."""

from __future__ import annotations

from pathlib import Path

from app.frontend_static import resolve_frontend_out_dir


def test_resolve_flat_bundle_layout(tmp_path: Path) -> None:
    bundle = tmp_path / "project"
    (bundle / "app").mkdir(parents=True)
    out = bundle / "frontend" / "out"
    out.mkdir(parents=True)
    main_py = bundle / "app" / "main.py"
    main_py.write_text("#", encoding="utf-8")

    assert resolve_frontend_out_dir(str(main_py)) == out.resolve()


def test_resolve_monorepo_layout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "backend" / "app").mkdir(parents=True)
    out = repo / "frontend" / "out"
    out.mkdir(parents=True)
    main_py = repo / "backend" / "app" / "main.py"
    main_py.write_text("#", encoding="utf-8")

    assert resolve_frontend_out_dir(str(main_py)) == out.resolve()


def test_resolve_returns_none_when_missing(tmp_path: Path) -> None:
    bundle = tmp_path / "project"
    (bundle / "app").mkdir(parents=True)
    main_py = bundle / "app" / "main.py"
    main_py.write_text("#", encoding="utf-8")

    assert resolve_frontend_out_dir(str(main_py)) is None
