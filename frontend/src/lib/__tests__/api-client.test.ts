import { backendUrl, buildApiUrl, getApiBaseUrl } from "@/lib/api-client";

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
