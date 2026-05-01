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
      }),
};

module.exports = nextConfig;
