/**
 * @jest-environment jsdom
 */

import {
  buildCanvasContextMenu,
  LENS_OPTIONS,
} from "@/components/workspace/contextMenus/canvas";
import type { WorkspaceContextMenuActions } from "@/components/workspace/contextMenus/types";

function makeActions(
  overrides: Partial<WorkspaceContextMenuActions> = {},
): WorkspaceContextMenuActions {
  return {
    handleNodeSelect: jest.fn(),
    handleEdgeSelect: jest.fn(),
    handleSelectOntology: jest.fn(),
    handleSelectRun: jest.fn(),
    setInfoPanelItem: jest.fn(),
    setDetailPanelOpen: jest.fn(),
    setQualityOverlay: jest.fn(),
    fetchOntologyQualityReport: jest.fn(),
    approveClass: jest.fn(),
    rejectClass: jest.fn(),
    approveEdge: jest.fn(),
    rejectEdge: jest.fn(),
    approveProperty: jest.fn(),
    rejectProperty: jest.fn(),
    deleteClass: jest.fn(),
    deleteOntology: jest.fn(),
    deleteDocument: jest.fn(),
    deleteRun: jest.fn(),
    setRenameOntology: jest.fn(),
    setReleaseOntology: jest.fn(),
    setShowCreateOntology: jest.fn(),
    setShowCatalogBrowser: jest.fn(),
    setShowSchemaExtraction: jest.fn(),
    setShowRelationalExtraction: jest.fn(),
    setManageImports: jest.fn(),
    setDependencyOverlay: jest.fn(),
    setSchemaDiffOverlay: jest.fn(),
    setFeedbackLearning: jest.fn(),
    setEdgeRepair: jest.fn(),
    setRevisionsInbox: jest.fn(),
    setMergeCandidates: jest.fn(),
    setAlignmentReview: jest.fn(),
    setRequirementsOverlay: jest.fn(),
    setOntologyDelete: jest.fn(),
    exportOntology: jest.fn(),
    removeImportEdge: jest.fn(),
    retryRun: jest.fn(),
    pipelineRunId: null,
    activeLens: "semantic",
    setActiveLens: jest.fn(),
    graphViewMode: "network",
    setGraphViewMode: jest.fn(),
    fitAllNodes: jest.fn(),
    centerView: jest.fn(),
    relayout: jest.fn(),
    setEdgeStyle: jest.fn(),
    fitPipelineView: jest.fn(),
    centerPipelineView: jest.fn(),
    closeContextMenu: jest.fn(),
    requestConfirm: jest.fn(),
    selectedOntologyId: null,
    ...overrides,
  };
}

describe("buildCanvasContextMenu", () => {
  it("includes View As / Graph Style / Layout / Edge Style / Fit / Center / New / Feedback in network mode", () => {
    const actions = makeActions({ graphViewMode: "network" });
    const items = buildCanvasContextMenu({}, actions);

    const visibleLabels = items
      .filter((it) => !it.separator)
      .map((it) => it.label);

    expect(visibleLabels).toEqual([
      "View As",
      "Graph Style",
      "Layout",
      "Edge Style",
      "Fit All Nodes",
      "Center View",
      "New Ontology…",
      "Browse Standard Catalog…",
      "Extract from ArangoDB…",
      "Extract from Relational DB…",
      "Review Feedback Learning",
    ]);
  });

  it("hides Layout and Edge Style in box-arrow mode", () => {
    const actions = makeActions({ graphViewMode: "box-arrow" });
    const items = buildCanvasContextMenu({}, actions);

    const visibleLabels = items
      .filter((it) => !it.separator)
      .map((it) => it.label);

    expect(visibleLabels).not.toContain("Layout");
    expect(visibleLabels).not.toContain("Edge Style");
    expect(visibleLabels).toEqual([
      "View As",
      "Graph Style",
      "Fit All Nodes",
      "Center View",
      "New Ontology…",
      "Browse Standard Catalog…",
      "Extract from ArangoDB…",
      "Extract from Relational DB…",
      "Review Feedback Learning",
    ]);
  });

  it("View As submenu has all 5 lenses; the active one is checked", () => {
    const actions = makeActions({ activeLens: "confidence" });
    const items = buildCanvasContextMenu({}, actions);
    const viewAs = items.find((it) => it.label === "View As")!;

    expect(viewAs.submenu).toHaveLength(LENS_OPTIONS.length);
    const checked = viewAs.submenu!.filter((s) => s.checked);
    expect(checked).toHaveLength(1);
    expect(checked[0].label).toBe("Confidence");
  });

  it("View As submenu items dispatch setActiveLens with the matching id", () => {
    const actions = makeActions();
    const items = buildCanvasContextMenu({}, actions);
    const viewAs = items.find((it) => it.label === "View As")!;

    viewAs.submenu!.find((s) => s.label === "Diff (vs timeline)")!.onClick!();
    expect(actions.setActiveLens).toHaveBeenCalledWith("diff");
  });

  it("Graph Style toggles between network and box-arrow", () => {
    const actions = makeActions({ graphViewMode: "network" });
    const items = buildCanvasContextMenu({}, actions);
    const gs = items.find((it) => it.label === "Graph Style")!;

    expect(gs.submenu!.find((s) => s.label === "Network (circles)")!.checked)
      .toBe(true);
    expect(gs.submenu!.find((s) => s.label === "Box & Arrow (UML)")!.checked)
      .toBe(false);

    gs.submenu!.find((s) => s.label === "Box & Arrow (UML)")!.onClick!();
    expect(actions.setGraphViewMode).toHaveBeenCalledWith("box-arrow");
  });

  it("Layout submenu fires relayout for each mode", () => {
    const actions = makeActions({ graphViewMode: "network" });
    const items = buildCanvasContextMenu({}, actions);
    const layout = items.find((it) => it.label === "Layout")!;

    layout.submenu!.find((s) => s.label === "Force-Directed")!.onClick!();
    layout.submenu!.find((s) => s.label === "Circular")!.onClick!();
    layout.submenu!.find((s) => s.label === "Grid")!.onClick!();
    layout.submenu!.find((s) => s.label === "Random")!.onClick!();

    expect(actions.relayout).toHaveBeenNthCalledWith(1, "force");
    expect(actions.relayout).toHaveBeenNthCalledWith(2, "circular");
    expect(actions.relayout).toHaveBeenNthCalledWith(3, "grid");
    expect(actions.relayout).toHaveBeenNthCalledWith(4, "random");
  });

  it("Edge Style submenu fires setEdgeStyle for curved and straight", () => {
    const actions = makeActions({ graphViewMode: "network" });
    const items = buildCanvasContextMenu({}, actions);
    const es = items.find((it) => it.label === "Edge Style")!;

    es.submenu!.find((s) => s.label === "Curved")!.onClick!();
    es.submenu!.find((s) => s.label === "Straight")!.onClick!();

    expect(actions.setEdgeStyle).toHaveBeenNthCalledWith(1, "curved");
    expect(actions.setEdgeStyle).toHaveBeenNthCalledWith(2, "straight");
  });

  it("Fit All Nodes closes the context menu BEFORE calling fitAllNodes", () => {
    const actions = makeActions();
    const items = buildCanvasContextMenu({}, actions);

    items.find((it) => it.label === "Fit All Nodes")!.onClick!();

    expect(actions.closeContextMenu).toHaveBeenCalled();
    expect(actions.fitAllNodes).toHaveBeenCalled();
    // ordering: closeContextMenu fires first so the menu is gone before the
    // viewport pans / zooms
    const closeCall = (actions.closeContextMenu as jest.Mock).mock
      .invocationCallOrder[0];
    const fitCall = (actions.fitAllNodes as jest.Mock).mock
      .invocationCallOrder[0];
    expect(closeCall).toBeLessThan(fitCall);
  });

  it("Center View closes the context menu before calling centerView", () => {
    const actions = makeActions();
    const items = buildCanvasContextMenu({}, actions);

    items.find((it) => it.label === "Center View")!.onClick!();

    expect(actions.closeContextMenu).toHaveBeenCalled();
    expect(actions.centerView).toHaveBeenCalled();
  });

  it("New Ontology… opens the create dialog", () => {
    const actions = makeActions();
    const items = buildCanvasContextMenu({}, actions);

    items.find((it) => it.label === "New Ontology…")!.onClick!();
    expect(actions.setShowCreateOntology).toHaveBeenCalledWith(true);
  });

  it("Browse Standard Catalog… opens the catalog browser overlay", () => {
    const actions = makeActions();
    const items = buildCanvasContextMenu({}, actions);

    items.find((it) => it.label === "Browse Standard Catalog…")!.onClick!();
    expect(actions.setShowCatalogBrowser).toHaveBeenCalledWith(true);
  });

  // Stream 5 PR 2 -- the schema-extraction overlay is the peer of the
  // catalog browser: both are add-an-ontology actions, both are
  // overlays-not-routes, both fire ``setShow…(true)`` on click.
  it("Extract from ArangoDB… opens the schema extraction overlay", () => {
    const actions = makeActions();
    const items = buildCanvasContextMenu({}, actions);

    items.find((it) => it.label === "Extract from ArangoDB…")!.onClick!();
    expect(actions.setShowSchemaExtraction).toHaveBeenCalledWith(true);
  });

  // The relational extraction overlay is the SQL peer of the ArangoDB
  // extraction: same add-an-ontology surface, same overlay-not-route rule.
  it("Extract from Relational DB… opens the relational extraction overlay", () => {
    const actions = makeActions();
    const items = buildCanvasContextMenu({}, actions);

    items.find((it) => it.label === "Extract from Relational DB…")!.onClick!();
    expect(actions.setShowRelationalExtraction).toHaveBeenCalledWith(true);
  });

  it("Review Feedback Learning opens the overlay with no specific ontology", () => {
    const actions = makeActions();
    const items = buildCanvasContextMenu({}, actions);

    items.find((it) => it.label === "Review Feedback Learning")!.onClick!();
    expect(actions.setFeedbackLearning).toHaveBeenCalledWith({
      ontologyId: null,
      ontologyName: null,
    });
  });

  it("hides Show Pending Revisions when no ontology is selected", () => {
    const actions = makeActions({ selectedOntologyId: null });
    const items = buildCanvasContextMenu({}, actions);

    const visibleLabels = items
      .filter((it) => !it.separator)
      .map((it) => it.label);

    expect(visibleLabels).not.toContain("Show Pending Revisions");
  });

  it("shows Show Pending Revisions when an ontology is selected and dispatches with that key", () => {
    const actions = makeActions({ selectedOntologyId: "ont-active" });
    const items = buildCanvasContextMenu({}, actions);

    const inbox = items.find((it) => it.label === "Show Pending Revisions");
    expect(inbox).toBeDefined();

    inbox!.onClick!();
    expect(actions.setRevisionsInbox).toHaveBeenCalledWith({
      key: "ont-active",
      name: "ont-active",
    });
  });

  // Stream 2 PR 1 -- Find Duplicates… opens the MergeCandidatesOverlay.
  // Same per-ontology gating as Show Pending Revisions because ER has
  // nothing to run against without an open ontology.
  it("hides Find Duplicates… when no ontology is selected", () => {
    const actions = makeActions({ selectedOntologyId: null });
    const items = buildCanvasContextMenu({}, actions);

    const visibleLabels = items
      .filter((it) => !it.separator)
      .map((it) => it.label);

    expect(visibleLabels).not.toContain("Find Duplicates…");
    expect(actions.setMergeCandidates).not.toHaveBeenCalled();
  });

  it("shows Find Duplicates… when an ontology is selected and dispatches with that key", () => {
    const actions = makeActions({ selectedOntologyId: "ont-er-target" });
    const items = buildCanvasContextMenu({}, actions);

    const findDups = items.find((it) => it.label === "Find Duplicates…");
    expect(findDups).toBeDefined();

    findDups!.onClick!();
    expect(actions.setMergeCandidates).toHaveBeenCalledWith({
      key: "ont-er-target",
      name: "ont-er-target",
    });
  });

  it("hides Compare Schema Evolution… when no ontology is selected", () => {
    const actions = makeActions({ selectedOntologyId: null });
    const items = buildCanvasContextMenu({}, actions);

    const visibleLabels = items
      .filter((it) => !it.separator)
      .map((it) => it.label);

    expect(visibleLabels).not.toContain("Compare Schema Evolution…");
  });

  it("shows Compare Schema Evolution… when an ontology is selected and dispatches with key + name", () => {
    const actions = makeActions({
      selectedOntologyId: "ont-diff-a",
      selectedOntologyName: "Ontology Alpha",
    });
    const items = buildCanvasContextMenu({}, actions);

    const diffItem = items.find((it) => it.label === "Compare Schema Evolution…");
    expect(diffItem).toBeDefined();

    diffItem!.onClick!();
    expect(actions.setSchemaDiffOverlay).toHaveBeenCalledWith({
      key: "ont-diff-a",
      name: "Ontology Alpha",
    });
  });
});
