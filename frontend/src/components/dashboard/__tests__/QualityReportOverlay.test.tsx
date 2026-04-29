import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import QualityReportOverlay from "../QualityReportOverlay";

const loadQualityHistory = jest.fn();

jest.mock("@/lib/qualityHistory", () => ({
  loadQualityHistory: (...args: unknown[]) => loadQualityHistory(...args),
}));

jest.mock("recharts", () => ({
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  Line: ({ name }: { name: string }) => <div>{name}</div>,
  LineChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  PolarAngleAxis: () => <div data-testid="polar-angle-axis" />,
  PolarGrid: () => <div data-testid="polar-grid" />,
  PolarRadiusAxis: () => <div data-testid="polar-radius-axis" />,
  Radar: () => <div data-testid="radar" />,
  RadarChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  ResponsiveContainer: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Tooltip: () => <div data-testid="tooltip" />,
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
}));

describe("QualityReportOverlay", () => {
  beforeEach(() => {
    loadQualityHistory.mockReset();
    loadQualityHistory.mockResolvedValue({
      ontology_id: "onto_1",
      count: 2,
      snapshots: [
        {
          _key: "snap1",
          ontology_id: "onto_1",
          timestamp: "2026-04-28T12:00:00+00:00",
          health_score: 75,
          completeness: 60,
          acceptance_rate: 0.8,
        },
        {
          _key: "snap2",
          ontology_id: "onto_1",
          timestamp: "2026-04-28T13:00:00+00:00",
          health_score: 82,
          completeness: 70,
          acceptance_rate: 0.9,
        },
      ],
    });
  });

  it("loads and renders quality history trends", async () => {
    render(
      <QualityReportOverlay
        name="Customer Ontology"
        data={{
          ontology_id: "onto_1",
          avg_confidence: 0.8,
          class_count: 10,
          property_count: 4,
          completeness: 70,
          connectivity: 50,
          relationship_count: 5,
          orphan_count: 1,
          has_cycles: false,
          health_score: 82,
          acceptance_rate: 0.9,
          schema_metrics: { annotation_completeness: 0.8 },
        }}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(loadQualityHistory).toHaveBeenCalledWith("onto_1", { limit: 30 });
    });
    expect(await screen.findByText("Quality History")).toBeInTheDocument();
    expect(screen.getByText("2 snapshots")).toBeInTheDocument();
    expect(screen.getAllByText("Health").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Completeness").length).toBeGreaterThan(0);
    expect(screen.getByText("Acceptance")).toBeInTheDocument();
    expect(screen.getByText("90.0%")).toBeInTheDocument();
  });

  it("does not request history when ontology id is missing", async () => {
    render(
      <QualityReportOverlay
        name="Missing ID"
        data={{
          avg_confidence: null,
          class_count: 0,
          property_count: 0,
          completeness: 0,
          connectivity: 0,
          relationship_count: 0,
          orphan_count: 0,
          has_cycles: false,
          health_score: null,
          acceptance_rate: null,
        }}
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Quality History")).toBeInTheDocument();
    });
    expect(loadQualityHistory).not.toHaveBeenCalled();
    expect(screen.getByText(/No historical snapshots yet/)).toBeInTheDocument();
  });
});
