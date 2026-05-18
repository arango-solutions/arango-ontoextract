import { render, screen } from "@testing-library/react";

import CanvasLensLegend from "@/components/workspace/CanvasLensLegend";

describe("CanvasLensLegend", () => {
  it("shows semantic lens headline", () => {
    render(<CanvasLensLegend activeLens="semantic" timelineActive={false} />);
    const el = screen.getByTestId("canvas-lens-legend");
    expect(el).toHaveTextContent("Semantic");
    expect(el).toHaveTextContent("PageRank");
    expect(el).toHaveTextContent("Edge —");
    expect(el).toHaveTextContent("Subclass");
  });

  it("mentions timeline when diff lens and timeline active", () => {
    render(<CanvasLensLegend activeLens="diff" timelineActive />);
    expect(screen.getByTestId("canvas-lens-legend")).toHaveTextContent("Timeline filter");
  });

  it("curation lens explains node size is structural not approval", () => {
    render(<CanvasLensLegend activeLens="curation" timelineActive={false} />);
    const el = screen.getByTestId("canvas-lens-legend");
    expect(el).toHaveTextContent("not approval");
    expect(el).toHaveTextContent("PageRank");
  });

  it("confidence lens documents the edge encoding explicitly", () => {
    // The legend must call out exactly how edge confidence is rendered so the
    // user can read a stroke / color and know what it means (workspace rule
    // §12, "every encoding is legible in-UI"). The aggregation that feeds it
    // lives in ``backend/app/services/edge_confidence.py``.
    render(<CanvasLensLegend activeLens="confidence" timelineActive={false} />);
    const el = screen.getByTestId("canvas-lens-legend");
    expect(el).toHaveTextContent(/Edge color and stroke width/i);
    expect(el).toHaveTextContent(/per-evidence confidences/i);
    expect(el).toHaveTextContent(/relation label appends a %/i);
  });

  it("confidence lens points the user at the threshold slider below the canvas", () => {
    // Discoverability: the slider is only visible in the Confidence lens, so
    // the legend has to advertise it (workspace rule §20, "context-menu-
    // primary is hard to discover — mitigate explicitly").
    render(<CanvasLensLegend activeLens="confidence" timelineActive={false} />);
    const el = screen.getByTestId("canvas-lens-legend");
    expect(el).toHaveTextContent(/slider below the canvas/i);
    expect(el).toHaveTextContent(/composes with the time slider/i);
  });

  describe("imported swatch (Stream 1 H.15)", () => {
    // The legend has to spell out what the dashed border + dimmed fill on
    // imported entities means (workspace rule §12, "every encoding is legible
    // in-UI"). In the common case — an ontology with no imports — the row is
    // suppressed so the legend stays compact (rule §20 mitigation: copy that
    // never appears can't be discovered).
    it("omits the imported-swatch row when no imports are on the canvas", () => {
      render(
        <CanvasLensLegend activeLens="semantic" timelineActive={false} />,
      );
      expect(
        screen.queryByTestId("canvas-lens-legend-imported"),
      ).not.toBeInTheDocument();
    });

    it("omits the imported-swatch row when hasImported is explicitly false", () => {
      render(
        <CanvasLensLegend
          activeLens="semantic"
          timelineActive={false}
          hasImported={false}
        />,
      );
      expect(
        screen.queryByTestId("canvas-lens-legend-imported"),
      ).not.toBeInTheDocument();
    });

    it("surfaces the imported-swatch row when hasImported is true", () => {
      render(
        <CanvasLensLegend
          activeLens="semantic"
          timelineActive={false}
          hasImported
        />,
      );
      const row = screen.getByTestId("canvas-lens-legend-imported");
      expect(row).toBeInTheDocument();
      expect(row).toHaveTextContent(/dashed border/i);
      expect(row).toHaveTextContent(/dimmed fill/i);
      // Discoverability: tell the user the imported entity has actions
      // (right-click → "Open Source Ontology"), since left-click only
      // selects.
      expect(row).toHaveTextContent(/right-click/i);
    });

    it("renders the imported-swatch row across every lens, not just semantic", () => {
      // The encoding is lens-independent — the dashed border is the same
      // signal whether the user is in confidence, curation, diff, or source
      // mode. Verifying every lens guarantees the row is wired through the
      // shared rendering path rather than an accidental semantic-only branch.
      for (const lens of [
        "semantic",
        "confidence",
        "curation",
        "diff",
        "source",
      ] as const) {
        const { unmount } = render(
          <CanvasLensLegend
            activeLens={lens}
            timelineActive={false}
            hasImported
          />,
        );
        expect(
          screen.getByTestId("canvas-lens-legend-imported"),
        ).toBeInTheDocument();
        unmount();
      }
    });
  });
});
