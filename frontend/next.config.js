/**
 * Single source for path prefix: repo-root `.env` → `SERVICE_URL_PATH_PREFIX`
 * (same as backend `app.config.Settings.service_url_path_prefix`).
 *
 * Optional override: `NEXT_PUBLIC_BASE_PATH` (must match if both are set).
 */
const path = require("path");
const { loadEnvConfig } = require("@next/env");

const repoRoot = path.join(__dirname, "..");
loadEnvConfig(repoRoot);

const pathPrefix = (
  process.env.SERVICE_URL_PATH_PREFIX ||
  process.env.NEXT_PUBLIC_BASE_PATH ||
  ""
).replace(/\/$/, "");

const staticExport = process.env.AOE_STATIC_EXPORT === "1";

// Dev/standalone proxy target: the browser calls same-origin `/api/*` and Next
// forwards to FastAPI (see api-client `DEFAULT_BACKEND_ORIGIN` + same-origin
// fallback). Mirrors `src/lib/backendProxyTarget.ts`. Rewrites are intentionally
// NOT defined for `output: "export"` (a static bundle has no server to proxy
// through — nginx / FastAPI serve `/api/*` directly in that deployment).
const backendProxyTarget = (
  process.env.BACKEND_PROXY_URL || "http://127.0.0.1:8010"
).replace(/\/$/, "");

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  env: {
    NEXT_PUBLIC_BASE_PATH: pathPrefix,
  },
  ...(staticExport
    ? {
        output: "export",
        ...(pathPrefix ? { basePath: pathPrefix } : {}),
      }
    : {
        output: "standalone",
        ...(pathPrefix ? { basePath: pathPrefix } : {}),
        async rewrites() {
          return [
            {
              source: "/api/:path*",
              destination: `${backendProxyTarget}/api/:path*`,
            },
          ];
        },
      }),
};

module.exports = nextConfig;
