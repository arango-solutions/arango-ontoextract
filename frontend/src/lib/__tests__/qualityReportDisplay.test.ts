import { buildQualityReportMetrics, formatOntologyHealthSummary } from "../qualityReportDisplay";

describe("formatOntologyHealthSummary", () => {
  it("treats 0–1 as a ratio", () => {
    expect(formatOntologyHealthSummary(0.74)).toBe("74%");
  });

  it("treats >1 as 0–100 score", () => {
    expect(formatOntologyHealthSummary(74)).toBe("74%");
  });
});

describe("buildQualityReportMetrics", () => {
  it("formats health_score as 0–100 percent, not multiplied", () => {
    const rows = buildQualityReportMetrics({ health_score: 74 });
    const h = rows.find((r) => r.label === "Health Score");
    expect(h?.value).toBe("74.0%");
  });

  it("formats completeness as 0–100 without multiplying", () => {
    const rows = buildQualityReportMetrics({ completeness: 45.2 });
    const c = rows.find((r) => r.label === "Completeness");
    expect(c?.value).toBe("45.2%");
  });

  it("formats avg_confidence as ratio 0–1", () => {
    const rows = buildQualityReportMetrics({ avg_confidence: 0.743 });
    const a = rows.find((r) => r.label === "Avg Confidence");
    expect(a?.value).toBe("74.3%");
  });

  it("includes class and property counts", () => {
    const rows = buildQualityReportMetrics({
      class_count: 12,
      property_count: 30,
    });
    expect(rows.some((r) => r.label === "Classes" && r.value === "12")).toBe(true);
    expect(rows.some((r) => r.label === "Properties" && r.value === "30")).toBe(true);
  });

  it("formats acceptance_rate as ratio", () => {
    const rows = buildQualityReportMetrics({ acceptance_rate: 0.8 });
    const x = rows.find((r) => r.label === "Curation acceptance");
    expect(x?.value).toBe("80.0%");
  });
});
