/**
 * FastAPI origin for the dev/standalone `/api/*` proxy.
 *
 * Single source of the `BACKEND_PROXY_URL` default; `next.config.js` inlines
 * the same expression for its `rewrites()` (config is CommonJS, loaded before
 * the TS build, so it cannot import this module). Exported for any server-side
 * Route Handler that needs to reach FastAPI directly.
 */
export function getBackendProxyTarget(): string {
  return (process.env.BACKEND_PROXY_URL || "http://127.0.0.1:8010").replace(/\/$/, "");
}
