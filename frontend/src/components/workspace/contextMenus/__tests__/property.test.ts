/**
 * @jest-environment jsdom
 */

import { buildPropertyContextMenu } from "@/components/workspace/contextMenus/property";
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
    selectedOntologyId: "ont-fallback",
    ...overrides,
  };
}

describe("buildPropertyContextMenu", () => {
  it("returns View / Approve / Reject / Copy URI in canonical order", () => {
    const actions = makeActions();
    const items = buildPropertyContextMenu(
      { _key: "P1", label: "name", uri: "http://ex/name", ontology_id: "ont-1" },
      actions,
    );

    const visibleLabels = items
      .filter((it) => !it.separator)
      .map((it) => it.label);

    expect(visibleLabels).toEqual(["name", "Approve", "Reject", "Copy URI"]);
  });

  it("View opens the side panel with status, range and ontology_id", () => {
    const actions = makeActions();
    const items = buildPropertyContextMenu(
      {
        _key: "P1",
        label: "age",
        status: "approved",
        range_datatype: "xsd:integer",
        ontology_id: "ont-1",
      },
      actions,
    );

    items[0].onClick!();

    expect(actions.setInfoPanelItem).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "run",
        data: expect.objectContaining({
          _key: "P1",
          name: "age",
          status: "approved",
          range: "xsd:integer",
          ontology_id: "ont-1",
        }),
      }),
    );
  });

  it("falls back to selectedOntologyId when the row has no ontology_id", () => {
    const actions = makeActions({ selectedOntologyId: "ont-fallback" });
    const items = buildPropertyContextMenu(
      { _key: "P1", label: "n" },
      actions,
    );

    items.find((it) => it.label === "Approve")!.onClick!();
    expect(actions.approveProperty).toHaveBeenCalledWith("P1", "ont-fallback");

    items.find((it) => it.label === "Reject")!.onClick!();
    expect(actions.rejectProperty).toHaveBeenCalledWith("P1", "ont-fallback");
  });

  it("disables the action that matches the current status (no-op writes)", () => {
    const actions = makeActions();
    const approved = buildPropertyContextMenu(
      { _key: "P1", status: "approved" },
      actions,
    );
    expect(approved.find((it) => it.label === "Approve")!.disabled).toBe(true);
    expect(approved.find((it) => it.label === "Reject")!.disabled).toBe(false);

    const rejected = buildPropertyContextMenu(
      { _key: "P1", status: "rejected" },
      actions,
    );
    expect(rejected.find((it) => it.label === "Approve")!.disabled).toBe(false);
    expect(rejected.find((it) => it.label === "Reject")!.disabled).toBe(true);
  });

  it("falls back to range, then target_class.label, for the View payload range field", () => {
    const actions = makeActions();
    const itemsRange = buildPropertyContextMenu(
      { _key: "P1", range: "xsd:string" },
      actions,
    );
    itemsRange[0].onClick!();
    expect(
      (actions.setInfoPanelItem as jest.Mock).mock.calls[0][0].data.range,
    ).toBe("xsd:string");

    const actions2 = makeActions();
    const itemsTarget = buildPropertyContextMenu(
      { _key: "P1", target_class: { label: "Person" } },
      actions2,
    );
    itemsTarget[0].onClick!();
    expect(
      (actions2.setInfoPanelItem as jest.Mock).mock.calls[0][0].data.range,
    ).toBe("Person");
  });

  it("Copy URI is disabled when no uri and writes to clipboard when present", () => {
    const writeText = jest.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });

    const actions = makeActions();
    const itemsNoUri = buildPropertyContextMenu({ _key: "P1" }, actions);
    expect(itemsNoUri.find((it) => it.label === "Copy URI")!.disabled).toBe(true);

    const itemsWithUri = buildPropertyContextMenu(
      { _key: "P1", uri: "http://ex/p" },
      actions,
    );
    const copy = itemsWithUri.find((it) => it.label === "Copy URI")!;
    expect(copy.disabled).toBe(false);
    copy.onClick!();
    expect(writeText).toHaveBeenCalledWith("http://ex/p");
  });
});
