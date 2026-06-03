import { render, screen } from "@testing-library/react";
import type { OntologyScorecard } from "@/types/curation";
import MetricCards from "../MetricCards";

function scorecard(overrides: Partial<OntologyScorecard> = {}): OntologyScorecard {
  return {
    ontology_id: "o1",
    name: "Demo",
    tier: "domain",
    health_score: 80,
    avg_confidence: 0.8,
    avg_faithfulness: 0.9,
    avg_semantic_validity: 0.85,
    completeness: 100,
    connectivity: 100,
    relationship_count: 10,
    class_count: 5,
    property_count: 8,
    orphan_count: 1,
    has_cycles: false,
    classes_without_properties: 0,
    estimated_cost: 0.01,
    schema_metrics: null,
    ...overrides,
  };
}

describe("MetricCards (Stream 15 SO.2)", () => {
  it("prefers the backend structural_integrity over the client fallback", () => {
    // Client fallback for orphan_count=1/class_count=5 would be 0.80;
    // the backend value (0.70) must win.
    render(<MetricCards ontology={scorecard({ structural_integrity: 0.7 })} />);
    expect(screen.getByText("0.70")).toBeInTheDocument();
  });

  it("falls back to the client formula when backend value is absent", () => {
    render(<MetricCards ontology={scorecard({ structural_integrity: null })} />);
    // 1 - 0 - 1/5 = 0.80
    expect(screen.getByText("0.80")).toBeInTheDocument();
  });

  it("renders the Isolated Classes card from island_count", () => {
    render(<MetricCards ontology={scorecard({ island_count: 4 })} />);
    expect(screen.getByText("Isolated Classes")).toBeInTheDocument();
    expect(screen.getByText("4")).toBeInTheDocument();
  });

  it("defaults Isolated Classes to 0 when island_count is missing", () => {
    render(<MetricCards ontology={scorecard()} />);
    expect(screen.getByText("Isolated Classes")).toBeInTheDocument();
    // "0" is the island card's value; other cards render "0.90", "100%", etc.
    expect(screen.getByText("0")).toBeInTheDocument();
  });
});
