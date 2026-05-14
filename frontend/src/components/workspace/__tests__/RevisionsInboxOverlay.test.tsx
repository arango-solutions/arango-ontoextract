/**
 * Tests for ``RevisionsInboxOverlay`` (IBR.14 + IBR.15).
 *
 * Smoke-tests the wire path: fetches inbox, renders rows, accepts /
 * rejects via the inline buttons, dispatches the modify payload from
 * the detail panel, and exercises the "no pending revisions" empty
 * state. ``api.get`` and ``api.post`` are mocked at the module
 * boundary so we never touch the network.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import RevisionsInboxOverlay, {
  type RevisionRow,
} from "../RevisionsInboxOverlay";

const apiGet = jest.fn();
const apiPost = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: {
    get: (...args: unknown[]) => apiGet(...args),
    post: (...args: unknown[]) => apiPost(...args),
  },
  ApiError: class ApiError extends Error {
    public readonly status = 500;
    public readonly body = { code: "X", message: "stub" };
  },
}));

function makeRow(overrides: Partial<RevisionRow> = {}): RevisionRow {
  return {
    _key: "rev-1",
    ontology_id: "ont-1",
    verdict: "REFINED",
    action: "REVISE",
    status: "pending",
    agent_type: "belief_revision_llm",
    agent_version: "v1",
    triggering_doc_id: "doc-1",
    existing_entity_id: "ontology_classes/ont-1__VirtualCare",
    existing_version: "v1",
    new_version: null,
    evidence_quotes: ["quote A", "quote B"],
    reasoning: "VirtualCare description should mention telehealth.",
    confidence_before: 0.6,
    confidence_after: 0.8,
    created: Math.floor(Date.now() / 1000) - 60,
    decision_log: [],
    ...overrides,
  };
}

describe("RevisionsInboxOverlay", () => {
  beforeEach(() => {
    apiGet.mockReset();
    apiPost.mockReset();
  });

  it("fetches the inbox on mount and renders one row per pending revision", async () => {
    apiGet.mockResolvedValue({
      data: [
        makeRow(),
        makeRow({
          _key: "rev-2",
          action: "GAP_FILL",
          verdict: "GAP-FILLING",
          existing_entity_id: "ontology_classes/ont-1__Telehealth",
        }),
      ],
      ontology_id: "ont-1",
      count: 2,
    });

    render(
      <RevisionsInboxOverlay
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
      />,
    );

    expect(apiGet).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/revisions/inbox?ontology_id=ont-1"),
    );

    await screen.findByText(/2 pending revisions/);
    expect(screen.getAllByText(/REVISE|GAP FILL/i).length).toBeGreaterThan(0);
    expect(
      screen.getByText("ontology_classes/ont-1__VirtualCare"),
    ).toBeInTheDocument();
  });

  it("renders the empty state when no pending revisions exist", async () => {
    apiGet.mockResolvedValue({ data: [], ontology_id: "ont-1", count: 0 });

    render(
      <RevisionsInboxOverlay
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
      />,
    );

    await screen.findByText(/No pending revisions/);
    expect(
      screen.getByText(/Right-click on canvas for more options/i),
    ).toBeInTheDocument();
  });

  it("Accept button POSTs to /accept with the curator id and removes the row optimistically", async () => {
    apiGet.mockResolvedValueOnce({
      data: [makeRow()],
      ontology_id: "ont-1",
      count: 1,
    });
    apiPost.mockResolvedValue({
      revision_key: "rev-1",
      decision: "accept",
      status: "accepted",
      already_decided: false,
      revision: {},
    });
    apiGet.mockResolvedValueOnce({ data: [], ontology_id: "ont-1", count: 0 });

    const onChanged = jest.fn();
    render(
      <RevisionsInboxOverlay
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        curatorId="alice"
        onClose={() => {}}
        onChanged={onChanged}
      />,
    );

    const accept = await screen.findByRole("button", { name: /Accept/ });
    fireEvent.click(accept);

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith(
        "/api/v1/revisions/rev-1/accept",
        expect.objectContaining({ decided_by: "alice" }),
      ),
    );

    // Row should disappear (optimistic) and onChanged fires so the
    // canvas refresh cycle is triggered.
    await waitFor(() =>
      expect(screen.queryByRole("button", { name: /Accept/ })).toBeNull(),
    );
    expect(onChanged).toHaveBeenCalled();
  });

  it("Reject button POSTs to /reject", async () => {
    apiGet.mockResolvedValueOnce({
      data: [makeRow()],
      ontology_id: "ont-1",
      count: 1,
    });
    apiPost.mockResolvedValue({
      revision_key: "rev-1",
      decision: "reject",
      status: "rejected",
      already_decided: false,
      revision: {},
    });
    apiGet.mockResolvedValueOnce({ data: [], ontology_id: "ont-1", count: 0 });

    render(
      <RevisionsInboxOverlay
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /Reject/ }));

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith(
        "/api/v1/revisions/rev-1/reject",
        expect.objectContaining({ decided_by: "curator" }),
      ),
    );
  });

  it("Clicking a row opens the detail panel; Modify submits an override_action payload", async () => {
    apiGet.mockResolvedValueOnce({
      data: [makeRow()],
      ontology_id: "ont-1",
      count: 1,
    });
    apiPost.mockResolvedValue({
      revision_key: "rev-1",
      decision: "modify",
      status: "modified",
      already_decided: false,
      revision: {},
    });
    apiGet.mockResolvedValueOnce({ data: [], ontology_id: "ont-1", count: 0 });

    render(
      <RevisionsInboxOverlay
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
      />,
    );

    fireEvent.click(
      await screen.findByText("ontology_classes/ont-1__VirtualCare"),
    );

    await screen.findByRole("heading", { name: /Details/ });

    fireEvent.click(screen.getByRole("button", { name: /Modify…/ }));

    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "RETRACT" } });

    const note = screen.getByRole("textbox");
    fireEvent.change(note, { target: { value: "Looks like noise from page 4" } });

    fireEvent.click(
      screen.getByRole("button", { name: /Apply modification/ }),
    );

    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith(
        "/api/v1/revisions/rev-1/modify",
        expect.objectContaining({
          override_action: "RETRACT",
          note: "Looks like noise from page 4",
        }),
      ),
    );
  });

  it("Esc key closes the overlay when no row is selected", async () => {
    apiGet.mockResolvedValue({ data: [], ontology_id: "ont-1", count: 0 });
    const onClose = jest.fn();

    render(
      <RevisionsInboxOverlay
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={onClose}
      />,
    );

    await screen.findByText(/No pending revisions/);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("renders an error banner when the inbox fetch fails", async () => {
    apiGet.mockRejectedValue(new Error("network down"));

    render(
      <RevisionsInboxOverlay
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
      />,
    );

    await screen.findByText(/network down/);
  });
});
