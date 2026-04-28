/** @type {import('next').NextConfig} */
const staticExport = process.env.AOE_STATIC_EXPORT === "1";
const basePath = (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/$/, "");

const nextConfig = {
  reactStrictMode: true,
  ...(staticExport
    ? {
        output: "export",
        ...(basePath ? { basePath } : {}),
      }
    : {
        output: "standalone",
      }),
};

module.exports = nextConfig;
