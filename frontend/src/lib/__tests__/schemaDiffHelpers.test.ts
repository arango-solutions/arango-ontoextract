import {
  constraintDiffLabel,
  entityDiffLabel,
  formatSchemaDiffSummaryLine,
  registryDisplayName,
  schemaDiffUrl,
  validateSchemaDiffSelection,
  type SchemaDiffSummary,
} from "../schemaDiffHelpers";

describe("formatSchemaDiffSummaryLine", () => {
  it("returns a no-diff message when all counts are zero", () => {
    const summary: SchemaDiffSummary = {
      classes_added: 0,
      classes_removed: 0,
      classes_changed: 0,
      properties_added: 0,
      properties_removed: 0,
      properties_changed: 0,
      constraints_added: 0,
      constraints_removed: 0,
      constraints_changed: 0,
    };
    expect(formatSchemaDiffSummaryLine(summary)).toBe("No schema differences detected.");
  });

  it("joins non-zero buckets with middle dots", () => {
    const summary: SchemaDiffSummary = {
      classes_added: 2,
      classes_removed: 0,
      classes_changed: 1,
      properties_added: 0,
      properties_removed: 0,
      properties_changed: 0,
      constraints_added: 0,
      constraints_removed: 0,
      constraints_changed: 0,
    };
    expect(formatSchemaDiffSummaryLine(summary)).toBe(
      "2 classes added · 1 class changed",
    );
  });
});

describe("entityDiffLabel", () => {
  it("prefers label over uri tail", () => {
    expect(entityDiffLabel({ label: "Person", uri: "http://ex#Person" })).toBe("Person");
  });

  it("falls back to uri fragment", () => {
    expect(entityDiffLabel({ uri: "http://example.org/ontology#Account" })).toBe("Account");
  });
});

describe("constraintDiffLabel", () => {
  it("formats property tail and restriction type", () => {
    expect(
      constraintDiffLabel({
        class_uri: "http://ex#Person",
        property_uri: "http://ex#hasAge",
        restriction_type: "minCount",
        before: {},
        after: {},
      }),
    ).toBe("hasAge (minCount)");
  });
});

describe("validateSchemaDiffSelection", () => {
  it("rejects empty selection", () => {
    expect(validateSchemaDiffSelection("", "b")).toMatch(/Select both/);
  });

  it("rejects self-diff", () => {
    expect(validateSchemaDiffSelection("same", "same")).toMatch(/different ontologies/);
  });

  it("accepts two distinct keys", () => {
    expect(validateSchemaDiffSelection("a", "b")).toBeNull();
  });
});

describe("registryDisplayName", () => {
  it("uses name when present", () => {
    expect(registryDisplayName({ _key: "k1", name: "Demo" })).toBe("Demo");
  });

  it("falls back to key", () => {
    expect(registryDisplayName({ _key: "k1" })).toBe("k1");
  });
});

describe("schemaDiffUrl", () => {
  it("encodes query parameters", () => {
    expect(schemaDiffUrl("ont a", "ont/b")).toBe(
      "/api/v1/ontology/schema/diff?a=ont%20a&b=ont%2Fb",
    );
  });
});
