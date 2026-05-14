/**
 * Q.4 — qualityRecall client tests.
 */

import {
  computeQualityRecall,
  inferRdfFormatFromFilename,
} from "../qualityRecall";

const apiPost = jest.fn();
jest.mock("@/lib/api-client", () => ({
  api: { post: (...args: unknown[]) => apiPost(...args) },
  ApiError: class ApiError extends Error {},
}));

beforeEach(() => {
  apiPost.mockReset();
});

describe("inferRdfFormatFromFilename", () => {
  it.each([
    ["reference.ttl", "turtle"],
    ["foo.bar.ttl", "turtle"],
    ["gold.owl", "xml"],
    ["gold.RDF", "xml"],
    ["data.xml", "xml"],
    ["dump.nt", "nt"],
    ["bundle.jsonld", "json-ld"],
    ["thing.json-ld", "json-ld"],
    ["unknown.zzz", "turtle"],
  ])("%s → %s", (name, expected) => {
    expect(inferRdfFormatFromFilename(name)).toBe(expected);
  });
});

describe("computeQualityRecall", () => {
  it("posts the request body to /api/v1/quality/recall", async () => {
    apiPost.mockResolvedValue({ summary: { recall: 0.5 } });
    await computeQualityRecall({
      ontology_id: "onto1",
      reference_content: "@prefix : <x#> .",
      rdf_format: "turtle",
      match_threshold: 0.9,
      include_object_properties: false,
    });
    expect(apiPost).toHaveBeenCalledWith("/api/v1/quality/recall", {
      ontology_id: "onto1",
      reference_content: "@prefix : <x#> .",
      rdf_format: "turtle",
      match_threshold: 0.9,
      include_object_properties: false,
    });
  });
});
