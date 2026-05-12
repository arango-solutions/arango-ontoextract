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

  // -------------------------------------------------------------------
  // IBR.12 -- Belief Revision tiles
  // -------------------------------------------------------------------
  // These tests pin the three states the Pipeline Monitor must handle
  // distinctly so future refactors can't silently break IBR rendering.

  describe("Belief Revision tiles", () => {
    it("renders a neutral 'no IBR data' tile for legacy runs", async () => {
      // belief_revision missing entirely (legacy pre-IBR run, or a
      // crash before the IBR node fired).
      mockFetchMetrics(mockMetrics);
      render(<RunMetrics runId="run_123" />);

      await waitFor(() => {
        expect(screen.getByTestId("run-metrics")).toBeInTheDocument();
      });

      expect(screen.getByText("Belief Revision")).toBeInTheDocument();
      expect(
        screen.getByText("No IBR data on this run"),
      ).toBeInTheDocument();
      // Make sure we DON'T render the per-bucket tiles for the
      // legacy case -- otherwise users see four "0"s and assume IBR
      // ran with zero work to do.
      expect(screen.queryByText("IBR Touchpoints")).not.toBeInTheDocument();
      expect(screen.queryByText("IBR Verdicts")).not.toBeInTheDocument();
    });

    it("renders a single 'Skipped' tile with reason when IBR was disabled", async () => {
      mockFetchMetrics({
        ...mockMetrics,
        belief_revision: {
          status: "skipped",
          reason: "feature_flag_off",
          touchpoints_discovered: 0,
          verdict_counts: {},
          auto_applied: 0,
          flagged_for_curation: 0,
          llm_invocations: 0,
          skipped_idempotency: 0,
        },
      });
      render(<RunMetrics runId="run_123" />);

      await waitFor(() => {
        expect(screen.getByTestId("run-metrics")).toBeInTheDocument();
      });

      expect(screen.getByText("Belief Revision")).toBeInTheDocument();
      expect(screen.getByText("Skipped")).toBeInTheDocument();
      // Human-readable reason mapped from the wire code.
      expect(
        screen.getByText("IBR disabled in this environment"),
      ).toBeInTheDocument();
    });

    it("renders the raw reason code when it isn't in the label map", async () => {
      // Forward-compat: a future backend reason that the frontend
      // doesn't yet know about must still surface to the user (so a
      // bug report can quote the symbol), not silently disappear.
      mockFetchMetrics({
        ...mockMetrics,
        belief_revision: {
          status: "skipped",
          reason: "future_unknown_reason",
          touchpoints_discovered: 0,
          verdict_counts: {},
          auto_applied: 0,
          flagged_for_curation: 0,
          llm_invocations: 0,
          skipped_idempotency: 0,
        },
      });
      render(<RunMetrics runId="run_123" />);

      await waitFor(() => {
        expect(
          screen.getByText("Skipped: future_unknown_reason"),
        ).toBeInTheDocument();
      });
    });

    it("renders four IBR tiles with counts and verdict breakdown when completed", async () => {
      mockFetchMetrics({
        ...mockMetrics,
        belief_revision: {
          status: "completed",
          touchpoints_discovered: 12,
          verdict_counts: {
            AUTO_MERGE: 5,
            FLAG_FOR_CURATION: 3,
            STRENGTHEN_NEW: 2,
          },
          auto_applied: 7,
          flagged_for_curation: 3,
          llm_invocations: 4,
          skipped_idempotency: 2,
        },
      });
      render(<RunMetrics runId="run_123" />);

      await waitFor(() => {
        expect(screen.getByTestId("run-metrics")).toBeInTheDocument();
      });

      // Touchpoints tile
      expect(screen.getByText("IBR Touchpoints")).toBeInTheDocument();
      expect(screen.getByText("12")).toBeInTheDocument();
      expect(screen.getByText("4 LLM calls")).toBeInTheDocument();

      // Verdicts tile -- value is the SUM, sublabel is the
      // frequency-sorted breakdown (5 + 3 + 2 = 10).
      expect(screen.getByText("IBR Verdicts")).toBeInTheDocument();
      expect(screen.getByText("10")).toBeInTheDocument();
      expect(
        screen.getByText("AUTO_MERGE 5 · FLAG·CURATION 3 · STRENGTHEN_NEW 2"),
      ).toBeInTheDocument();

      // Auto-applied tile -- with idempotency sublabel.
      expect(screen.getByText("IBR Auto-applied")).toBeInTheDocument();
      expect(screen.getByText("7")).toBeInTheDocument();
      expect(
        screen.getByText("2 skipped (idempotent)"),
      ).toBeInTheDocument();

      // Flagged tile -- pending-review sublabel.
      expect(
        screen.getByText("IBR Flagged for Curation"),
      ).toBeInTheDocument();
      expect(screen.getByText("3")).toBeInTheDocument();
      expect(screen.getByText("Awaiting human review")).toBeInTheDocument();
    });

    it("singularises the LLM-call sublabel for one call", async () => {
      mockFetchMetrics({
        ...mockMetrics,
        belief_revision: {
          status: "completed",
          touchpoints_discovered: 1,
          verdict_counts: { AUTO_MERGE: 1 },
          auto_applied: 1,
          flagged_for_curation: 0,
          llm_invocations: 1,
          skipped_idempotency: 0,
        },
      });
      render(<RunMetrics runId="run_123" />);

      await waitFor(() => {
        expect(screen.getByText("1 LLM call")).toBeInTheDocument();
      });
    });

    it("shows '(failed)' suffix when IBR phase failed", async () => {
      mockFetchMetrics({
        ...mockMetrics,
        belief_revision: {
          status: "failed",
          touchpoints_discovered: 5,
          verdict_counts: { AUTO_MERGE: 2 },
          auto_applied: 2,
          flagged_for_curation: 0,
          llm_invocations: 1,
          skipped_idempotency: 0,
        },
      });
      render(<RunMetrics runId="run_123" />);

      await waitFor(() => {
        expect(
          screen.getByText("IBR Touchpoints (failed)"),
        ).toBeInTheDocument();
      });
    });

    it("renders the verdicts tile with sum=0 when verdict_counts is empty", async () => {
      // Edge case: IBR ran but found no contested touchpoints, so no
      // verdict was emitted. Tile should still render (don't suppress
      // it -- the user should see "ran with 0 verdicts" not "tile
      // missing"). Scope to the Verdicts tile to avoid colliding
      // with the placeholder "—" rendered by the
      // Avg-Confidence / Completeness tiles when those are null.
      mockFetchMetrics({
        ...mockMetrics,
        belief_revision: {
          status: "completed",
          touchpoints_discovered: 0,
          verdict_counts: {},
          auto_applied: 0,
          flagged_for_curation: 0,
          llm_invocations: 0,
          skipped_idempotency: 0,
        },
      });
      render(<RunMetrics runId="run_123" />);

      await waitFor(() => {
        expect(screen.getByText("IBR Verdicts")).toBeInTheDocument();
      });
      // The label sits in its own div inside the tile root; walk up
      // one level (parentElement) to grab the whole MetricCard so we
      // can inspect value + sublabel together.
      const verdictsTile =
        screen.getByText("IBR Verdicts").parentElement;
      expect(verdictsTile).not.toBeNull();
      expect(verdictsTile!.textContent).toContain("IBR Verdicts");
      expect(verdictsTile!.textContent).toContain("0");
      expect(verdictsTile!.textContent).toContain("—");
    });
  });
});
