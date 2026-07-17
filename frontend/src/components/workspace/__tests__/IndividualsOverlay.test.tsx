/**
 * Tests for ``IndividualsOverlay`` (Stream 21 AB-PR6, A-box instance lens).
 */

import { render, screen } from "@testing-library/react";

import IndividualsOverlay from "../IndividualsOverlay";

const apiGet = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: { get: (...a: unknown[]) => apiGet(...a) },
  ApiError: class ApiError extends Error {
    public readonly status: number;
    public readonly body: { code: string; message: string };
    constructor(status = 500, body = { code: "X", message: "stub" }) {
      super(body.message);
      this.status = status;
      this.body = body;
    }
  },
}));

beforeEach(() => apiGet.mockReset());

function renderOverlay() {
  return render(
    <IndividualsOverlay ontologyId="o1" ontologyName="Alpha" onClose={jest.fn()} />,
  );
}

test("lists individuals with type + provenance count", async () => {
  apiGet.mockResolvedValue({
    data: [
      {
        _key: "i1",
        label: "Acme Corp",
        type_label: "Organization",
        type_key: "Org",
        provenance: [{ doc_id: "d1" }, { doc_id: "d2" }],
      },
      { _key: "i2", label: "Bob", type_label: "Person", type_key: "Per", provenance: [] },
    ],
  });
  renderOverlay();

  expect(await screen.findByTestId("individual-i1")).toHaveTextContent("Acme Corp");
  expect(screen.getByTestId("individual-type-i1")).toHaveTextContent("Organization");
  expect(screen.getByTestId("individual-i1")).toHaveTextContent("📎 2");
  expect(apiGet.mock.calls[0][0]).toBe("/api/v1/ontology/o1/individuals?limit=500");
});

test("empty state when no individuals", async () => {
  apiGet.mockResolvedValue({ data: [] });
  renderOverlay();
  expect(await screen.findByTestId("individuals-empty")).toBeInTheDocument();
});

test("surfaces an error", async () => {
  apiGet.mockRejectedValue(new Error("boom"));
  renderOverlay();
  expect(await screen.findByTestId("individuals-error")).toHaveTextContent("boom");
});
