import { resolveWsUrl } from "@/lib/use-websocket";

describe("resolveWsUrl", () => {
  const prevApiUrl = process.env.NEXT_PUBLIC_API_URL;
  const prevBasePath = process.env.NEXT_PUBLIC_BASE_PATH;

  afterEach(() => {
    process.env.NEXT_PUBLIC_API_URL = prevApiUrl;
    process.env.NEXT_PUBLIC_BASE_PATH = prevBasePath;
    localStorage.clear();
  });

  it("produces wss://host/ws/... when NEXT_PUBLIC_API_URL is a relative /api/v1 (unified image regression)", () => {
    process.env.NEXT_PUBLIC_API_URL = "/api/v1";
    process.env.NEXT_PUBLIC_BASE_PATH = "";
    const url = resolveWsUrl("run-123");
    expect(url).toMatch(/^wss?:\/\//);
    expect(url).not.toContain("/api/v1/ws/");
    expect(url).toContain("/ws/extraction/run-123");
  });

  it("strips path component from absolute NEXT_PUBLIC_API_URL", () => {
    process.env.NEXT_PUBLIC_API_URL = "https://api.example.com:9000/api/v1";
    process.env.NEXT_PUBLIC_BASE_PATH = "";
    expect(resolveWsUrl("abc")).toBe("wss://api.example.com:9000/ws/extraction/abc");
  });

  it("includes NEXT_PUBLIC_BASE_PATH so SERVICE_URL_PATH_PREFIX deployments reach the backend strip middleware", () => {
    process.env.NEXT_PUBLIC_API_URL = "https://host.test/api/v1";
    process.env.NEXT_PUBLIC_BASE_PATH = "/_service/uds/_db/aoe/svc";
    expect(resolveWsUrl("r1")).toBe(
      "wss://host.test/_service/uds/_db/aoe/svc/ws/extraction/r1",
    );
  });

  it("appends auth token from localStorage", () => {
    process.env.NEXT_PUBLIC_API_URL = "https://host.test";
    process.env.NEXT_PUBLIC_BASE_PATH = "";
    localStorage.setItem("aoe_auth_token", "tok+/=&");
    expect(resolveWsUrl("r1")).toBe(
      "wss://host.test/ws/extraction/r1?token=tok%2B%2F%3D%26",
    );
  });

  it("returns empty string in SSR context (no window)", () => {
    const origWindow = global.window;
    // @ts-expect-error simulate SSR
    delete global.window;
    try {
      expect(resolveWsUrl("r1")).toBe("");
    } finally {
      global.window = origWindow;
    }
  });
});
