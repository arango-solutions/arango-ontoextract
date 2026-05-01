"""Regression: .env resolution must not depend on process cwd (Container Manager uses /project)."""

from __future__ import annotations

from pathlib import Path

import app.config as app_config


def test_resolved_env_files_helpers_exist() -> None:
    paths = app_config._resolved_env_files()
    assert isinstance(paths, tuple)
    for p in paths:
        assert Path(p).is_file(), p


def test_settings_loads_without_cwd_dependent_dotdot_env() -> None:
    """Smoke: Settings() imports; env files resolved from this file's location."""
    assert app_config.settings.effective_arango_host
