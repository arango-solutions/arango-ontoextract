"use client";

import { useState, useCallback, useEffect, useRef, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import LensToolbar, { type LensType } from "@/components/workspace/LensToolbar";
import AssetExplorer from "@/components/workspace/AssetExplorer";
import EmptyCanvasState from "@/components/workspace/EmptyCanvasState";
import FloatingDetailPanel from "@/components/workspace/FloatingDetailPanel";
import ContextMenu, { type ContextMenuItem } from "@/components/workspace/ContextMenu";
import { api, ApiError, type PaginatedResponse } from "@/lib/api-client";
import type {
  OntologyRegistryEntry,
  OntologyClass,
  OntologyProperty,
  OntologyEdge,
} from "@/types/curation";
import type { SigmaViewportApi } from "@/components/workspace/SigmaCanvas";

const SigmaCanvas = dynamic(() => import("@/components/workspace/SigmaCanvas"), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center bg-[#111118]">
      <div className="animate-spin h-8 w-8 border-2 border-indigo-400 border-t-transparent rounded-full" />
    </div>
  ),
});

const VCRTimeline = dynamic(() => import("@/components/timeline/VCRTimeline"), {
  ssr: false,
});

interface ContextMenuState {
  x: number;
  y: number;
  type: string;
  data: Record<string, unknown>;
}

const MIN_PANEL_WIDTH = 200;
const MAX_PANEL_WIDTH = 480;
const DEFAULT_PANEL_WIDTH = 280;

const LENS_OPTIONS: { id: LensType; label: string }[] = [
  { id: "semantic", label: "Semantic" },
  { id: "confidence", label: "Confidence" },
  { id: "curation", label: "Curation Status" },
  { id: "diff", label: "Diff (vs timeline)" },
  { id: "source", label: "Source Type" },
];

export default function WorkspacePage() {
  return (
    <Suspense>
      <WorkspacePageInner />
    </Suspense>
  );
}

function WorkspacePageInner() {
  const searchParams = useSearchParams();
  const [selectedOntologyId, setSelectedOntologyId] = useState<string | null>(null);
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const [selectedEdgeKey, setSelectedEdgeKey] = useState<string | null>(null);
  const [assetExplorerWidth, setAssetExplorerWidth] = useState(DEFAULT_PANEL_WIDTH);
  const [detailPanelOpen, setDetailPanelOpen] = useState(false);
  const [activeLens, setActiveLens] = useState<LensType>("semantic");
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [ontologyName, setOntologyName] = useState<string | null>(null);

  const [classes, setClasses] = useState<OntologyClass[]>([]);
  const [properties, setProperties] = useState<OntologyProperty[]>([]);
  const [edges, setEdges] = useState<OntologyEdge[]>([]);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [timelineVisibleKeys, setTimelineVisibleKeys] = useState<Set<string> | null>(null);

  const resizingRef = useRef(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(DEFAULT_PANEL_WIDTH);
  const viewportApiRef = useRef<SigmaViewportApi | null>(null);
  const didReadUrlParam = useRef(false);

  useEffect(() => {
    if (didReadUrlParam.current) return;
    didReadUrlParam.current = true;
    const ontologyParam = searchParams.get("ontologyId");
    if (ontologyParam && !selectedOntologyId) {
      setSelectedOntologyId(ontologyParam);
    }
  }, [searchParams, selectedOntologyId]);

  const handleViewportApi = useCallback((api: SigmaViewportApi | null) => {
    viewportApiRef.current = api;
  }, []);

  useEffect(() => {
    if (!selectedOntologyId) {
      setOntologyName(null);
      return;
    }

    let cancelled = false;
    async function loadName() {
      try {
        const res = await api.get<PaginatedResponse<OntologyRegistryEntry>>(
          "/api/v1/ontology/library",
        );
        const match = res.data.find((o) => o._key === selectedOntologyId);
        if (!cancelled && match) setOntologyName(match.name);
      } catch {
        // non-critical — fall back to ID display
      }
    }
    loadName();
    return () => { cancelled = true; };
  }, [selectedOntologyId]);

  const fetchGraphData = useCallback(async (ontologyId: string) => {
    setGraphLoading(true);
    setGraphError(null);
    try {
      const [classesRes, edgesRes] = await Promise.all([
        api.get<PaginatedResponse<OntologyClass>>(
          `/api/v1/ontology/${ontologyId}/classes`,
        ),
        api.get<PaginatedResponse<OntologyEdge>>(
          `/api/v1/ontology/${ontologyId}/edges`,
        ),
      ]);
      const classesList = Array.isArray(classesRes) ? classesRes : classesRes.data;
      const edgesList = Array.isArray(edgesRes) ? edgesRes : edgesRes.data;
      setClasses(classesList);
      setEdges(edgesList);
      setProperties([]);
    } catch (err) {
      setGraphError(
        err instanceof ApiError
          ? err.body.message
          : "Failed to load ontology graph data",
      );
    } finally {
      setGraphLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!selectedOntologyId) {
      setClasses([]);
      setProperties([]);
      setEdges([]);
      setGraphError(null);
      return;
    }
    fetchGraphData(selectedOntologyId);
  }, [selectedOntologyId, fetchGraphData]);

  useEffect(() => {
    const lensKeys: Record<string, LensType> = {
      "1": "semantic",
      "2": "confidence",
      "3": "curation",
      "4": "diff",
      "5": "source",
    };

    function handleKeyDown(e: KeyboardEvent) {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return;
      if (e.key === "Escape") {
        setContextMenu(null);
        setDetailPanelOpen(false);
        return;
      }
      const lens = lensKeys[e.key];
      if (lens && selectedOntologyId) {
        setActiveLens(lens);
      }
    }

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [selectedOntologyId]);

  const handleResizeStart = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    resizingRef.current = true;
    startXRef.current = e.clientX;
    startWidthRef.current = assetExplorerWidth;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";

    function onMouseMove(ev: MouseEvent) {
      if (!resizingRef.current) return;
      const delta = ev.clientX - startXRef.current;
      const newWidth = Math.min(MAX_PANEL_WIDTH, Math.max(MIN_PANEL_WIDTH, startWidthRef.current + delta));
      setAssetExplorerWidth(newWidth);
    }

    function onMouseUp() {
      resizingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      document.removeEventListener("mousemove", onMouseMove);
      document.removeEventListener("mouseup", onMouseUp);
    }

    document.addEventListener("mousemove", onMouseMove);
    document.addEventListener("mouseup", onMouseUp);
  }, [assetExplorerWidth]);

  const handleSelectOntology = useCallback((ontologyId: string) => {
    setSelectedNodeKey(null);
    setSelectedEdgeKey(null);
    setDetailPanelOpen(false);
    setGraphError(null);
    setInfoPanelItem(null);
    if (ontologyId === selectedOntologyId) {
      fetchGraphData(ontologyId);
    } else {
      setSelectedOntologyId(ontologyId);
    }
  }, [selectedOntologyId, fetchGraphData]);

  const handleNodeSelect = useCallback((classKey: string) => {
    setSelectedNodeKey(classKey);
    setSelectedEdgeKey(null);
    setDetailPanelOpen(true);
  }, []);

  const handleEdgeSelect = useCallback((edgeKey: string) => {
    setSelectedEdgeKey(edgeKey);
    setSelectedNodeKey(null);
  }, []);

  const [infoPanelItem, setInfoPanelItem] = useState<{
    type: "document" | "ontology" | "run";
    data: Record<string, unknown>;
  } | null>(null);

  const handleSelectDocument = useCallback(async (docId: string) => {
    try {
      const doc = await api.get<Record<string, unknown>>(`/api/v1/documents/${docId}`);
      setInfoPanelItem({ type: "document", data: doc });
    } catch {
      setInfoPanelItem({ type: "document", data: { _key: docId } });
    }
  }, []);

  const handleSelectRun = useCallback(async (runId: string) => {
    try {
      const run = await api.get<Record<string, unknown>>(`/api/v1/extraction/runs/${runId}`);
      setInfoPanelItem({ type: "run", data: run });
    } catch {
      setInfoPanelItem({ type: "run", data: { _key: runId } });
    }
  }, []);

  const handleAssetContextMenu = useCallback(
    (e: React.MouseEvent, type: string, data: unknown) => {
      e.preventDefault();
      setContextMenu({ x: e.clientX, y: e.clientY, type, data: data as Record<string, unknown> });
    },
    [],
  );

  const handleSigmaContextMenu = useCallback(
    (e: MouseEvent, type: "node" | "edge" | "canvas", data?: Record<string, unknown>) => {
      const cmType = type === "node" ? "class" : type;
      setContextMenu({ x: e.clientX, y: e.clientY, type: cmType, data: data ?? {} });
    },
    [],
  );

  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  const refreshGraph = useCallback(() => {
    if (selectedOntologyId) fetchGraphData(selectedOntologyId);
  }, [selectedOntologyId, fetchGraphData]);

  const approveClass = useCallback(async (key: string) => {
    if (!selectedOntologyId) return;
    try {
      await api.put(`/api/v1/ontology/${selectedOntologyId}/classes/${key}`, { status: "approved" });
      refreshGraph();
    } catch (err) {
      console.error("Failed to approve class", err);
    }
  }, [selectedOntologyId, refreshGraph]);

  const rejectClass = useCallback(async (key: string) => {
    if (!selectedOntologyId) return;
    try {
      await api.put(`/api/v1/ontology/${selectedOntologyId}/classes/${key}`, { status: "rejected" });
      refreshGraph();
    } catch (err) {
      console.error("Failed to reject class", err);
    }
  }, [selectedOntologyId, refreshGraph]);

  const deleteClass = useCallback(async (key: string) => {
    if (!selectedOntologyId) return;
    try {
      await api.del(`/api/v1/ontology/${selectedOntologyId}/classes/${key}`);
      refreshGraph();
    } catch (err) {
      console.error("Failed to delete class", err);
    }
  }, [selectedOntologyId, refreshGraph]);

  const deleteOntology = useCallback(async (key: string) => {
    try {
      await api.del(`/api/v1/ontology/library/${key}?confirm=true`);
      if (selectedOntologyId === key) {
        setSelectedOntologyId(null);
        setClasses([]);
        setEdges([]);
      }
    } catch (err) {
      console.error("Failed to delete ontology", err);
    }
  }, [selectedOntologyId]);

  const deleteDocument = useCallback(async (key: string) => {
    try {
      await api.del(`/api/v1/documents/${key}`);
    } catch (err) {
      console.error("Failed to delete document", err);
    }
  }, []);

  const exportOntology = useCallback(async (key: string, format: string) => {
    try {
      const url = `/api/v1/ontology/${key}/export?format=${format}`;
      window.open(`${window.location.origin}${url}`, "_blank");
    } catch (err) {
      console.error("Failed to export ontology", err);
    }
  }, []);

  const retryRun = useCallback(async (key: string) => {
    try {
      await api.post(`/api/v1/extraction/runs/${key}/retry`);
    } catch (err) {
      console.error("Failed to retry run", err);
    }
  }, []);

  function getContextMenuItems(): ContextMenuItem[] {
    if (!contextMenu) return [];

    const { type, data } = contextMenu;

    switch (type) {
      case "class": {
        const classKey = (data._key ?? data.key) as string;
        const classLabel = (data.label ?? classKey) as string;
        return [
          {
            label: "View Details", icon: "🔍",
            onClick: () => { handleNodeSelect(classKey); },
          },
          { label: "separator0", separator: true },
          {
            label: "Approve", icon: "✅",
            onClick: () => { approveClass(classKey); },
          },
          {
            label: "Reject", icon: "❌",
            onClick: () => { rejectClass(classKey); },
          },
          { label: "separator1", separator: true },
          {
            label: "View Version History", icon: "📜",
            onClick: () => { handleNodeSelect(classKey); },
          },
          {
            label: "View Provenance", icon: "🔗",
            onClick: () => { handleNodeSelect(classKey); },
          },
          { label: "separator2", separator: true },
          {
            label: "Delete", icon: "🗑️", danger: true,
            onClick: () => {
              if (confirm(`Delete class "${classLabel}"? This will expire the class and all connected edges.`)) {
                deleteClass(classKey);
              }
            },
          },
        ];
      }
      case "edge": {
        const edgeKey = (data._key ?? data.key) as string;
        const edgeLabel = (data.label ?? data.edgeType ?? edgeKey) as string;
        return [
          {
            label: `${edgeLabel}`, icon: "🔍",
            onClick: () => {
              handleEdgeSelect(edgeKey);
              setDetailPanelOpen(true);
            },
          },
          { label: "separator", separator: true },
          {
            label: "Delete", icon: "🗑️", danger: true,
            disabled: true,
          },
        ];
      }
      case "document": {
        const docKey = (data._key) as string;
        return [
          {
            label: "View Info", icon: "📋",
            onClick: () => { setInfoPanelItem({ type: "document", data }); },
          },
          { label: "separator1", separator: true },
          {
            label: "Delete", icon: "🗑️", danger: true,
            onClick: () => { deleteDocument(docKey); },
          },
        ];
      }
      case "ontology": {
        const ontKey = (data._key) as string;
        return [
          {
            label: "Open in Canvas", icon: "🔷",
            onClick: () => handleSelectOntology(ontKey),
          },
          {
            label: "View Info", icon: "📊",
            onClick: () => { setInfoPanelItem({ type: "ontology", data }); },
          },
          {
            label: "Export",
            icon: "📤",
            submenu: [
              { label: "Turtle (.ttl)", onClick: () => { exportOntology(ontKey, "turtle"); } },
              { label: "JSON-LD", onClick: () => { exportOntology(ontKey, "jsonld"); } },
              { label: "CSV", onClick: () => { exportOntology(ontKey, "csv"); } },
            ],
          },
          { label: "separator1", separator: true },
          {
            label: "Delete", icon: "🗑️", danger: true,
            onClick: () => { deleteOntology(ontKey); },
          },
        ];
      }
      case "run": {
        const runKey = (data._key) as string;
        return [
          {
            label: "View Details", icon: "🔍",
            onClick: () => { setInfoPanelItem({ type: "run", data }); },
          },
          {
            label: "Open Ontology", icon: "🔷",
            disabled: !data.ontology_id && !data.target_ontology_id,
            onClick: () => {
              const oid = (data.ontology_id ?? data.target_ontology_id) as string | undefined;
              if (oid) handleSelectOntology(oid);
            },
          },
          {
            label: "View Pipeline Metrics", icon: "⚡",
            onClick: () => {
              handleSelectRun(runKey);
            },
          },
          { label: "separator", separator: true },
          {
            label: "Retry Run", icon: "🔄",
            onClick: () => { retryRun(runKey); },
          },
        ];
      }
      case "canvas":
        return [
          {
            label: "View As",
            icon: "👁",
            submenu: LENS_OPTIONS.map((opt) => ({
              label: opt.label,
              checked: activeLens === opt.id,
              onClick: () => setActiveLens(opt.id),
            })),
          },
          {
            label: "Layout",
            icon: "🔄",
            submenu: [
              { label: "Force-Directed", onClick: () => { viewportApiRef.current?.relayout("force"); } },
              { label: "Circular", onClick: () => { viewportApiRef.current?.relayout("circular"); } },
              { label: "Grid", onClick: () => { viewportApiRef.current?.relayout("grid"); } },
              { label: "Random", onClick: () => { viewportApiRef.current?.relayout("random"); } },
            ],
          },
          {
            label: "Edge Style",
            icon: "〰",
            submenu: [
              { label: "Curved", onClick: () => { viewportApiRef.current?.setEdgeStyle("curved"); } },
              { label: "Straight", onClick: () => { viewportApiRef.current?.setEdgeStyle("straight"); } },
            ],
          },
          { label: "separator1", separator: true },
          {
            label: "Fit All Nodes",
            icon: "⬜",
            onClick: () => {
              closeContextMenu();
              viewportApiRef.current?.fitAll();
            },
          },
          {
            label: "Center View",
            icon: "🎯",
            onClick: () => {
              closeContextMenu();
              viewportApiRef.current?.centerView();
            },
          },
        ];
      default:
        return [];
    }
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-[#12121f]">
      {/* Top Bar: minimal toolbar */}
      <LensToolbar
        activeLens={activeLens}
        onLensChange={setActiveLens}
        selectedOntologyId={selectedOntologyId}
        selectedOntologyName={ontologyName ?? undefined}
      />

      <div className="flex-1 flex overflow-hidden">
        {/* Left: Asset Explorer */}
        <aside
          style={{ width: assetExplorerWidth }}
          className="border-r border-gray-800 flex-shrink-0 overflow-hidden bg-[#16162a]"
        >
          <AssetExplorer
            onSelectOntology={handleSelectOntology}
            onSelectDocument={handleSelectDocument}
            onSelectRun={handleSelectRun}
            selectedOntologyId={selectedOntologyId}
            onContextMenu={handleAssetContextMenu}
          />
        </aside>

        {/* Resize handle */}
        <div
          className="w-1 cursor-col-resize hover:bg-indigo-500 active:bg-indigo-400 transition-colors flex-shrink-0"
          onMouseDown={handleResizeStart}
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize asset explorer"
        />

        {/* Center: Canvas + VCR — min-h-0 lets the flex child shrink so Sigma gets a real height */}
        <main className="flex-1 flex flex-col relative min-w-0 min-h-0">
          {/* Graph Canvas area */}
          <div className="flex-1 relative overflow-hidden min-h-0">
            {selectedOntologyId ? (
              graphLoading ? (
                <div className="h-full flex flex-col items-center justify-center gap-3 bg-[#111118]">
                  <div className="animate-spin h-10 w-10 border-3 border-indigo-400 border-t-transparent rounded-full" />
                  <p className="text-sm text-gray-400">
                    Loading {ontologyName ?? selectedOntologyId}…
                  </p>
                </div>
              ) : graphError ? (
                <div className="h-full flex flex-col items-center justify-center gap-3 text-center px-8 bg-[#111118]">
                  <div className="w-12 h-12 rounded-full bg-red-900/30 flex items-center justify-center">
                    <svg className="w-6 h-6 text-red-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                    </svg>
                  </div>
                  <p className="text-sm text-red-400 font-medium">{graphError}</p>
                  <button
                    onClick={() => selectedOntologyId && fetchGraphData(selectedOntologyId)}
                    className="text-xs text-indigo-400 hover:text-indigo-300 underline"
                  >
                    Retry
                  </button>
                </div>
              ) : (
                <SigmaCanvas
                  classes={classes}
                  edges={edges}
                  activeLens={activeLens}
                  onNodeSelect={handleNodeSelect}
                  onEdgeSelect={handleEdgeSelect}
                  onContextMenu={handleSigmaContextMenu}
                  onViewportApi={handleViewportApi}
                  visibleNodeKeys={timelineVisibleKeys}
                />
              )
            ) : (
              <EmptyCanvasState />
            )}

            {/* Floating detail panel */}
            {detailPanelOpen && selectedNodeKey && selectedOntologyId && (
              <FloatingDetailPanel
                entityType="class"
                entityKey={selectedNodeKey}
                ontologyId={selectedOntologyId}
                onClose={() => setDetailPanelOpen(false)}
              />
            )}

            {detailPanelOpen && selectedEdgeKey && selectedOntologyId && !selectedNodeKey && (
              <FloatingDetailPanel
                entityType="edge"
                entityKey={selectedEdgeKey}
                ontologyId={selectedOntologyId}
                onClose={() => setDetailPanelOpen(false)}
              />
            )}

            {/* Asset info panel (left-click on document / run) */}
            {infoPanelItem && (
              <AssetInfoPanel
                type={infoPanelItem.type}
                data={infoPanelItem.data}
                onClose={() => setInfoPanelItem(null)}
                onOpenOntology={(key) => {
                  setInfoPanelItem(null);
                  handleSelectOntology(key);
                }}
              />
            )}
          </div>

          {/* Bottom: VCR Timeline */}
          {selectedOntologyId && (
            <div className="h-auto min-h-[56px] border-t border-gray-800 bg-[#16162a] px-4 py-2 flex-shrink-0">
              <VCRTimeline
                ontologyId={selectedOntologyId}
                onVisibleEntitiesChange={setTimelineVisibleKeys}
              />
            </div>
          )}
        </main>
      </div>

      {/* Global context menu */}
      {contextMenu && (
        <ContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          items={getContextMenuItems()}
          onClose={closeContextMenu}
        />
      )}
    </div>
  );
}

/* ── Asset info panel (left-click detail overlay) ───── */

function AssetInfoPanel({
  type,
  data,
  onClose,
  onOpenOntology,
}: {
  type: "document" | "ontology" | "run";
  data: Record<string, unknown>;
  onClose: () => void;
  onOpenOntology: (key: string) => void;
}) {
  const titleMap: Record<string, string> = {
    document: "Document",
    ontology: "Ontology",
    run: "Pipeline Run",
  };

  const rows: { label: string; value: string | number | undefined }[] = [];

  if (type === "document") {
    rows.push(
      { label: "Filename", value: data.filename as string },
      { label: "MIME Type", value: data.mime_type as string },
      { label: "Chunks", value: data.chunk_count as number },
      { label: "Status", value: data.status as string },
      { label: "Uploaded", value: data.upload_date as string },
    );
  } else if (type === "ontology") {
    rows.push(
      { label: "Name", value: data.name as string },
      { label: "Description", value: data.description as string },
      { label: "Status", value: data.status as string },
      { label: "Classes", value: data.class_count as number },
      { label: "Properties", value: data.property_count as number },
      { label: "Edges", value: data.edge_count as number },
      { label: "Health Score", value: data.health_score != null ? `${Math.round((data.health_score as number) * 100)}%` : undefined },
      { label: "Created", value: data.created_at as string },
    );
  } else if (type === "run") {
    const stats = (data.stats ?? {}) as Record<string, unknown>;
    const startedAt = data.started_at as number | undefined;
    const completedAt = data.completed_at as number | undefined;
    const duration = startedAt && completedAt
      ? `${Math.round(((completedAt as number) - (startedAt as number)))}s`
      : data.duration_ms != null
        ? `${Math.round((data.duration_ms as number) / 1000)}s`
        : undefined;
    const tokenUsage = stats.token_usage as Record<string, number> | undefined;
    const totalTokens = tokenUsage
      ? (tokenUsage.prompt_tokens ?? 0) + (tokenUsage.completion_tokens ?? 0)
      : undefined;

    rows.push(
      { label: "Document", value: data.document_name as string ?? (data.doc_id as string) },
      { label: "Status", value: data.status as string },
      { label: "Model", value: data.model as string },
      { label: "Duration", value: duration },
      { label: "Classes Extracted", value: data.classes_extracted as number ?? stats.classes_extracted as number },
      { label: "Properties Extracted", value: data.properties_extracted as number ?? stats.properties_extracted as number },
      { label: "Total Tokens", value: totalTokens },
      { label: "Estimated Cost", value: stats.estimated_cost != null ? `$${(stats.estimated_cost as number).toFixed(4)}` : undefined },
      { label: "Agreement Rate", value: stats.pass_agreement_rate != null ? `${((stats.pass_agreement_rate as number) * 100).toFixed(1)}%` : undefined },
    );
  }

  const filteredRows = rows.filter((r) => r.value != null && r.value !== "");

  return (
    <div
      className="absolute top-4 right-4 w-[360px] max-h-[70vh] bg-white rounded-xl border border-gray-200 shadow-xl overflow-hidden flex flex-col z-50"
      role="dialog"
      aria-label={`${titleMap[type]} info panel`}
    >
      <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100 flex-shrink-0">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-600 font-medium flex-shrink-0">
            {titleMap[type]}
          </span>
          <span className="text-sm font-semibold text-gray-800 truncate">
            {(data.name ?? data.filename ?? data.document_name ?? data._key) as string}
          </span>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 text-lg leading-none ml-2 flex-shrink-0"
          aria-label="Close info panel"
        >
          &times;
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {filteredRows.map((row) => (
          <div key={row.label}>
            <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-0.5">
              {row.label}
            </dt>
            <dd className="text-sm text-gray-700">{String(row.value)}</dd>
          </div>
        ))}
      </div>

      {type === "ontology" && typeof data._key === "string" && (
        <div className="px-4 py-3 border-t border-gray-100 flex-shrink-0">
          <button
            onClick={() => onOpenOntology(data._key as string)}
            className="w-full px-3 py-1.5 text-xs font-medium bg-blue-50 text-blue-700 rounded-md hover:bg-blue-100 transition-colors"
          >
            Open in Canvas
          </button>
        </div>
      )}

      {type === "run" && typeof data.ontology_id === "string" && (
        <div className="px-4 py-3 border-t border-gray-100 flex-shrink-0">
          <button
            onClick={() => onOpenOntology(data.ontology_id as string)}
            className="w-full px-3 py-1.5 text-xs font-medium bg-blue-50 text-blue-700 rounded-md hover:bg-blue-100 transition-colors"
          >
            Open Ontology
          </button>
        </div>
      )}

      {type === "document" && typeof data._key === "string" && (
        <DocumentContentSection docKey={data._key as string} />
      )}
    </div>
  );
}

function DocumentContentSection({ docKey }: { docKey: string }) {
  const [chunks, setChunks] = useState<{ _key: string; text: string; page?: number }[]>([]);
  const [loading, setLoading] = useState(false);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    if (!expanded) return;
    let cancelled = false;
    setLoading(true);
    api
      .get<{ data: { _key: string; text: string; page?: number }[] }>(
        `/api/v1/documents/${docKey}/chunks`,
      )
      .then((res) => {
        if (!cancelled) {
          const list = Array.isArray(res) ? res : res.data;
          setChunks(Array.isArray(list) ? list : []);
        }
      })
      .catch(() => {
        if (!cancelled) setChunks([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [docKey, expanded]);

  return (
    <div className="border-t border-gray-100">
      <button
        onClick={() => setExpanded((v) => !v)}
        className="w-full px-4 py-2.5 text-xs font-medium text-blue-700 bg-blue-50 hover:bg-blue-100 transition-colors flex items-center gap-1"
      >
        <span>{expanded ? "▼" : "▶"}</span>
        <span>View Document Content ({chunks.length || "…"})</span>
      </button>
      {expanded && (
        <div className="max-h-[300px] overflow-y-auto px-4 py-2 space-y-2">
          {loading && (
            <p className="text-xs text-gray-400 animate-pulse py-2">Loading chunks...</p>
          )}
          {!loading && chunks.length === 0 && (
            <p className="text-xs text-gray-400 italic py-2">No chunks found</p>
          )}
          {chunks.map((chunk, idx) => (
            <div
              key={chunk._key ?? idx}
              className="text-xs text-gray-600 bg-gray-50 rounded-md p-2 border border-gray-100"
            >
              {chunk.page != null && (
                <span className="text-[10px] text-gray-400 font-medium mr-1">
                  p.{chunk.page}
                </span>
              )}
              <span className="whitespace-pre-wrap break-words">
                {chunk.text.length > 500
                  ? chunk.text.slice(0, 500) + "…"
                  : chunk.text}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
