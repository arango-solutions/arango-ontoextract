/**
 * Regression guard for the dev/standalone `/api/*` proxy rewrite.
 *
 * The BYOC refactor (commit 9c138e8) dropped the `rewrites()` that forwards
 * same-origin `/api/*` to FastAPI, so every browser API call (including
 * `POST /api/v1/auth/login`) 404'd at the Next dev server and the login page
 * showed "Login failed (404)". This test loads the real `next.config.js` and
 * pins the proxy so the rewrite can't silently disappear again.
 *
 * `next.config.js` reads env at module-evaluation time, so each case is loaded
 * in an isolated module registry with the relevant env var set.
 */

interface RewriteRule {
  source: string;
  destination: string;
}

interface LoadedNextConfig {
  output?: string;
  rewrites?: () => Promise<RewriteRule[]>;
}

function loadConfig(): LoadedNextConfig {
  let config!: LoadedNextConfig;
  jest.isolateModules(() => {
    config = require("../../../next.config.js") as LoadedNextConfig;
  });
  return config;
}

describe("next.config.js /api proxy", () => {
  const savedStaticExport = process.env.AOE_STATIC_EXPORT;

  afterEach(() => {
    if (savedStaticExport === undefined) {
      delete process.env.AOE_STATIC_EXPORT;
    } else {
      process.env.AOE_STATIC_EXPORT = savedStaticExport;
    }
  });

  it("proxies /api/* to the FastAPI backend in non-static (dev/standalone) builds", async () => {
    delete process.env.AOE_STATIC_EXPORT;

    const config = loadConfig();
    expect(typeof config.rewrites).toBe("function");

    const rules = await config.rewrites!();
    const apiRule = rules.find((r) => r.source === "/api/:path*");
    expect(apiRule).toBeDefined();
    // Forwards the wildcard tail to a real FastAPI origin (host varies with
    // BACKEND_PROXY_URL), so the login POST reaches the backend rather than
    // 404ing against the Next server.
    expect(apiRule!.destination).toMatch(/^https?:\/\/.+\/api\/:path\*$/);
  });

  it("proxies the root-level health probes (/ready, /health) too", async () => {
    delete process.env.AOE_STATIC_EXPORT;

    const rules = await loadConfig().rewrites!();
    // The home page reads /ready (and /health) directly — these are NOT under
    // /api, so they need their own rewrites or they 404 at the Next server and
    // the backend-status card lies in local dev.
    for (const path of ["/ready", "/health"]) {
      const rule = rules.find((r) => r.source === path);
      expect(rule).toBeDefined();
      expect(rule!.destination).toMatch(new RegExp(`^https?://.+${path}$`));
    }
  });

  it("omits the rewrite for static export — nginx/FastAPI serve /api directly there", () => {
    process.env.AOE_STATIC_EXPORT = "1";

    const config = loadConfig();
    expect(config.output).toBe("export");
    // A static bundle has no Node server, so a rewrite would be a no-op lie.
    expect(config.rewrites).toBeUndefined();
  });
});
