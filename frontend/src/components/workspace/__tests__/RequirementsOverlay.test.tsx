/**
 * Tests for ``RequirementsOverlay`` (Stream 22 CQ-PR2 authoring + CQ-PR6 coverage).
 *
 * Pins: load spec (incl. 404 -> empty), edit + Save (PUT), Run coverage (POST)
 * and render the report + gaps. ``api`` is mocked at the module boundary.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ApiError } from "@/lib/api-client";
import RequirementsOverlay from "../RequirementsOverlay";

const apiGet = jest.fn();
const apiPut = jest.fn();
const apiPost = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: {
    get: (...a: unknown[]) => apiGet(...a),
    put: (...a: unknown[]) => apiPut(...a),
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
  apiPut.mockReset();
  apiPost.mockReset();
  apiPut.mockResolvedValue({});
});

function renderOverlay() {
  return render(
    <RequirementsOverlay ontologyId="o1" ontologyName="Alpha" onClose={jest.fn()} />,
  );
}

test("404 on load starts with an empty editable spec", async () => {
  apiGet.mockRejectedValue(new ApiError(404, { code: "NF", message: "no spec" }));
  renderOverlay();
  expect(await screen.findByTestId("requirements-editor")).toBeInTheDocument();
  // no error surfaced for a 404 (just an empty spec)
  expect(screen.queryByTestId("requirements-error")).not.toBeInTheDocument();
});

test("loads an existing spec", async () => {
  apiGet.mockResolvedValue({
    purpose: "Fraud",
    use_cases: [{ name: "Trace", priority: "high", competency_questions: [{ text: "Q1" }] }],
  });
  renderOverlay();
  expect(await screen.findByTestId("use-case-0")).toBeInTheDocument();
  expect(screen.getByTestId("requirements-purpose")).toHaveValue("Fraud");
  expect(screen.getByTestId("cq-text-0-0")).toHaveValue("Q1");
});

test("add a use case + CQ, then Save PUTs the spec", async () => {
  apiGet.mockRejectedValue(new ApiError(404, { code: "NF", message: "no spec" }));
  renderOverlay();
  await screen.findByTestId("requirements-editor");

  fireEvent.click(screen.getByTestId("use-case-add"));
  fireEvent.change(screen.getByTestId("use-case-name-0"), { target: { value: "Trace mules" } });
  fireEvent.click(screen.getByTestId("cq-add-0"));
  fireEvent.change(screen.getByTestId("cq-text-0-0"), {
    target: { value: "Which accounts are mule accounts?" },
  });

  fireEvent.click(screen.getByTestId("requirements-save"));
  await waitFor(() => expect(apiPut).toHaveBeenCalled());
  const [path, body] = apiPut.mock.calls[0];
  expect(path).toBe("/api/v1/ontology/o1/requirements");
  expect(body.use_cases[0].name).toBe("Trace mules");
  expect(body.use_cases[0].competency_questions[0].text).toBe(
    "Which accounts are mule accounts?",
  );
});

test("Run coverage renders the report + gaps", async () => {
  apiGet.mockResolvedValue({ purpose: "", use_cases: [] });
  apiPost.mockResolvedValue({
    total: 3,
    answerable: 1,
    unanswerable: 1,
    unformalized: 1,
    error: 0,
    coverage_pct: 33.3,
    by_use_case: { UC: { total: 3, answerable: 1 } },
    gaps: [{ text: "Q2", use_case: "UC", status: "unanswerable" }],
  });
  renderOverlay();
  await screen.findByTestId("requirements-editor");

  fireEvent.click(screen.getByTestId("requirements-run-coverage"));
  const report = await screen.findByTestId("coverage-report");
  expect(report).toHaveTextContent("33.3%");
  expect(screen.getByTestId("coverage-gaps")).toHaveTextContent("Q2");
  expect(apiPost.mock.calls[0][0]).toBe("/api/v1/ontology/o1/coverage");
});
