/**
 * @jest-environment jsdom
 */

import { buildDocumentContextMenu } from "@/components/workspace/contextMenus/document";
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
    setEdgeRepair: jest.fn(),
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
    selectedOntologyId: null,
  };
}

describe("buildDocumentContextMenu", () => {
  it("returns View Info / Delete in canonical order", () => {
    const actions = makeActions();
    const items = buildDocumentContextMenu(
      { _key: "doc-1", filename: "intro.pdf" },
      actions,
    );

    const visibleLabels = items
      .filter((it) => !it.separator)
      .map((it) => it.label);

    expect(visibleLabels).toEqual(["View Info", "Delete"]);
  });

  it("View Info opens the asset info panel with the full row", () => {
    const actions = makeActions();
    const data = { _key: "doc-1", filename: "intro.pdf", size: 12345 };
    const items = buildDocumentContextMenu(data, actions);

    items.find((it) => it.label === "View Info")!.onClick!();

    expect(actions.setInfoPanelItem).toHaveBeenCalledWith({
      type: "document",
      data,
    });
  });

  it("Delete is danger-styled and fires deleteDocument with the key (no confirm)", () => {
    const actions = makeActions();
    const items = buildDocumentContextMenu({ _key: "doc-1" }, actions);
    const deleteItem = items.find((it) => it.label === "Delete")!;

    expect(deleteItem.danger).toBe(true);

    deleteItem.onClick!();

    expect(actions.deleteDocument).toHaveBeenCalledWith("doc-1");
  });
});
