/**
 * @jest-environment jsdom
 *
 * Stream 1 H.16: ontology rows in the asset explorer must be draggable
 * so the user can drop one onto the workspace canvas to create an
 * ``owl:imports`` edge. The contract this test pins:
 *
 *  * Every ontology row carries ``draggable=true``.
 *  * ``dragstart`` calls ``dataTransfer.setData`` with the canonical
 *    MIME (``application/x-aoe-ontology``) and a JSON-encoded payload
 *    that includes both ``ontologyId`` and ``ontologyName``.
 *  * The payload uses the explorer's *display* name (the same string
 *    the user sees on the row), so the drop-side toast can quote what
 *    they dragged.
 *  * ``dataTransfer.effectAllowed`` is set to ``copy`` so the OS-level
 *    cursor advertises the right action (we are not removing the row).
 */

import { fireEvent, render, screen } from "@testing-library/react";

import AssetExplorer from "../AssetExplorer";
import { clearOntologyCache } from "@/lib/ontologyDataCache";
import {
  IMPORT_DRAG_MIME,
  readImportDragPayload,
} from "@/lib/importDragCheck";

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

/** Hand-rolled minimal DataTransfer so we do not depend on jsdom's
 *  drag-and-drop coverage (which varies by version). The same shape is
 *  used by ``importDragCheck.test.ts``. */
function makeTransfer(): DataTransfer {
  const store = new Map<string, string>();
  return {
    setData: (mime: string, value: string) => {
      store.set(mime, value);
    },
    getData: (mime: string) => store.get(mime) ?? "",
    effectAllowed: "none",
    types: [] as readonly string[],
  } as unknown as DataTransfer;
}

describe("AssetExplorer ontology row drag (H.16)", () => {
  beforeEach(() => {
    get.mockReset();
    clearOntologyCache();
    get.mockImplementation((path: string) => {
      if (path === "/api/v1/ontology/library") {
        return Promise.resolve({
          data: [
            {
              _key: "ont_wtw",
              name: "WTW Ontology",
              label: null,
              tier: "domain",
              status: "active",
            },
          ],
          cursor: null,
          has_more: false,
          total_count: 1,
        });
      }
      return Promise.resolve({ data: [] });
    });
  });

  it("renders ontology rows with draggable=true", async () => {
    render(
      <AssetExplorer
        onSelectOntology={() => {}}
        onSelectDocument={() => {}}
        onSelectRun={() => {}}
        selectedOntologyId={null}
        selectedRunId={null}
        onContextMenu={() => {}}
      />,
    );

    const row = (await screen.findByText("WTW Ontology")).closest("button")!;
    expect(row).not.toBeNull();
    // ``draggable`` is the HTML attribute set on the button wrapper —
    // a missing or "false" value here breaks the whole drop flow, so
    // it's worth pinning explicitly.
    expect(row.getAttribute("draggable")).toBe("true");
  });

  it("dragStart writes the canonical payload (id + name) to dataTransfer", async () => {
    render(
      <AssetExplorer
        onSelectOntology={() => {}}
        onSelectDocument={() => {}}
        onSelectRun={() => {}}
        selectedOntologyId={null}
        selectedRunId={null}
        onContextMenu={() => {}}
      />,
    );

    const row = (await screen.findByText("WTW Ontology")).closest("button")!;
    const dataTransfer = makeTransfer();
    fireEvent.dragStart(row, { dataTransfer });

    // Round-trip via the shared decoder so the test exercises the SAME
    // shape the drop handler in page.tsx reads. If a future refactor
    // changes the wire shape on one side and not the other, this
    // assertion catches it.
    const payload = readImportDragPayload(dataTransfer);
    expect(payload).toEqual({
      ontologyId: "ont_wtw",
      ontologyName: "WTW Ontology",
    });
    expect(dataTransfer.effectAllowed).toBe("copy");
    // The raw MIME content is JSON — sanity check for direct readers.
    expect(dataTransfer.getData(IMPORT_DRAG_MIME)).toContain("ont_wtw");
  });
});
