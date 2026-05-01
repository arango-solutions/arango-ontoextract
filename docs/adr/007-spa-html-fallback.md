# ADR 007: SPA `<path>.html` Fallback for Next.js Static Exports

**Status:** Accepted
**Date:** 2026-04-30
**Decision Makers:** AOE Core Team

---

## Context

When AOE is deployed via the Arango Container Manager (manual packaging),
FastAPI serves the Next.js frontend as a static export from
`frontend/out/` — there is no separate Node runtime in the pod, just
uvicorn + the FastAPI app. The static bundle is mounted under
`StaticFiles` somewhere inside `backend/app/main.py`.

Two facts about the deployment shape this decision:

1. **The frontend uses `output: 'export'` + `basePath`** (Next 15). Together,
   these emit a **flat** export tree:

   ```
   frontend/out/
   ├── _next/static/…
   ├── 404.html
   ├── library.html         ← per-route HTML, not library/index.html
   ├── workspace.html
   ├── upload.html
   ├── ontology/
   │   └── edit.html
   └── <basePath>/          ← only the index page is nested under basePath
       └── index.html
   ```

   Per-route pages are emitted as **`<route>.html`**, **not** as
   `<route>/index.html`. The basePath is embedded inside emitted URLs but
   does not nest the file tree (except for `index.html`).

2. **The Arango BYOC ingress sends requests through unchanged.** AOE's
   `StripServicePrefixMiddleware` removes `SERVICE_URL_PATH_PREFIX` so
   FastAPI sees the post-strip path:

   ```
   browser:        /_service/uds/_db/db/svc/library
   middleware →    /library
   StaticFiles ?:  no /library/ directory exists; no /library file exists
   → 404
   ```

The natural request shape — `/library`, `/workspace`, `/ontology/edit` —
matches **none** of:

- A static asset path (`/_next/static/…`)
- A directory containing `index.html` (Starlette's `html=True` only handles
  this case)
- A literal file (no `library` file, only `library.html`)

### Why the first fix tried (`html=True` alone) didn't work

`starlette.staticfiles.StaticFiles(html=True)` adds **one** behavior to the
default: when the resolved filesystem path is a directory, serve
`<dir>/index.html` if present. It does **not** retry
`<missing-path>.html`. With Next 15 export's flat layout, that's the wrong
heuristic — there are no per-route directories.

### Why we can't change Next's output shape

`output: 'export'` with `basePath` produces this layout deliberately for
hosts that map clean URLs to files via filesystem rules (Vercel, Cloudflare
Pages, S3 + CloudFront with custom function, …). We do not control the
ingress; rewriting paths on the AOE side is the right boundary.

### Why we can't redirect `/library` → `/library/`

Some hosts (Apache, nginx) handle this via mod_dir / `try_files`. Doing it
inside FastAPI would add a 30x hop on every page load and would still need
the underlying file to exist at `library/index.html` — which it doesn't,
unless we restructure the export.

---

## Decision

We added **`NextStaticExportApp`** (`backend/app/static_export_app.py`), a
subclass of `starlette.staticfiles.StaticFiles` that, after the standard
lookup misses, retries **`<path>.html`** for paths that look like clean SPA
routes (extensionless, no trailing slash). Starlette's existing `404.html`
fallback inside `get_response` is preserved for true misses.

`backend/app/main.py` mounts `NextStaticExportApp(directory=…, html=True)`
in place of vanilla `StaticFiles`.

### Behavior summary

| Request path | Behavior |
|--------------|----------|
| `/_next/static/chunks/abc.js` | Standard StaticFiles serves the asset (extensionful — fallback skipped) |
| `/<basePath>/` | Standard StaticFiles serves `<basePath>/index.html` via `html=True` |
| `/library` | StaticFiles 404 → fallback retries `library.html` → 200 |
| `/ontology/edit` | StaticFiles 404 → fallback retries `ontology/edit.html` → 200 |
| `/library.html` | Standard StaticFiles serves the file (extensionful path bypasses fallback) |
| `/library/` | Standard StaticFiles 404 (trailing slash → fallback skipped — there's no directory to translate) |
| `/does-not-exist` | StaticFiles 404 → fallback retries `does-not-exist.html` → not found → returns Starlette's `404.html` |
| `/api/v1/...` | Never reaches StaticFiles; matched by API routers first |

### Implementation sketch

```python
class NextStaticExportApp(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        original_response: Response | None = None
        try:
            original_response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or not self.html:
                raise
            if not _is_extensionless_clean_url(path):
                raise
        else:
            if original_response.status_code != 404 or not self.html:
                return original_response
            if not _is_extensionless_clean_url(path):
                return original_response

        html_path = f"{path}.html"
        full_path, stat_result = await anyio.to_thread.run_sync(
            self.lookup_path, html_path,
        )
        if stat_result is not None and stat.S_ISREG(stat_result.st_mode):
            return self.file_response(full_path, stat_result, scope)

        if original_response is not None:
            return original_response
        raise HTTPException(status_code=404)
```

`_is_extensionless_clean_url(path)` is true for paths like `library` or
`ontology/edit` — no trailing slash, no extension on the last segment.

---

## Rationale

### Why a `StaticFiles` subclass and not middleware

- **Symmetric with Starlette's own behavior.** Starlette already has a
  `404.html` fallback inside `get_response`; sitting in the same method
  keeps the lookup priority obvious and keeps the existing fallback intact.
- **Single mount point in `main.py`.** Operators reading the wiring see
  `app.mount("/", NextStaticExportApp(...))` and don't have to chase a
  separate middleware that rewrites paths.
- **No middleware ordering surprises.** Auth, CORS, and rate-limit
  middleware see the original request path; only the static layer rewrites
  the lookup, and only after the standard lookup fails.

### Why retry `<path>.html` instead of `<path>/index.html`

- The export literally emits `library.html`, not `library/index.html`.
  Adding the `index.html` retry on top would still 404 against this layout
  and would only help if Next's export shape changes.
- Adding both retries silently masks misconfiguration — if `library.html`
  is missing because the build was wrong, we want to fall through to the
  Next 404 page, not silently serve a different route.

### Why guard with `_is_extensionless_clean_url`

- Static asset 404s (`/_next/static/foo.js`) must **not** retry as
  `/_next/static/foo.js.html` — they're either present or genuinely
  missing.
- Trailing-slash requests (`/library/`) skip the fallback because the
  matching `index.html` lookup is StaticFiles' job — if that misses, the
  user has the wrong URL shape.

---

## Consequences

### Positive

- All Next-export routes work behind a path-prefix ingress with no Node
  runtime in the pod.
- The change is **contained** — one new file (`static_export_app.py`) and
  one mount swap in `main.py`. No middleware, no router gymnastics, no new
  config knob.
- Starlette's standard behaviors (asset serving, `index.html` for
  directories, `404.html` fallback) are unchanged.
- 16 unit tests in `backend/tests/unit/test_static_export_app.py` pin
  every branch (root → `index.html`, `/library` → `library.html`,
  `/ontology/edit` → `ontology/edit.html`, direct `*.html` unchanged,
  `/_next/static/...` bypasses fallback, unknown route serves `404.html`,
  `html=False` short-circuits).

### Negative

- The fallback adds one extra `lookup_path` call per missed clean URL.
  Negligible (single `stat` against the export tree); cached by the OS
  page cache after the first hit.
- Slightly different from "vanilla Starlette" — newcomers may need to read
  the docstring to understand the `<path>.html` retry. Mitigated by the
  detailed docstring at the top of the file and this ADR.

### Trade-offs considered

| Alternative | Why Not |
|-------------|---------|
| Run nginx in front of uvicorn with `try_files $uri $uri.html =404` | Adds another process to the pod and another config to keep in sync. The Container Manager path explicitly avoids nginx in the pod. |
| Generate `<route>/index.html` instead of `<route>.html` | Requires forking Next's export, or post-processing the build. Both add a build-time step that drifts from upstream Next. |
| Custom FastAPI middleware that rewrites `path` to `path + ".html"` | Splits responsibility across two files (middleware + static mount), requires guards against double-rewriting, and has to know which paths are static-served vs. API-served. |
| Issue 30x redirect from `/library` to `/library.html` | Doubles every page load; visible in DevTools; doesn't match the pretty URLs we want users to bookmark. |
| Deploy with a separate Node runtime | Defeats the purpose of the manual-packaging path (`py13base` only). |

---

## Operational notes

- If the bundled `frontend/out/` is empty or lacks `index.html`,
  `resolve_frontend_out_dir` refuses to mount it (so `NextStaticExportApp`
  is never engaged) and FastAPI falls back to the minimal `/login` HTML in
  `backend/app/minimal_login.py`. This prevents an empty static dir from
  shadowing every route with a 404.
- Verifying the fallback is engaged in a deployed environment:

  ```bash
  curl -sI https://<host>/<prefix>/library
  # → 200, content-type: text/html
  curl -sI https://<host>/<prefix>/does-not-exist
  # → 404, body = Next 404.html (not Starlette's default 404 body)
  ```

- See [`docs/path-prefix-routing.md`](../path-prefix-routing.md) for the
  end-to-end picture (frontend `basePath`, `withBasePath`, backend
  `StripServicePrefixMiddleware`, this fallback).

---

## Files

| Concern | Path |
|---------|------|
| Implementation | `backend/app/static_export_app.py` |
| Mount | `backend/app/main.py` |
| Static export resolver | `backend/app/frontend_static.py` |
| Strip middleware | `backend/app/middleware/strip_service_prefix.py` |
| Tests | `backend/tests/unit/test_static_export_app.py` |
