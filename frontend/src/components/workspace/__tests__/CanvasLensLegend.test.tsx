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
});
