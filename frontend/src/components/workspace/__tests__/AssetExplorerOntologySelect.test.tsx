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
 * Regression test for the "Loading <wrong ontology name>" race.
 *
 * The asset explorer used to call ``onSelectOntology(ont._key)`` with just
 * the key, leaving the workspace page to derive the human-readable name
 * via an async ``/library`` fetch. Between the click and the fetch
 * resolving, the canvas's loading spinner displayed the PREVIOUSLY
 * selected ontology's name -- e.g. clicking "WTW Ontology" briefly
 * showed "Loading Best Practices in Healthcare Survey Results Slides...".
 *
 * The fix is to pass the explorer's already-known display name as a
 * second argument so the workspace can set ``ontologyName`` synchronously
 * before the canvas re-renders. This test pins that contract.
 */

describe("AssetExplorer onSelectOntology displayName pass-through", () => {
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
            {
              _key: "ont_bp",
              name: "Best Practices in Healthcare Survey Results Slides",
              label: null,
              tier: "local",
              status: "active",
            },
          ],
          cursor: null,
          has_more: false,
          total_count: 2,
        });
      }
      // Catch-all: empty list for /api/v1/documents and any other route
      // the explorer might fire during mount.
      return Promise.resolve({ data: [] });
    });
  });

  it("passes (ontologyId, displayName) to onSelectOntology when an ontology row is clicked", async () => {
    const onSelectOntology = jest.fn();

    render(
      <AssetExplorer
        onSelectOntology={onSelectOntology}
        onSelectDocument={() => {}}
        onSelectRun={() => {}}
        selectedOntologyId={null}
        selectedRunId={null}
        onContextMenu={() => {}}
      />,
    );

    const wtwRow = await screen.findByText("WTW Ontology");
    fireEvent.click(wtwRow);

    await waitFor(() => {
      expect(onSelectOntology).toHaveBeenCalled();
    });

    // The whole point of this test: BOTH arguments must be present.
    // (key, displayName) -- displayName is what the loading spinner reads.
    expect(onSelectOntology).toHaveBeenCalledWith("ont_wtw", "WTW Ontology");
  });

  it("passes the long display name verbatim (the original bug case)", async () => {
    const onSelectOntology = jest.fn();

    render(
      <AssetExplorer
        onSelectOntology={onSelectOntology}
        onSelectDocument={() => {}}
        onSelectRun={() => {}}
        selectedOntologyId={null}
        selectedRunId={null}
        onContextMenu={() => {}}
      />,
    );

    // The explorer truncates the visible label, so .findByText needs a
    // partial matcher; the second arg to onSelectOntology must still be
    // the FULL display name (not the truncated UI version).
    const bpRow = await screen.findByText(
      /Best Practices in Healthcare/i,
    );
    fireEvent.click(bpRow);

    await waitFor(() => {
      expect(onSelectOntology).toHaveBeenCalled();
    });

    expect(onSelectOntology).toHaveBeenCalledWith(
      "ont_bp",
      "Best Practices in Healthcare Survey Results Slides",
    );
  });

  it("falls back to label, then _key, when name is absent", async () => {
    // Mirrors the ``ontologyDisplayName`` fallback chain in
    // AssetExplorer.tsx -- prove that switching the source field does
    // not break the second-arg contract.
    get.mockReset();
    get.mockImplementation((path: string) => {
      if (path === "/api/v1/ontology/library") {
        return Promise.resolve({
          data: [
            { _key: "ont_a", name: null, label: "From-Label", status: "active" },
            { _key: "ont_b", name: null, label: null, status: "active" },
          ],
          cursor: null,
          has_more: false,
          total_count: 2,
        });
      }
      return Promise.resolve({ data: [] });
    });

    const onSelectOntology = jest.fn();
    render(
      <AssetExplorer
        onSelectOntology={onSelectOntology}
        onSelectDocument={() => {}}
        onSelectRun={() => {}}
        selectedOntologyId={null}
        selectedRunId={null}
        onContextMenu={() => {}}
      />,
    );

    fireEvent.click(await screen.findByText("From-Label"));
    await waitFor(() => expect(onSelectOntology).toHaveBeenCalled());
    expect(onSelectOntology).toHaveBeenLastCalledWith("ont_a", "From-Label");

    fireEvent.click(await screen.findByText("ont_b"));
    await waitFor(() => expect(onSelectOntology).toHaveBeenCalledTimes(2));
    expect(onSelectOntology).toHaveBeenLastCalledWith("ont_b", "ont_b");
  });
});
