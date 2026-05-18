/**
 * @jest-environment jsdom
 */

import { buildPipelineCanvasContextMenu } from "@/components/workspace/contextMenus/pipelineCanvas";
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
  backendUrl: (p: string) => `http://api.test${p}`,
}));

const mockedApi = apiClient.api as jest.Mocked<typeof apiClient.api>;

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
    setManageImports: jest.fn(),
    setDependencyOverlay: jest.fn(),
    setFeedbackLearning: jest.fn(),
    setEdgeRepair: jest.fn(),
    setRevisionsInbox: jest.fn(),
    setOntologyDelete: jest.fn(),
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
    ...overrides,
  };
}

describe("buildPipelineCanvasContextMenu", () => {
  beforeEach(() => {
    jest.clearAllMocks();
    (global as unknown as { fetch: jest.Mock }).fetch = jest.fn();
  });

  it("only shows Fit / Center when no run is loaded", () => {
    const actions = makeActions({ pipelineRunId: null });
    const items = buildPipelineCanvasContextMenu({}, actions);

    const labels = items.filter((it) => !it.separator).map((it) => it.label);
    expect(labels).toEqual(["Fit All Nodes", "Center View"]);
  });

  it("adds run controls when a run is loaded, in canonical order", () => {
    const actions = makeActions({ pipelineRunId: "run-1" });
    const items = buildPipelineCanvasContextMenu({}, actions);

    const labels = items.filter((it) => !it.separator).map((it) => it.label);
    expect(labels).toEqual([
      "Fit All Nodes",
      "Center View",
      "Copy Run ID",
      "View Run Info",
      "View Extracted Entities",
      "Retry Run",
      "Delete Run",
    ]);
  });

  it("Fit All Nodes closes the menu before calling fitPipelineView", () => {
    const actions = makeActions();
    const items = buildPipelineCanvasContextMenu({}, actions);

    items.find((it) => it.label === "Fit All Nodes")!.onClick!();

    expect(actions.closeContextMenu).toHaveBeenCalled();
    expect(actions.fitPipelineView).toHaveBeenCalled();

    const closeCall = (actions.closeContextMenu as jest.Mock).mock
      .invocationCallOrder[0];
    const fitCall = (actions.fitPipelineView as jest.Mock).mock
      .invocationCallOrder[0];
    expect(closeCall).toBeLessThan(fitCall);
  });

  it("Center View closes the menu before calling centerPipelineView", () => {
    const actions = makeActions();
    const items = buildPipelineCanvasContextMenu({}, actions);

    items.find((it) => it.label === "Center View")!.onClick!();
    expect(actions.closeContextMenu).toHaveBeenCalled();
    expect(actions.centerPipelineView).toHaveBeenCalled();
  });

  it("Copy Run ID writes pipelineRunId to the clipboard", () => {
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    const actions = makeActions({ pipelineRunId: "run-1" });
    const items = buildPipelineCanvasContextMenu({}, actions);

    items.find((it) => it.label === "Copy Run ID")!.onClick!();
    expect(writeText).toHaveBeenCalledWith("run-1");
  });

  it("View Run Info uses raw fetch + backendUrl and opens the panel on res.ok", async () => {
    const actions = makeActions({ pipelineRunId: "run-1" });
    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ _key: "run-1", status: "succeeded" }),
    });

    const items = buildPipelineCanvasContextMenu({}, actions);
    await items.find((it) => it.label === "View Run Info")!.onClick!();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://api.test/api/v1/extraction/runs/run-1",
    );
    expect(actions.setInfoPanelItem).toHaveBeenCalledWith({
      type: "run",
      data: { _key: "run-1", status: "succeeded" },
    });
  });

  it("View Run Info silently skips the panel when res.ok is false (raw-fetch quirk)", async () => {
    const actions = makeActions({ pipelineRunId: "run-1" });
    const fetchMock = global.fetch as jest.Mock;
    fetchMock.mockResolvedValueOnce({ ok: false, json: async () => ({}) });

    const items = buildPipelineCanvasContextMenu({}, actions);
    await items.find((it) => it.label === "View Run Info")!.onClick!();

    expect(actions.setInfoPanelItem).not.toHaveBeenCalled();
  });

  it("View Extracted Entities uses api.get and merges results into the panel payload", async () => {
    const actions = makeActions({ pipelineRunId: "run-1" });
    mockedApi.get.mockResolvedValueOnce({ classes: 4 });

    const items = buildPipelineCanvasContextMenu({}, actions);
    await items
      .find((it) => it.label === "View Extracted Entities")!
      .onClick!();

    expect(mockedApi.get).toHaveBeenCalledWith(
      "/api/v1/extraction/runs/run-1/results",
    );
    expect(actions.setInfoPanelItem).toHaveBeenCalledWith({
      type: "run",
      data: { _key: "run-1", name: "Extracted Entities", classes: 4 },
    });
  });

  it("Retry Run dispatches retryRun with the loaded run id", () => {
    const actions = makeActions({ pipelineRunId: "run-1" });
    const items = buildPipelineCanvasContextMenu({}, actions);

    items.find((it) => it.label === "Retry Run")!.onClick!();
    expect(actions.retryRun).toHaveBeenCalledWith("run-1");
  });

  it("Delete Run is danger-styled and routes through requestConfirm (no window.confirm)", () => {
    const actions = makeActions({ pipelineRunId: "run-1" });
    const items = buildPipelineCanvasContextMenu({}, actions);
    const del = items.find((it) => it.label === "Delete Run")!;

    expect(del.danger).toBe(true);

    const confirmSpy = jest.spyOn(window, "confirm");
    del.onClick!();

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(actions.deleteRun).not.toHaveBeenCalled();
    expect(actions.requestConfirm).toHaveBeenCalledTimes(1);

    const req = (actions.requestConfirm as jest.Mock).mock.calls[0][0];
    expect(req).toEqual(
      expect.objectContaining({
        title: "Delete run",
        confirmLabel: "Delete",
        danger: true,
      }),
    );
    expect(req.message).toContain("run-1");

    confirmSpy.mockRestore();
  });

  it("requestConfirm.onConfirm fires deleteRun with the loaded run id", () => {
    const actions = makeActions({ pipelineRunId: "run-1" });
    const items = buildPipelineCanvasContextMenu({}, actions);

    items.find((it) => it.label === "Delete Run")!.onClick!();
    const req = (actions.requestConfirm as jest.Mock).mock.calls[0][0];

    req.onConfirm();
    expect(actions.deleteRun).toHaveBeenCalledWith("run-1");
  });
});
