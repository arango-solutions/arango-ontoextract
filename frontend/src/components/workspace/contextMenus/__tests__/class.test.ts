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

  // Stream 1 H.15: classes imported from another ontology cannot be
  // curated or deleted here — the menu drops every mutating action and
  // surfaces "Open Source Ontology" so the user can jump to the owning
  // ontology and act there.
  describe("imported classes (Stream 1 H.15)", () => {
    it("drops Approve/Reject/Delete and adds Open Source Ontology + Remove Import", () => {
      const actions = makeActions();
      const items = buildClassContextMenu(
        {
          _key: "C1",
          label: "Person",
          is_imported: true,
          source_ontology_id: "foaf",
          source_ontology_name: "FOAF",
        },
        actions,
      );

      const visibleLabels = items
        .filter((it) => !it.separator)
        .map((it) => it.label);

      expect(visibleLabels).toEqual([
        "View Details",
        "View Version History",
        "View Provenance",
        "Open Source Ontology (FOAF)",
        "Remove Import (FOAF)",
      ]);
      // Mutating verbs against the imported class itself must not even
      // appear — "Remove Import" operates on the parent imports edge,
      // not on the entity. Leaving Approve/Reject/Delete in would imply
      // "fix me here once you do X", which is not the intent.
      expect(visibleLabels).not.toContain("Approve");
      expect(visibleLabels).not.toContain("Reject");
      expect(visibleLabels).not.toContain("Delete");
    });

    it("Open Source Ontology deep-links via handleSelectOntology", () => {
      const actions = makeActions();
      const items = buildClassContextMenu(
        {
          _key: "C1",
          label: "Person",
          is_imported: true,
          source_ontology_id: "foaf",
          source_ontology_name: "FOAF",
        },
        actions,
      );

      const open = items.find((it) =>
        typeof it.label === "string" && it.label.startsWith("Open Source Ontology"),
      )!;
      expect(open.disabled).toBeFalsy();
      open.onClick!();
      expect(actions.handleSelectOntology).toHaveBeenCalledWith("foaf");
    });

    it("falls back to a bare 'Open Source Ontology' label when source name is missing", () => {
      const actions = makeActions();
      const items = buildClassContextMenu(
        {
          _key: "C1",
          label: "Person",
          is_imported: true,
          source_ontology_id: "foaf",
        },
        actions,
      );

      const visibleLabels = items
        .filter((it) => !it.separator)
        .map((it) => it.label);
      expect(visibleLabels).toContain("Open Source Ontology");
      expect(visibleLabels).not.toContain("Open Source Ontology (FOAF)");
    });

    it("Remove Import is danger-styled and fires removeImportEdge with source id + name (H.16)", () => {
      const actions = makeActions();
      const items = buildClassContextMenu(
        {
          _key: "C1",
          label: "Person",
          is_imported: true,
          source_ontology_id: "foaf",
          source_ontology_name: "FOAF",
        },
        actions,
      );

      const remove = items.find((it) =>
        typeof it.label === "string" && it.label.startsWith("Remove Import"),
      )!;
      expect(remove.danger).toBe(true);
      expect(remove.disabled).toBeFalsy();
      remove.onClick!();
      expect(actions.removeImportEdge).toHaveBeenCalledWith("foaf", "FOAF");
    });

    it("Remove Import falls back to source id when source name is missing (H.16)", () => {
      const actions = makeActions();
      const items = buildClassContextMenu(
        {
          _key: "C1",
          label: "Person",
          is_imported: true,
          source_ontology_id: "foaf",
        },
        actions,
      );

      const remove = items.find((it) =>
        typeof it.label === "string" && it.label.startsWith("Remove Import"),
      )!;
      expect(remove.label).toBe("Remove Import");
      remove.onClick!();
      // Name falls back to the source id so the toast still has
      // something to render (the page-level handler then passes that
      // forward into the toast copy).
      expect(actions.removeImportEdge).toHaveBeenCalledWith("foaf", "foaf");
    });

    it("Remove Import is disabled when source_ontology_id is missing (H.16)", () => {
      const actions = makeActions();
      const items = buildClassContextMenu(
        { _key: "C1", label: "Person", is_imported: true },
        actions,
      );
      const remove = items.find((it) =>
        typeof it.label === "string" && it.label.startsWith("Remove Import"),
      )!;
      expect(remove.disabled).toBe(true);
      remove.onClick!();
      expect(actions.removeImportEdge).not.toHaveBeenCalled();
    });

    it("disables 'Open Source Ontology' when source_ontology_id is missing", () => {
      // Defensive: the wire format from ``/effective`` always populates
      // ``source_ontology_id`` for imported entities, but if a future bug
      // or a legacy fixture omits it, the menu must not silently no-op or
      // fire ``handleSelectOntology(undefined)``. Disabled + no click = the
      // safe fallback.
      const actions = makeActions();
      const items = buildClassContextMenu(
        { _key: "C1", label: "Person", is_imported: true },
        actions,
      );
      const open = items.find((it) =>
        typeof it.label === "string" && it.label.startsWith("Open Source Ontology"),
      )!;
      expect(open.disabled).toBe(true);
      open.onClick!();
      expect(actions.handleSelectOntology).not.toHaveBeenCalled();
    });

    it("keeps View Version History and View Provenance for imported classes", () => {
      // Read-only inspection is always safe and useful even on imported
      // classes — provenance is how the user verifies why an axiom is
      // present at all.
      const actions = makeActions();
      mockedApi.get
        .mockResolvedValueOnce([{ ts: 1 }])
        .mockResolvedValueOnce({ data: [{ source: "doc-1" }] });

      const items = buildClassContextMenu(
        {
          _key: "C1",
          label: "Person",
          is_imported: true,
          source_ontology_id: "foaf",
        },
        actions,
      );

      const history = items.find((it) => it.label === "View Version History")!;
      const provenance = items.find((it) => it.label === "View Provenance")!;
      expect(history).toBeDefined();
      expect(provenance).toBeDefined();
    });

    it("treats is_imported: false as a regular class", () => {
      // Boundary: the field is optional, and the falsy paths (undefined,
      // false, missing) must all yield the full mutating menu.
      const actions = makeActions();
      const items = buildClassContextMenu(
        { _key: "C1", label: "Person", is_imported: false },
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
  });
});
