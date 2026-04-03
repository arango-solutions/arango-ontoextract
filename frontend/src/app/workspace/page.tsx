"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import LensToolbar, { type LensType } from "@/components/workspace/LensToolbar";
import AssetExplorer from "@/components/workspace/AssetExplorer";
import EmptyCanvasState from "@/components/workspace/EmptyCanvasState";
import FloatingDetailPanel from "@/components/workspace/FloatingDetailPanel";
import ContextMenu, { type ContextMenuItem } from "@/components/workspace/ContextMenu";
import VCRTimeline from "@/components/timeline/VCRTimeline";
import { api, type PaginatedResponse } from "@/lib/api-client";
import type { OntologyRegistryEntry } from "@/types/curation";

interface ContextMenuState {
  x: number;
  y: number;
  type: string;
  data: Record<string, unknown>;
}

const MIN_PANEL_WIDTH = 200;
const MAX_PANEL_WIDTH = 480;
const DEFAULT_PANEL_WIDTH = 280;

export default function WorkspacePage() {
  const [selectedOntologyId, setSelectedOntologyId] = useState<string | null>(null);
  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const [selectedEdgeKey, setSelectedEdgeKey] = useState<string | null>(null);
  const [assetExplorerWidth, setAssetExplorerWidth] = useState(DEFAULT_PANEL_WIDTH);
  const [detailPanelOpen, setDetailPanelOpen] = useState(false);
  const [activeLens, setActiveLens] = useState<LensType>("semantic");
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [ontologyName, setOntologyName] = useState<string | null>(null);

  const resizingRef = useRef(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(DEFAULT_PANEL_WIDTH);

  // Fetch ontology name when selection changes
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

  // Keyboard shortcuts for lens switching
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

  // Resize drag handlers
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
  }, []);

  const handleSelectDocument = useCallback((_docId: string) => {
    // Future: show document in a panel or trigger extraction
  }, []);

  const handleSelectRun = useCallback((_runId: string) => {
    // Future: show run details in overlay
  }, []);

  const handleContextMenu = useCallback(
    (e: React.MouseEvent, type: string, data: unknown) => {
      e.preventDefault();
      setContextMenu({ x: e.clientX, y: e.clientY, type, data: data as Record<string, unknown> });
    },
    [],
  );

  const handleCanvasContextMenu = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      setContextMenu({ x: e.clientX, y: e.clientY, type: "canvas", data: {} });
    },
    [],
  );

  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  function getContextMenuItems(): ContextMenuItem[] {
    if (!contextMenu) return [];

    const { type, data } = contextMenu;

    switch (type) {
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
          { label: "Add Document", icon: "📄", onClick: () => {} },
          { label: "Center View", icon: "🎯", onClick: () => {} },
          { label: "Fit All", icon: "⬜", onClick: () => {} },
        ];
      default:
        return [];
    }
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-gray-50">
      {/* Top Bar: Lens toolbar */}
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
          className="border-r border-gray-200 flex-shrink-0 overflow-hidden"
        >
          <AssetExplorer
            onSelectOntology={handleSelectOntology}
            onSelectDocument={handleSelectDocument}
            onSelectRun={handleSelectRun}
            selectedOntologyId={selectedOntologyId}
            onContextMenu={handleContextMenu}
          />
        </aside>

        {/* Resize handle */}
        <div
          className="w-1 cursor-col-resize hover:bg-blue-400 active:bg-blue-500 transition-colors flex-shrink-0"
          onMouseDown={handleResizeStart}
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize asset explorer"
        />

        {/* Center: Canvas + VCR */}
        <main className="flex-1 flex flex-col relative min-w-0">
          {/* Graph Canvas area */}
          <div
            className="flex-1 relative overflow-hidden"
            onContextMenu={selectedOntologyId ? handleCanvasContextMenu : undefined}
          >
            {selectedOntologyId ? (
              <div className="h-full flex items-center justify-center text-sm text-gray-400">
                <div className="text-center">
                  <div className="w-16 h-16 mx-auto mb-4 rounded-full bg-blue-50 flex items-center justify-center">
                    <svg className="w-8 h-8 text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={1.5}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 14.25v2.25m3-4.5v4.5m3-6.75v6.75m3-9v9M6 20.25h12A2.25 2.25 0 0020.25 18V6A2.25 2.25 0 0018 3.75H6A2.25 2.25 0 003.75 6v12A2.25 2.25 0 006 20.25z" />
                    </svg>
                  </div>
                  <p className="font-medium text-gray-600 mb-1">
                    Canvas: {ontologyName ?? selectedOntologyId}
                  </p>
                  <p className="text-xs text-gray-400">
                    Lens: <span className="capitalize">{activeLens}</span>
                  </p>
                  <p className="text-xs text-gray-300 mt-2">
                    Graph visualization will render here
                  </p>
                </div>
              </div>
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
            <div className="h-auto min-h-[56px] border-t border-gray-200 bg-white px-4 py-2 flex-shrink-0">
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
