import { documentKey } from "../arangoId";

describe("documentKey", () => {
  it("extracts the key half of a full _id", () => {
    expect(documentKey("ontology_classes/Customer")).toBe("Customer");
    expect(documentKey("ontology_properties/has_name")).toBe("has_name");
  });

  it("returns a bare key unchanged when there is no collection prefix", () => {
    expect(documentKey("Customer")).toBe("Customer");
  });

  it("keeps only the last segment for multi-slash ids", () => {
    expect(documentKey("a/b/c")).toBe("c");
  });

  it("falls back to the input for an empty string", () => {
    expect(documentKey("")).toBe("");
  });
});
