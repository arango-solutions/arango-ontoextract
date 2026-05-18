import { render, screen } from "@testing-library/react";
import { ReactFlowProvider } from "reactflow";

jest.mock("reactflow", () => {
  const React = require("react");
  const actual = jest.requireActual("reactflow");
  return {
    ...actual,
    Handle: ({ type, position }: { type: string; position: string }) =>
      React.createElement("div", { "data-testid": `handle-${type}`, "data-position": position }),
    Position: actual.Position,
    ReactFlowProvider: ({ children }: { children: React.ReactNode }) =>
      React.createElement("div", null, children),
  };
});

import ClassBoxNode, { type ClassBoxNodeData } from "../ClassBoxNode";

function renderNode(overrides: Partial<ClassBoxNodeData> = {}) {
  const defaultData: ClassBoxNodeData = {
    label: "Person",
    uri: "http://example.org#Person",
    status: "approved",
    confidence: 0.9,
    headerColor: "#22c55e",
    borderColor: "#475569",
    properties: [],
    isSelected: false,
    ...overrides,
  };

  const props = {
    id: "Person",
    data: defaultData,
    type: "classBox" as const,
    selected: false,
    isConnectable: false,
    xPos: 0,
    yPos: 0,
    zIndex: 0,
    dragging: false,
  };

  return render(
    <ReactFlowProvider>
      <ClassBoxNode {...props} />
    </ReactFlowProvider>,
  );
}

describe("ClassBoxNode", () => {
  it("renders the class label", () => {
    renderNode({ label: "Vehicle" });
    expect(screen.getByText("Vehicle")).toBeInTheDocument();
  });

  it("shows 'No properties' when properties list is empty", () => {
    renderNode({ properties: [] });
    expect(screen.getByText("No properties")).toBeInTheDocument();
  });

  it("renders properties with their labels", () => {
    renderNode({
      properties: [
        { _key: "name", label: "name", range_datatype: "string" },
        { _key: "age", label: "age", range_datatype: "integer" },
      ],
    });
    expect(screen.getByText("name")).toBeInTheDocument();
    expect(screen.getByText("age")).toBeInTheDocument();
    expect(screen.getByText("string")).toBeInTheDocument();
    expect(screen.getByText("integer")).toBeInTheDocument();
  });

  it("shows overflow indicator when properties exceed max", () => {
    const manyProps = Array.from({ length: 15 }, (_, i) => ({
      _key: `prop_${i}`,
      label: `property_${i}`,
      range_datatype: "string",
    }));
    renderNode({ properties: manyProps });
    expect(screen.getByText("+3 more")).toBeInTheDocument();
  });

  it("applies selected styling when isSelected is true", () => {
    const { container } = renderNode({ isSelected: true });
    const box = container.firstChild?.firstChild as HTMLElement;
    expect(box.className).toContain("ring-2");
    expect(box.className).toContain("ring-indigo-400");
  });

  it("shows status dot for approved classes", () => {
    renderNode({ status: "approved" });
    const dot = screen.getByTitle("approved");
    expect(dot).toBeInTheDocument();
    expect(dot.className).toContain("bg-green-500");
  });

  it("renders source and target handles", () => {
    renderNode();
    expect(screen.getByTestId("handle-target")).toBeInTheDocument();
    expect(screen.getByTestId("handle-source")).toBeInTheDocument();
  });

  describe("imported classes (Stream 1 H.15)", () => {
    it("renders a solid border + no imported pill when isImported is omitted", () => {
      const { container } = renderNode({ label: "Owned" });
      const box = container.firstChild?.firstChild as HTMLElement;

      expect(box.style.borderStyle).toBe("solid");
      expect(box.dataset.imported).toBeUndefined();
      expect(box.className).not.toContain("opacity-75");
      // The pill is the only element with the "imported" aria-label;
      // when absent neither the wrapper nor any child should reference it.
      expect(screen.queryByLabelText(/imported from/i)).not.toBeInTheDocument();
      expect(box.title).toBe("");
    });

    it("renders a dashed border + dim opacity + imported pill when isImported is true", () => {
      const { container } = renderNode({
        label: "Vehicle",
        isImported: true,
        sourceOntologyName: "FOAF",
      });
      const box = container.firstChild?.firstChild as HTMLElement;

      expect(box.style.borderStyle).toBe("dashed");
      expect(box.dataset.imported).toBe("true");
      expect(box.className).toContain("opacity-75");
      // Header pill announces the imported state. Both the box wrapper and
      // the pill carry the same tooltip text so hover discovery works at
      // either target. The pill is the *only* element labelled "Imported
      // from …" — we target it by aria-label to avoid collisions with
      // class names that happen to contain the word "imported".
      const pill = screen.getByLabelText("Imported from FOAF");
      expect(pill).toBeInTheDocument();
      expect(pill.textContent?.toLowerCase()).toBe("imported");
      expect(pill.getAttribute("title")).toBe("Imported from FOAF");
      expect(box.title).toBe("Imported from FOAF");
    });

    it("falls back to a generic source label when sourceOntologyName is missing", () => {
      const { container } = renderNode({
        label: "Vehicle",
        isImported: true,
      });
      const box = container.firstChild?.firstChild as HTMLElement;
      expect(box.title).toBe("Imported from another ontology");
    });
  });
});
