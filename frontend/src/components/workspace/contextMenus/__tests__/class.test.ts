/**
 * @jest-environment jsdom
 */

import { buildClassContextMenu } from "@/components/workspace/contextMenus/class";
import type { WorkspaceContextMenuActions } from "@/components/workspace/contextMenus/types";
import * as apiClient from "@/lib/api-client";

jest.mock("@/lib/api-client", () => ({
  api: {
    get: jest.fn(),
    put: jest.fn(),
    post: jest.fn(),
    del: jest.fn(),
  },
  ApiError: class ApiError extends Error {},
}));

const mockedApi = apiClient.api as jest.Mocked<typeof apiClient.api>;

/** Build a ``WorkspaceContextMenuActions`` whose every method is a Jest mock,
 *  so individual tests can assert the right one fired with the right args. */
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
    setRevisionsInbox: jest.fn(),
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

describe("buildClassContextMenu", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("returns the canonical class menu inventory in order", () => {
    const actions = makeActions();
    const items = buildClassContextMenu(
      { _key: "C1", label: "Person" },
      actions,
    );

    const visibleLabels = items
      .filter((it) => !it.separator)
      .map((it) => it.label);

    expect(visibleLabels).toEqual([
      "View Details",
      "Approve",
      "Reject",
      "View Version History",
      "View Provenance",
      "Delete",
    ]);
  });

  it("View Details fires handleNodeSelect with the class key", () => {
    const actions = makeActions();
    const items = buildClassContextMenu({ _key: "C1", label: "Person" }, actions);

    items.find((it) => it.label === "View Details")!.onClick!();

    expect(actions.handleNodeSelect).toHaveBeenCalledWith("C1");
  });

  it("Approve and Reject fire the matching curation callbacks", () => {
    const actions = makeActions();
    const items = buildClassContextMenu({ _key: "C1", label: "Person" }, actions);

    items.find((it) => it.label === "Approve")!.onClick!();
    items.find((it) => it.label === "Reject")!.onClick!();

    expect(actions.approveClass).toHaveBeenCalledWith("C1");
    expect(actions.rejectClass).toHaveBeenCalledWith("C1");
  });

  it("falls back to data.key when _key is absent", () => {
    const actions = makeActions();
    const items = buildClassContextMenu({ key: "C9", label: "Org" }, actions);

    items.find((it) => it.label === "View Details")!.onClick!();

    expect(actions.handleNodeSelect).toHaveBeenCalledWith("C9");
  });

  it("View Version History opens the info panel with fetched history", async () => {
    const actions = makeActions();
    mockedApi.get.mockResolvedValueOnce([{ ts: 1 }, { ts: 2 }]);

    const items = buildClassContextMenu({ _key: "C1", label: "Person" }, actions);
    await items.find((it) => it.label === "View Version History")!.onClick!();

    expect(mockedApi.get).toHaveBeenCalledWith(
      "/api/v1/ontology/class/C1/history",
    );
    expect(actions.setInfoPanelItem).toHaveBeenCalledWith({
      type: "ontology",
      data: {
        _key: "C1",
        name: "Person",
        _history: [{ ts: 1 }, { ts: 2 }],
      },
    });
  });

  it("View Version History falls back to handleNodeSelect on fetch error", async () => {
    const actions = makeActions();
    mockedApi.get.mockRejectedValueOnce(new Error("boom"));

    const items = buildClassContextMenu({ _key: "C1", label: "Person" }, actions);
    await items.find((it) => it.label === "View Version History")!.onClick!();

    expect(actions.setInfoPanelItem).not.toHaveBeenCalled();
    expect(actions.handleNodeSelect).toHaveBeenCalledWith("C1");
  });

  it("View Provenance opens the info panel with provenance data on success", async () => {
    const actions = makeActions();
    mockedApi.get.mockResolvedValueOnce({ data: [{ source: "doc-1" }] });

    const items = buildClassContextMenu({ _key: "C1", label: "Person" }, actions);
    await items.find((it) => it.label === "View Provenance")!.onClick!();

    expect(mockedApi.get).toHaveBeenCalledWith(
      "/api/v1/ontology/class/C1/provenance",
    );
    expect(actions.setInfoPanelItem).toHaveBeenCalledWith({
      type: "ontology",
      data: {
        _key: "C1",
        name: "Person",
        _provenance: [{ source: "doc-1" }],
      },
    });
  });

  it("Delete is danger-styled and routes through requestConfirm (no window.confirm)", () => {
    const actions = makeActions();
    const items = buildClassContextMenu({ _key: "C1", label: "Person" }, actions);
    const deleteItem = items.find((it) => it.label === "Delete")!;

    expect(deleteItem.danger).toBe(true);

    const confirmSpy = jest.spyOn(window, "confirm");
    deleteItem.onClick!();
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(actions.deleteClass).not.toHaveBeenCalled();

    expect(actions.requestConfirm).toHaveBeenCalledTimes(1);
    const req = (actions.requestConfirm as jest.Mock).mock.calls[0][0];
    expect(req).toEqual(
      expect.objectContaining({
        title: "Delete class",
        confirmLabel: "Delete",
        danger: true,
      }),
    );
    expect(req.message).toContain('"Person"');
    expect(req.message).toContain("expire the class and all connected edges");

    confirmSpy.mockRestore();
  });

  it("requestConfirm.onConfirm fires deleteClass with the class key", () => {
    const actions = makeActions();
    const items = buildClassContextMenu({ _key: "C1", label: "Person" }, actions);

    items.find((it) => it.label === "Delete")!.onClick!();
    const req = (actions.requestConfirm as jest.Mock).mock.calls[0][0];

    req.onConfirm();
    expect(actions.deleteClass).toHaveBeenCalledWith("C1");
  });
});
