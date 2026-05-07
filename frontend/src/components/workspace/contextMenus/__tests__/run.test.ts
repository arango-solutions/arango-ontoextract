/**
 * @jest-environment jsdom
 */

import { buildRunContextMenu } from "@/components/workspace/contextMenus/run";
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
    selectedOntologyId: null,
  };
}

describe("buildRunContextMenu", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("returns the canonical run menu inventory in order", () => {
    const actions = makeActions();
    const items = buildRunContextMenu({ _key: "run-1" }, actions);

    const visibleLabels = items
      .filter((it) => !it.separator)
      .map((it) => it.label);

    expect(visibleLabels).toEqual([
      "View Pipeline & Metrics",
      "Copy Run ID",
      "View Run Info",
      "View Extracted Entities",
      "Retry Run",
      "Delete Run",
    ]);
  });

  it("View Pipeline & Metrics dispatches handleSelectRun", () => {
    const actions = makeActions();
    const items = buildRunContextMenu({ _key: "run-1" }, actions);

    items.find((it) => it.label === "View Pipeline & Metrics")!.onClick!();
    expect(actions.handleSelectRun).toHaveBeenCalledWith("run-1");
  });

  it("Copy Run ID writes the key to the clipboard", () => {
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    const actions = makeActions();
    const items = buildRunContextMenu({ _key: "run-1" }, actions);

    items.find((it) => it.label === "Copy Run ID")!.onClick!();
    expect(writeText).toHaveBeenCalledWith("run-1");
  });

  it("View Run Info opens the side panel with the fetched run", async () => {
    const actions = makeActions();
    mockedApi.get.mockResolvedValueOnce({ _key: "run-1", status: "completed" });

    const items = buildRunContextMenu({ _key: "run-1" }, actions);
    await items.find((it) => it.label === "View Run Info")!.onClick!();

    expect(mockedApi.get).toHaveBeenCalledWith("/api/v1/extraction/runs/run-1");
    expect(actions.setInfoPanelItem).toHaveBeenCalledWith({
      type: "run",
      data: { _key: "run-1", status: "completed" },
    });
  });

  it("View Run Info logs and skips the panel on fetch error", async () => {
    const actions = makeActions();
    mockedApi.get.mockRejectedValueOnce(new Error("nope"));
    const errSpy = jest.spyOn(console, "error").mockImplementation(() => {});

    const items = buildRunContextMenu({ _key: "run-1" }, actions);
    await items.find((it) => it.label === "View Run Info")!.onClick!();

    expect(actions.setInfoPanelItem).not.toHaveBeenCalled();
    expect(errSpy).toHaveBeenCalled();
    errSpy.mockRestore();
  });

  it("View Extracted Entities opens the panel with merged results payload", async () => {
    const actions = makeActions();
    mockedApi.get.mockResolvedValueOnce({ classes: 3, edges: 5 });

    const items = buildRunContextMenu({ _key: "run-1" }, actions);
    await items.find((it) => it.label === "View Extracted Entities")!.onClick!();

    expect(mockedApi.get).toHaveBeenCalledWith(
      "/api/v1/extraction/runs/run-1/results",
    );
    expect(actions.setInfoPanelItem).toHaveBeenCalledWith({
      type: "run",
      data: {
        _key: "run-1",
        name: "Extracted Entities",
        classes: 3,
        edges: 5,
      },
    });
  });

  it("Retry Run dispatches retryRun with the key", () => {
    const actions = makeActions();
    const items = buildRunContextMenu({ _key: "run-1" }, actions);

    items.find((it) => it.label === "Retry Run")!.onClick!();
    expect(actions.retryRun).toHaveBeenCalledWith("run-1");
  });

  it("Delete Run prompts via confirm and only dispatches on accept", () => {
    const actions = makeActions();
    const items = buildRunContextMenu({ _key: "run-1" }, actions);
    const del = items.find((it) => it.label === "Delete Run")!;

    expect(del.danger).toBe(true);

    const confirmSpy = jest.spyOn(window, "confirm").mockReturnValueOnce(false);
    del.onClick!();
    expect(actions.deleteRun).not.toHaveBeenCalled();

    confirmSpy.mockReturnValueOnce(true);
    del.onClick!();
    expect(actions.deleteRun).toHaveBeenCalledWith("run-1");

    confirmSpy.mockRestore();
  });
});
