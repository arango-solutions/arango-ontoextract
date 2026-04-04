"use client";

import { useState, useCallback, useEffect, useRef } from "react";
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

const SigmaCanvas = dynamic(() => import("@/components/workspace/SigmaCanvas"), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center bg-[#1a1a2e]">
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

  const resizingRef = useRef(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(DEFAULT_PANEL_WIDTH);

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
    setSelectedOntologyId(ontologyId);
    setSelectedNodeKey(null);
    setSelectedEdgeKey(null);
    setDetailPanelOpen(false);
    setGraphError(null);
  }, []);

  const handleNodeSelect = useCallback((classKey: string) => {
    setSelectedNodeKey(classKey);
    setSelectedEdgeKey(null);
    setDetailPanelOpen(true);
  }, []);

  const handleEdgeSelect = useCallback((edgeKey: string) => {
    setSelectedEdgeKey(edgeKey);
    setSelectedNodeKey(null);
  }, []);

  const handleSelectDocument = useCallback((_docId: string) => {
    // Future: show document in a panel or trigger extraction
  }, []);

  const handleSelectRun = useCallback((_runId: string) => {
    // Future: show run details in overlay
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

  function triggerRelayout() {
    const fn = (window as unknown as Record<string, unknown>).__sigmaRelayout;
    if (typeof fn === "function") (fn as () => void)();
  }

  function getContextMenuItems(): ContextMenuItem[] {
    if (!contextMenu) return [];

    const { type, data } = contextMenu;

    switch (type) {
      case "class":
        return [
          { label: "Edit Metadata", icon: "✏️", onClick: () => {} },
          { label: "Approve", icon: "✅", onClick: () => {} },
          { label: "Reject", icon: "❌", onClick: () => {} },
          { label: "separator", separator: true },
          { label: "Create Relationship", icon: "🔗", onClick: () => {} },
          { label: "Merge", icon: "🔀", onClick: () => {} },
          { label: "separator2", separator: true },
          { label: "View History", icon: "📜", onClick: () => {} },
          { label: "View Provenance", icon: "🔍", onClick: () => {} },
          { label: "separator3", separator: true },
          { label: "Delete", icon: "🗑️", onClick: () => {}, danger: true },
        ];
      case "edge":
        return [
          { label: "Change Type", icon: "🔄", onClick: () => {} },
          { label: "Reverse Direction", icon: "↔️", onClick: () => {} },
          { label: "Approve", icon: "✅", onClick: () => {} },
          { label: "separator", separator: true },
          { label: "Delete", icon: "🗑️", onClick: () => {}, danger: true },
        ];
      case "document":
        return [
          { label: "Extract to New Ontology", icon: "🔷", onClick: () => {} },
          { label: "Extract to Selected Ontology", icon: "➕", onClick: () => {}, disabled: !selectedOntologyId },
          { label: "View Chunks", icon: "📋", onClick: () => {} },
          { label: "Rename", icon: "✏️", onClick: () => {} },
          { label: "Delete", icon: "🗑️", onClick: () => {}, danger: true },
        ];
      case "ontology":
        return [
          { label: "Open in Canvas", icon: "🔷", onClick: () => handleSelectOntology(data._key as string) },
          { label: "Edit Metadata", icon: "✏️", onClick: () => {} },
          { label: "Export", icon: "📤", onClick: () => {} },
          { label: "Add Document", icon: "📄", onClick: () => {} },
          { label: "View Quality", icon: "📊", onClick: () => {} },
          { label: "Delete", icon: "🗑️", onClick: () => {}, danger: true },
        ];
      case "run":
        return [
          { label: "View Details", icon: "🔍", onClick: () => {} },
          { label: "Open Ontology", icon: "🔷", onClick: () => {}, disabled: !data.ontology_id },
          { label: "Retry Run", icon: "🔄", onClick: () => {} },
        ];
      case "canvas":
        return [
          { label: "Add New Class", icon: "➕", onClick: () => {} },
          { label: "Import Document", icon: "📄", onClick: () => {} },
          { label: "separator1", separator: true },
          {
            label: "View As",
            icon: "👁",
            submenu: LENS_OPTIONS.map((opt) => ({
              label: opt.label,
              checked: activeLens === opt.id,
              onClick: () => setActiveLens(opt.id),
            })),
          },
          { label: "separator2", separator: true },
          { label: "Fit All Nodes", icon: "⬜", onClick: () => {} },
          { label: "Re-layout (ForceAtlas2)", icon: "🔄", onClick: triggerRelayout },
          { label: "Center View", icon: "🎯", onClick: () => {} },
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
                <div className="h-full flex flex-col items-center justify-center gap-3 bg-[#1a1a2e]">
                  <div className="animate-spin h-10 w-10 border-3 border-indigo-400 border-t-transparent rounded-full" />
                  <p className="text-sm text-gray-400">
                    Loading {ontologyName ?? selectedOntologyId}…
                  </p>
                </div>
              ) : graphError ? (
                <div className="h-full flex flex-col items-center justify-center gap-3 text-center px-8 bg-[#1a1a2e]">
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
          </div>

          {/* Bottom: VCR Timeline */}
          {selectedOntologyId && (
            <div className="h-auto min-h-[56px] border-t border-gray-800 bg-[#16162a] px-4 py-2 flex-shrink-0">
              <VCRTimeline ontologyId={selectedOntologyId} />
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
