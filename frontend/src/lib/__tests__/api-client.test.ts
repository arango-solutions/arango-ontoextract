import { buildApiUrl } from "@/lib/api-client";

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
