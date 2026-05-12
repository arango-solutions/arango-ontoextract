import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import EdgeRepairOverlay from "../EdgeRepairOverlay";

const previewEdgeRepair = jest.fn();
const applyEdgeRepair = jest.fn();

jest.mock("@/lib/edgeRepair", () => ({
  previewEdgeRepair: (...args: unknown[]) => previewEdgeRepair(...args),
  applyEdgeRepair: (...args: unknown[]) => applyEdgeRepair(...args),
}));

jest.mock("@/lib/api-client", () => ({
  ApiError: class ApiError extends Error {
    public readonly status = 500;
    public readonly body = { code: "X", message: "stub" };
  },
}));

function makePreview(overrides: Record<string, unknown> = {}) {
  return {
    ontology_id: "ont-1",
    orphans_found: 3,
    repaired_count: 2,
    unrecoverable_count: 1,
    no_domain_count: 0,
    repaired: [
      {
        prop_key: "Lsa_is_contributed_to_by",
        domain_class_key: "LifestyleSpendingAccount",
        range_class_key: "Employer",
        matched_text: "employer matched in description",
        matched_via: "label",
        other_candidates: [],
      },
      {
        prop_key: "Tr_is_presented_at",
        domain_class_key: "TotalRewards",
        range_class_key: "TotalRewardsBrand",
        matched_text: "presented at brand",
        matched_via: "key",
        other_candidates: [],
      },
    ],
    unrecoverable: [
      {
        prop_key: "Vc_evaluates_impact_on_healthcare_cost",
        domain_class_key: "VirtualCare",
        label: "evaluates impact on healthcare cost",
        description: "",
      },
    ],
    no_domain: [],
    ...overrides,
  };
}

describe("EdgeRepairOverlay", () => {
  beforeEach(() => {
    previewEdgeRepair.mockReset();
    applyEdgeRepair.mockReset();
  });

  it("calls preview on mount and renders the repairable / unrecoverable buckets", async () => {
    previewEdgeRepair.mockResolvedValue(makePreview());

    render(
      <EdgeRepairOverlay
        ontologyId="ont-1"
        ontologyName="WTW Ontology"
        onClose={() => {}}
        onApplied={() => {}}
      />,
    );

    expect(previewEdgeRepair).toHaveBeenCalledWith("ont-1");

    await screen.findByText(/Repairable \(2\)/);
    expect(screen.getByText(/Unrecoverable \(1\)/)).toBeInTheDocument();
    expect(screen.getByText("Lsa_is_contributed_to_by")).toBeInTheDocument();
    expect(screen.getByText("TotalRewardsBrand")).toBeInTheDocument();
    expect(
      screen.getByText("Vc_evaluates_impact_on_healthcare_cost"),
    ).toBeInTheDocument();
  });

  it("Apply button label reflects the repair count and is disabled while applying", async () => {
    previewEdgeRepair.mockResolvedValue(makePreview());
    let resolveApply: (v: unknown) => void = () => {};
    applyEdgeRepair.mockReturnValue(
      new Promise((r) => {
        resolveApply = r;
      }),
    );

    render(
      <EdgeRepairOverlay
        ontologyId="ont-1"
        ontologyName="WTW Ontology"
        onClose={() => {}}
        onApplied={() => {}}
      />,
    );

    const applyBtn = await screen.findByRole("button", {
      name: /Apply 2 repairs/,
    });
    fireEvent.click(applyBtn);

    expect(applyEdgeRepair).toHaveBeenCalledWith("ont-1");
    await screen.findByRole("button", { name: /Applying…/ });
    expect(screen.getByRole("button", { name: /Applying…/ })).toBeDisabled();

    // Resolve the apply promise and wait for the resulting state
    // transition so cleanup state updates happen inside React's
    // ``act`` window (avoids a noisy act() warning at teardown).
    resolveApply(
      makePreview({
        orphans_found: 1,
        repaired_count: 2,
        unrecoverable_count: 1,
        repaired: [],
        unrecoverable: [],
      }),
    );
    await waitFor(() =>
      expect(screen.getByText(/Repair complete/)).toBeInTheDocument(),
    );
  });

  it("on successful apply, fires onApplied and renders the success summary", async () => {
    previewEdgeRepair.mockResolvedValue(makePreview());
    applyEdgeRepair.mockResolvedValue(
      makePreview({
        orphans_found: 1,
        repaired_count: 2,
        unrecoverable_count: 1,
      }),
    );

    const onApplied = jest.fn();
    render(
      <EdgeRepairOverlay
        ontologyId="ont-1"
        ontologyName="WTW Ontology"
        onClose={() => {}}
        onApplied={onApplied}
      />,
    );

    fireEvent.click(
      await screen.findByRole("button", { name: /Apply 2 repairs/ }),
    );

    await screen.findByText(/Repair complete/);
    expect(onApplied).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Inserted/)).toBeInTheDocument();
    // Unrecoverable footnote should be present when >0 remain.
    expect(
      screen.getByText(/still need.*new evidence or human curation/i),
    ).toBeInTheDocument();
  });

  it("disables Apply when there are no repairable orphans", async () => {
    previewEdgeRepair.mockResolvedValue(
      makePreview({
        orphans_found: 0,
        repaired_count: 0,
        unrecoverable_count: 0,
        repaired: [],
        unrecoverable: [],
      }),
    );

    render(
      <EdgeRepairOverlay
        ontologyId="ont-1"
        ontologyName="WTW Ontology"
        onClose={() => {}}
        onApplied={() => {}}
      />,
    );

    await screen.findByText(/No orphan object properties found/);
    const btn = screen.getByRole("button", { name: /Nothing to apply/ });
    expect(btn).toBeDisabled();
  });

  it("renders an error banner with retry when preview fails", async () => {
    previewEdgeRepair.mockRejectedValue(new Error("network down"));

    render(
      <EdgeRepairOverlay
        ontologyId="ont-1"
        ontologyName="WTW Ontology"
        onClose={() => {}}
        onApplied={() => {}}
      />,
    );

    await screen.findByText(/network down/);
    const retry = screen.getByRole("button", { name: /Try again/ });

    previewEdgeRepair.mockResolvedValueOnce(makePreview());
    fireEvent.click(retry);

    await screen.findByText(/Repairable \(2\)/);
    expect(previewEdgeRepair).toHaveBeenCalledTimes(2);
  });

  it("Cancel triggers onClose", async () => {
    previewEdgeRepair.mockResolvedValue(makePreview());
    const onClose = jest.fn();

    render(
      <EdgeRepairOverlay
        ontologyId="ont-1"
        ontologyName="WTW Ontology"
        onClose={onClose}
        onApplied={() => {}}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: /Cancel/ }));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("renders the no_domain bucket as a structurally-broken section", async () => {
    previewEdgeRepair.mockResolvedValue(
      makePreview({
        orphans_found: 5,
        repaired_count: 2,
        unrecoverable_count: 1,
        no_domain_count: 2,
        no_domain: ["floating_p1", "floating_p2"],
      }),
    );

    render(
      <EdgeRepairOverlay
        ontologyId="ont-1"
        ontologyName="WTW Ontology"
        onClose={() => {}}
        onApplied={() => {}}
      />,
    );

    await screen.findByText(/No domain \(2\)/);
    expect(screen.getByText("floating_p1")).toBeInTheDocument();
    expect(screen.getByText("floating_p2")).toBeInTheDocument();
  });
});
