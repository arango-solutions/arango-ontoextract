import { render, screen, waitFor } from "@testing-library/react";

import FloatingDetailPanel from "../FloatingDetailPanel";

const apiGet = jest.fn();

// Class declared inside the factory to satisfy jest.mock's hoisting --
// the factory runs at module load time, before any top-level declarations
// in the test file are evaluated.
jest.mock("@/lib/api-client", () => {
  class ApiError extends Error {
    public readonly status: number;
    public readonly body: { code: string; message: string };
    constructor(status: number, body: { code: string; message: string }) {
      super(body.message);
      this.status = status;
      this.body = body;
    }
  }
  return {
    api: { get: (...args: unknown[]) => apiGet(...args) },
    ApiError,
  };
});

// Re-import the mocked ApiError so test code can construct rejection values
// of the same class the SUT does instanceof checks against.
const { ApiError: MockApiError } = require("@/lib/api-client") as {
  ApiError: new (
    status: number,
    body: { code: string; message: string },
  ) => Error & { status: number; body: { code: string; message: string } };
};

beforeEach(() => {
  apiGet.mockReset();
});

/**
 * The whole point of these tests is to pin the contract that
 * FloatingDetailPanel hits the **single-item** endpoints
 * (``/edges/{key}``, ``/properties/{key}``) and never the list
 * endpoints. The previous code path fetched the entire list and
 * called ``.find()`` on the result -- on the WTW Ontology that meant
 * pulling 555 KB of edge data over the WAN per click. If anyone
 * regresses to the list-fetch shape, these tests fail.
 */

describe("FloatingDetailPanel", () => {
  it("class entity hits GET /classes/{key} (one row, not a list)", async () => {
    apiGet.mockResolvedValue({
      _key: "Foo",
      label: "Foo",
      uri: "ex:Foo",
      attributes: [],
      relationships: [],
    });

    render(
      <FloatingDetailPanel
        entityType="class"
        entityKey="Foo"
        ontologyId="ont1"
        onClose={() => {}}
      />,
    );

    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(apiGet).toHaveBeenCalledWith("/api/v1/ontology/ont1/classes/Foo");
    // Verify we did NOT use the list endpoint (which has no key suffix).
    const calls = apiGet.mock.calls.map((c) => c[0] as string);
    expect(calls.some((u) => u === "/api/v1/ontology/ont1/classes")).toBe(false);
  });

  it("edge entity hits GET /edges/{key} (the new single-item endpoint)", async () => {
    apiGet.mockResolvedValue({
      _key: "e123",
      _from: "ontology_classes/A",
      _to: "ontology_classes/B",
      label: "relates",
      edge_type: "rdfs_range_class",
      confidence: 0.85,
    });

    render(
      <FloatingDetailPanel
        entityType="edge"
        entityKey="e123"
        ontologyId="ont1"
        onClose={() => {}}
      />,
    );

    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(apiGet).toHaveBeenCalledWith("/api/v1/ontology/ont1/edges/e123");
    // The N+1 anti-pattern was: fetch the whole list then .find(). Pin that
    // we never call the list URL again.
    const calls = apiGet.mock.calls.map((c) => c[0] as string);
    expect(calls.some((u) => u === "/api/v1/ontology/ont1/edges")).toBe(false);
  });

  it("property entity hits GET /properties/{key} (the new single-item endpoint)", async () => {
    apiGet.mockResolvedValue({
      _key: "p999",
      label: "name",
      uri: "ex:name",
    });

    render(
      <FloatingDetailPanel
        entityType="property"
        entityKey="p999"
        ontologyId="ont1"
        onClose={() => {}}
      />,
    );

    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(apiGet).toHaveBeenCalledWith("/api/v1/ontology/ont1/properties/p999");
    const calls = apiGet.mock.calls.map((c) => c[0] as string);
    expect(calls.some((u) => u === "/api/v1/ontology/ont1/properties")).toBe(false);
  });

  it("404 from a single-item endpoint surfaces a 'not found' message", async () => {
    apiGet.mockRejectedValue(
      new MockApiError(404, { code: "ENTITY_NOT_FOUND", message: "Edge not found" }),
    );

    render(
      <FloatingDetailPanel
        entityType="edge"
        entityKey="missing"
        ontologyId="ont1"
        onClose={() => {}}
      />,
    );

    // The error UI text says "{type} \"{key}\" not found"; assert on the
    // distinctive substring rather than the precise wrapper markup.
    await waitFor(() => {
      expect(screen.getByText(/edge .* not found/i)).toBeInTheDocument();
    });
  });

  it("non-404 errors surface the API error message, not the not-found path", async () => {
    apiGet.mockRejectedValue(
      new MockApiError(500, { code: "INTERNAL_ERROR", message: "DB down" }),
    );

    render(
      <FloatingDetailPanel
        entityType="edge"
        entityKey="any"
        ontologyId="ont1"
        onClose={() => {}}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("DB down")).toBeInTheDocument();
    });
  });

  it("does not fire the request again when only re-rendered with same props", async () => {
    apiGet.mockResolvedValue({ _key: "Foo", label: "Foo" });
    const { rerender } = render(
      <FloatingDetailPanel
        entityType="class"
        entityKey="Foo"
        ontologyId="ont1"
        onClose={() => {}}
      />,
    );
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(1));
    rerender(
      <FloatingDetailPanel
        entityType="class"
        entityKey="Foo"
        ontologyId="ont1"
        onClose={() => {}}
      />,
    );
    // Effect deps are [entityType, entityKey, ontologyId] -- same values
    // mean no refetch.
    expect(apiGet).toHaveBeenCalledTimes(1);
  });

  it("refetches when entityKey changes (panel reused for a different selection)", async () => {
    apiGet.mockResolvedValue({ _key: "Foo", label: "Foo" });
    const { rerender } = render(
      <FloatingDetailPanel
        entityType="class"
        entityKey="Foo"
        ontologyId="ont1"
        onClose={() => {}}
      />,
    );
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(1));

    apiGet.mockResolvedValue({ _key: "Bar", label: "Bar" });
    rerender(
      <FloatingDetailPanel
        entityType="class"
        entityKey="Bar"
        ontologyId="ont1"
        onClose={() => {}}
      />,
    );
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(2));
    expect(apiGet).toHaveBeenLastCalledWith("/api/v1/ontology/ont1/classes/Bar");
  });
});
