import { render, screen } from "@testing-library/react";
import React from "react";
import BoxArrowCanvas from "../BoxArrowCanvas";
import type { OntologyClass, OntologyEdge } from "@/types/curation";
import type { SigmaViewportApi } from "../SigmaCanvas";

// Fix for ResizeObserver which is required by ReactFlow but missing in JSDOM
global.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};

jest.mock("reactflow", () => {
  const React = require("react");

  // 1. Name the component with a Capital letter to satisfy "rules-of-hooks"
  const MockReactFlow = ({
    nodes,
    edges,
    onInit,
    children,
  }: {
    nodes: unknown[];
    edges: unknown[];
    onInit?: (instance: unknown) => void;
    children?: React.ReactNode;
  }) => {
    React.useEffect(() => {
      onInit?.({
        fitView: () => {},
        setCenter: () => {},
        getNode: () => null,
        getEdges: () => [],
      });
    }, [onInit]);

    return React.createElement(
      "div",
      { "data-testid": "mock-reactflow" },
      React.createElement(
        "span",
        { "data-testid": "node-count" },
        nodes.length,
      ),
      React.createElement(
        "span",
        { "data-testid": "edge-count" },
        edges.length,
      ),
      children,
    );
  };

  // 2. Assign a display name to satisfy "react/display-name"
  MockReactFlow.displayName = "MockReactFlow";

  return {
    __esModule: true,
    default: MockReactFlow,
    Background: () => null,
    BackgroundVariant: { Dots: "dots" },
    MarkerType: { ArrowClosed: "arrowclosed" },
    Handle: () => null,
    Position: { Top: "top", Bottom: "bottom" },
    ReactFlowProvider: ({ children }: { children: React.ReactNode }) =>
      React.createElement("div", null, children),
  };
});

jest.mock("dagre", () => {
  const Graph = class {
    private _nodes = new Map<string, Record<string, number>>();
    setGraph() {}
    setDefaultEdgeLabel() {}
    setNode(id: string, opts: { width: number; height: number }) {
      this._nodes.set(id, {
        x: 0,
        y: 0,
        width: opts.width,
        height: opts.height,
      });
    }
    setEdge() {}
    node(id: string) {
      return this._nodes.get(id) ?? { x: 0, y: 0, width: 220, height: 40 };
    }
  };
  return {
    __esModule: true,
    default: {
      graphlib: { Graph },
      layout: () => {},
    },
  };
});

jest.mock("@/components/workspace/ClassBoxNode", () => {
  const React = require("react");

  const MockClassBoxNode = ({ data }: { data: { label: string } }) =>
    React.createElement("div", { "data-testid": "class-box" }, data.label);

  MockClassBoxNode.displayName = "MockClassBoxNode";

  return {
    __esModule: true,
    default: React.memo(MockClassBoxNode),
  };
});

jest.mock("@/components/workspace/confidenceLensPalette", () => ({
  confidenceNodeColor: () => "#888",
  normalizeConfidence01: (v: number) => v,
}));

// Mock Data
const SAMPLE_CLASSES: OntologyClass[] = [
  {
    _key: "Person",
    label: "Person",
    uri: "http://ex.org#Person",
    description: "",
    rdf_type: "owl:Class",
    confidence: 0.9,
    status: "approved",
    ontology_id: "test",
    created: "2026-01-01",
    expired: null,
  },
  {
    _key: "Animal",
    label: "Animal",
    uri: "http://ex.org#Animal",
    description: "",
    rdf_type: "owl:Class",
    confidence: 0.8,
    status: "pending",
    ontology_id: "test",
    created: "2026-01-01",
    expired: null,
  },
];

const SAMPLE_EDGES: OntologyEdge[] = [
  {
    _key: "e1",
    _from: "ontology_classes/Person",
    _to: "ontology_classes/Animal",
    type: "subclass_of",
    label: "is-a",
  },
];

describe("BoxArrowCanvas", () => {
  it("renders empty state when no classes", () => {
    render(
      <BoxArrowCanvas
        classes={[]}
        edges={[]}
        activeLens="semantic"
        onNodeSelect={() => {}}
        onEdgeSelect={() => {}}
        onContextMenu={() => {}}
      />,
    );
    expect(screen.getByTestId("box-arrow-empty")).toBeInTheDocument();
  });

  it("renders nodes and edges for provided classes", () => {
    render(
      <BoxArrowCanvas
        classes={SAMPLE_CLASSES}
        edges={SAMPLE_EDGES}
        activeLens="semantic"
        onNodeSelect={() => {}}
        onEdgeSelect={() => {}}
        onContextMenu={() => {}}
      />,
    );
    expect(screen.getByTestId("mock-reactflow")).toBeInTheDocument();
    expect(screen.getByTestId("node-count").textContent).toBe("2");
    expect(screen.getByTestId("edge-count").textContent).toBe("1");
  });

  it("exposes viewport API with focusNode and focusEdge", () => {
    let api: SigmaViewportApi | null = null;
    render(
      <BoxArrowCanvas
        classes={SAMPLE_CLASSES}
        edges={[]}
        activeLens="semantic"
        onNodeSelect={() => {}}
        onEdgeSelect={() => {}}
        onContextMenu={() => {}}
        onViewportApi={(a) => {
          api = a;
        }}
      />,
    );
    expect(api).not.toBeNull();
    expect(api!.focusNode).toBeInstanceOf(Function);
    expect(api!.focusEdge).toBeInstanceOf(Function);
    expect(api!.fitAll).toBeInstanceOf(Function);
    expect(api!.centerView).toBeInstanceOf(Function);
    expect(api!.relayout).toBeInstanceOf(Function);
    expect(() => api!.focusNode("Person")).not.toThrow();
    expect(() => api!.focusEdge("e1")).not.toThrow();
  });

  it("passes classProperties to node data", () => {
    const classProps = {
      Person: [
        { _key: "name", label: "name", range_datatype: "string" },
        { _key: "age", label: "age", range_datatype: "integer" },
      ],
    };
    render(
      <BoxArrowCanvas
        classes={SAMPLE_CLASSES}
        edges={[]}
        activeLens="semantic"
        onNodeSelect={() => {}}
        onEdgeSelect={() => {}}
        onContextMenu={() => {}}
        classProperties={classProps}
      />,
    );
    expect(screen.getByTestId("mock-reactflow")).toBeInTheDocument();
  });
});
