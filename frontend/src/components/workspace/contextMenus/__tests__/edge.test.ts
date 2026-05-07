/**
 * @jest-environment jsdom
 */

import { buildEdgeContextMenu } from "@/components/workspace/contextMenus/edge";
import type { WorkspaceContextMenuActions } from "@/components/workspace/contextMenus/types";

function makeActions(): WorkspaceContextMenuActions {
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
    setManageImports: jest.fn(),
    setFeedbackLearning: jest.fn(),
    exportOntology: jest.fn(),
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
    selectedOntologyId: "ont-1",
  };
}

describe("buildEdgeContextMenu", () => {
  it("returns the canonical edge menu inventory using the edge label", () => {
    const actions = makeActions();
    const items = buildEdgeContextMenu(
      { _key: "E1", label: "knows" },
      actions,
    );

    const visibleLabels = items
      .filter((it) => !it.separator)
      .map((it) => it.label);

    expect(visibleLabels).toEqual([
      "knows",
      "Approve edge",
      "Reject edge",
      "Delete",
    ]);
  });

  it("falls back to data.edgeType then data.key for the label", () => {
    const actions = makeActions();
    const itemsByEdgeType = buildEdgeContextMenu(
      { _key: "E1", edgeType: "subClassOf" },
      actions,
    );
    expect(itemsByEdgeType[0].label).toBe("subClassOf");

    const itemsByKey = buildEdgeContextMenu(
      { key: "E2" },
      actions,
    );
    expect(itemsByKey[0].label).toBe("E2");
  });

  it("View item selects the edge and opens the detail panel", () => {
    const actions = makeActions();
    const items = buildEdgeContextMenu({ _key: "E1", label: "knows" }, actions);

    items[0].onClick!();

    expect(actions.handleEdgeSelect).toHaveBeenCalledWith("E1");
    expect(actions.setDetailPanelOpen).toHaveBeenCalledWith(true);
  });

  it("Approve / Reject fire the matching curation callbacks with the edge key", () => {
    const actions = makeActions();
    const items = buildEdgeContextMenu({ _key: "E1", label: "knows" }, actions);

    items.find((it) => it.label === "Approve edge")!.onClick!();
    items.find((it) => it.label === "Reject edge")!.onClick!();

    expect(actions.approveEdge).toHaveBeenCalledWith("E1");
    expect(actions.rejectEdge).toHaveBeenCalledWith("E1");
  });

  it("Delete is disabled and danger-styled (edge deletion not yet supported)", () => {
    const actions = makeActions();
    const items = buildEdgeContextMenu({ _key: "E1", label: "knows" }, actions);
    const deleteItem = items.find((it) => it.label === "Delete")!;

    expect(deleteItem.disabled).toBe(true);
    expect(deleteItem.danger).toBe(true);
    expect(deleteItem.onClick).toBeUndefined();
  });
});
