import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import MergeCandidates from "@/components/curation/MergeCandidates";
import type { MergeCandidate } from "@/types/entity-resolution";

const MOCK_CANDIDATES: MergeCandidate[] = [
  {
    pair_id: "pair_001",
    entity_1: { key: "cls_001", uri: "http://example.org/Person", label: "Person" },
    entity_2: { key: "cls_002", uri: "http://example.org/Individual", label: "Individual" },
    overall_score: 0.92,
    field_scores: {
      label_sim: 0.7,
      description_sim: 0.95,
      uri_sim: 0.6,
      topology_sim: 0.88,
    },
    status: "pending",
  },
  {
    pair_id: "pair_002",
    entity_1: { key: "cls_003", uri: "http://example.org/Org", label: "Organization" },
    entity_2: { key: "cls_004", uri: "http://example.org/Company", label: "Company" },
    overall_score: 0.45,
    field_scores: {
      label_sim: 0.4,
      description_sim: 0.5,
      uri_sim: 0.3,
      topology_sim: 0.55,
    },
    status: "pending",
  },
];

const MOCK_EXPLANATION = {
  pair_id: "pair_001",
  entity_1: { key: "cls_001", uri: "http://example.org/Person", label: "Person" },
  entity_2: { key: "cls_002", uri: "http://example.org/Individual", label: "Individual" },
  overall_score: 0.92,
  fields: [
    {
      field_name: "label",
      value_1: "Person",
      value_2: "Individual",
      similarity: 0.7,
      method: "jaro_winkler" as const,
    },
    {
      field_name: "description",
      value_1: "A human being",
      value_2: "A single person",
      similarity: 0.95,
      method: "cosine" as const,
    },
  ],
};

function mockFetchCandidates() {
  global.fetch = jest.fn().mockImplementation((url: string) => {
    if (url.includes("/candidates") && !url.includes("/explain") && !url.includes("/accept") && !url.includes("/reject")) {
      return Promise.resolve({
        ok: true,
        json: () =>
          Promise.resolve({
            data: MOCK_CANDIDATES,
            cursor: null,
            has_more: false,
            total_count: 2,
          }),
      });
    }
    if (url.includes("/explain")) {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(MOCK_EXPLANATION),
      });
    }
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve({ status: "ok" }),
    });
  });
}

afterEach(() => {
  jest.restoreAllMocks();
});

describe("MergeCandidates", () => {
  it("renders candidate list after loading", async () => {
    mockFetchCandidates();
    render(<MergeCandidates />);

    await waitFor(() => {
      expect(screen.getByTestId("candidate-pair_001")).toBeInTheDocument();
    });

    expect(screen.getByTestId("candidate-pair_002")).toBeInTheDocument();
    expect(screen.getByText("Person")).toBeInTheDocument();
    expect(screen.getByText("Individual")).toBeInTheDocument();
    expect(screen.getByText("Organization")).toBeInTheDocument();
    expect(screen.getByText("Company")).toBeInTheDocument();
  });

  it("displays overall score bars for each candidate", async () => {
    mockFetchCandidates();
    render(<MergeCandidates />);

    await waitFor(() => {
      expect(screen.getByTestId("score-bar-pair_001")).toBeInTheDocument();
    });

    const scoreBar1 = screen.getByTestId("score-bar-pair_001");
    expect(scoreBar1).toHaveStyle({ width: "92%" });

    const scoreBar2 = screen.getByTestId("score-bar-pair_002");
    expect(scoreBar2).toHaveStyle({ width: "45%" });
  });

  it("filters candidates by score threshold", async () => {
    mockFetchCandidates();
    render(<MergeCandidates />);

    await waitFor(() => {
      expect(screen.getByTestId("candidate-pair_001")).toBeInTheDocument();
    });

    const slider = screen.getByTestId("score-threshold-slider");
    fireEvent.change(slider, { target: { value: "50" } });

    expect(screen.getByTestId("candidate-pair_001")).toBeInTheDocument();
    expect(
      screen.queryByTestId("candidate-pair_002"),
    ).not.toBeInTheDocument();
  });

  it("shows explain panel when Explain is clicked", async () => {
    mockFetchCandidates();
    render(<MergeCandidates />);

    await waitFor(() => {
      expect(screen.getByTestId("explain-btn-pair_001")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("explain-btn-pair_001"));

    await waitFor(() => {
      expect(screen.getByTestId("explanation-pair_001")).toBeInTheDocument();
    });

    expect(screen.getByTestId("explanation-table")).toBeInTheDocument();
    expect(screen.getByText("label")).toBeInTheDocument();
    expect(screen.getByText("description")).toBeInTheDocument();
  });

  it("calls onAcceptMerge when Accept is clicked", async () => {
    mockFetchCandidates();
    const onAcceptMerge = jest.fn();
    render(<MergeCandidates onAcceptMerge={onAcceptMerge} />);

    await waitFor(() => {
      expect(screen.getByTestId("accept-btn-pair_001")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("accept-btn-pair_001"));

    await waitFor(() => {
      expect(onAcceptMerge).toHaveBeenCalledWith(MOCK_CANDIDATES[0]);
    });
  });

  it("updates candidate status on reject", async () => {
    mockFetchCandidates();
    render(<MergeCandidates />);

    await waitFor(() => {
      expect(screen.getByTestId("reject-btn-pair_001")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("reject-btn-pair_001"));

    await waitFor(() => {
      expect(screen.getByTestId("status-pair_001")).toHaveTextContent(
        "Rejected",
      );
    });
  });

  it("shows empty state when no candidates match threshold", async () => {
    mockFetchCandidates();
    render(<MergeCandidates />);

    await waitFor(() => {
      expect(screen.getByTestId("candidate-pair_001")).toBeInTheDocument();
    });

    const slider = screen.getByTestId("score-threshold-slider");
    fireEvent.change(slider, { target: { value: "99" } });

    expect(screen.getByTestId("no-candidates")).toBeInTheDocument();
  });

  it("displays score threshold value", async () => {
    mockFetchCandidates();
    render(<MergeCandidates />);

    await waitFor(() => {
      expect(screen.getByTestId("score-threshold-value")).toHaveTextContent(
        "0%",
      );
    });

    const slider = screen.getByTestId("score-threshold-slider");
    fireEvent.change(slider, { target: { value: "75" } });

    expect(screen.getByTestId("score-threshold-value")).toHaveTextContent(
      "75%",
    );
  });
});
