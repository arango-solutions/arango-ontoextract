"""Locate the Next.js static export directory (``frontend/out``) for FastAPI."""

from __future__ import annotations

from pathlib import Path


def _is_usable_next_static_out(path: Path) -> bool:
    """True only if this looks like a real Next static export (not an empty dir).

    Otherwise an empty ``frontend/out`` or placeholder ``/app/static`` would mount and
    every HTML route (``/login``, ``/dashboard``, …) returns 404 while blocking the
    minimal FastAPI ``/login`` fallback.
    """
    if not path.is_dir():
        return False
    return (path / "index.html").is_file()


def _expand_override_dir(override: str) -> Path | None:
    raw = override.strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    p = (Path.cwd() / p).resolve() if not p.is_absolute() else p.resolve()
    return p if p.is_dir() else None


def _resolve_candidate(
    candidate: Path,
    service_url_path_prefix: str,
    *,
    explicit_override: bool,
) -> Path | None:
    """Explicit path may already be the nested export dir; auto paths need basePath nesting."""
    if explicit_override and _is_usable_next_static_out(candidate):
        return candidate
    return _resolve_next_export_mount_dir(candidate, service_url_path_prefix)


def _resolve_next_export_mount_dir(out_root: Path, service_url_path_prefix: str) -> Path | None:
    """Next.js ``basePath`` exports nest pages under ``out/<basePath>/``, not ``out/index.html``.

    Requests are stripped to ``/workspace`` etc., so ``StaticFiles`` must use the nested
    folder as its root when ``SERVICE_URL_PATH_PREFIX`` matches ``basePath``.
    """
    prefix = (service_url_path_prefix or "").strip().strip("/")
    if prefix:
        nested = out_root
        for segment in prefix.split("/"):
            if not segment:
                continue
            nested = nested / segment
        if _is_usable_next_static_out(nested):
            return nested
    if _is_usable_next_static_out(out_root):
        return out_root
    return None


def resolve_frontend_out_dir(
    main_module_file: str,
    *,
    override: str | None = None,
    service_url_path_prefix: str = "",
) -> Path | None:
    """Return the directory ``StaticFiles`` should mount — or ``None``.

    Resolution order:

    1. **Explicit** — ``override`` (env ``AOE_FRONTEND_OUT_DIR`` / ``FRONTEND_STATIC_ROOT``)
    2. **Flat bundle** (Container Manager): ``<root>/app/main.py`` → ``<root>/frontend/out``
    3. **Monorepo**: ``<repo>/backend/app/main.py`` → ``<repo>/frontend/out``
    4. **Unified Docker image**: ``/app/static``

    When ``service_url_path_prefix`` matches Next ``basePath``, files live under
    ``frontend/out/<prefix>/``; that nested path is preferred over ``frontend/out/``.
    """
    if override is not None:
        o = _expand_override_dir(override)
        if o is not None:
            resolved = _resolve_candidate(
                o,
                service_url_path_prefix,
                explicit_override=True,
            )
            if resolved is not None:
                return resolved

    here = Path(main_module_file).resolve()
    for c in (
        here.parents[1] / "frontend" / "out",
        here.parents[2] / "frontend" / "out",
        Path("/app/static"),
    ):
        resolved = _resolve_candidate(c, service_url_path_prefix, explicit_override=False)
        if resolved is not None:
            return resolved
    return None
