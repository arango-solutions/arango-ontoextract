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
});
