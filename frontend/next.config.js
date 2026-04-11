/** @type {import('next').NextConfig} */
// `/api/*` → FastAPI. `/ready` and `/health` use `app/*/route.ts` proxies (clearer errors than rewrite 500).
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
        source: "/api/:path*",
        destination: `${backendTarget}/api/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
