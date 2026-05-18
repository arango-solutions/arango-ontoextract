/**
 * Tests for ``MergeCandidatesOverlay`` (Stream 2 PR 1).
 *
 * Pins the wire path:
 *   - Triggers ER pipeline run on mount (POST /api/v1/er/run)
 *   - Fetches candidates after the run completes (GET .../runs/{id}/candidates)
 *   - Renders one row per candidate; empty / loading / failure states
 *   - Accept / Dismiss buttons dispatch the correct POST and remove
 *     the row optimistically
 *   - Explain expansion fires GET .../candidates/{pair_id}/explain and
 *     shows the per-field score table
 *   - The min-score slider filters visible rows without dropping them
 *     from local state
 *
 * ``api`` is mocked at the module boundary so we never touch the
 * network.
 */

import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";

import MergeCandidatesOverlay from "../MergeCandidatesOverlay";

const apiGet = jest.fn();
const apiPost = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
  },
  // Match the production signature so a future ApiError catch in the
  // component does not pass a wrong-shape error through (mock-fidelity
  // rule).
  ApiError: class ApiError extends Error {
    public readonly status: number;
    public readonly body: { code: string; message: string };
    constructor(status = 500, body = { code: "X", message: "stub" }) {
      super(body.message);
      this.status = status;
      this.body = body;
    }
  },
}));

function makeRun(overrides: Record<string, unknown> = {}) {
  return {
    run_id: "er_run_1",
    status: "complete",
    candidate_count: 0,
    cluster_count: 0,
    duration_seconds: 0.2,
    error: null,
    ...overrides,
  };
}

function makeCandidate(overrides: Record<string, unknown> = {}) {
  return {
    pair_id: "pair_1",
    source_key: "ont1__Customer",
    source_label: "Customer",
    source_uri: "http://ex.org#Customer",
    target_key: "ont1__Client",
    target_label: "Client",
    target_uri: "http://ex.org#Client",
    combined_score: 0.91,
    field_scores: { label_jaro_winkler: 0.95, uri_exact: 0 },
    topological_score: 0.7,
    accepted_at: null,
    rejected_at: null,
    ...overrides,
  };
}

describe("MergeCandidatesOverlay", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiPost.mockReset();
  });

  it("triggers an ER run on mount and then fetches candidates", async () => {
    apiPost.mockResolvedValueOnce(makeRun({ run_id: "er_xyz" }));
    apiGet.mockResolvedValueOnce({
      data: [makeCandidate()],
      total_count: 1,
    });

    render(
      <MergeCandidatesOverlay
        ontologyId="ont1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
      />,
    );

    expect(apiPost).toHaveBeenCalledWith("/api/v1/er/run", {
      ontology_id: "ont1",
    });

    // Candidate list AQL fires after the run completes -- run-id from
    // the run response must thread into the URL.
    await waitFor(() =>
      expect(apiGet).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/er/runs/er_xyz/candidates"),
      ),
    );

    await screen.findByText("Customer");
    expect(screen.getByText("Client")).toBeInTheDocument();
  });

  it("renders the empty state when the run finds zero candidates", async () => {
    apiPost.mockResolvedValueOnce(makeRun());
    apiGet.mockResolvedValueOnce({ data: [], total_count: 0 });

    render(
      <MergeCandidatesOverlay
        ontologyId="ont1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
      />,
    );

    await screen.findByTestId("merge-empty");
    expect(screen.getByText(/No duplicate candidates found/)).toBeInTheDocument();
  });

  it("surfaces a failed ER pipeline run", async () => {
    apiPost.mockResolvedValueOnce(
      makeRun({ status: "failed", error: "blocking step crashed" }),
    );

    render(
      <MergeCandidatesOverlay
        ontologyId="ont1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
      />,
    );

    await screen.findByTestId("merge-failed");
    expect(screen.getByText("blocking step crashed")).toBeInTheDocument();
  });

  it("accepts a pair: POSTs accept, removes the row optimistically, fires onChanged", async () => {
    apiPost.mockResolvedValueOnce(makeRun()); // run
    apiGet.mockResolvedValueOnce({
      data: [makeCandidate(), makeCandidate({ pair_id: "pair_2", source_label: "Order" })],
      total_count: 2,
    });
    const onChanged = jest.fn();

    render(
      <MergeCandidatesOverlay
        ontologyId="ont1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
        onChanged={onChanged}
      />,
    );

    await screen.findByText("Customer");

    // Second apiPost call = the accept itself. Returning the
    // status-shape the backend now emits keeps the toast assertion
    // honest.
    apiPost.mockResolvedValueOnce({
      pair_id: "pair_1",
      status: "accepted",
      accepted_at: Date.now() / 1000,
    });

    fireEvent.click(screen.getByTestId("merge-accept-btn-pair_1"));

    await waitFor(() =>
      expect(apiPost).toHaveBeenLastCalledWith(
        "/api/v1/er/candidates/pair_1/accept",
      ),
    );

    // Row removed optimistically -- second card still there.
    await waitFor(() =>
      expect(screen.queryByTestId("merge-row-pair_1")).toBeNull(),
    );
    expect(screen.getByTestId("merge-row-pair_2")).toBeInTheDocument();
    expect(onChanged).toHaveBeenCalled();
  });

  it("dismisses a pair: POSTs reject and removes the row", async () => {
    apiPost.mockResolvedValueOnce(makeRun());
    apiGet.mockResolvedValueOnce({
      data: [makeCandidate()],
      total_count: 1,
    });

    render(
      <MergeCandidatesOverlay
        ontologyId="ont1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
      />,
    );

    await screen.findByText("Customer");

    apiPost.mockResolvedValueOnce({
      pair_id: "pair_1",
      status: "rejected",
      rejected_at: Date.now() / 1000,
    });

    fireEvent.click(screen.getByTestId("merge-reject-btn-pair_1"));

    await waitFor(() =>
      expect(apiPost).toHaveBeenLastCalledWith(
        "/api/v1/er/candidates/pair_1/reject",
      ),
    );
    await waitFor(() =>
      expect(screen.queryByTestId("merge-row-pair_1")).toBeNull(),
    );
  });

  it("expands explain: fires GET /explain and renders the per-field score table", async () => {
    apiPost.mockResolvedValueOnce(makeRun());
    apiGet.mockResolvedValueOnce({
      data: [makeCandidate()],
      total_count: 1,
    });

    render(
      <MergeCandidatesOverlay
        ontologyId="ont1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
      />,
    );

    await screen.findByText("Customer");

    apiGet.mockResolvedValueOnce({
      pair_id: "pair_1",
      key1: "ont1__Customer",
      key2: "ont1__Client",
      class_1: { label: "Customer", uri: "u1" },
      class_2: { label: "Client", uri: "u2" },
      field_scores: {
        label_jaro_winkler: 0.95,
        description_token_overlap: 0.5,
        uri_exact: 0,
        topological: 0.7,
      },
      combined_score: 0.91,
    });

    fireEvent.click(screen.getByTestId("merge-explain-btn-pair_1"));

    await waitFor(() =>
      expect(apiGet).toHaveBeenLastCalledWith(
        "/api/v1/er/candidates/pair_1/explain",
      ),
    );

    await screen.findByTestId("merge-explanation-pair_1");
    // Field display name humanises the snake_case algorithm name.
    expect(screen.getByText(/Label Jaro Winkler/)).toBeInTheDocument();
    expect(screen.getByText(/Topological/)).toBeInTheDocument();
  });

  it("filters rows by the min-score slider without dropping them from state", async () => {
    apiPost.mockResolvedValueOnce(makeRun());
    apiGet.mockResolvedValueOnce({
      data: [
        makeCandidate({ pair_id: "p_high", combined_score: 0.95 }),
        makeCandidate({ pair_id: "p_low", combined_score: 0.55, source_label: "Order" }),
      ],
      total_count: 2,
    });

    render(
      <MergeCandidatesOverlay
        ontologyId="ont1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
      />,
    );

    await screen.findByText("Customer");
    // Default min-score is 0.7 -> only the high-score row visible.
    expect(screen.getByTestId("merge-row-p_high")).toBeInTheDocument();
    expect(screen.queryByTestId("merge-row-p_low")).toBeNull();

    // Drag the slider down to 0% -> both rows now visible. The
    // low-score row was never dropped from state, just hidden.
    const slider = screen.getByTestId("merge-min-score-slider");
    fireEvent.change(slider, { target: { value: "0" } });

    expect(screen.getByTestId("merge-row-p_low")).toBeInTheDocument();
  });

  it("Esc collapses the explain panel first, then closes the overlay", async () => {
    apiPost.mockResolvedValueOnce(makeRun());
    apiGet.mockResolvedValueOnce({
      data: [makeCandidate()],
      total_count: 1,
    });
    const onClose = jest.fn();

    render(
      <MergeCandidatesOverlay
        ontologyId="ont1"
        ontologyName="Demo Ontology"
        onClose={onClose}
      />,
    );

    await screen.findByText("Customer");

    // No expansion yet -> Esc closes immediately.
    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(onClose).toHaveBeenCalledTimes(1);

    // Expand a row, then Esc once -> overlay stays open, panel
    // collapsed.
    onClose.mockClear();
    apiGet.mockResolvedValueOnce({
      pair_id: "pair_1",
      key1: "k1",
      key2: "k2",
      class_1: { label: "Customer", uri: "u1" },
      class_2: { label: "Client", uri: "u2" },
      field_scores: { label_jaro_winkler: 0.9 },
      combined_score: 0.9,
    });
    fireEvent.click(screen.getByTestId("merge-explain-btn-pair_1"));
    await screen.findByTestId("merge-explanation-pair_1");

    act(() => {
      fireEvent.keyDown(window, { key: "Escape" });
    });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByTestId("merge-explanation-pair_1")).toBeNull();
  });
});
