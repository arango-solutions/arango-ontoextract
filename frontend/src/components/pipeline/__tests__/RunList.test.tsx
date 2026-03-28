import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import RunList from "@/components/pipeline/RunList";
import type { ExtractionRun } from "@/types/pipeline";

const mockRuns: ExtractionRun[] = [
  {
    _key: "run_abc123def456",
    document_id: "doc_1",
    document_name: "policy_doc.pdf",
    status: "completed",
    created_at: new Date(Date.now() - 120_000).toISOString(),
    updated_at: new Date().toISOString(),
    duration_ms: 45_000,
  },
  {
    _key: "run_xyz789",
    document_id: "doc_2",
    document_name: "spec_document.docx",
    status: "running",
    created_at: new Date(Date.now() - 60_000).toISOString(),
    updated_at: new Date().toISOString(),
    duration_ms: undefined,
  },
  {
    _key: "run_failed_001",
    document_id: "doc_3",
    document_name: "broken_file.md",
    status: "failed",
    created_at: new Date(Date.now() - 300_000).toISOString(),
    updated_at: new Date().toISOString(),
    duration_ms: 12_000,
  },
];

function mockFetchSuccess(data: ExtractionRun[]) {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: () =>
      Promise.resolve({
        data,
        cursor: null,
        has_more: false,
        total_count: data.length,
      }),
  });
}

function mockFetchEmpty() {
  global.fetch = jest.fn().mockResolvedValue({
    ok: true,
    json: () =>
      Promise.resolve({
        data: [],
        cursor: null,
        has_more: false,
        total_count: 0,
      }),
  });
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe("RunList", () => {
  it("renders the run list with items", async () => {
    mockFetchSuccess(mockRuns);
    render(<RunList onSelectRun={jest.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("policy_doc.pdf")).toBeInTheDocument();
    });
    expect(screen.getByText("spec_document.docx")).toBeInTheDocument();
    expect(screen.getByText("broken_file.md")).toBeInTheDocument();
  });

  it("shows empty state when no runs exist", async () => {
    mockFetchEmpty();
    render(<RunList onSelectRun={jest.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    });
    expect(
      screen.getByText("No extraction runs found."),
    ).toBeInTheDocument();
  });

  it("calls onSelectRun when a run is clicked", async () => {
    mockFetchSuccess(mockRuns);
    const onSelect = jest.fn();
    render(<RunList onSelectRun={onSelect} />);

    await waitFor(() => {
      expect(screen.getByText("policy_doc.pdf")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("run-item-run_abc123def456"));
    expect(onSelect).toHaveBeenCalledWith("run_abc123def456");
  });

  it("highlights the selected run", async () => {
    mockFetchSuccess(mockRuns);
    render(
      <RunList
        onSelectRun={jest.fn()}
        selectedRunId="run_abc123def456"
      />,
    );

    await waitFor(() => {
      const button = screen.getByTestId("run-item-run_abc123def456");
      expect(button.className).toContain("bg-blue-50");
    });
  });

  it("has a status filter dropdown", async () => {
    mockFetchSuccess(mockRuns);
    render(<RunList onSelectRun={jest.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId("status-filter")).toBeInTheDocument();
    });
  });

  it("changes filter and refetches", async () => {
    mockFetchSuccess(mockRuns);
    render(<RunList onSelectRun={jest.fn()} />);

    await waitFor(() => {
      expect(screen.getByTestId("status-filter")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByTestId("status-filter"), {
      target: { value: "failed" },
    });

    await waitFor(() => {
      expect(global.fetch).toHaveBeenCalledTimes(2);
    });
  });

  it("displays truncated run IDs", async () => {
    mockFetchSuccess(mockRuns);
    render(<RunList onSelectRun={jest.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("run_abc123de\u2026")).toBeInTheDocument();
    });
  });
});
