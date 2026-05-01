"""Regression test for Arango manual packaging tarball layout."""

from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path


def _repo_root() -> Path:
    # backend/tests/unit/test_*.py -> parents[3] == repo root
    return Path(__file__).resolve().parents[3]


def test_arango_manual_tarball_contains_expected_layout(tmp_path: Path) -> None:
    repo_root = _repo_root()
    script = repo_root / "scripts" / "package-arango-manual.sh"
    out = tmp_path / "pkg.tar.gz"
    subprocess.run(
        ["bash", str(script), str(out)],
        check=True,
        cwd=str(repo_root),
    )
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
