import { fireEvent, render, screen } from "@testing-library/react";

import ConfidenceThresholdSlider from "@/components/workspace/ConfidenceThresholdSlider";
import type { OntologyClass, OntologyEdge } from "@/types/curation";

function makeClass(key: string, confidence: number): OntologyClass {
  return {
    _key: key,
    label: key,
    uri: `http://ex.org#${key}`,
    ontology_id: "ont-1",
    status: "approved",
    rdf_type: "owl:Class",
    confidence,
    description: "",
    created: "2026-05-08",
    expired: null,
  } as OntologyClass;
}

function makeEdge(key: string, confidence: number | undefined): OntologyEdge {
  return {
    _key: key,
    _from: "ontology_classes/A",
    _to: "ontology_classes/B",
    type: "subclass_of",
    label: "subclass_of",
    confidence,
  } as OntologyEdge;
}

describe("ConfidenceThresholdSlider", () => {
  const classes: OntologyClass[] = [
    makeClass("hi", 0.9),
    makeClass("med", 0.6),
    makeClass("lo", 0.3),
    makeClass("zero", 0.0),
  ];
  const edges: OntologyEdge[] = [
    makeEdge("e_hi", 0.9),
    makeEdge("e_lo", 0.4),
    makeEdge("e_unk", undefined),
  ];

  it("at threshold 0 emits null sets and shows totals in the readout", () => {
    const onClasses = jest.fn();
    const onEdges = jest.fn();
    render(
      <ConfidenceThresholdSlider
        classes={classes}
        edges={edges}
        onVisibleClassesChange={onClasses}
        onVisibleEdgesChange={onEdges}
      />,
    );

    // First emission is the initial pass at threshold=0.
    expect(onClasses).toHaveBeenLastCalledWith(null);
    expect(onEdges).toHaveBeenLastCalledWith(null);
    const counts = screen.getByTestId("confidence-threshold-counts");
    expect(counts).toHaveTextContent("Showing 4 of 4 classes");
    expect(counts).toHaveTextContent("3 of 3 edges");
    expect(screen.getByTestId("confidence-threshold-value")).toHaveTextContent("0%");
  });

  it("dragging to 50% emits a class set keeping >=0.5 confidence and an edge set keeping >=0.5 (no-confidence edges hidden)", () => {
    const onClasses = jest.fn();
    const onEdges = jest.fn();
    render(
      <ConfidenceThresholdSlider
        classes={classes}
        edges={edges}
        onVisibleClassesChange={onClasses}
        onVisibleEdgesChange={onEdges}
      />,
    );

    fireEvent.change(screen.getByTestId("confidence-threshold-input"), {
      target: { value: "50" },
    });

    const lastClassesCall = onClasses.mock.calls.at(-1)![0] as Set<string> | null;
    const lastEdgesCall = onEdges.mock.calls.at(-1)![0] as Set<string> | null;
    expect(lastClassesCall).not.toBeNull();
    expect(lastEdgesCall).not.toBeNull();
    expect([...lastClassesCall!].sort()).toEqual(["hi", "med"]);
    expect([...lastEdgesCall!].sort()).toEqual(["e_hi"]);

    const counts = screen.getByTestId("confidence-threshold-counts");
    expect(counts).toHaveTextContent("Showing 2 of 4 classes");
    expect(counts).toHaveTextContent("1 of 3 edges");
    // The amber callout fires once a no-confidence edge is being hidden.
    expect(counts).toHaveTextContent(/edge.*have no confidence and are hidden/i);
  });

  it("dragging to 100% leaves only the high-confidence class visible", () => {
    const onClasses = jest.fn();
    const onEdges = jest.fn();
    render(
      <ConfidenceThresholdSlider
        classes={classes}
        edges={edges}
        onVisibleClassesChange={onClasses}
        onVisibleEdgesChange={onEdges}
      />,
    );

    fireEvent.change(screen.getByTestId("confidence-threshold-input"), {
      target: { value: "100" },
    });

    const lastClassesCall = onClasses.mock.calls.at(-1)![0] as Set<string> | null;
    expect([...lastClassesCall!].sort()).toEqual([]); // 0.9 < 1.0
    const lastEdgesCall = onEdges.mock.calls.at(-1)![0] as Set<string> | null;
    expect([...lastEdgesCall!].sort()).toEqual([]);
  });

  it("Reset button returns to 0% and re-emits null sets", () => {
    const onClasses = jest.fn();
    const onEdges = jest.fn();
    render(
      <ConfidenceThresholdSlider
        classes={classes}
        edges={edges}
        onVisibleClassesChange={onClasses}
        onVisibleEdgesChange={onEdges}
      />,
    );

    fireEvent.change(screen.getByTestId("confidence-threshold-input"), {
      target: { value: "70" },
    });
    fireEvent.click(screen.getByTestId("confidence-threshold-reset"));

    expect(screen.getByTestId("confidence-threshold-value")).toHaveTextContent("0%");
    expect(onClasses).toHaveBeenLastCalledWith(null);
    expect(onEdges).toHaveBeenLastCalledWith(null);
  });

  it("clicking a tick snaps the slider to that percent", () => {
    const onClasses = jest.fn();
    const onEdges = jest.fn();
    render(
      <ConfidenceThresholdSlider
        classes={classes}
        edges={edges}
        onVisibleClassesChange={onClasses}
        onVisibleEdgesChange={onEdges}
      />,
    );

    fireEvent.click(screen.getByTestId("confidence-threshold-tick-70"));

    expect(screen.getByTestId("confidence-threshold-value")).toHaveTextContent("70%");
    const lastClassesCall = onClasses.mock.calls.at(-1)![0] as Set<string> | null;
    expect([...lastClassesCall!].sort()).toEqual(["hi"]);
  });

  it("on unmount it emits null so a lens switch doesn't leave the page filtering", () => {
    const onClasses = jest.fn();
    const onEdges = jest.fn();
    const { unmount } = render(
      <ConfidenceThresholdSlider
        classes={classes}
        edges={edges}
        onVisibleClassesChange={onClasses}
        onVisibleEdgesChange={onEdges}
      />,
    );

    fireEvent.change(screen.getByTestId("confidence-threshold-input"), {
      target: { value: "70" },
    });
    onClasses.mockClear();
    onEdges.mockClear();

    unmount();

    expect(onClasses).toHaveBeenLastCalledWith(null);
    expect(onEdges).toHaveBeenLastCalledWith(null);
  });
});
