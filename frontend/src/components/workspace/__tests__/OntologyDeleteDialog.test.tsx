/**
 * Tests for ``OntologyDeleteDialog`` (Stream 1 H.4).
 *
 * The dialog has three responsibilities and we cover each:
 *
 *   1. Fetch the ``GET /library/{id}/deletion-impact`` payload on mount
 *      and render its summary.
 *   2. Gate ``onConfirm`` behind the typed-name input (matching the
 *      ontology display name).
 *   3. Surface API failures clearly and refuse to confirm while the
 *      impact has not loaded.
 *
 * ``api.get`` is mocked at the module boundary so no network is touched.
 */

import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import OntologyDeleteDialog from "../OntologyDeleteDialog";

const apiGet = jest.fn();

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
      get: (...args: unknown[]) => apiGet(...args),
    },
    ApiError: MockApiError,
  };
});

function makeImpact(overrides: Record<string, unknown> = {}) {
  return {
    ontology_id: "ont-1",
    ontology_name: "Demo Ontology",
    status: "active",
    direct_dependents: [],
    transitive_dependents: [],
    imports_outgoing: [],
    cross_ontology_extends_edges: 0,
    expire_counts: {
      ontology_classes: 12,
      ontology_properties: 4,
      subclass_of: 9,
      has_property: 0,
    },
    extraction_runs: { as_target: 1, as_domain: 0, total: 1 },
    quality_history_snapshots: 3,
    released_versions: 0,
    open_revisions: 0,
    has_dependents: false,
    safe_to_delete: true,
    warnings: [],
    ...overrides,
  };
}

describe("OntologyDeleteDialog", () => {
  beforeEach(() => {
    apiGet.mockReset();
  });

  it("fetches the deletion impact on mount and renders the summary", async () => {
    apiGet.mockResolvedValue(
      makeImpact({
        transitive_dependents: [
          { _key: "dep-1", name: "Dep One", status: "active", depth: 1 },
          { _key: "dep-2", name: "Dep Two", status: "active", depth: 2 },
        ],
        warnings: ["2 ontology(ies) depend on this one via imports; ..."],
      }),
    );

    render(
      <OntologyDeleteDialog
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
        onConfirm={() => {}}
      />,
    );

    expect(apiGet).toHaveBeenCalledWith(
      "/api/v1/ontology/library/ont-1/deletion-impact",
    );

    // Loading skeleton shows first.
    expect(screen.getByRole("status")).toBeInTheDocument();

    await screen.findByText(/Dependent ontologies \(2\)/);
    expect(screen.getByText("Dep One")).toBeInTheDocument();
    expect(screen.getByText(/depth 1 · active/)).toBeInTheDocument();
    expect(screen.getByText("Dep Two")).toBeInTheDocument();
    // Non-zero counts are surfaced; zero rows are filtered out so the
    // table doesn't wall the user with noise.
    expect(screen.getByText("ontology_classes")).toBeInTheDocument();
    expect(screen.getByText("12")).toBeInTheDocument();
    expect(screen.queryByText("has_property")).toBeNull();
    // Warnings are listed prominently.
    expect(
      screen.getByText(/ontology\(ies\) depend on this one via imports/),
    ).toBeInTheDocument();
  });

  it("renders the 'no entities affected' empty state when everything is zero", async () => {
    apiGet.mockResolvedValue(
      makeImpact({
        expire_counts: {},
        extraction_runs: { as_target: 0, as_domain: 0, total: 0 },
        quality_history_snapshots: 0,
        released_versions: 0,
      }),
    );

    render(
      <OntologyDeleteDialog
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
        onConfirm={() => {}}
      />,
    );

    await screen.findByText(
      /No live entities, edges, runs, or history reference this ontology/,
    );
  });

  it("disables Confirm until the typed name matches AND the impact has loaded", async () => {
    apiGet.mockResolvedValue(makeImpact());
    const onConfirm = jest.fn();

    render(
      <OntologyDeleteDialog
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
        onConfirm={onConfirm}
      />,
    );

    const input = (await screen.findByPlaceholderText(
      "Demo Ontology",
    )) as HTMLInputElement;
    const confirm = screen.getByRole("button", { name: /^Delete$/ });

    // Confirm is disabled before typing.
    expect(confirm).toBeDisabled();

    // Typing the wrong name keeps it disabled.
    fireEvent.change(input, { target: { value: "Wrong" } });
    expect(confirm).toBeDisabled();

    // Typing the exact name enables it; clicking fires onConfirm with
    // the ontology id (not the display name).
    fireEvent.change(input, { target: { value: "Demo Ontology" } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledWith("ont-1");
  });

  it("Enter in the input fires Confirm only when the name matches", async () => {
    apiGet.mockResolvedValue(makeImpact());
    const onConfirm = jest.fn();

    render(
      <OntologyDeleteDialog
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
        onConfirm={onConfirm}
      />,
    );

    const input = await screen.findByPlaceholderText("Demo Ontology");
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onConfirm).not.toHaveBeenCalled();

    fireEvent.change(input, { target: { value: "Demo Ontology" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(onConfirm).toHaveBeenCalledWith("ont-1");
  });

  it("renders an error banner when the impact fetch fails AND keeps the input disabled", async () => {
    apiGet.mockRejectedValue(new Error("network down"));

    render(
      <OntologyDeleteDialog
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={() => {}}
        onConfirm={() => {}}
      />,
    );

    await screen.findByRole("alert");
    expect(screen.getByText(/network down/)).toBeInTheDocument();

    // Even if the user types the correct name, Delete must stay disabled
    // because we don't have a confirmed impact to base the decision on.
    const input = screen.getByPlaceholderText("Demo Ontology") as HTMLInputElement;
    expect(input).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Delete$/ })).toBeDisabled();
  });

  it("Esc and the × button close the dialog", async () => {
    apiGet.mockResolvedValue(makeImpact());
    const onClose = jest.fn();

    render(
      <OntologyDeleteDialog
        ontologyId="ont-1"
        ontologyName="Demo Ontology"
        onClose={onClose}
        onConfirm={() => {}}
      />,
    );

    await screen.findByRole("dialog");
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: /Close/ }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("re-fetches when the ontologyId prop changes", async () => {
    apiGet
      .mockResolvedValueOnce(makeImpact({ ontology_id: "ont-1" }))
      .mockResolvedValueOnce(makeImpact({ ontology_id: "ont-2" }));

    const { rerender } = render(
      <OntologyDeleteDialog
        ontologyId="ont-1"
        ontologyName="Demo One"
        onClose={() => {}}
        onConfirm={() => {}}
      />,
    );

    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(1));

    rerender(
      <OntologyDeleteDialog
        ontologyId="ont-2"
        ontologyName="Demo Two"
        onClose={() => {}}
        onConfirm={() => {}}
      />,
    );

    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(2));
    expect(apiGet).toHaveBeenLastCalledWith(
      "/api/v1/ontology/library/ont-2/deletion-impact",
    );
  });
});
