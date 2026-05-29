import {
  CONFIDENCE_HIGH,
  CONFIDENCE_MEDIUM,
  HEALTH_HIGH,
  HEALTH_MEDIUM,
  confidenceBand,
  confidenceBgColor,
  confidenceColor,
  healthBand,
  healthScoreColor,
} from "../thresholds";

describe("threshold constants", () => {
  it("expose the canonical confidence and health bands", () => {
    expect(CONFIDENCE_HIGH).toBe(0.7);
    expect(CONFIDENCE_MEDIUM).toBe(0.5);
    expect(HEALTH_HIGH).toBe(70);
    expect(HEALTH_MEDIUM).toBe(50);
  });
});

describe("confidenceBand", () => {
  it("classifies high at or above the high threshold (inclusive)", () => {
    expect(confidenceBand(CONFIDENCE_HIGH)).toBe("high");
    expect(confidenceBand(0.95)).toBe("high");
  });

  it("classifies medium at or above the medium threshold and below high", () => {
    expect(confidenceBand(CONFIDENCE_MEDIUM)).toBe("medium");
    expect(confidenceBand(0.69)).toBe("medium");
  });

  it("classifies low below the medium threshold", () => {
    expect(confidenceBand(0.49)).toBe("low");
    expect(confidenceBand(0)).toBe("low");
  });

  it("classifies unknown for null, undefined, and NaN", () => {
    expect(confidenceBand(null)).toBe("unknown");
    expect(confidenceBand(undefined)).toBe("unknown");
    expect(confidenceBand(Number.NaN)).toBe("unknown");
  });
});

describe("healthBand", () => {
  it("uses the 0-100 bands inclusively", () => {
    expect(healthBand(HEALTH_HIGH)).toBe("high");
    expect(healthBand(HEALTH_MEDIUM)).toBe("medium");
    expect(healthBand(49)).toBe("low");
  });

  it("classifies unknown for missing values", () => {
    expect(healthBand(null)).toBe("unknown");
    expect(healthBand(Number.NaN)).toBe("unknown");
  });
});

describe("color helpers", () => {
  it("map confidence scores to text colors", () => {
    expect(confidenceColor(0.8)).toBe("text-green-600");
    expect(confidenceColor(0.6)).toBe("text-yellow-600");
    expect(confidenceColor(0.2)).toBe("text-red-600");
    expect(confidenceColor(null)).toBe("text-gray-400");
  });

  it("map confidence scores to background colors", () => {
    expect(confidenceBgColor(0.8)).toBe("bg-green-100");
    expect(confidenceBgColor(0.6)).toBe("bg-yellow-100");
    expect(confidenceBgColor(0.2)).toBe("bg-red-100");
    expect(confidenceBgColor(null)).toBe("bg-gray-100");
  });

  it("map health scores to text colors", () => {
    expect(healthScoreColor(85)).toBe("text-green-600");
    expect(healthScoreColor(55)).toBe("text-yellow-600");
    expect(healthScoreColor(10)).toBe("text-red-600");
    expect(healthScoreColor(null)).toBe("text-gray-400");
  });
});
