"""Regression test for Arango manual packaging tarball layout."""

from __future__ import annotations

import os
import subprocess
import tarfile
from pathlib import Path


def _repo_root() -> Path:
    # backend/tests/unit/test_*.py -> parents[3] == repo root
    return Path(__file__).resolve().parents[3]


def _build_tarball(out: Path, *, env_overrides: dict[str, str] | None = None) -> None:
    repo_root = _repo_root()
    script = repo_root / "scripts" / "package-arango-manual.sh"
    env = os.environ.copy()
    if env_overrides:
        env.update(env_overrides)
    subprocess.run(
        ["bash", str(script), str(out)],
        check=True,
        cwd=str(repo_root),
        env=env,
    )


def _flat_names(path: Path) -> set[str]:
    with tarfile.open(path, "r:gz") as tf:
        return {n.removeprefix("./").strip("/") for n in tf.getnames()}


def test_arango_manual_tarball_contains_expected_layout(tmp_path: Path) -> None:
    out = tmp_path / "pkg.tar.gz"
    _build_tarball(out)
    with tarfile.open(out, "r:gz") as tf:
        names = sorted(tf.getnames())
        members = {m.name: m for m in tf.getmembers()}
    # Flat archive: paths are entrypoint, pyproject.toml, app/… (no myservice/ prefix).
    flat = {n.removeprefix("./").strip("/") for n in names}
    assert "entrypoint" in flat, names[:30]
    assert "pyproject.toml" in flat
    assert "uv.lock" in flat
    assert "app/main.py" in flat
    ep_key = next(
        k for k in members if k.endswith("entrypoint") and "/" not in k.removeprefix("./")
    )
    assert members[ep_key].mode & 0o100, "entrypoint must be executable in archive"


def test_dotenv_excluded_by_default(tmp_path: Path) -> None:
    """Repo .env (which typically contains real API keys) must not leak into the
    bundle unless the operator explicitly opts in."""
    repo_root = _repo_root()
    if not (repo_root / ".env").is_file():
        # No local .env to leak; nothing to verify.
        return
    out = tmp_path / "pkg.tar.gz"
    _build_tarball(out)
    assert ".env" not in _flat_names(out), (
        "Default packaging must NOT bundle repo .env; set PACKAGE_INCLUDE_ENV=1 to opt in."
    )


def test_dotenv_included_when_opted_in(tmp_path: Path) -> None:
    repo_root = _repo_root()
    if not (repo_root / ".env").is_file():
        # Can't verify the opt-in path without a local .env file; skip rather
        # than create a synthetic one (would risk overwriting real config).
        return
    out = tmp_path / "pkg.tar.gz"
    _build_tarball(out, env_overrides={"PACKAGE_INCLUDE_ENV": "1"})
    assert ".env" in _flat_names(out), (
        "PACKAGE_INCLUDE_ENV=1 must bundle repo .env into the tarball."
    )
