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


def test_default_extraction_model_is_not_the_deprecated_snapshot() -> None:
    """Regression: the bundled default must not be a retired model id.

    ``claude-sonnet-4-20250514`` was deprecated by Anthropic (retires
    2026-06-15) and already returns HTTP 404 ``not_found_error`` for most
    keys, which silently failed every extraction batch for fresh installs
    that didn't override ``LLM_EXTRACTION_MODEL``. Pin the class default so a
    future edit can't quietly reintroduce a dead model id.
    """
    default = app_config.Settings.model_fields["llm_extraction_model"].default
    assert default == "claude-sonnet-4-6", default
    assert "20250514" not in default
