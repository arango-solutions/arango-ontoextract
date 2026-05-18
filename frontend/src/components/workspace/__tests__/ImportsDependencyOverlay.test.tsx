/**
 * Tests for the H.7 ``ImportsDependencyOverlay``.
 *
 * Two layers:
 *
 *  1. Pure ``computeLayout`` exhaustive coverage -- layered placement,
 *     stable ordering, unreachable-node bucket. No React; no API.
 *  2. Component integration: fetch, render, re-root on double-click,
 *     navigate via "Open in workspace", error / loading paths.
 *
 * Mock fidelity (per mock-fidelity.mdc): the mocked ``ApiError`` mirrors
 * the real ``ApiError(status: number, body: ApiErrorBody)`` signature.
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";

jest.mock("@/lib/api-client", () => {
  class MockApiError extends Error {
    public readonly status: number;
    public readonly body: { code: string; message: string };
    constructor(status: number, body: { code: string; message: string }) {
      super(body.message);
      this.status = status;
      this.body = body;
    }
  }
  return {
    api: { get: jest.fn(), post: jest.fn() },
    ApiError: MockApiError,
  };
});

import ImportsDependencyOverlay, {
  computeLayout,
  type ImportsGraphNode,
  type ImportsGraphEdge,
} from "../ImportsDependencyOverlay";
import { api, ApiError } from "@/lib/api-client";

const mockedGet = api.get as jest.Mock;

function node(key: string, name?: string, extra: Partial<ImportsGraphNode> = {}): ImportsGraphNode {
  return { _key: key, name: name ?? key, ...extra };
}

function edge(from: string, to: string, key?: string): ImportsGraphEdge {
  return { edge_key: key ?? `${from}->${to}`, from_key: from, to_key: to };
}

describe("computeLayout", () => {
  it("returns empty layout for empty graph", () => {
    expect(computeLayout(null, "root")).toEqual({
      nodes: [],
      edges: [],
      width: 320,
      height: 120,
    });
    expect(
      computeLayout({ nodes: [], edges: [] }, "root"),
    ).toEqual(expect.objectContaining({ nodes: [], edges: [] }));
  });

  it("places the root at layer 0 and outbound chain to the right", () => {
    const layout = computeLayout(
      {
        nodes: [node("root"), node("a"), node("b")],
        edges: [edge("root", "a"), edge("a", "b")],
      },
      "root",
    );
    const byKey = Object.fromEntries(layout.nodes.map((n) => [n._key, n]));
    expect(byKey.root.layer).toBe(0);
    expect(byKey.a.layer).toBe(1);
    expect(byKey.b.layer).toBe(2);
    expect(byKey.a.x).toBeGreaterThan(byKey.root.x);
    expect(byKey.b.x).toBeGreaterThan(byKey.a.x);
  });

  it("places inbound chain to the left", () => {
    const layout = computeLayout(
      {
        nodes: [node("root"), node("p"), node("gp")],
        edges: [edge("p", "root"), edge("gp", "p")],
      },
      "root",
    );
    const byKey = Object.fromEntries(layout.nodes.map((n) => [n._key, n]));
    expect(byKey.root.layer).toBe(0);
    expect(byKey.p.layer).toBe(-1);
    expect(byKey.gp.layer).toBe(-2);
    expect(byKey.p.x).toBeLessThan(byKey.root.x);
    expect(byKey.gp.x).toBeLessThan(byKey.p.x);
  });

  it("places unreachable nodes in a far-right unrelated column", () => {
    const layout = computeLayout(
      {
        nodes: [node("root"), node("a"), node("orphan")],
        edges: [edge("root", "a")],
      },
      "root",
    );
    const orphan = layout.nodes.find((n) => n._key === "orphan")!;
    expect(orphan.layer).toBe(99);
  });

  it("dedupes when both outbound and inbound BFS would visit the same node first via outbound", () => {
    // Diamond: root → a → bottom AND root → bottom (direct). 'bottom' should
    // settle at the shortest outbound path (layer 1), not be re-numbered by
    // the inbound BFS pass.
    const layout = computeLayout(
      {
        nodes: [node("root"), node("a"), node("bottom")],
        edges: [edge("root", "a"), edge("a", "bottom"), edge("root", "bottom")],
      },
      "root",
    );
    const bottom = layout.nodes.find((n) => n._key === "bottom")!;
    expect(bottom.layer).toBe(1);
  });

  it("produces stable y ordering across two runs with identical input", () => {
    const data = {
      nodes: [node("root"), node("a"), node("b"), node("c")],
      edges: [edge("root", "a"), edge("root", "b"), edge("root", "c")],
    };
    const a = computeLayout(data, "root");
    const b = computeLayout(data, "root");
    expect(a.nodes.map((n) => [n._key, n.x, n.y])).toEqual(
      b.nodes.map((n) => [n._key, n.x, n.y]),
    );
  });
});

describe("ImportsDependencyOverlay (integration)", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockedGet.mockImplementation(() =>
      Promise.resolve({
        nodes: [node("ont-1", "Demo Ontology"), node("ont-parent", "Parent Vocab", { tier: "core" })],
        edges: [edge("ont-1", "ont-parent")],
        root: "ont-1",
        direction: "both",
        truncated: false,
      }),
    );
  });

  it("fetches the imports graph with root + depth params on mount", async () => {
    render(
      <ImportsDependencyOverlay
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={jest.fn()}
        onNavigate={jest.fn()}
      />,
    );
    await waitFor(() => {
      expect(mockedGet).toHaveBeenCalledWith(
        "/api/v1/ontology/imports-graph?root=ont-1&direction=both&max_depth=5",
      );
    });
  });

  it("renders one node per graph node returned by the API", async () => {
    render(
      <ImportsDependencyOverlay
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={jest.fn()}
        onNavigate={jest.fn()}
      />,
    );
    expect(await screen.findByTestId("dep-node-ont-1")).toBeInTheDocument();
    expect(screen.getByTestId("dep-node-ont-parent")).toBeInTheDocument();
  });

  it("shows the empty-state copy when the graph has zero or one node", async () => {
    mockedGet.mockResolvedValueOnce({
      nodes: [node("ont-1", "Lonely Ontology")],
      edges: [],
      root: "ont-1",
      direction: "both",
      truncated: false,
    });
    render(
      <ImportsDependencyOverlay
        ontologyId="ont-1"
        ontologyName="Lonely Ontology"
        onClose={jest.fn()}
        onNavigate={jest.fn()}
      />,
    );
    // The empty-state copy splits "has no <span>owl:imports</span> edges..."
    // across multiple DOM nodes, so we match on textContent of an ancestor
    // rather than relying on findByText's node-level matcher.
    await waitFor(() => {
      const overlay = screen.getByRole("dialog", { name: /Dependency Graph/ });
      expect(overlay.textContent).toMatch(
        /has no\s*owl:imports\s*edges and is not imported/,
      );
    });
  });

  it("calls onNavigate when the user selects a non-root node and clicks 'Open in workspace'", async () => {
    const onNavigate = jest.fn();
    const onClose = jest.fn();
    render(
      <ImportsDependencyOverlay
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={onClose}
        onNavigate={onNavigate}
      />,
    );

    const parent = await screen.findByTestId("dep-node-ont-parent");
    fireEvent.click(parent);

    const open = await screen.findByRole("button", { name: /Open in workspace/i });
    fireEvent.click(open);

    expect(onNavigate).toHaveBeenCalledWith("ont-parent", "Parent Vocab");
  });

  it("does NOT show 'Open in workspace' when the selected node is the initial root", async () => {
    render(
      <ImportsDependencyOverlay
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={jest.fn()}
        onNavigate={jest.fn()}
      />,
    );
    const rootEl = await screen.findByTestId("dep-node-ont-1");
    fireEvent.click(rootEl);
    expect(screen.queryByRole("button", { name: /Open in workspace/i })).toBeNull();
  });

  it("re-roots the graph when the user double-clicks a non-root node", async () => {
    render(
      <ImportsDependencyOverlay
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={jest.fn()}
        onNavigate={jest.fn()}
      />,
    );
    await screen.findByTestId("dep-node-ont-parent");

    // Set up the re-fetch response so the new root is ont-parent.
    mockedGet.mockResolvedValueOnce({
      nodes: [node("ont-parent", "Parent Vocab", { tier: "core" })],
      edges: [],
      root: "ont-parent",
      direction: "both",
      truncated: false,
    });

    fireEvent.doubleClick(screen.getByTestId("dep-node-ont-parent"));

    await waitFor(() => {
      expect(mockedGet).toHaveBeenCalledWith(
        "/api/v1/ontology/imports-graph?root=ont-parent&direction=both&max_depth=5",
      );
    });
  });

  it("changing the depth dropdown re-fetches with the new max_depth", async () => {
    render(
      <ImportsDependencyOverlay
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={jest.fn()}
        onNavigate={jest.fn()}
      />,
    );
    await screen.findByTestId("dep-node-ont-1");

    const depthSelect = screen.getByLabelText(/Max traversal depth/);
    fireEvent.change(depthSelect, { target: { value: "10" } });

    await waitFor(() => {
      expect(mockedGet).toHaveBeenCalledWith(
        "/api/v1/ontology/imports-graph?root=ont-1&direction=both&max_depth=10",
      );
    });
  });

  it("shows the error message when the imports-graph call fails", async () => {
    mockedGet.mockReset();
    mockedGet.mockRejectedValueOnce(
      new ApiError(500, { code: "BOOM", message: "AQL exploded" }),
    );
    render(
      <ImportsDependencyOverlay
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={jest.fn()}
        onNavigate={jest.fn()}
      />,
    );
    expect(await screen.findByText(/AQL exploded/)).toBeInTheDocument();
  });

  it("warns when the backend reports truncated traversal", async () => {
    mockedGet.mockResolvedValueOnce({
      nodes: [node("ont-1", "Demo"), node("ont-parent", "Parent")],
      edges: [edge("ont-1", "ont-parent")],
      root: "ont-1",
      direction: "both",
      truncated: true,
    });
    render(
      <ImportsDependencyOverlay
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={jest.fn()}
        onNavigate={jest.fn()}
      />,
    );
    expect(await screen.findByText(/truncated at depth/)).toBeInTheDocument();
  });

  it("closes on Escape and on × button", async () => {
    const onClose = jest.fn();
    render(
      <ImportsDependencyOverlay
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={onClose}
        onNavigate={jest.fn()}
      />,
    );
    await screen.findByTestId("dep-node-ont-1");
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByLabelText(/Close dependency graph/));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
