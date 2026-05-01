import { render, screen, fireEvent, waitFor, act } from "@testing-library/react";
import PipelineHistorySlider from "../PipelineHistorySlider";

const MOCK_RUNS = [
  {
    _key: "run_001",
    document_id: "doc_1",
    document_name: "report.pdf",
    status: "completed" as const,
    created_at: "2026-04-09T10:00:00Z",
    updated_at: "2026-04-09T10:05:00Z",
    started_at: 1744192800,
    completed_at: 1744193100,
    duration_ms: 5000,
    classes_extracted: 12,
  },
  {
    _key: "run_002",
    document_id: "doc_2",
    document_name: "spec.md",
    status: "failed" as const,
    created_at: "2026-04-09T11:00:00Z",
    updated_at: "2026-04-09T11:02:00Z",
    started_at: 1744196400,
    duration_ms: 2000,
    error_count: 1,
  },
  {
    _key: "run_003",
    document_id: "doc_3",
    document_name: "policy.docx",
    status: "completed" as const,
    created_at: "2026-04-09T12:00:00Z",
    updated_at: "2026-04-09T12:10:00Z",
    started_at: 1744200000,
    completed_at: 1744200600,
    duration_ms: 10000,
    classes_extracted: 25,
  },
];

const mockFetch = jest.fn();

beforeEach(() => {
  mockFetch.mockReset();
  globalThis.fetch = mockFetch;
});

function stubRuns(runs = MOCK_RUNS) {
  mockFetch.mockImplementation(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          data: runs,
          cursor: null,
          has_more: false,
          total_count: runs.length,
        }),
      headers: new Headers({ "content-type": "application/json" }),
    }),
  );
}

function stubEmpty() {
  mockFetch.mockImplementation(() =>
    Promise.resolve({
      ok: true,
      status: 200,
      json: () =>
        Promise.resolve({
          data: [],
          cursor: null,
          has_more: false,
          total_count: 0,
        }),
      headers: new Headers({ "content-type": "application/json" }),
    }),
  );
}

describe("PipelineHistorySlider", () => {
  it("shows loading state initially", () => {
    mockFetch.mockImplementation(() => new Promise(() => {}));
    render(
      <PipelineHistorySlider onSelectRun={jest.fn()} selectedRunId={null} />,
    );
    expect(screen.getByTestId("history-slider-loading")).toBeInTheDocument();
  });

  it("shows empty state when no runs exist", async () => {
    stubEmpty();
    render(
      <PipelineHistorySlider onSelectRun={jest.fn()} selectedRunId={null} />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("history-slider-empty")).toBeInTheDocument();
    });
  });

  it("renders slider with correct range when runs are loaded", async () => {
    stubRuns();
    render(
      <PipelineHistorySlider onSelectRun={jest.fn()} selectedRunId={null} />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("pipeline-history-slider")).toBeInTheDocument();
    });
    const slider = screen.getByTestId("history-slider") as HTMLInputElement;
    expect(slider.min).toBe("0");
    expect(slider.max).toBe("2");
  });

  it("shows run count", async () => {
    stubRuns();
    render(
      <PipelineHistorySlider onSelectRun={jest.fn()} selectedRunId={null} />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("history-counter")).toHaveTextContent("3 / 3");
    });
  });

  it("fires onSelectRun when slider value changes", async () => {
    stubRuns();
    const onSelectRun = jest.fn();
    render(
      <PipelineHistorySlider
        onSelectRun={onSelectRun}
        selectedRunId="run_003"
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("history-slider")).toBeInTheDocument();
    });

    const slider = screen.getByTestId("history-slider") as HTMLInputElement;
    await act(async () => {
      fireEvent.change(slider, { target: { value: "0" } });
    });

    await waitFor(() => {
      expect(onSelectRun).toHaveBeenCalledWith("run_001");
    });
  });

  it("displays current run document name and status", async () => {
    stubRuns();
    render(
      <PipelineHistorySlider
        onSelectRun={jest.fn()}
        selectedRunId="run_003"
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("policy.docx")).toBeInTheDocument();
      expect(screen.getByText("completed")).toBeInTheDocument();
    });
  });

  it("displays class count for runs with extracted classes", async () => {
    stubRuns();
    render(
      <PipelineHistorySlider
        onSelectRun={jest.fn()}
        selectedRunId="run_003"
      />,
    );
    await waitFor(() => {
      expect(screen.getByText("25 classes")).toBeInTheDocument();
    });
  });

  it("syncs slider position when selectedRunId changes externally", async () => {
    stubRuns();
    const { rerender } = render(
      <PipelineHistorySlider
        onSelectRun={jest.fn()}
        selectedRunId="run_003"
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("history-slider")).toBeInTheDocument();
    });

    rerender(
      <PipelineHistorySlider
        onSelectRun={jest.fn()}
        selectedRunId="run_001"
      />,
    );

    await waitFor(() => {
      const slider = screen.getByTestId("history-slider") as HTMLInputElement;
      expect(slider.value).toBe("0");
    });
  });

  it("has play/pause, rewind, and fast-forward buttons", async () => {
    stubRuns();
    render(
      <PipelineHistorySlider onSelectRun={jest.fn()} selectedRunId={null} />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("history-play-pause")).toBeInTheDocument();
      expect(screen.getByTestId("history-rewind")).toBeInTheDocument();
      expect(screen.getByTestId("history-ff")).toBeInTheDocument();
    });
  });

  it("has a speed control button", async () => {
    stubRuns();
    render(
      <PipelineHistorySlider onSelectRun={jest.fn()} selectedRunId={null} />,
    );
    await waitFor(() => {
      const speedBtn = screen.getByTestId("history-speed");
      expect(speedBtn).toHaveTextContent("1x");
      fireEvent.click(speedBtn);
      expect(speedBtn).toHaveTextContent("2x");
    });
  });

  // Regression: a previous version had two effects that sync'd selectedRunId
  // ↔ currentIndex bidirectionally. They ping-ponged forever whenever the
  // initial selectedRunId pointed to a run that wasn't the most recent one,
  // because `fetchAllRuns` always sets currentIndex = runs.length-1. Each
  // bounce called onSelectRun, which (via the parent) reopened the WebSocket
  // and re-fetched run metrics — flickering the page and spamming the server.
  it("does not call onSelectRun when external selectedRunId is non-latest", async () => {
    stubRuns();
    const onSelectRun = jest.fn();
    render(
      <PipelineHistorySlider
        onSelectRun={onSelectRun}
        selectedRunId="run_001"
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("pipeline-history-slider")).toBeInTheDocument();
    });
    // Give any pending effects a chance to flush.
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    // The slider should sync to position 0 (run_001) without ever calling
    // onSelectRun — selectedRunId is the source of truth, not the slider.
    const slider = screen.getByTestId("history-slider") as HTMLInputElement;
    expect(slider.value).toBe("0");
    expect(onSelectRun).not.toHaveBeenCalled();
  });

  // Regression: with the bidirectional sync removed, an unstable
  // `onSelectRun` prop reference (e.g. inline arrow in the parent) must not
  // cause the slider to re-emit a selection for the same run.
  it("does not re-emit onSelectRun when only its prop reference changes", async () => {
    stubRuns();
    const calls: string[] = [];
    const { rerender } = render(
      <PipelineHistorySlider
        onSelectRun={(id) => calls.push(id)}
        selectedRunId="run_002"
      />,
    );
    await waitFor(() => {
      expect(screen.getByTestId("pipeline-history-slider")).toBeInTheDocument();
    });
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    // Re-render with a fresh inline handler reference but unchanged
    // selectedRunId — this used to trigger the auto-call effect.
    rerender(
      <PipelineHistorySlider
        onSelectRun={(id) => calls.push(id)}
        selectedRunId="run_002"
      />,
    );
    await act(async () => {
      await new Promise((r) => setTimeout(r, 50));
    });
    expect(calls).toEqual([]);
  });
});
