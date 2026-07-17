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
    setOntologyDelete: jest.fn(),
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
      "View Dependency Graph…",
      "Compare Schema Evolution…",
      "View Quality Report",
      "Requirements & Coverage…",
      "View Feedback Learning",
      "Repair Orphan Properties…",
      "Show Pending Revisions",
      "Export",
      "Delete",
    ]);
  });

  it("Compare Schema Evolution… seeds the schema diff overlay with key + name", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu(
      { _key: "ont-1", name: "WTW Ontology" },
      actions,
    );

    items.find((it) => it.label === "Compare Schema Evolution…")!.onClick!();
    expect(actions.setSchemaDiffOverlay).toHaveBeenCalledWith({
      key: "ont-1",
      name: "WTW Ontology",
    });
  });

  it("View Dependency Graph… seeds the dependency overlay with key + name", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu(
      { _key: "ont-1", name: "WTW Ontology" },
      actions,
    );

    items.find((it) => it.label === "View Dependency Graph…")!.onClick!();
    expect(actions.setDependencyOverlay).toHaveBeenCalledWith({
      key: "ont-1",
      name: "WTW Ontology",
    });
  });

  it("View Dependency Graph… is a no-op when the ontology has no key", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu({ name: "Floating" }, actions);

    items.find((it) => it.label === "View Dependency Graph…")!.onClick!();
    expect(actions.setDependencyOverlay).not.toHaveBeenCalled();
  });

  it("View Dependency Graph… falls back to the key when name + label are missing", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu({ _key: "ont-bare" }, actions);

    items.find((it) => it.label === "View Dependency Graph…")!.onClick!();
    expect(actions.setDependencyOverlay).toHaveBeenCalledWith({
      key: "ont-bare",
      name: "ont-bare",
    });
  });

  it("Repair Orphan Properties seeds the edge-repair overlay with key + name", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu(
      { _key: "ont-1", name: "WTW Ontology" },
      actions,
    );

    items.find((it) => it.label === "Repair Orphan Properties…")!.onClick!();
    expect(actions.setEdgeRepair).toHaveBeenCalledWith({
      key: "ont-1",
      name: "WTW Ontology",
    });
  });

  it("Repair Orphan Properties is a no-op when key is missing", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu({ name: "Orphan" }, actions);

    items.find((it) => it.label === "Repair Orphan Properties…")!.onClick!();
    expect(actions.setEdgeRepair).not.toHaveBeenCalled();
  });

  it("Repair Orphan Properties falls back to the key when name + label are missing", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu({ _key: "ont-bare" }, actions);

    items.find((it) => it.label === "Repair Orphan Properties…")!.onClick!();
    expect(actions.setEdgeRepair).toHaveBeenCalledWith({
      key: "ont-bare",
      name: "ont-bare",
    });
  });

  it("Show Pending Revisions seeds the inbox overlay with key + name", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu(
      { _key: "ont-1", name: "WTW Ontology" },
      actions,
    );

    items.find((it) => it.label === "Show Pending Revisions")!.onClick!();
    expect(actions.setRevisionsInbox).toHaveBeenCalledWith({
      key: "ont-1",
      name: "WTW Ontology",
    });
  });

  it("Show Pending Revisions is a no-op when the ontology has no key", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu({ name: "Floating" }, actions);

    items.find((it) => it.label === "Show Pending Revisions")!.onClick!();
    expect(actions.setRevisionsInbox).not.toHaveBeenCalled();
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

  it("Delete opens the OntologyDeleteDialog instead of bypassing the impact preview (H.4)", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu(
      { _key: "ont-1", name: "Demo Ontology" },
      actions,
    );
    const del = items.find((it) => it.label === "Delete")!;

    expect(del.danger).toBe(true);

    // Native browser dialogs are forbidden by ui-architecture.mdc §18; the
    // builder must never call ``window.confirm`` regardless of the route
    // it picks.
    const confirmSpy = jest.spyOn(window, "confirm");
    del.onClick!();

    expect(confirmSpy).not.toHaveBeenCalled();

    // The dedicated H.4 dialog must be opened with the ontology's key
    // and display name. Crucially, ``deleteOntology`` MUST NOT fire
    // here -- the dialog itself decides when to call it (after the
    // typed-name gate AND the impact analysis have been satisfied).
    expect(actions.deleteOntology).not.toHaveBeenCalled();
    expect(actions.requestConfirm).not.toHaveBeenCalled();
    expect(actions.setOntologyDelete).toHaveBeenCalledTimes(1);
    expect(actions.setOntologyDelete).toHaveBeenCalledWith({
      key: "ont-1",
      name: "Demo Ontology",
    });

    confirmSpy.mockRestore();
  });

  it("Delete falls back to the ontology key when name + label are absent", () => {
    const actions = makeActions();
    const items = buildOntologyContextMenu({ _key: "ont-orphan" }, actions);

    items.find((it) => it.label === "Delete")!.onClick!();

    expect(actions.setOntologyDelete).toHaveBeenCalledWith({
      key: "ont-orphan",
      name: "ont-orphan",
    });
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
    expect(actions.setOntologyDelete).not.toHaveBeenCalled();
  });
});
