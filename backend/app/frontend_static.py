"""Locate the Next.js static export directory (``frontend/out``) for FastAPI."""

from __future__ import annotations

from pathlib import Path


def resolve_frontend_out_dir(main_module_file: str) -> Path | None:
    """Return a directory to serve as static HTML, or ``None``.

    Resolution order:

    1. **Flat bundle** (Container Manager): ``<root>/app/main.py`` → ``<root>/frontend/out``
    2. **Monorepo**: ``<repo>/backend/app/main.py`` → ``<repo>/frontend/out``
    3. **Unified Docker image**: ``/app/static``
    """
    here = Path(main_module_file).resolve()
    candidates = (
        here.parents[1] / "frontend" / "out",
        here.parents[2] / "frontend" / "out",
        Path("/app/static"),
    )
    for c in candidates:
        if c.is_dir():
            return c
    return None
