import {
  backendUrl,
  buildApiUrl,
  getApiBaseUrl,
  getApiOrigin,
  nextPublicBasePath,
} from "@/lib/api-client";

describe("buildApiUrl", () => {
  it("joins base and path when base has no /api/v1 suffix", () => {
    expect(buildApiUrl("http://localhost:8001", "/api/v1/ontology/library")).toBe(
      "http://localhost:8001/api/v1/ontology/library",
    );
  });

  it("deduplicates /api/v1 when base already ends with /api/v1", () => {
    expect(
      buildApiUrl("http://localhost:8001/api/v1", "/api/v1/ontology/library"),
    ).toBe("http://localhost:8001/api/v1/ontology/library");
  });
});

describe("backendUrl", () => {
  it("matches buildApiUrl(getApiBaseUrl(), path)", () => {
    expect(backendUrl("/ready")).toBe(buildApiUrl(getApiBaseUrl(), "/ready"));
    expect(backendUrl("/api/v1/auth/login")).toBe(
      buildApiUrl(getApiBaseUrl(), "/api/v1/auth/login"),
    );
  });
});

describe("getApiOrigin", () => {
  const prevApiUrl = process.env.NEXT_PUBLIC_API_URL;

  afterEach(() => {
    process.env.NEXT_PUBLIC_API_URL = prevApiUrl;
  });

  it("returns window.location.origin when NEXT_PUBLIC_API_URL is a relative path (unified Docker image)", () => {
    process.env.NEXT_PUBLIC_API_URL = "/api/v1";
    // jsdom's default location is http://localhost
    expect(getApiOrigin()).toBe(window.location.origin);
    expect(getApiOrigin().startsWith("http")).toBe(true);
  });

  it("strips path component from absolute NEXT_PUBLIC_API_URL", () => {
    process.env.NEXT_PUBLIC_API_URL = "https://api.example.com:9000/api/v1";
    expect(getApiOrigin()).toBe("https://api.example.com:9000");
  });

  it("never returns a value containing /api/v1 (would break ws:// URL construction)", () => {
    process.env.NEXT_PUBLIC_API_URL = "/api/v1";
    expect(getApiOrigin()).not.toContain("/api/v1");
    process.env.NEXT_PUBLIC_API_URL = "https://api.example.com/api/v1";
    expect(getApiOrigin()).not.toContain("/api/v1");
  });
});

describe("nextPublicBasePath", () => {
  const prev = process.env.NEXT_PUBLIC_BASE_PATH;

  afterEach(() => {
    process.env.NEXT_PUBLIC_BASE_PATH = prev;
  });

  it("returns empty string when NEXT_PUBLIC_BASE_PATH is unset or empty", () => {
    process.env.NEXT_PUBLIC_BASE_PATH = "";
    expect(nextPublicBasePath()).toBe("");
  });

  it("strips trailing slash from configured prefix", () => {
    process.env.NEXT_PUBLIC_BASE_PATH = "/_service/uds/_db/ontoextract/aoe/";
    expect(nextPublicBasePath()).toBe("/_service/uds/_db/ontoextract/aoe");
  });
});
