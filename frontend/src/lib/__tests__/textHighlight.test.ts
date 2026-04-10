import {
  splitTextByKeywordAlternation,
  termsFromEntityLabel,
  escapeRegExp,
} from "@/lib/textHighlight";

describe("textHighlight", () => {
  it("escapeRegExp escapes metacharacters", () => {
    expect(escapeRegExp("a+b")).toBe("a\\+b");
  });

  it("splitTextByKeywordAlternation marks odd indices as keyword spans", () => {
    const parts = splitTextByKeywordAlternation("hello Transaction world", [
      "Transaction",
    ]);
    expect(parts).toEqual(["hello ", "Transaction", " world"]);
  });

  it("returns single segment when no valid terms", () => {
    expect(splitTextByKeywordAlternation("abc", [])).toEqual(["abc"]);
    expect(splitTextByKeywordAlternation("abc", ["x"])).toEqual(["abc"]);
  });

  it("termsFromEntityLabel includes label and long words", () => {
    const t = termsFromEntityLabel("Foo Bar");
    expect(t).toContain("Foo Bar");
    expect(t.map((x) => x.toLowerCase())).toContain("foo");
  });
});
