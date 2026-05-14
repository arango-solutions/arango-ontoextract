import { render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import QualityReportOverlay from "../QualityReportOverlay";

const loadQualityHistory = jest.fn();
const apiGet = jest.fn();

jest.mock("@/lib/qualityHistory", () => ({
  loadQualityHistory: (...args: unknown[]) => loadQualityHistory(...args),
}));

jest.mock("@/lib/api-client", () => ({
  api: {
    get: (...args: unknown[]) => apiGet(...args),
  },
  ApiError: class ApiError extends Error {
    public readonly status = 500;
    public readonly body = { code: "X", message: "stub" };
  },
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
    apiGet.mockReset();
    // Default revisions response: empty list so the activity tile
    // renders the "No belief-revision activity" copy without
    // dominating any test that doesn't care about it.
    apiGet.mockResolvedValue({ data: [], count: 0 });
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

  it("renders the IBR.19 revisions activity tile and surfaces the inbox CTA when pending > 0", async () => {
    apiGet.mockResolvedValue({
      data: [
        {
          _key: "rev-1",
          verdict: "REFINED",
          action: "REVISE",
          status: "pending",
          agent_type: "belief_revision_llm",
          created: 0,
        },
        {
          _key: "rev-2",
          verdict: "REINFORCED",
          action: "REINFORCE",
          status: "applied",
          agent_type: "belief_revision_llm",
          created: 0,
        },
        {
          _key: "rev-3",
          verdict: "CONTRADICTED",
          action: "FLAG_FOR_CURATION",
          status: "rejected",
          agent_type: "belief_revision_mechanical",
          created: 0,
        },
      ],
      count: 3,
    });
    const onShowInbox = jest.fn();

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
        }}
        onClose={() => {}}
        onShowInbox={onShowInbox}
      />,
    );

    await screen.findByText(/Revisions Activity/);
    await waitFor(() =>
      expect(apiGet).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/revisions/?ontology_id=onto_1"),
      ),
    );

    const inboxBtn = await screen.findByRole("button", { name: /Show inbox/ });
    inboxBtn.click();
    expect(onShowInbox).toHaveBeenCalledWith("onto_1", "Customer Ontology");

    expect(screen.getByText(/Verdict distribution/)).toBeInTheDocument();
    expect(screen.getByText(/REFINED · 1/)).toBeInTheDocument();
    expect(screen.getByText(/REINFORCED · 1/)).toBeInTheDocument();
    expect(screen.getByText(/CONTRADICTED · 1/)).toBeInTheDocument();
  });

  it("revisions tile renders an empty state when no audit rows exist", async () => {
    apiGet.mockResolvedValue({ data: [], count: 0 });

    render(
      <QualityReportOverlay
        name="Empty Activity"
        data={{
          ontology_id: "onto_2",
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

    await screen.findByText(/Revisions Activity/);
    expect(
      await screen.findByText(/No belief-revision activity recorded yet/),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Show inbox/ })).toBeNull();
  });
});
