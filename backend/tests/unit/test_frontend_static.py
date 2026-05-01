"""Tests for ``app.frontend_static.resolve_frontend_out_dir``."""

from __future__ import annotations

from pathlib import Path

from app.frontend_static import resolve_frontend_out_dir


def _minimal_export(out: Path) -> None:
    (out / "index.html").write_text("<!DOCTYPE html><html></html>", encoding="utf-8")


def test_resolve_flat_bundle_layout(tmp_path: Path) -> None:
    bundle = tmp_path / "project"
    (bundle / "app").mkdir(parents=True)
    out = bundle / "frontend" / "out"
    out.mkdir(parents=True)
    _minimal_export(out)
    main_py = bundle / "app" / "main.py"
    main_py.write_text("#", encoding="utf-8")

    assert resolve_frontend_out_dir(str(main_py)) == out.resolve()


def test_resolve_monorepo_layout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "backend" / "app").mkdir(parents=True)
    out = repo / "frontend" / "out"
    out.mkdir(parents=True)
    _minimal_export(out)
    main_py = repo / "backend" / "app" / "main.py"
    main_py.write_text("#", encoding="utf-8")

    assert resolve_frontend_out_dir(str(main_py)) == out.resolve()


def test_resolve_returns_none_when_missing(tmp_path: Path) -> None:
    bundle = tmp_path / "project"
    (bundle / "app").mkdir(parents=True)
    main_py = bundle / "app" / "main.py"
    main_py.write_text("#", encoding="utf-8")

    assert resolve_frontend_out_dir(str(main_py)) is None


def test_resolve_explicit_override(tmp_path: Path) -> None:
    bundle = tmp_path / "project"
    (bundle / "app").mkdir(parents=True)
    main_py = bundle / "app" / "main.py"
    main_py.write_text("#", encoding="utf-8")
    custom = tmp_path / "custom-out"
    custom.mkdir()
    _minimal_export(custom)

    assert resolve_frontend_out_dir(str(main_py), override=str(custom)) == custom.resolve()


def test_resolve_override_invalid_falls_back_to_auto(tmp_path: Path) -> None:
    bundle = tmp_path / "project"
    (bundle / "app").mkdir(parents=True)
    out = bundle / "frontend" / "out"
    out.mkdir(parents=True)
    _minimal_export(out)
    main_py = bundle / "app" / "main.py"
    main_py.write_text("#", encoding="utf-8")

    assert (
        resolve_frontend_out_dir(str(main_py), override="/no/such/static/export") == out.resolve()
    )


def test_resolve_nested_when_service_prefix_matches_next_basepath(tmp_path: Path) -> None:
    bundle = tmp_path / "project"
    (bundle / "app").mkdir(parents=True)
    main_py = bundle / "app" / "main.py"
    main_py.write_text("#", encoding="utf-8")
    out = bundle / "frontend" / "out"
    nested = out / "_svc" / "myapp"
    nested.mkdir(parents=True)
    _minimal_export(nested)

    resolved = resolve_frontend_out_dir(
        str(main_py),
        service_url_path_prefix="/_svc/myapp",
    )
    assert resolved == nested.resolve()


def test_resolve_rejects_empty_frontend_out(tmp_path: Path) -> None:
    bundle = tmp_path / "project"
    (bundle / "app").mkdir(parents=True)
    out = bundle / "frontend" / "out"
    out.mkdir(parents=True)
    main_py = bundle / "app" / "main.py"
    main_py.write_text("#", encoding="utf-8")

    assert resolve_frontend_out_dir(str(main_py)) is None
