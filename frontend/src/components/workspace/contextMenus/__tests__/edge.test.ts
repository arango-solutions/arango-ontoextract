/**
 * @jest-environment jsdom
 */

import { buildEdgeContextMenu } from "@/components/workspace/contextMenus/edge";
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

describe("buildEdgeContextMenu", () => {
  beforeEach(() => {
    mockedApi.get.mockReset();
  });

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
      "View Version History",
      "View Provenance",
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

  it("View Version History fetches the edge history endpoint and opens the info panel with _history", async () => {
    const actions = makeActions();
    const versions = [
      { _key: "v3", label: "knows", created: 3 },
      { _key: "v2", label: "knows", created: 2 },
      { _key: "v1", label: "knows", created: 1 },
    ];
    mockedApi.get.mockResolvedValueOnce(versions);

    const items = buildEdgeContextMenu({ _key: "E1", label: "knows" }, actions);
    await items.find((it) => it.label === "View Version History")!.onClick!();

    expect(mockedApi.get).toHaveBeenCalledWith("/api/v1/ontology/edge/E1/history");
    expect(actions.setInfoPanelItem).toHaveBeenCalledWith({
      type: "ontology",
      data: { _key: "E1", name: "knows", _history: versions },
    });
  });

  it("View Version History falls back to opening the detail panel when the API errors", async () => {
    const actions = makeActions();
    mockedApi.get.mockRejectedValueOnce(new Error("boom"));

    const items = buildEdgeContextMenu({ _key: "E1", label: "knows" }, actions);
    await items.find((it) => it.label === "View Version History")!.onClick!();

    expect(actions.handleEdgeSelect).toHaveBeenCalledWith("E1");
    expect(actions.setDetailPanelOpen).toHaveBeenCalledWith(true);
    expect(actions.setInfoPanelItem).not.toHaveBeenCalled();
  });

  it("View Provenance fetches the edge provenance endpoint and opens the info panel with _provenance", async () => {
    const actions = makeActions();
    const provData = [
      { _key: "c1", text: "Customer is …", chunk_index: 0, doc_id: "D1" },
    ];
    mockedApi.get.mockResolvedValueOnce({ data: provData });

    const items = buildEdgeContextMenu({ _key: "E1", label: "knows" }, actions);
    await items.find((it) => it.label === "View Provenance")!.onClick!();

    expect(mockedApi.get).toHaveBeenCalledWith("/api/v1/ontology/edge/E1/provenance");
    expect(actions.setInfoPanelItem).toHaveBeenCalledWith({
      type: "ontology",
      data: { _key: "E1", name: "knows", _provenance: provData },
    });
  });

  it("View Provenance falls back to opening the detail panel when the API errors", async () => {
    const actions = makeActions();
    mockedApi.get.mockRejectedValueOnce(new Error("boom"));

    const items = buildEdgeContextMenu({ _key: "E1", label: "knows" }, actions);
    await items.find((it) => it.label === "View Provenance")!.onClick!();

    expect(actions.handleEdgeSelect).toHaveBeenCalledWith("E1");
    expect(actions.setDetailPanelOpen).toHaveBeenCalledWith(true);
    expect(actions.setInfoPanelItem).not.toHaveBeenCalled();
  });

  it("Delete is disabled and danger-styled (edge deletion not yet supported)", () => {
    const actions = makeActions();
    const items = buildEdgeContextMenu({ _key: "E1", label: "knows" }, actions);
    const deleteItem = items.find((it) => it.label === "Delete")!;

    expect(deleteItem.disabled).toBe(true);
    expect(deleteItem.danger).toBe(true);
    expect(deleteItem.onClick).toBeUndefined();
  });

  // Stream 1 H.15: edges that came from an imported ontology cannot be
  // curated here. Same treatment as imported classes — drop the mutating
  // section, surface "Open Source Ontology".
  describe("imported edges (Stream 1 H.15)", () => {
    it("drops Approve/Reject/Delete and adds Open Source Ontology + Remove Import", () => {
      const actions = makeActions();
      const items = buildEdgeContextMenu(
        {
          _key: "E1",
          label: "subClassOf",
          is_imported: true,
          source_ontology_id: "rdfs-core",
          source_ontology_name: "RDFS Core",
        },
        actions,
      );

      const visibleLabels = items
        .filter((it) => !it.separator)
        .map((it) => it.label);

      expect(visibleLabels).toEqual([
        "subClassOf",
        "View Version History",
        "View Provenance",
        "Open Source Ontology (RDFS Core)",
        "Remove Import (RDFS Core)",
      ]);
      expect(visibleLabels).not.toContain("Approve edge");
      expect(visibleLabels).not.toContain("Reject edge");
      expect(visibleLabels).not.toContain("Delete");
    });

    it("Remove Import is danger-styled and fires removeImportEdge (H.16)", () => {
      const actions = makeActions();
      const items = buildEdgeContextMenu(
        {
          _key: "E1",
          label: "subClassOf",
          is_imported: true,
          source_ontology_id: "rdfs-core",
          source_ontology_name: "RDFS Core",
        },
        actions,
      );
      const remove = items.find((it) =>
        typeof it.label === "string" && it.label.startsWith("Remove Import"),
      )!;
      expect(remove.danger).toBe(true);
      expect(remove.disabled).toBeFalsy();
      remove.onClick!();
      expect(actions.removeImportEdge).toHaveBeenCalledWith(
        "rdfs-core",
        "RDFS Core",
      );
    });

    it("Open Source Ontology deep-links via handleSelectOntology", () => {
      const actions = makeActions();
      const items = buildEdgeContextMenu(
        {
          _key: "E1",
          label: "subClassOf",
          is_imported: true,
          source_ontology_id: "rdfs-core",
          source_ontology_name: "RDFS Core",
        },
        actions,
      );

      const open = items.find((it) =>
        typeof it.label === "string" && it.label.startsWith("Open Source Ontology"),
      )!;
      expect(open.disabled).toBeFalsy();
      open.onClick!();
      expect(actions.handleSelectOntology).toHaveBeenCalledWith("rdfs-core");
    });

    it("disables 'Open Source Ontology' when source_ontology_id is missing", () => {
      const actions = makeActions();
      const items = buildEdgeContextMenu(
        { _key: "E1", label: "subClassOf", is_imported: true },
        actions,
      );
      const open = items.find((it) =>
        typeof it.label === "string" && it.label.startsWith("Open Source Ontology"),
      )!;
      expect(open.disabled).toBe(true);
      open.onClick!();
      expect(actions.handleSelectOntology).not.toHaveBeenCalled();
    });

    it("treats is_imported: false as a regular edge (full mutating menu)", () => {
      const actions = makeActions();
      const items = buildEdgeContextMenu(
        { _key: "E1", label: "knows", is_imported: false },
        actions,
      );
      const visibleLabels = items
        .filter((it) => !it.separator)
        .map((it) => it.label);
      expect(visibleLabels).toEqual([
        "knows",
        "Approve edge",
        "Reject edge",
        "View Version History",
        "View Provenance",
        "Delete",
      ]);
    });
  });
});
