"""Version wiring regression tests.

``app/__init__.py:__version__`` is the single source of truth (the build reads
it via ``[tool.hatch.version]``; runtime surfaces import it). These tests guard
against a regression to per-file hardcoded versions, which is exactly how the
manifests drifted to a stale ``0.1.0`` while tagged releases moved on.
"""

from __future__ import annotations

import re

import app


def test_version_is_pep440_dev_or_release() -> None:
    # Accept either a tagged release (X.Y.Z) or a dev line (X.Y.Z.devN).
    assert re.fullmatch(r"\d+\.\d+\.\d+(\.dev\d+)?", app.__version__), (
        f"unexpected version format: {app.__version__!r}"
    )


def test_fastapi_app_reports_the_single_source_version() -> None:
    import app.main as main

    assert main.app.version == app.__version__


def test_tracing_resource_uses_the_single_source_version() -> None:
    # The OTel resource embeds the same version string; assert the module
    # imports the shared symbol rather than a literal.
    from app.observability import tracing

    assert tracing.__version__ == app.__version__
