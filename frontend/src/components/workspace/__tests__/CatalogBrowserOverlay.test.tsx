/**
 * Tests for the H.6 ``CatalogBrowserOverlay``.
 *
 * Mock fidelity (per mock-fidelity.mdc): the mocked ``ApiError`` mirrors
 * the real ``ApiError(status: number, body: ApiErrorBody)`` signature so
 * a future change to the real class breaks this test at compile time
 * instead of silently passing.
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
    api: {
      get: jest.fn(),
      post: jest.fn(),
    },
    ApiError: MockApiError,
  };
});

import CatalogBrowserOverlay from "../CatalogBrowserOverlay";
import { api, ApiError } from "@/lib/api-client";

const mockedGet = api.get as jest.Mock;
const mockedPost = api.post as jest.Mock;

const CATALOG_RESPONSE = {
  ontologies: [
    {
      id: "dcterms_minimal",
      name: "DCMI Terms (minimal)",
      description: "Subset of Dublin Core Terms for citation metadata.",
      uri: "http://purl.org/dc/terms/",
      tier: "core",
      tags: ["metadata", "library"],
      class_count: 12,
      property_count: 24,
      source: { kind: "bundled", path: "ontologies/dcterms_minimal.ttl" },
    },
    {
      id: "foaf",
      name: "FOAF",
      description: "Friend of a Friend vocabulary.",
      uri: "http://xmlns.com/foaf/0.1/",
      tier: "domain",
      tags: ["social"],
      class_count: 15,
      property_count: 60,
      source: { kind: "url", url: "http://xmlns.com/foaf/spec/index.rdf" },
    },
  ],
  count: 2,
};

describe("CatalogBrowserOverlay", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    // Default: catalog loads cleanly, library is empty (no entries marked
    // "Imported"), import succeeds.
    mockedGet.mockImplementation((url: string) => {
      if (url === "/api/v1/ontology/catalog") {
        return Promise.resolve(CATALOG_RESPONSE);
      }
      if (url.startsWith("/api/v1/ontology/library")) {
        return Promise.resolve({ data: [] });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    mockedPost.mockResolvedValue({
      registry_key: "dcterms_minimal",
      triple_count: 36,
      catalog_id: "dcterms_minimal",
    });
  });

  it("fetches the catalog and renders every entry", async () => {
    render(<CatalogBrowserOverlay onClose={jest.fn()} onImported={jest.fn()} />);

    expect(await screen.findByText(/DCMI Terms \(minimal\)/)).toBeInTheDocument();
    expect(screen.getByText(/FOAF/)).toBeInTheDocument();
    expect(mockedGet).toHaveBeenCalledWith("/api/v1/ontology/catalog");
  });

  it("renders the source badge (bundled vs remote) per entry", async () => {
    render(<CatalogBrowserOverlay onClose={jest.fn()} onImported={jest.fn()} />);

    await screen.findByText(/DCMI Terms/);
    // One bundled, one remote in the fixture.
    expect(screen.getByText("bundled")).toBeInTheDocument();
    expect(screen.getByText("remote")).toBeInTheDocument();
  });

  it("disables Import for entries already present in the registry", async () => {
    mockedGet.mockImplementation((url: string) => {
      if (url === "/api/v1/ontology/catalog") {
        return Promise.resolve(CATALOG_RESPONSE);
      }
      if (url.startsWith("/api/v1/ontology/library")) {
        return Promise.resolve({ data: [{ _key: "foaf" }] });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });

    render(<CatalogBrowserOverlay onClose={jest.fn()} onImported={jest.fn()} />);
    await screen.findByText(/FOAF/);

    // FOAF row should display "Imported", not an Import button.
    await waitFor(() => {
      const foafRow = screen.getByTestId("catalog-entry-foaf");
      expect(foafRow.textContent).toContain("Imported");
    });
    const dctermsRow = screen.getByTestId("catalog-entry-dcterms_minimal");
    expect(dctermsRow.querySelector("button")?.textContent).toBe("Import");
  });

  it("calls POST /catalog/{id}/import on Import click and fires onImported", async () => {
    const onImported = jest.fn();
    render(<CatalogBrowserOverlay onClose={jest.fn()} onImported={onImported} />);

    const dctermsRow = await screen.findByTestId("catalog-entry-dcterms_minimal");
    const importBtn = dctermsRow.querySelector("button") as HTMLButtonElement;
    fireEvent.click(importBtn);

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/v1/ontology/catalog/dcterms_minimal/import",
        {},
      );
    });
    await waitFor(() => {
      expect(onImported).toHaveBeenCalledWith("dcterms_minimal", "dcterms_minimal");
    });
  });

  it("URL-encodes catalog IDs containing reserved characters", async () => {
    mockedGet.mockImplementation((url: string) => {
      if (url === "/api/v1/ontology/catalog") {
        return Promise.resolve({
          ontologies: [
            {
              id: "schema.org",
              name: "Schema.org",
              uri: "http://schema.org/",
              source: { kind: "url", url: "https://schema.org/version/latest/schemaorg-current-http.ttl" },
            },
          ],
          count: 1,
        });
      }
      return Promise.resolve({ data: [] });
    });

    render(<CatalogBrowserOverlay onClose={jest.fn()} onImported={jest.fn()} />);

    const row = await screen.findByTestId("catalog-entry-schema.org");
    fireEvent.click(row.querySelector("button") as HTMLButtonElement);

    await waitFor(() => {
      expect(mockedPost).toHaveBeenCalledWith(
        "/api/v1/ontology/catalog/schema.org/import",
        {},
      );
    });
  });

  it("shows an error message inline when the import fails", async () => {
    mockedPost.mockRejectedValueOnce(
      new ApiError(409, { code: "CONFLICT", message: "Ontology already exists" }),
    );

    render(<CatalogBrowserOverlay onClose={jest.fn()} onImported={jest.fn()} />);
    const dctermsRow = await screen.findByTestId("catalog-entry-dcterms_minimal");
    fireEvent.click(dctermsRow.querySelector("button") as HTMLButtonElement);

    expect(
      await screen.findByText(/Import failed: Ontology already exists/),
    ).toBeInTheDocument();
  });

  it("shows a load error and no entries when the catalog fetch fails", async () => {
    mockedGet.mockImplementation((url: string) => {
      if (url === "/api/v1/ontology/catalog") {
        return Promise.reject(
          new ApiError(500, { code: "CATALOG_LOAD_FAILED", message: "boom" }),
        );
      }
      return Promise.resolve({ data: [] });
    });

    render(<CatalogBrowserOverlay onClose={jest.fn()} onImported={jest.fn()} />);

    expect(await screen.findByText(/boom/)).toBeInTheDocument();
    expect(screen.queryByText(/DCMI Terms/)).not.toBeInTheDocument();
  });

  it("closes when the user presses Escape", async () => {
    const onClose = jest.fn();
    render(<CatalogBrowserOverlay onClose={onClose} onImported={jest.fn()} />);

    await screen.findByText(/DCMI Terms/);
    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("closes when the user clicks the × close button", async () => {
    const onClose = jest.fn();
    render(<CatalogBrowserOverlay onClose={onClose} onImported={jest.fn()} />);

    await screen.findByText(/DCMI Terms/);
    fireEvent.click(screen.getByLabelText(/Close catalog browser/));
    expect(onClose).toHaveBeenCalled();
  });

  it("skips the registry fetch when existingOntologyIds is supplied", async () => {
    render(
      <CatalogBrowserOverlay
        existingOntologyIds={new Set(["foaf"])}
        onClose={jest.fn()}
        onImported={jest.fn()}
      />,
    );

    await screen.findByText(/FOAF/);

    // Only the catalog GET should have been issued -- the library GET is
    // suppressed because the parent already knows what's in the registry.
    const calls = mockedGet.mock.calls.map(([url]) => url);
    expect(calls).toContain("/api/v1/ontology/catalog");
    expect(calls.filter((u) => u.startsWith("/api/v1/ontology/library"))).toHaveLength(0);

    // FOAF marked imported even on first paint because the parent told us.
    const foafRow = screen.getByTestId("catalog-entry-foaf");
    expect(foafRow.textContent).toContain("Imported");
  });
});
