/**
 * FastAPI origin for server-side proxying (Route Handlers).
 * Must match `BACKEND_PROXY_URL` in next.config.js rewrites.
 */
export function getBackendProxyTarget(): string {
  return (process.env.BACKEND_PROXY_URL || "http://127.0.0.1:8010").replace(/\/$/, "");
}
