/**
 * Tests for ``AlignmentReviewOverlay`` (Stream 20 AL-PR5).
 *
 * Pins the wire path: load library -> select sources -> POST /sessions ->
 * list candidates -> accept -> POST /materialize; plus the adjudicate call.
 * ``api`` is mocked at the module boundary so we never touch the network.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import AlignmentReviewOverlay from "../AlignmentReviewOverlay";

const apiGet = jest.fn();
const apiPost = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
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

const CANDIDATE = {
  _key: "c1",
  source_a: { ontology_id: "ont1", entity_key: "A", label: "Account" },
  source_b: { ontology_id: "ont2", entity_key: "B", label: "Acct" },
  scores: { label: 1.0, combined: 0.95 },
  confidence: 0.95,
  type: "owl:equivalentClass",
  status: "candidate",
};

beforeEach(() => {
  apiGet.mockReset();
  apiPost.mockReset();
  apiGet.mockImplementation((path: string) => {
    if (path.startsWith("/api/v1/ontology/library")) {
      return Promise.resolve({
        data: [
          { _key: "ont1", name: "Alpha" }, // the open ontology -> excluded
          { _key: "ont2", name: "Beta" },
        ],
      });
    }
    if (path.includes("/candidates")) {
      return Promise.resolve({ session_id: "S1", candidates: [CANDIDATE], count: 1 });
    }
    return Promise.resolve({});
  });
  apiPost.mockImplementation((path: string) => {
    if (path === "/api/v1/alignment/sessions") {
      return Promise.resolve({ _key: "S1", candidate_count: 1 });
    }
    if (path.endsWith("/materialize")) {
      return Promise.resolve({ master_id: "M1", class_count: 1, equivalence_edges: 2 });
    }
    if (path.endsWith("/adjudicate")) {
      return Promise.resolve({ adjudicated: 1, llm_calls: 0 });
    }
    return Promise.resolve({});
  });
});

function renderOverlay() {
  return render(
    <AlignmentReviewOverlay ontologyId="ont1" ontologyName="Alpha" onClose={jest.fn()} />,
  );
}

test("lists other ontologies (excluding the open one) and gates Run", async () => {
  renderOverlay();
  // Beta is selectable; Alpha (the open ontology) is filtered out.
  expect(await screen.findByTestId("alignment-source-ont2")).toBeInTheDocument();
  expect(screen.queryByTestId("alignment-source-ont1")).not.toBeInTheDocument();
  expect(screen.getByTestId("alignment-run")).toBeDisabled();
});

test("running alignment creates a session and lists candidates", async () => {
  renderOverlay();
  fireEvent.click(await screen.findByTestId("alignment-source-ont2"));
  fireEvent.click(screen.getByTestId("alignment-run"));

  expect(await screen.findByTestId("alignment-candidate-c1")).toBeInTheDocument();
  const sessionCall = apiPost.mock.calls.find((c) => c[0] === "/api/v1/alignment/sessions");
  expect(sessionCall?.[1]).toEqual({ source_ontology_ids: ["ont1", "ont2"] });
});

test("accept then materialize writes the master", async () => {
  renderOverlay();
  fireEvent.click(await screen.findByTestId("alignment-source-ont2"));
  fireEvent.click(screen.getByTestId("alignment-run"));
  await screen.findByTestId("alignment-candidate-c1");

  // materialize is disabled until at least one correspondence is accepted
  expect(screen.getByTestId("alignment-materialize")).toBeDisabled();

  fireEvent.click(screen.getByTestId("alignment-accept-c1"));
  await waitFor(() =>
    expect(
      apiPost.mock.calls.some((c) => c[0] === "/api/v1/alignment/candidates/c1/accept"),
    ).toBe(true),
  );
  await waitFor(() => expect(screen.getByTestId("alignment-materialize")).not.toBeDisabled());

  fireEvent.click(screen.getByTestId("alignment-materialize"));
  expect(await screen.findByTestId("alignment-master")).toHaveTextContent("M1");
});

test("adjudicate calls the endpoint and refetches", async () => {
  renderOverlay();
  fireEvent.click(await screen.findByTestId("alignment-source-ont2"));
  fireEvent.click(screen.getByTestId("alignment-run"));
  await screen.findByTestId("alignment-candidate-c1");

  fireEvent.click(screen.getByTestId("alignment-adjudicate"));
  await waitFor(() =>
    expect(
      apiPost.mock.calls.some((c) => String(c[0]).endsWith("/sessions/S1/adjudicate")),
    ).toBe(true),
  );
});
