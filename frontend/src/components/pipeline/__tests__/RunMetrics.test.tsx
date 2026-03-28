import { render, screen, waitFor } from "@testing-library/react";
import RunMetrics from "@/components/pipeline/RunMetrics";
import type { RunCostResponse } from "@/types/pipeline";

const mockMetrics: RunCostResponse = {
  run_id: "run_123",
  total_duration_ms: 102_000,
  prompt_tokens: 8_000,
  completion_tokens: 4_450,
  total_tokens: 12_450,
  estimated_cost: 0.18,
  classes_extracted: 28,
  properties_extracted: 6,
  pass_agreement_rate: 0.857,
};

function mockFetchMetrics(data: RunCostResponse) {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve(data),
  });
}

function mockFetchError() {
  global.fetch = jest.fn().mockResolvedValue({
    ok: false,
    statusText: "Internal Server Error",
    json: () =>
      Promise.resolve({
        error: {
          code: "INTERNAL_ERROR",
          message: "Failed to compute cost",
        },
      }),
  });
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe("RunMetrics", () => {
  it("shows empty state when no runId", () => {
    render(<RunMetrics runId={null} />);
    expect(screen.getByTestId("metrics-empty")).toBeInTheDocument();
    expect(
      screen.getByText("Select a run to view metrics."),
    ).toBeInTheDocument();
  });

  it("shows loading skeletons while fetching", () => {
    global.fetch = jest.fn().mockReturnValue(new Promise(() => {}));
    render(<RunMetrics runId="run_123" />);
    expect(screen.getByTestId("metrics-loading")).toBeInTheDocument();
  });

  it("displays metrics after successful fetch", async () => {
    mockFetchMetrics(mockMetrics);
    render(<RunMetrics runId="run_123" />);

    await waitFor(() => {
      expect(screen.getByTestId("run-metrics")).toBeInTheDocument();
    });

    expect(screen.getByText("1m 42s")).toBeInTheDocument();
    expect(screen.getByText("12,450")).toBeInTheDocument();
    expect(screen.getByText("$0.18")).toBeInTheDocument();
    expect(screen.getByText("34")).toBeInTheDocument();
    expect(screen.getByText("85.7%")).toBeInTheDocument();
  });

  it("shows token breakdown sublabel", async () => {
    mockFetchMetrics(mockMetrics);
    render(<RunMetrics runId="run_123" />);

    await waitFor(() => {
      expect(
        screen.getByText("8,000 prompt + 4,450 completion"),
      ).toBeInTheDocument();
    });
  });

  it("shows entity count breakdown sublabel", async () => {
    mockFetchMetrics(mockMetrics);
    render(<RunMetrics runId="run_123" />);

    await waitFor(() => {
      expect(
        screen.getByText("28 classes + 6 properties"),
      ).toBeInTheDocument();
    });
  });

  it("shows error state on fetch failure", async () => {
    mockFetchError();
    render(<RunMetrics runId="run_123" />);

    await waitFor(() => {
      expect(screen.getByTestId("metrics-error")).toBeInTheDocument();
    });
  });
});
