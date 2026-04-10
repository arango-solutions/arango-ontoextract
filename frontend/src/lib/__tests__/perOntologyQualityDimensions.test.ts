import {
  PER_ONTOLOGY_QUALITY_DIMENSIONS,
  type PerOntologyQualityApiShape,
} from "../perOntologyQualityDimensions";

const base: PerOntologyQualityApiShape = {
  avg_confidence: 0.8,
  class_count: 10,
  property_count: 5,
  completeness: 60,
  connectivity: 40,
  relationship_count: 3,
  orphan_count: 1,
  has_cycles: false,
  health_score: 72,
  acceptance_rate: 0.9,
  schema_metrics: { annotation_completeness: 0.5 },
};

describe("PER_ONTOLOGY_QUALITY_DIMENSIONS", () => {
  it("maps completeness to 0–5 scale", () => {
    const d = PER_ONTOLOGY_QUALITY_DIMENSIONS.find((x) => x.key === "completeness")!;
    expect(d.compute(base)).toBeCloseTo(3, 5);
  });

  it("maps avg_confidence to faithfulness when avg_faithfulness is absent", () => {
    const d = PER_ONTOLOGY_QUALITY_DIMENSIONS.find((x) => x.key === "faithfulness")!;
    expect(d.compute({ ...base, avg_faithfulness: null })).toBeCloseTo(4, 5);
  });

  it("prefers avg_faithfulness over avg_confidence for faithfulness", () => {
    const d = PER_ONTOLOGY_QUALITY_DIMENSIONS.find((x) => x.key === "faithfulness")!;
    expect(
      d.compute({
        ...base,
        avg_faithfulness: 0.5,
        avg_confidence: 0.9,
      }),
    ).toBeCloseTo(2.5, 5);
  });

  it("returns null for faithfulness only when both faithfulness and confidence are missing", () => {
    const d = PER_ONTOLOGY_QUALITY_DIMENSIONS.find((x) => x.key === "faithfulness")!;
    expect(d.compute({ ...base, avg_faithfulness: null, avg_confidence: null })).toBeNull();
  });

  it("applies cycle penalty in structural integrity", () => {
    const d = PER_ONTOLOGY_QUALITY_DIMENSIONS.find((x) => x.key === "structural")!;
    const noCycle = d.compute({ ...base, has_cycles: false, orphan_count: 0 });
    const withCycle = d.compute({ ...base, has_cycles: true, orphan_count: 0 });
    expect(withCycle!).toBeLessThan(noCycle!);
  });
});
