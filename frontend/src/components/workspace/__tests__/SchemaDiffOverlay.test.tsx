/**
 * Tests for the Stream 5 S.5 ``SchemaDiffOverlay``.
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

import SchemaDiffOverlay from "../SchemaDiffOverlay";
import { api, ApiError } from "@/lib/api-client";

const mockedGet = api.get as jest.Mock;

const MOCK_LIBRARY = {
  data: [
    { _key: "ont-a", name: "Ontology A" },
    { _key: "ont-b", name: "Ontology B" },
  ],
};

const MOCK_DIFF = {
  ontology_a: "ont-a",
  ontology_b: "ont-b",
  classes: { added: [{ uri: "http://ex#New", label: "NewClass" }], removed: [], changed: [] },
  properties: { added: [], removed: [], changed: [] },
  constraints: { added: [], removed: [], changed: [] },
  summary: {
    classes_added: 1,
    classes_removed: 0,
    classes_changed: 0,
    properties_added: 0,
    properties_removed: 0,
    properties_changed: 0,
    constraints_added: 0,
    constraints_removed: 0,
    constraints_changed: 0,
  },
  provenance: { a: {}, b: {}, compatible: true, warning: null },
};

describe("SchemaDiffOverlay", () => {
  beforeEach(() => {
    mockedGet.mockReset();
    mockedGet.mockImplementation((url: string) => {
      if (url.includes("/library")) {
        return Promise.resolve(MOCK_LIBRARY);
      }
      if (url.includes("/schema/diff")) {
        return Promise.resolve(MOCK_DIFF);
      }
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });
  });

  it("renders ontology A and loads registry for B", async () => {
    render(
      <SchemaDiffOverlay
        ontologyAKey="ont-a"
        ontologyAName="Ontology A"
        onClose={jest.fn()}
      />,
    );

    expect(screen.getByTestId("schema-diff-overlay")).toBeInTheDocument();
    expect(screen.getByTestId("schema-diff-ontology-a")).toHaveTextContent("Ontology A");

    await waitFor(() => {
      expect(screen.getByTestId("schema-diff-ontology-b-select")).toHaveValue("ont-b");
    });
  });

  it("fetches diff and shows summary on Compare", async () => {
    render(
      <SchemaDiffOverlay
        ontologyAKey="ont-a"
        ontologyAName="Ontology A"
        onClose={jest.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("schema-diff-ontology-b-select")).toHaveValue("ont-b");
    });

    fireEvent.click(screen.getByTestId("schema-diff-compare-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("schema-diff-summary-line")).toHaveTextContent("1 class added");
    });

    expect(mockedGet).toHaveBeenCalledWith(
      "/api/v1/ontology/schema/diff?a=ont-a&b=ont-b",
    );
  });

  it("surfaces API errors inline", async () => {
    mockedGet.mockImplementation((url: string) => {
      if (url.includes("/library")) return Promise.resolve(MOCK_LIBRARY);
      return Promise.reject(new ApiError(400, { code: "bad_request", message: "Incompatible" }));
    });

    render(
      <SchemaDiffOverlay
        ontologyAKey="ont-a"
        ontologyAName="Ontology A"
        onClose={jest.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("schema-diff-ontology-b-select")).toHaveValue("ont-b");
    });

    fireEvent.click(screen.getByTestId("schema-diff-compare-btn"));

    await waitFor(() => {
      expect(screen.getByTestId("schema-diff-error")).toHaveTextContent("Incompatible");
    });
  });

  it("closes on Esc and ×", async () => {
    const onClose = jest.fn();
    render(
      <SchemaDiffOverlay
        ontologyAKey="ont-a"
        ontologyAName="Ontology A"
        onClose={onClose}
      />,
    );

    await waitFor(() => {
      expect(screen.getByTestId("schema-diff-ontology-b-select")).toHaveValue("ont-b");
    });

    fireEvent.keyDown(window, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("schema-diff-close"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});
