import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import AssetExplorer from "../AssetExplorer";
import { clearOntologyCache } from "@/lib/ontologyDataCache";

const get = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: {
    get: (...args: unknown[]) => get(...args),
  },
  ApiError: class ApiError extends Error {
    body: { message: string };
    status: number;
    constructor(status: number, body: { message: string }) {
      super(body.message);
      this.status = status;
      this.body = body;
    }
  },
}));

/**
 * W.7 (Stream 10) -- pins the `[data-sidebar-row]` contract that the
 * workspace page's keydown handler uses to discover the asset
 * explorer's navigable rows. If a future refactor moves to a virtual
 * list or renames the attribute without updating the page's
 * `computeNextSidebarRow` query selector, this test fails.
 *
 * The value format is `<kind>:<ontologyId>:<entityKey>`; the
 * `<kind>` prefix lets future row kinds (properties, documents) opt
 * in by tagging themselves with their own discriminator.
 */
describe("AssetExplorer [data-sidebar-row] attribute", () => {
  beforeEach(() => {
    get.mockReset();
    clearOntologyCache();
    get.mockImplementation((path: string) => {
      if (path === "/api/v1/ontology/library") {
        return Promise.resolve({
          data: [
            {
              _key: "ont1",
              name: "Test Ontology",
              tier: "domain",
              status: "active",
            },
          ],
          cursor: null,
          has_more: false,
          total_count: 1,
        });
      }
      if (path.startsWith("/api/v1/ontology/ont1/classes")) {
        return Promise.resolve({
          data: [
            {
              _key: "cls_a",
              label: "Class A",
              uri: "http://example/cls_a",
              status: "approved",
            },
            {
              _key: "cls_b",
              label: "Class B",
              uri: "http://example/cls_b",
              status: "pending",
            },
          ],
        });
      }
      if (path.startsWith("/api/v1/ontology/ont1/edges")) {
        return Promise.resolve({
          data: [
            {
              _key: "edge_x",
              label: "uses",
              edge_type: "object_property",
              source_class_key: "cls_a",
              target_class_key: "cls_b",
            },
          ],
        });
      }
      return Promise.resolve({ data: [] });
    });
  });

  it("tags class rows with data-sidebar-row=\"class:<ontologyId>:<classKey>\"", async () => {
    render(
      <AssetExplorer
        onSelectOntology={() => {}}
        onSelectDocument={() => {}}
        onSelectRun={() => {}}
        selectedOntologyId="ont1"
        selectedRunId={null}
        onContextMenu={() => {}}
      />,
    );

    // Expand the ontology to surface the Classes / Relations sections.
    const ontologyRow = await screen.findByText("Test Ontology");
    fireEvent.click(ontologyRow);

    // Expand the Classes accordion.
    const classesHeader = await screen.findByText(/Classes/);
    fireEvent.click(classesHeader);

    await waitFor(() => {
      const rows = document.querySelectorAll(
        "[data-sidebar-row^=\"class:ont1:\"]",
      );
      expect(rows.length).toBeGreaterThan(0);
    });

    const classRows = document.querySelectorAll(
      "[data-sidebar-row^=\"class:ont1:\"]",
    );
    const values = Array.from(classRows).map((el) =>
      el.getAttribute("data-sidebar-row"),
    );
    expect(values).toContain("class:ont1:cls_a");
    expect(values).toContain("class:ont1:cls_b");
  });

  it("tags edge rows with data-sidebar-row=\"edge:<ontologyId>:<edgeKey>\"", async () => {
    render(
      <AssetExplorer
        onSelectOntology={() => {}}
        onSelectDocument={() => {}}
        onSelectRun={() => {}}
        selectedOntologyId="ont1"
        selectedRunId={null}
        onContextMenu={() => {}}
      />,
    );

    const ontologyRow = await screen.findByText("Test Ontology");
    fireEvent.click(ontologyRow);

    const relationsHeader = await screen.findByText(/Relations/);
    fireEvent.click(relationsHeader);

    await waitFor(() => {
      const rows = document.querySelectorAll(
        "[data-sidebar-row^=\"edge:ont1:\"]",
      );
      expect(rows.length).toBe(1);
    });

    const edgeRow = document.querySelector(
      "[data-sidebar-row^=\"edge:ont1:\"]",
    );
    expect(edgeRow?.getAttribute("data-sidebar-row")).toBe(
      "edge:ont1:edge_x",
    );
  });
});
