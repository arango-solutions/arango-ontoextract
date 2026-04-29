"""Locate the Next.js static export directory (``frontend/out``) for FastAPI."""

from __future__ import annotations

from pathlib import Path


def _normalize_override(override: str) -> Path | None:
    raw = override.strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = (Path.cwd() / p).resolve()
    else:
        p = p.resolve()
    return p if p.is_dir() else None


def resolve_frontend_out_dir(
    main_module_file: str,
    *,
    override: str | None = None,
) -> Path | None:
    """Return a directory to serve as static HTML, or ``None``.

    Resolution order:

    1. **Explicit** — ``override`` (env ``AOE_FRONTEND_OUT_DIR`` / ``FRONTEND_STATIC_ROOT``)
    2. **Flat bundle** (Container Manager): ``<root>/app/main.py`` → ``<root>/frontend/out``
    3. **Monorepo**: ``<repo>/backend/app/main.py`` → ``<repo>/frontend/out``
    4. **Unified Docker image**: ``/app/static``
    """
    candidates: list[Path] = []
    if override is not None:
        o = _normalize_override(override)
        if o is not None:
            candidates.append(o)

    here = Path(main_module_file).resolve()
    candidates.extend(
        (
            here.parents[1] / "frontend" / "out",
            here.parents[2] / "frontend" / "out",
            Path("/app/static"),
        ),
    )
    for c in candidates:
        if c.is_dir():
            return c
    return None
