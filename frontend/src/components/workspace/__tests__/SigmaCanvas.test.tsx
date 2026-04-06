import { render, screen } from "@testing-library/react";

jest.mock("sigma/rendering", () => ({
  __esModule: true,
  NodeCircleProgram: class {},
  EdgeArrowProgram: class {},
  EdgeRectangleProgram: class {},
}));

jest.mock("sigma", () => ({
  __esModule: true,
  default: class MockSigma {
    constructor() {
      /* Sigma touches WebGL at import in real package; mocked for JSDOM. */
    }

    on() {
      return this;
    }

    kill() {}

    refresh() {}

    resize() {}

    getDimensions() {
      return { width: 800, height: 600 };
    }

    getBBox() {
      return { x: [0, 100] as [number, number], y: [0, 100] as [number, number] };
    }

    getCamera() {
      return {
        setState: () => {},
        getState: () => ({ ratio: 1, angle: 0, x: 0, y: 0 }),
      };
    }

    getStagePadding() {
      return 40;
    }

    setSetting() {}
  },
}));

import SigmaCanvas from "@/components/workspace/SigmaCanvas";

describe("SigmaCanvas", () => {
  beforeAll(() => {
    global.ResizeObserver = class {
      observe() {}
      unobserve() {}
      disconnect() {}
    };
  });

  it("shows empty state when there are no classes", () => {
    render(
      <SigmaCanvas
        classes={[]}
        edges={[]}
        activeLens="semantic"
        onNodeSelect={() => {}}
        onEdgeSelect={() => {}}
        onContextMenu={() => {}}
      />,
    );
    expect(screen.getByTestId("sigma-empty")).toBeInTheDocument();
    expect(screen.getByText(/No ontology data available/i)).toBeInTheDocument();
  });
});
