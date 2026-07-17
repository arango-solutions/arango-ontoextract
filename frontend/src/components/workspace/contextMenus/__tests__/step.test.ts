/**
 * @jest-environment jsdom
 */

import { buildStepContextMenu } from "@/components/workspace/contextMenus/step";
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

const baseStepData = {
  stepKey: "ingest",
  label: "Ingest",
  status: "succeeded",
  startedAt: "2026-05-01T00:00:00Z",
  completedAt: "2026-05-01T00:00:30Z",
  data: { duration_ms: 30000, foo: "bar" },
};

describe("buildStepContextMenu", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  it("always shows View Step Details first", () => {
    const actions = makeActions();
    const items = buildStepContextMenu(baseStepData, actions);
    expect(items[0].label).toBe("View Step Details");
  });

  it("View Step Details opens the side panel with the merged step payload", () => {
    const actions = makeActions();
    const items = buildStepContextMenu(baseStepData, actions);

    items.find((it) => it.label === "View Step Details")!.onClick!();

    expect(actions.setInfoPanelItem).toHaveBeenCalledWith({
      type: "run",
      data: expect.objectContaining({
        _key: "step:ingest",
        name: "Ingest",
        status: "succeeded",
        started_at: "2026-05-01T00:00:00Z",
        completed_at: "2026-05-01T00:00:30Z",
        duration_ms: 30000,
        foo: "bar",
      }),
    });
  });

  it("omits Copy Error when the step has no error payload", () => {
    const actions = makeActions();
    const items = buildStepContextMenu(baseStepData, actions);
    expect(items.find((it) => it.label === "Copy Error")).toBeUndefined();
  });

  it("Copy Error appears when error is set and writes the error to the clipboard", () => {
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    const actions = makeActions();
    const items = buildStepContextMenu(
      { ...baseStepData, error: "boom: schema mismatch" },
      actions,
    );

    const copy = items.find((it) => it.label === "Copy Error")!;
    copy.onClick!();
    expect(writeText).toHaveBeenCalledWith("boom: schema mismatch");
  });

  it("omits View Run Results and Retry Run when no pipelineRunId is loaded", () => {
    const actions = makeActions({ pipelineRunId: null });
    const items = buildStepContextMenu(baseStepData, actions);

    const labels = items.filter((it) => !it.separator).map((it) => it.label);
    expect(labels).not.toContain("View Run Results");
    expect(labels).not.toContain("Retry Run");
    expect(labels).toEqual(["View Step Details"]);
  });

  it("View Run Results fetches results scoped to pipelineRunId and labels them with the step", async () => {
    const actions = makeActions({ pipelineRunId: "run-1" });
    mockedApi.get.mockResolvedValueOnce({ classes: 7 });

    const items = buildStepContextMenu(baseStepData, actions);
    await items.find((it) => it.label === "View Run Results")!.onClick!();

    expect(mockedApi.get).toHaveBeenCalledWith(
      "/api/v1/extraction/runs/run-1/results",
    );
    expect(actions.setInfoPanelItem).toHaveBeenCalledWith({
      type: "run",
      data: { _key: "run-1", name: "Results — Ingest", classes: 7 },
    });
  });

  it("View Run Results logs and skips on fetch error", async () => {
    const actions = makeActions({ pipelineRunId: "run-1" });
    mockedApi.get.mockRejectedValueOnce(new Error("nope"));
    const errSpy = jest.spyOn(console, "error").mockImplementation(() => {});

    const items = buildStepContextMenu(baseStepData, actions);
    await items.find((it) => it.label === "View Run Results")!.onClick!();

    expect(actions.setInfoPanelItem).not.toHaveBeenCalled();
    expect(errSpy).toHaveBeenCalled();
    errSpy.mockRestore();
  });

  it("Retry Run is disabled when status is not failed", () => {
    const actions = makeActions({ pipelineRunId: "run-1" });
    const items = buildStepContextMenu(baseStepData, actions);
    const retry = items.find((it) => it.label === "Retry Run")!;

    expect(retry.disabled).toBe(true);
  });

  it("Retry Run is enabled when status is failed and dispatches with pipelineRunId", () => {
    const actions = makeActions({ pipelineRunId: "run-1" });
    const items = buildStepContextMenu(
      { ...baseStepData, status: "failed" },
      actions,
    );
    const retry = items.find((it) => it.label === "Retry Run")!;

    expect(retry.disabled).toBe(false);
    retry.onClick!();
    expect(actions.retryRun).toHaveBeenCalledWith("run-1");
  });
});
