/** @type {import('next').NextConfig} */
// Browser can call same-origin `/api/*`; Next forwards to FastAPI (see api-client default base).
const backendTarget = (process.env.BACKEND_PROXY_URL || "http://127.0.0.1:8010").replace(
  /\/$/,
  "",
);

const nextConfig = {
  reactStrictMode: true,
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/favicon.ico",
        destination: "/favicon.svg",
      },
      {
        source: "/ready",
        destination: `${backendTarget}/ready`,
      },
      {
        source: "/health",
        destination: `${backendTarget}/health`,
      },
      {
        source: "/api/:path*",
        destination: `${backendTarget}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
