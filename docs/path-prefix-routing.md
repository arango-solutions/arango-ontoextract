# Path-Prefix Routing (`SERVICE_URL_PATH_PREFIX`)

**Audience:** anyone deploying AOE behind a reverse proxy that mounts the
service under a non-root URL path — e.g. the Arango BYOC ingress, or any nginx
/ Caddy / k8s Ingress that strips a fixed prefix before forwarding to AOE.

**TL;DR:** one env var (`SERVICE_URL_PATH_PREFIX`) drives routing in three
places — the **ingress strip rule**, the **Next.js `basePath`**, and the
**FastAPI strip middleware**. Get them out of sync and you get either 404s on
SPA routes, blank pages from broken asset URLs, or auth redirects to the wrong
host.

---

## 1. The end-to-end picture

```
                ┌──────────────────────────────────────────────┐
                │                Browser                       │
                │   GET https://host/_service/uds/_db/db/svc/  │
                └──────────────────────┬───────────────────────┘
                                       │
                                       ▼
                ┌──────────────────────────────────────────────┐
                │  BYOC ingress (Arango Container Manager)     │
                │  Routes /_service/.../<svc> → AOE pod        │
                │  Strips nothing — preserves the prefix       │
                └──────────────────────┬───────────────────────┘
                                       │  GET /_service/uds/_db/db/svc/library
                                       ▼
                ┌──────────────────────────────────────────────┐
                │  StripServicePrefixMiddleware (FastAPI)      │
                │  removes SERVICE_URL_PATH_PREFIX from path,  │
                │  preserves it in scope["root_path"]          │
                └──────────────────────┬───────────────────────┘
                                       │  GET /library
                                       ▼
                ┌──────────────────────────────────────────────┐
                │  FastAPI router  ─────►  /library            │
                │  ① /api/v1/...   handled by API routers      │
                │  ② /ws/...       handled by WS routes        │
                │  ③ everything    falls through to            │
                │     else        NextStaticExportApp →         │
                │                 frontend/out/<prefix>/library.html│
                └──────────────────────────────────────────────┘
```

The matching frontend story when the static export is served from FastAPI:

```
Next build (with NEXT_PUBLIC_BASE_PATH = SERVICE_URL_PATH_PREFIX)
  ├─ Pages emit href="<prefix>/library"     ← Next <Link> + basePath
  ├─ Asset URLs are /<prefix>/_next/...     ← basePath
  └─ frontend/out/ tree is FLAT             ← Next 15 export quirk
       library.html, workspace.html, ontology/edit.html, …
```

---

## 2. The single source of truth

`SERVICE_URL_PATH_PREFIX` is read in **exactly three places** and must be
identical (no trailing slash, leading slash optional but normalized):

| Layer | Where | What it does |
|------|------|--------------|
| Backend strip middleware | `backend/app/middleware/strip_service_prefix.py` | Removes the prefix from incoming HTTP/WebSocket paths so existing routers (mounted at `/health`, `/api/...`, `/login`, …) match. |
| Next.js basePath | `frontend/next.config.js` (env: `NEXT_PUBLIC_BASE_PATH`) | Drives how `<Link>` / `router.push` / `next/image` build URLs in the static export. |
| Static export resolver | `backend/app/frontend_static.py` | Picks the `frontend/out/<prefix>/` nested mount point so flat HTML files (`library.html`, etc.) get served at the prefix-stripped URL. |

Settings access is centralised on `Settings.service_url_path_prefix`
(`backend/app/config.py`) — never read the env var elsewhere.

---

## 3. Frontend helpers

### 3.1 `withBasePath(path)` — `frontend/src/lib/base-path.ts`

Use for **raw `<a href>`** anchors and `window.location` redirects. Idempotent
(safe to call twice).

```tsx
import { withBasePath } from "@/lib/base-path";

// Raw anchor — survives Next's "/" trailing-slash stripping (see §6).
<a href={withBasePath("/")}>Home</a>

// Manual navigation
window.location.href = withBasePath(`/pipeline?runId=${runId}`);
```

Next's own `<Link href="/library">` already prepends `basePath` automatically
— do **not** double-wrap.

### 3.2 `backendUrl(path)` — `frontend/src/lib/api-client.ts`

Use for **`fetch`** to backend routes (`/health`, `/ready`, `/api/v1/...`,
file uploads). Resolves to a same-origin relative URL when the Next dev
rewrite handles CORS, otherwise an absolute origin.

```ts
const res = await fetch(backendUrl("/api/v1/documents/upload"), { ... });
```

### 3.3 `getApiOrigin()` — same module

Returns an **always-absolute** origin (no path). Use only when you need a real
URL — e.g. building a `ws://` / `wss://` URL for a WebSocket. HTTP callers
should prefer `backendUrl()`.

```ts
const wsBase = getApiOrigin().replace(/^http/, "ws");
new WebSocket(`${wsBase}/ws/extraction/${runId}`);
```

### 3.4 The `api` client (`api.get`, `api.post`, …)

The shared client already routes through `getApiBaseUrl()`, so you do **not**
need to wrap paths passed to `api.get("/api/v1/...")` — the prefix is applied
inside the client.

---

## 4. Backend pieces

### 4.1 `StripServicePrefixMiddleware` — `backend/app/middleware/strip_service_prefix.py`

ASGI middleware. Two operations on every HTTP / WebSocket request:

1. If `path` matches `prefix` exactly or starts with `prefix + "/"`, replace
   `scope["path"]` with the remainder (or `"/"` for an exact match).
2. Append `prefix` to `scope["root_path"]` so any URL Starlette generates
   (`url_for`, redirects) preserves the prefix.

Anything outside the prefix passes through unchanged. When the prefix is
empty, the middleware is a no-op.

### 4.2 `NextStaticExportApp` — `backend/app/static_export_app.py`

Subclass of `starlette.staticfiles.StaticFiles` that adds a `<path>.html`
fallback for clean SPA URLs. See ADR 007 for the rationale; in short:

- Next 15 `output: "export"` emits **flat** per-route HTML files
  (`out/library.html`, `out/workspace.html`, `out/ontology/edit.html`).
- Vanilla `StaticFiles(html=True)` only translates directory-style requests
  (`/dir/` → `/dir/index.html`). It never tries `<path>.html`, so after the
  middleware strips the prefix, `/library` 404s.
- `NextStaticExportApp` retries `<path>.html` for extensionless, slashless
  paths after the standard lookup misses, while preserving Starlette's own
  `404.html` fallback for true misses.

### 4.3 `resolve_frontend_out_dir` — `backend/app/frontend_static.py`

Locates the directory that should be mounted under `StaticFiles`, in this
priority order:

1. **Explicit override** — `AOE_FRONTEND_OUT_DIR` / `FRONTEND_STATIC_ROOT`
2. **Flat manual-packaging bundle** — `<root>/app/main.py` ⇒ `<root>/frontend/out`
3. **Monorepo dev** — `<repo>/backend/app/main.py` ⇒ `<repo>/frontend/out`
4. **Unified Docker image** — `/app/static`

Important: the candidate is only treated as usable if `index.html` exists at
the resolved root. An empty `frontend/out/` no longer mounts (it would shadow
the minimal `/login` HTML fallback and 404 every route).

When `SERVICE_URL_PATH_PREFIX` matches Next `basePath`, files live under
`frontend/out/<prefix>/` — the resolver prefers that nested folder so
`StaticFiles` is rooted **inside** it, not at bare `frontend/out/`.

### 4.4 Login & rate-limit graceful paths

Two related touches keep deployments healthy when ancillary services are
absent:

- **`backend/app/minimal_login.py`** — when no usable static export is
  present, FastAPI serves a tiny inline `/login` page that POSTs to
  `{prefix}/api/v1/auth/login` and stores `aoe_auth_token`. Aligned with
  `frontend/src/lib/auth.ts`.
- **`GET /api/v1/auth/login`** — returns JSON explaining that login is a
  POST. Useful when an operator hits the URL directly.
- **`backend/app/api/rate_limit.py`** — `ping()` + cached client + backoff
  after failures. `RATE_LIMIT_ENABLED=false` (or a real `REDIS_URL` in
  cluster) avoids pointless `localhost:6379` connection attempts.

---

## 5. Configuring the three layers

### 5.1 Environment

```bash
# Repo-root .env (single source of truth)
SERVICE_URL_PATH_PREFIX=/_service/uds/_db/<db>/<service>
```

Backend `Settings` reads this directly. The Makefile `include`s
`.env`, so `make package-arango-manual-all` propagates the value into the
frontend build via `SERVICE_URL_PATH_PREFIX=$(SERVICE_URL_PATH_PREFIX)`.

### 5.2 Frontend build

`frontend/next.config.js` reads `SERVICE_URL_PATH_PREFIX` at build time and
emits it as `NEXT_PUBLIC_BASE_PATH`, then sets:

```js
{
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || "",
  // output: "export" enabled when AOE_STATIC_EXPORT=1
}
```

Static-export builds (used by `make package-arango-manual-all`) bundle the
prefix into every emitted HTML file's `<script src>`, `<link href>`, and
`<a href>`.

### 5.3 Ingress / reverse proxy

The ingress must **route** requests under the prefix to the AOE pod, but
**not strip** the prefix from the request path — `StripServicePrefixMiddleware`
does that. If your ingress also strips, set `SERVICE_URL_PATH_PREFIX=""` in
the AOE config (the middleware then becomes a no-op) and rebuild the frontend
with no `basePath`.

---

## 6. The trailing-slash gotcha

The Arango BYOC ingress treats `/<prefix>` and `/<prefix>/` as **two
different routes**. Confirmed via `curl`:

| URL | Response |
|------|----------|
| `/<prefix>/` | `x-arango-platform-route: <aoe-service>` (AOE) |
| `/<prefix>` | `server: ArangoDB`, `www-authenticate: Basic, realm="ArangoDB"` (bare Arango) |

Next's `<Link href="/">` under `basePath` is rendered as
`<a href="/<prefix>">` — **without** the trailing slash — so a "Home" link
clicked from any subpage lands on bare Arango.

**Fix:** every "Home" / logo link in the app uses a raw anchor wrapped in
`withBasePath("/")`, which always returns `/<prefix>/`:

```tsx
// Wrong — Next strips the trailing slash under basePath
<Link href="/">Home</Link>

// Right — raw <a> preserves the slash through navigation
<a href={withBasePath("/")}>Home</a>
```

Touched files (see `handoff.md` for the full list):

- `frontend/src/components/workspace/LensToolbar.tsx`
- `frontend/src/app/{upload,library,pipeline,curation,entity-resolution,dashboard,ontology/edit}/page.tsx`

Regression tests in `frontend/src/lib/__tests__/base-path.test.ts` pin
`withBasePath("/")` to `/<prefix>/` (with prefix) and `/` (without).

### Cache caveat

Each Next page is its own HTML + JS chunk with its own cache lifetime. A
stale `workspace.html` can keep referencing a pre-fix `page-<oldhash>.js`
even after a redeploy. If a logo link still goes to no-slash after a fresh
`make package-arango-manual-all` and redeploy:

```bash
# 404 → bundle not deployed yet; 200 → browser/proxy cache is stale
curl -sI https://<host>/<prefix>/_next/static/chunks/app/workspace/page-<hash>.js
```

Hard-reload (Cmd-Shift-R) or bust the proxy cache.

---

## 7. Quick verification checklist

After deploying with a non-empty prefix, confirm:

```bash
# 1. SPA routes resolve via the .html fallback
curl -sI https://<host>/<prefix>/library     # → 200, content-type: text/html
curl -sI https://<host>/<prefix>/workspace   # → 200
curl -sI https://<host>/<prefix>/ontology/edit  # → 200

# 2. Root + readiness
curl -sI https://<host>/<prefix>/            # → 200
curl     https://<host>/<prefix>/ready       # → JSON {"status":"ready"}

# 3. Static assets are emitted with the prefix
curl -sI https://<host>/<prefix>/_next/static/chunks/app/workspace/page-<hash>.js
# → 200

# 4. Unknown route still serves the Next 404 page
curl -sI https://<host>/<prefix>/does-not-exist  # → 404, body = Next 404.html

# 5. Trailing slash quirk fix in emitted HTML
curl -s https://<host>/<prefix>/library | grep '>Home<'
# → href="/<prefix>/" (note trailing slash)
```

If `(1)` returns `404` with a Starlette body (not the Next 404 page), the
`NextStaticExportApp` fallback isn't engaged — confirm the mount is
`NextStaticExportApp(directory=..., html=True)` and not vanilla `StaticFiles`.

---

## 8. Related files

| Concern | Path |
|---------|------|
| Strip middleware | `backend/app/middleware/strip_service_prefix.py` |
| Static export resolver | `backend/app/frontend_static.py` |
| `<path>.html` fallback | `backend/app/static_export_app.py` |
| App wiring | `backend/app/main.py` |
| Settings | `backend/app/config.py` (`service_url_path_prefix`) |
| Frontend basePath helper | `frontend/src/lib/base-path.ts` |
| Frontend API client | `frontend/src/lib/api-client.ts` (`backendUrl`, `getApiOrigin`) |
| Next config | `frontend/next.config.js` |
| Tests (backend) | `backend/tests/unit/test_strip_service_prefix.py`, `test_static_export_app.py`, `test_frontend_static.py` |
| Tests (frontend) | `frontend/src/lib/__tests__/base-path.test.ts` |
| Operator runbook | `docs/container-manager-deployment.md` |
| Architectural decision | `docs/adr/007-spa-html-fallback.md` |
