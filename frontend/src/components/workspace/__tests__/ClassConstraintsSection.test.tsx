/**
 * Tests for ClassConstraintsSection (Stream 3 PR 4).
 *
 * Two layers under test:
 *
 *   1. Pure ``groupConstraintsByProperty`` helper -- it owns the
 *      OWL/SHACL cardinality collapse + cross-vocab "strictest bound
 *      wins" logic that mirrors the backend rule engine. If this
 *      grouping ever drifts from what the rule engine evaluates, the
 *      UI starts lying to the curator. Pin every branch.
 *
 *   2. Rendered DOM -- source pills (extracted / OWL / SHACL),
 *      severity icons (SHACL only), cardinality badges, and the
 *      empty-state contract (render nothing when there are no
 *      constraints, so the parent panel stays compact).
 */

import { render, screen, waitFor } from "@testing-library/react";

import ClassConstraintsSection, {
  groupConstraintsByProperty,
} from "../ClassConstraintsSection";
import type { OntologyConstraint } from "@/types/timeline";

const apiGet = jest.fn();

jest.mock("@/lib/api-client", () => {
  class ApiError extends Error {
    public readonly status: number;
    public readonly body: { code: string; message: string };
    constructor(status: number, body: { code: string; message: string }) {
      super(body.message);
      this.status = status;
      this.body = body;
    }
  }
  return {
    api: { get: (...args: unknown[]) => apiGet(...args) },
    ApiError,
  };
});

const { ApiError: MockApiError } = require("@/lib/api-client") as {
  ApiError: new (
    status: number,
    body: { code: string; message: string },
  ) => Error & { status: number; body: { code: string; message: string } };
};

beforeEach(() => {
  apiGet.mockReset();
});

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function mkConstraint(
  overrides: Partial<OntologyConstraint> &
    Pick<
      OntologyConstraint,
      "constraint_type" | "restriction_type" | "restriction_value"
    >,
): OntologyConstraint {
  return {
    on_class: "ontology_classes/Customer",
    property_uri: "http://ex.org#hasName",
    ontology_id: "ont1",
    ...overrides,
  };
}

function stubConstraintsResponse(constraints: OntologyConstraint[]) {
  apiGet.mockResolvedValue({
    ontology_id: "ont1",
    constraints,
    total: constraints.length,
  });
}

// ===========================================================================
// groupConstraintsByProperty (pure logic)
// ===========================================================================

describe("groupConstraintsByProperty", () => {
  it("collapses min + max cardinality on the same property into one '1..5' badge", () => {
    const groups = groupConstraintsByProperty([
      mkConstraint({
        constraint_type: "owl:Restriction",
        restriction_type: "minCardinality",
        restriction_value: 1,
        property_label: "name",
      }),
      mkConstraint({
        constraint_type: "owl:Restriction",
        restriction_type: "maxCardinality",
        restriction_value: 5,
      }),
    ]);
    expect(groups).toHaveLength(1);
    expect(groups[0].cardinalityBadge).toBe("1..5");
    // Cardinality rows are absorbed into the badge -- they don't also
    // appear as separate chips, which would double-count for the user.
    expect(groups[0].chips).toHaveLength(0);
  });

  it("collapses min == max into '=N' rather than 'N..N'", () => {
    const groups = groupConstraintsByProperty([
      mkConstraint({
        constraint_type: "owl:Restriction",
        restriction_type: "minCardinality",
        restriction_value: 3,
      }),
      mkConstraint({
        constraint_type: "owl:Restriction",
        restriction_type: "maxCardinality",
        restriction_value: 3,
      }),
    ]);
    expect(groups[0].cardinalityBadge).toBe("=3");
  });

  it("expands owl:cardinality N into an '=N' badge", () => {
    const groups = groupConstraintsByProperty([
      mkConstraint({
        constraint_type: "owl:Restriction",
        restriction_type: "cardinality",
        restriction_value: 2,
      }),
    ]);
    expect(groups[0].cardinalityBadge).toBe("=2");
  });

  it("shows ≥N when only minCardinality is present", () => {
    const groups = groupConstraintsByProperty([
      mkConstraint({
        constraint_type: "owl:Restriction",
        restriction_type: "minCardinality",
        restriction_value: 1,
      }),
    ]);
    expect(groups[0].cardinalityBadge).toBe("≥1");
  });

  it("shows ≤N when only maxCardinality is present", () => {
    const groups = groupConstraintsByProperty([
      mkConstraint({
        constraint_type: "owl:Restriction",
        restriction_type: "maxCardinality",
        restriction_value: 4,
      }),
    ]);
    expect(groups[0].cardinalityBadge).toBe("≤4");
  });

  it("STRICTEST bound wins when OWL and SHACL both constrain min on same property", () => {
    // Mirror the rule engine's cross-vocab behaviour: if OWL says ≥1
    // and SHACL says ≥2, the effective minimum is 2. The UI must
    // surface what the engine evaluates, not the looser bound.
    const groups = groupConstraintsByProperty([
      mkConstraint({
        constraint_type: "owl:Restriction",
        restriction_type: "minCardinality",
        restriction_value: 1,
        import_source: "owl_restriction",
      }),
      mkConstraint({
        constraint_type: "sh:PropertyShape",
        restriction_type: "sh:minCount",
        restriction_value: 2,
        import_source: "shacl_shape",
      }),
    ]);
    expect(groups[0].cardinalityBadge).toBe("≥2");
    expect(groups[0].sources).toEqual(["owl", "shacl"]);
  });

  it("STRICTEST upper bound wins when OWL and SHACL both constrain max", () => {
    // SHACL's ≤3 is tighter than OWL's ≤5 -- show ≤3.
    const groups = groupConstraintsByProperty([
      mkConstraint({
        constraint_type: "owl:Restriction",
        restriction_type: "maxCardinality",
        restriction_value: 5,
        import_source: "owl_restriction",
      }),
      mkConstraint({
        constraint_type: "sh:PropertyShape",
        restriction_type: "sh:maxCount",
        restriction_value: 3,
        import_source: "shacl_shape",
      }),
    ]);
    expect(groups[0].cardinalityBadge).toBe("≤3");
  });

  it("keeps non-cardinality rows as chips and preserves cardinality badge alongside", () => {
    const groups = groupConstraintsByProperty([
      mkConstraint({
        constraint_type: "owl:Restriction",
        restriction_type: "minCardinality",
        restriction_value: 1,
      }),
      mkConstraint({
        constraint_type: "sh:PropertyShape",
        restriction_type: "sh:datatype",
        restriction_value: "http://www.w3.org/2001/XMLSchema#string",
        import_source: "shacl_shape",
      }),
    ]);
    expect(groups[0].cardinalityBadge).toBe("≥1");
    expect(groups[0].chips).toHaveLength(1);
    expect(groups[0].chips[0].restriction_type).toBe("sh:datatype");
  });

  it("groups by property_uri so two properties produce two groups", () => {
    const groups = groupConstraintsByProperty([
      mkConstraint({
        property_uri: "http://ex.org#hasName",
        property_label: "name",
        constraint_type: "owl:Restriction",
        restriction_type: "minCardinality",
        restriction_value: 1,
      }),
      mkConstraint({
        property_uri: "http://ex.org#hasAge",
        property_label: "age",
        constraint_type: "owl:Restriction",
        restriction_type: "maxCardinality",
        restriction_value: 1,
      }),
    ]);
    expect(groups).toHaveLength(2);
    // Sort is by label; age < name alphabetically.
    expect(groups.map((g) => g.property_label)).toEqual(["age", "name"]);
  });

  it("non-numeric restriction_value on a cardinality kind is treated as a chip (defensive)", () => {
    // If a future writer ever emits a string into a cardinality slot,
    // we'd rather show it as a chip than silently coerce it to NaN
    // and produce a misleading badge.
    const groups = groupConstraintsByProperty([
      mkConstraint({
        constraint_type: "owl:Restriction",
        restriction_type: "minCardinality",
        restriction_value: "many" as unknown as number,
      }),
    ]);
    expect(groups[0].cardinalityBadge).toBeNull();
    expect(groups[0].chips).toHaveLength(1);
  });
});

// ===========================================================================
// Rendering
// ===========================================================================

describe("ClassConstraintsSection (rendering)", () => {
  it("renders nothing when the class has zero constraints (keeps panel compact)", async () => {
    stubConstraintsResponse([]);
    const { container } = render(
      <ClassConstraintsSection ontologyId="ont1" classKey="Customer" />,
    );
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    // Empty state must be a hard null -- not "No constraints (0)".
    // Why: every class detail panel renders this section, and a noisy
    // "0 of 0" line under every class is exactly the kind of UI cruft
    // that pushes the curator's real work below the fold.
    expect(container.firstChild).toBeNull();
  });

  it("fires GET /library/{id}/constraints?class_id=ontology_classes/{key}", async () => {
    stubConstraintsResponse([]);
    render(<ClassConstraintsSection ontologyId="ont1" classKey="Customer" />);
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    const url = apiGet.mock.calls[0][0] as string;
    expect(url).toContain("/library/ont1/constraints");
    expect(url).toContain("class_id=ontology_classes%2FCustomer");
  });

  it("renders a SHACL constraint with severity icon + 'SHACL' source pill", async () => {
    // Use sh:pattern (a per-row chip) rather than sh:minCount (which
    // would collapse into the cardinality badge -- the badge is a
    // unified bound and intentionally carries no severity in v1, so
    // testing severity rendering against it would assert nothing).
    stubConstraintsResponse([
      mkConstraint({
        constraint_type: "sh:PropertyShape",
        restriction_type: "sh:pattern",
        restriction_value: "^[A-Z][a-z]+$",
        import_source: "shacl_shape",
        severity: "sh:Violation",
        property_label: "name",
      }),
    ]);
    render(<ClassConstraintsSection ontologyId="ont1" classKey="Customer" />);
    await waitFor(() =>
      expect(screen.getByText("Constraints (1)")).toBeInTheDocument(),
    );
    expect(screen.getByText("SHACL")).toBeInTheDocument();
    // The Violation icon is rendered with role="img" + aria-label
    // "Violation" so screen readers don't read the literal ⚠ glyph
    // and assistive tech instead announces the severity by name.
    expect(screen.getByRole("img", { name: "Violation" })).toBeInTheDocument();
    // The pattern itself is rendered as the value.
    expect(screen.getByText("^[A-Z][a-z]+$")).toBeInTheDocument();
  });

  it("strips XSD prefix from sh:datatype values for legibility", async () => {
    stubConstraintsResponse([
      mkConstraint({
        constraint_type: "sh:PropertyShape",
        restriction_type: "sh:datatype",
        restriction_value: "http://www.w3.org/2001/XMLSchema#string",
        import_source: "shacl_shape",
        property_label: "name",
      }),
    ]);
    render(<ClassConstraintsSection ontologyId="ont1" classKey="Customer" />);
    await waitFor(() => expect(screen.getByText("string")).toBeInTheDocument());
    // The full IRI must NOT appear -- it's noisy and the test pins
    // the humanisation rule from formatValue().
    expect(screen.queryByText(/XMLSchema#string/)).toBeNull();
  });

  it("renders sh:in arrays as a joined enumeration", async () => {
    stubConstraintsResponse([
      mkConstraint({
        constraint_type: "sh:PropertyShape",
        restriction_type: "sh:in",
        restriction_value: ["S", "M", "L"],
        import_source: "shacl_shape",
        property_label: "size",
      }),
    ]);
    render(<ClassConstraintsSection ontologyId="ont1" classKey="Customer" />);
    await waitFor(() => expect(screen.getByText("S, M, L")).toBeInTheDocument());
  });

  it("shows both 'OWL' and 'SHACL' source pills when a property is constrained from both", async () => {
    stubConstraintsResponse([
      mkConstraint({
        constraint_type: "owl:Restriction",
        restriction_type: "minCardinality",
        restriction_value: 1,
        import_source: "owl_restriction",
        property_label: "name",
      }),
      mkConstraint({
        constraint_type: "sh:PropertyShape",
        restriction_type: "sh:minCount",
        restriction_value: 2,
        import_source: "shacl_shape",
        property_label: "name",
      }),
    ]);
    render(<ClassConstraintsSection ontologyId="ont1" classKey="Customer" />);
    await waitFor(() => expect(screen.getByText("OWL")).toBeInTheDocument());
    expect(screen.getByText("SHACL")).toBeInTheDocument();
    // Cross-vocab strictest-wins -- show ≥2, not two separate badges.
    expect(screen.getByText("≥2")).toBeInTheDocument();
  });

  it("surfaces an API error inline (does not crash the parent panel)", async () => {
    apiGet.mockRejectedValueOnce(
      new MockApiError(500, { code: "INTERNAL_ERROR", message: "constraints down" }),
    );
    render(<ClassConstraintsSection ontologyId="ont1" classKey="Customer" />);
    await waitFor(() =>
      expect(screen.getByText("constraints down")).toBeInTheDocument(),
    );
  });

  it("refetches when classKey changes (panel reused for a different class)", async () => {
    stubConstraintsResponse([]);
    const { rerender } = render(
      <ClassConstraintsSection ontologyId="ont1" classKey="Customer" />,
    );
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(1));
    rerender(<ClassConstraintsSection ontologyId="ont1" classKey="Order" />);
    await waitFor(() => expect(apiGet).toHaveBeenCalledTimes(2));
    const lastUrl = apiGet.mock.calls.at(-1)?.[0] as string;
    expect(lastUrl).toContain("class_id=ontology_classes%2FOrder");
  });
});
