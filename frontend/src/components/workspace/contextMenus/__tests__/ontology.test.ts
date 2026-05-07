/**
 * @jest-environment jsdom
 */

import { buildOntologyContextMenu } from "@/components/workspace/contextMenus/ontology";
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
    selectedOntologyId: null,
  };
}

describe("buildOntologyContextMenu", () => {
  it("returns the canonical ontology menu inventory in order", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu(
      { _key: "ont-1", name: "Demo Ontology" },
      actions,
    );

    const visibleLabels = items
      .filter((it) => !it.separator)
      .map((it) => it.label);

    expect(visibleLabels).toEqual([
      "Open in Canvas",
      "View Info",
      "Edit name & description",
      "Release",
      "Manage Imports",
      "View Quality Report",
      "View Feedback Learning",
      "Export",
      "Delete",
    ]);
  });

  it("Open in Canvas dispatches handleSelectOntology with the key", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu({ _key: "ont-1" }, actions);

    items.find((it) => it.label === "Open in Canvas")!.onClick!();

    expect(actions.handleSelectOntology).toHaveBeenCalledWith("ont-1");
  });

  it("falls back to data.ontology_id when _key is absent", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu(
      { ontology_id: "ont-9", name: "X" },
      actions,
    );

    items.find((it) => it.label === "Open in Canvas")!.onClick!();
    expect(actions.handleSelectOntology).toHaveBeenCalledWith("ont-9");
  });

  it("View Info opens the side panel with the row payload", () => {
    const actions = makeActions();
    const data = { _key: "ont-1", name: "Demo" };
    const items = buildOntologyContextMenu(data, actions);

    items.find((it) => it.label === "View Info")!.onClick!();
    expect(actions.setInfoPanelItem).toHaveBeenCalledWith({
      type: "ontology",
      data,
    });
  });

  it("Edit name & description seeds the rename dialog with name + description", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu(
      { _key: "ont-1", name: "Demo", description: "A demo." },
      actions,
    );

    items.find((it) => it.label === "Edit name & description")!.onClick!();
    expect(actions.setRenameOntology).toHaveBeenCalledWith({
      key: "ont-1",
      name: "Demo",
      description: "A demo.",
    });
  });

  it("Edit name & description defaults description to empty string", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu(
      { _key: "ont-1", label: "OnlyLabel" },
      actions,
    );

    items.find((it) => it.label === "Edit name & description")!.onClick!();
    expect(actions.setRenameOntology).toHaveBeenCalledWith({
      key: "ont-1",
      name: "OnlyLabel",
      description: "",
    });
  });

  it("Release is disabled for deprecated ontologies", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu(
      { _key: "ont-1", status: "deprecated" },
      actions,
    );
    const release = items.find((it) => it.label === "Release")!;

    expect(release.disabled).toBe(true);

    release.onClick!();
    expect(actions.setReleaseOntology).not.toHaveBeenCalled();
  });

  it("Release seeds the release dialog with current_release_version", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu(
      { _key: "ont-1", current_release_version: "v1.2.0" },
      actions,
    );

    items.find((it) => it.label === "Release")!.onClick!();
    expect(actions.setReleaseOntology).toHaveBeenCalledWith({
      key: "ont-1",
      currentReleaseVersion: "v1.2.0",
    });
  });

  it("Manage Imports seeds the dialog with the resolved name", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu(
      { _key: "ont-1", name: "Demo" },
      actions,
    );

    items.find((it) => it.label === "Manage Imports")!.onClick!();
    expect(actions.setManageImports).toHaveBeenCalledWith({
      key: "ont-1",
      name: "Demo",
    });
  });

  it("View Quality Report calls fetchOntologyQualityReport with the row", () => {
    const actions = makeActions();
    const data = { _key: "ont-1", name: "Demo" };
    const items = buildOntologyContextMenu(data, actions);

    items.find((it) => it.label === "View Quality Report")!.onClick!();
    expect(actions.fetchOntologyQualityReport).toHaveBeenCalledWith(data);
  });

  it("View Feedback Learning seeds the overlay with id + name", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu(
      { _key: "ont-1", name: "Demo" },
      actions,
    );

    items.find((it) => it.label === "View Feedback Learning")!.onClick!();
    expect(actions.setFeedbackLearning).toHaveBeenCalledWith({
      ontologyId: "ont-1",
      ontologyName: "Demo",
    });
  });

  it("Export submenu has Turtle / JSON-LD / CSV that fire exportOntology", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu({ _key: "ont-1" }, actions);
    const exp = items.find((it) => it.label === "Export")!;

    expect(exp.submenu?.map((s) => s.label)).toEqual([
      "Turtle (.ttl)",
      "JSON-LD",
      "CSV",
    ]);

    exp.submenu![0].onClick!();
    exp.submenu![1].onClick!();
    exp.submenu![2].onClick!();

    expect(actions.exportOntology).toHaveBeenNthCalledWith(1, "ont-1", "turtle");
    expect(actions.exportOntology).toHaveBeenNthCalledWith(2, "ont-1", "jsonld");
    expect(actions.exportOntology).toHaveBeenNthCalledWith(3, "ont-1", "csv");
  });

  it("Delete dispatches a typed-name requestConfirm whose Confirm fires deleteOntology", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu(
      { _key: "ont-1", name: "Demo Ontology" },
      actions,
    );
    const del = items.find((it) => it.label === "Delete")!;

    expect(del.danger).toBe(true);

    const confirmSpy = jest.spyOn(window, "confirm");
    del.onClick!();

    expect(confirmSpy).not.toHaveBeenCalled();
    expect(actions.deleteOntology).not.toHaveBeenCalled();
    expect(actions.requestConfirm).toHaveBeenCalledTimes(1);

    const req = (actions.requestConfirm as jest.Mock).mock.calls[0][0];
    expect(req).toEqual(
      expect.objectContaining({
        title: "Delete ontology",
        confirmLabel: "Delete",
        danger: true,
      }),
    );
    expect(req.message).toContain('"Demo Ontology"');
    expect(req.message).toMatch(/cascades to its classes/);
    expect(req.typedName).toEqual({
      expected: "Demo Ontology",
      label: "Type the ontology name to confirm:",
      placeholder: "Demo Ontology",
    });

    req.onConfirm();
    expect(actions.deleteOntology).toHaveBeenCalledWith("ont-1");

    confirmSpy.mockRestore();
  });

  it("Delete falls back to the key for the typed-name gate when name + label are absent", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu({ _key: "ont-orphan" }, actions);

    items.find((it) => it.label === "Delete")!.onClick!();
    const req = (actions.requestConfirm as jest.Mock).mock.calls[0][0];

    expect(req.typedName.expected).toBe("ont-orphan");
    expect(req.message).toContain('"ont-orphan"');
  });

  it("does not invoke ontology actions when key is missing", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu({ name: "Orphan" }, actions);

    items.find((it) => it.label === "Open in Canvas")!.onClick!();
    items.find((it) => it.label === "Edit name & description")!.onClick!();
    items.find((it) => it.label === "Manage Imports")!.onClick!();
    items.find((it) => it.label === "Delete")!.onClick!();

    expect(actions.handleSelectOntology).not.toHaveBeenCalled();
    expect(actions.setRenameOntology).not.toHaveBeenCalled();
    expect(actions.setManageImports).not.toHaveBeenCalled();
    expect(actions.deleteOntology).not.toHaveBeenCalled();
    expect(actions.requestConfirm).not.toHaveBeenCalled();
  });
});
