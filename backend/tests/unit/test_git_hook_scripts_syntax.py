"""Regression: git-hygiene shell scripts and pre-commit config must parse.

Covers:
  - bash `-n` syntax-check on every tracked shell script we ship for hooks.
  - PyYAML load of `.pre-commit-config.yaml` (catches bad indentation / tag
    mistakes before `pre-commit run` complains in someone's hook).
  - Sanity: stage names match the pre-commit framework's accepted values.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

SHELL_SCRIPTS = (
    "scripts/githooks/eslint-staged.sh",
    "scripts/smoke-test.sh",
    "scripts/setup-branch-protection.sh",
    "scripts/ensure-backend-deps.sh",
)

# Stages accepted by pre-commit framework v3.2+. Long names only — we
# don't allow the deprecated short aliases (`commit`, `push`).
ALLOWED_STAGES = {
    "manual",
    "pre-commit",
    "pre-merge-commit",
    "pre-push",
    "prepare-commit-msg",
    "commit-msg",
    "post-checkout",
    "post-commit",
    "post-merge",
    "post-rewrite",
}


@pytest.mark.parametrize("relative", SHELL_SCRIPTS)
def test_shell_scripts_have_valid_bash_syntax(relative: str) -> None:
    script = REPO_ROOT / relative
    assert script.is_file(), f"missing tracked script {script}"
    subprocess.run(["bash", "-n", str(script)], check=True)


def test_pre_commit_config_parses_and_uses_supported_stages() -> None:
    yaml = pytest.importorskip("yaml")
    config_path = REPO_ROOT / ".pre-commit-config.yaml"
    assert config_path.is_file(), f"missing {config_path}"

    with config_path.open(encoding="utf-8") as fh:
        config = yaml.safe_load(fh)

    assert isinstance(config, dict)
    assert config.get("default_install_hook_types"), (
        ".pre-commit-config.yaml must set default_install_hook_types so "
        "`pre-commit install` wires up both pre-commit and pre-push."
    )
    for stage in config.get("default_install_hook_types", []):
        assert stage in ALLOWED_STAGES, f"unsupported install hook type: {stage}"
    for stage in config.get("default_stages", []):
        assert stage in ALLOWED_STAGES, f"unsupported default stage: {stage}"

    for repo in config.get("repos", []):
        for hook in repo.get("hooks", []):
            for stage in hook.get("stages", []):
                assert stage in ALLOWED_STAGES, (
                    f"hook {hook.get('id')!r} uses unsupported stage {stage!r}"
                )


def test_eslint_staged_wrapper_strips_frontend_prefix() -> None:
    """The wrapper must strip the leading `frontend/` so eslint runs from
    `frontend/` with paths it can resolve."""
    wrapper = (REPO_ROOT / "scripts/githooks/eslint-staged.sh").read_text(encoding="utf-8")
    assert 'rel+=("${f#frontend/}")' in wrapper, (
        "eslint-staged.sh must strip the frontend/ prefix from each path"
    )
    assert 'cd "${ROOT}/frontend"' in wrapper, (
        "eslint-staged.sh must cd into frontend/ before invoking eslint"
    )
