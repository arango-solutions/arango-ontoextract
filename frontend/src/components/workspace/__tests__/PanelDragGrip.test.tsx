import { render } from "@testing-library/react";

import PanelDragGrip from "@/components/workspace/PanelDragGrip";

describe("PanelDragGrip", () => {
  it("renders an svg grip for the drag handle", () => {
    const { container } = render(<PanelDragGrip />);
    expect(container.querySelector("svg")).toBeTruthy();
    expect(container.querySelectorAll("circle").length).toBe(6);
  });
});
