/**
 * Tests for ``CQCoverageTile`` (Stream 22 / CQ-PR6).
 *
 * Pins: loads open gaps on mount (cheap GET); "Check coverage" runs the POST with
 * gate + persist and renders coverage %, the release-gate badge, per-use-case bars,
 * and the gap list. ``api`` is mocked at the module boundary.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import CQCoverageTile from "../CQCoverageTile";

const apiGet = jest.fn();
const apiPost = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: {
    get: (...a: unknown[]) => apiGet(...a),
    post: (...a: unknown[]) => apiPost(...a),
  },
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

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
});

function renderTile() {
  return render(<CQCoverageTile ontologyId="o1" ontologyName="Alpha" />);
}

test("loads open gaps on mount via GET", async () => {
  apiGet.mockResolvedValue({
    gaps: [{ cq_text: "Who supplies X?", priority: "high" }],
    count: 1,
  });
  renderTile();

  await waitFor(() => expect(apiGet).toHaveBeenCalled());
  expect(apiGet.mock.calls[0][0]).toBe("/api/v1/ontology/o1/coverage/gaps");
  expect(await screen.findByText("Who supplies X?")).toBeInTheDocument();
  expect(screen.getByText("Open gaps (1)")).toBeInTheDocument();
  // no coverage run yet
  expect(screen.queryByTestId("cq-coverage-pct")).not.toBeInTheDocument();
});

test("Check coverage runs POST with gate+persist and renders report", async () => {
  apiGet.mockResolvedValue({ gaps: [], count: 0 });
  apiPost.mockResolvedValue({
    coverage_pct: 50,
    total: 4,
    answerable: 2,
    by_use_case: { Sourcing: { total: 2, answerable: 1 } },
    gaps: [{ text: "unanswered q", priority: "high", status: "unanswerable" }],
    release_gate: {
      passed: false,
      required_pct: 80,
      actual_pct: 50,
      considered: 2,
      answerable: 1,
    },
  });
  renderTile();
  await waitFor(() => expect(apiGet).toHaveBeenCalled());

  fireEvent.click(screen.getByTestId("cq-coverage-run"));

  expect(await screen.findByTestId("cq-coverage-pct")).toHaveTextContent("50%");
  // POST hit the gate + persist_gaps query params
  expect(apiPost.mock.calls[0][0]).toBe(
    "/api/v1/ontology/o1/coverage?gate=true&persist_gaps=true",
  );
  // release gate FAIL badge
  const gate = screen.getByTestId("cq-coverage-gate");
  expect(gate).toHaveTextContent("FAIL");
  expect(gate).toHaveTextContent("50%");
  // per-use-case bar
  expect(screen.getByText("Sourcing")).toBeInTheDocument();
  // gap surfaced from the report
  expect(screen.getByText("unanswered q")).toBeInTheDocument();
});

test("404 on gaps load is treated as empty (no error)", async () => {
  const { ApiError } = jest.requireMock("@/lib/api-client") as {
    ApiError: new (s: number, b: { code: string; message: string }) => Error;
  };
  apiGet.mockRejectedValue(new ApiError(404, { code: "NF", message: "no spec" }));
  renderTile();

  await waitFor(() => expect(apiGet).toHaveBeenCalled());
  expect(await screen.findByText(/0 open gaps/)).toBeInTheDocument();
});
