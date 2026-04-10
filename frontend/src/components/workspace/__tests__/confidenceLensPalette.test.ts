import {
  confidenceNodeColor,
  normalizeConfidence01,
} from "@/components/workspace/confidenceLensPalette";

describe("confidenceLensPalette", () => {
  it("normalizeConfidence01 maps fractions and percents", () => {
    expect(normalizeConfidence01(0.77)).toBeCloseTo(0.77);
    expect(normalizeConfidence01(77)).toBeCloseTo(0.77);
    expect(normalizeConfidence01(1)).toBe(1);
    expect(normalizeConfidence01(100)).toBe(1);
  });

  it("confidenceNodeColor uses legend bands", () => {
    expect(confidenceNodeColor(0.77)).toBe("#22c55e");
    expect(confidenceNodeColor(0.6)).toBe("#eab308");
    expect(confidenceNodeColor(0.4)).toBe("#ef4444");
  });
});
