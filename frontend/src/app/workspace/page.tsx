"use client";

import { useState, useCallback, useEffect, useRef, useMemo, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import LensToolbar, { type LensType } from "@/components/workspace/LensToolbar";
import AssetExplorer from "@/components/workspace/AssetExplorer";
import OntologyRenameDialog from "@/components/workspace/OntologyRenameDialog";
import OntologyReleaseDialog from "@/components/workspace/OntologyReleaseDialog";
import CreateOntologyDialog from "@/components/workspace/CreateOntologyDialog";
import CatalogBrowserOverlay from "@/components/workspace/CatalogBrowserOverlay";
import ImportsDependencyOverlay from "@/components/workspace/ImportsDependencyOverlay";
import ConfirmDialog from "@/components/workspace/ConfirmDialog";
import OntologyDeleteDialog from "@/components/workspace/OntologyDeleteDialog";
import ManageImportsOverlay from "@/components/workspace/ManageImportsOverlay";
import RevisionsInboxOverlay from "@/components/workspace/RevisionsInboxOverlay";
import MergeCandidatesOverlay from "@/components/workspace/MergeCandidatesOverlay";
import FeedbackLearningOverlay from "@/components/workspace/FeedbackLearningOverlay";
import CanvasLensLegend from "@/components/workspace/CanvasLensLegend";
import ToastHost from "@/components/workspace/ToastHost";
import EmptyCanvasState from "@/components/workspace/EmptyCanvasState";
import FloatingDetailPanel from "@/components/workspace/FloatingDetailPanel";
import ContextMenu, { type ContextMenuItem } from "@/components/workspace/ContextMenu";
import {
  CONTEXT_MENU_BUILDERS,
  type WorkspaceContextMenuActions,
  type ConfirmRequest,
} from "@/components/workspace/contextMenus";
import { api, ApiError, type PaginatedResponse } from "@/lib/api-client";
import {
  fetchOntologyData,
  invalidateOntology,
  invalidateOntologyKind,
} from "@/lib/ontologyDataCache";
import { withBasePath } from "@/lib/base-path";
import {
  buildQualityReportMetrics,
  formatOntologyHealthSummary,
} from "@/lib/qualityReportDisplay";
import type { StepStatus } from "@/types/pipeline";
import type { AgentDAGApi } from "@/components/pipeline/AgentDAG";
import { filterStepsByTimestamp } from "@/lib/filterStepsByTimestamp";
import { buildStepTimelineEvents } from "@/lib/buildStepTimelineEvents";
import { backendUrl } from "@/lib/api-client";
import type {
  OntologyRegistryEntry,
  OntologyClass,
  OntologyProperty,
  OntologyEdge,
  EffectiveOntologyResponse,
  EffectiveSource,
} from "@/types/curation";
import {
  checkImportDragCandidate,
  readImportDragPayload,
} from "@/lib/importDragCheck";
import { pushToast } from "@/lib/toast";
import { computeNextSidebarRow } from "@/lib/sidebarKeyboardNav";
import type { SigmaViewportApi } from "@/components/workspace/SigmaCanvas";
import type { ClassBoxProperty } from "@/components/workspace/ClassBoxNode";

export type GraphViewMode = "network" | "box-arrow";
import PanelDragGrip from "@/components/workspace/PanelDragGrip";
import {
  splitTextByKeywordAlternation,
  termsFromEntityLabel,
} from "@/lib/textHighlight";
import { useDraggablePanel } from "@/hooks/useDraggablePanel";
import type { PerOntologyQualityApiShape } from "@/lib/perOntologyQualityDimensions";

const QualityReportOverlay = dynamic(
  () => import("@/components/dashboard/QualityReportOverlay"),
  { ssr: false },
);

const EdgeRepairOverlay = dynamic(
  () => import("@/components/workspace/EdgeRepairOverlay"),
  { ssr: false },
);

const SigmaCanvas = dynamic(() => import("@/components/workspace/SigmaCanvas"), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center bg-[#111118]">
      <div className="animate-spin h-8 w-8 border-2 border-indigo-400 border-t-transparent rounded-full" />
    </div>
  ),
});

const BoxArrowCanvas = dynamic(() => import("@/components/workspace/BoxArrowCanvas"), {
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

const ConfidenceThresholdSlider = dynamic(
  () => import("@/components/workspace/ConfidenceThresholdSlider"),
  { ssr: false },
);

const AgentDAG = dynamic(() => import("@/components/pipeline/AgentDAG"), {
  ssr: false,
  loading: () => (
    <div className="h-full flex items-center justify-center text-gray-400 animate-pulse">
      Loading pipeline graph…
    </div>
  ),
});

const RunMetrics = dynamic(() => import("@/components/pipeline/RunMetrics"), {
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
  const [graphViewMode, setGraphViewMode] = useState<GraphViewMode>("network");
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null);
  const [ontologyName, setOntologyName] = useState<string | null>(null);
  const [ontologyTier, setOntologyTier] = useState<"domain" | "local" | null>(null);
  const [explorerLibraryNonce, setExplorerLibraryNonce] = useState(0);
  const [renameOntology, setRenameOntology] = useState<{
    key: string;
    name: string;
    description: string;
  } | null>(null);
  const [releaseOntology, setReleaseOntology] = useState<{
    key: string;
    currentReleaseVersion?: string | null;
  } | null>(null);
  const [showCreateOntology, setShowCreateOntology] = useState(false);
  const [showCatalogBrowser, setShowCatalogBrowser] = useState(false);
  const [dependencyOverlay, setDependencyOverlay] = useState<{
    key: string;
    name: string;
  } | null>(null);
  const [manageImports, setManageImports] = useState<{
    key: string;
    name: string;
  } | null>(null);
  const [feedbackLearning, setFeedbackLearning] = useState<{
    ontologyId?: string | null;
    ontologyName?: string | null;
  } | null>(null);
  const [edgeRepair, setEdgeRepair] = useState<{
    key: string;
    name: string;
  } | null>(null);
  const [revisionsInbox, setRevisionsInbox] = useState<{
    key: string;
    name: string;
  } | null>(null);
  // Stream 2 PR 1: ER merge-candidates overlay state. Opened from the
  // canvas context menu's "Find Duplicates…" action; the overlay
  // itself triggers the ER run and lists candidate pairs for
  // accept/reject. Same per-ontology gating as ``revisionsInbox`` --
  // ER has nothing to run on without an open ontology.
  const [mergeCandidates, setMergeCandidates] = useState<{
    key: string;
    name: string;
  } | null>(null);
  // H.4: typed-name + cascade-impact dialog for ontology deletion. The
  // context-menu builder requests this via ``actions.setOntologyDelete``;
  // the dialog itself fetches the impact analysis and calls
  // ``deleteOntology`` only after the typed-name gate is satisfied.
  const [ontologyDelete, setOntologyDelete] = useState<{
    key: string;
    name: string;
  } | null>(null);

  // Outstanding ConfirmDialog request, populated by builders via
  // ``requestConfirm``. ``null`` means no dialog is open. Per
  // ``ui-architecture.mdc`` §18 this surface replaces every ``window.confirm``
  // in the workspace.
  const [pendingConfirm, setPendingConfirm] = useState<ConfirmRequest | null>(null);
  const requestConfirm = useCallback((request: ConfirmRequest) => {
    setPendingConfirm(request);
  }, []);

  const [classes, setClasses] = useState<OntologyClass[]>([]);
  const [properties, setProperties] = useState<OntologyProperty[]>([]);
  const [edges, setEdges] = useState<OntologyEdge[]>([]);
  // Stream 1 H.16: effective-graph sources for the open ontology (self
  // + transitive imports closure). Drives the drag-and-drop import
  // pre-check ("Already imported" rejection without a round-trip).
  // Cleared when the user closes the canvas; refreshed every time
  // ``fetchGraphData`` resolves a fresh ``/effective`` payload.
  const [effectiveSources, setEffectiveSources] = useState<EffectiveSource[]>([]);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [timelineVisibleKeys, setTimelineVisibleKeys] = useState<Set<string> | null>(null);
  // Confidence-threshold slider state. Both axes default to ``null`` ("no
  // filter"); each becomes a ``Set`` only when the slider is dragged above
  // 0% in the Confidence lens. The page intersects the class set with
  // ``timelineVisibleKeys`` below so timeline + threshold compose, and the
  // edge set is forwarded directly to ``SigmaCanvas.visibleEdgeKeys``.
  const [confidenceVisibleClasses, setConfidenceVisibleClasses] = useState<
    Set<string> | null
  >(null);
  const [confidenceVisibleEdges, setConfidenceVisibleEdges] = useState<
    Set<string> | null
  >(null);

  /** Class-key visibility merged across every active filter (currently:
   *  VCR timeline ∩ confidence threshold). ``null`` means "no filter
   *  active" so ``SigmaCanvas`` can skip the reducer entirely. */
  const mergedVisibleNodeKeys = useMemo<Set<string> | null>(() => {
    if (timelineVisibleKeys == null && confidenceVisibleClasses == null) {
      return null;
    }
    if (timelineVisibleKeys == null) return confidenceVisibleClasses;
    if (confidenceVisibleClasses == null) return timelineVisibleKeys;
    const out = new Set<string>();
    for (const k of timelineVisibleKeys) {
      if (confidenceVisibleClasses.has(k)) out.add(k);
    }
    return out;
  }, [timelineVisibleKeys, confidenceVisibleClasses]);

  const [pipelineRunId, setPipelineRunId] = useState<string | null>(null);
  const [pipelineSteps, setPipelineSteps] = useState<Map<string, StepStatus>>(new Map());
  const [vcrTimestamp, setVcrTimestamp] = useState<number | null>(null);

  const stepTimelineEvents = useMemo(
    () => (pipelineRunId ? buildStepTimelineEvents(pipelineSteps) : []),
    [pipelineRunId, pipelineSteps],
  );

  useEffect(() => {
    if (!pipelineRunId) {
      setPipelineSteps(new Map());
      return;
    }
    let cancelled = false;

    const FRONTEND_STEPS = [
      "strategy_selector", "extraction_agent", "consistency_checker",
      "quality_judge", "entity_resolution_agent", "pre_curation_filter",
    ];
    const BACKEND_TO_FRONTEND: Record<string, string> = {
      strategy_selector: "strategy_selector",
      extractor: "extraction_agent",
      consistency_checker: "consistency_checker",
      quality_judge: "quality_judge",
      er_agent: "entity_resolution_agent",
      filter: "pre_curation_filter",
    };

    async function load() {
      try {
        const res = await fetch(backendUrl(`/api/v1/extraction/runs/${pipelineRunId}`));
        if (!res.ok || cancelled) return;
        const run = await res.json();

        if (run.ontology_id && !cancelled) {
          setSelectedOntologyId((prev) => prev ?? run.ontology_id);
        }

        const stepLogs: { step: string; status: string; started_at?: number; completed_at?: number; error?: string | null; metadata?: Record<string, unknown> }[] =
          run?.stats?.step_logs ?? [];

        const map = new Map<string, StepStatus>();
        for (const s of FRONTEND_STEPS) {
          map.set(s, { status: "pending" });
        }

        for (const log of stepLogs) {
          const key = BACKEND_TO_FRONTEND[log.step] ?? log.step;
          if (!map.has(key)) continue;
          const status = log.status === "completed" || log.status === "skipped"
            ? "completed"
            : log.status === "failed" ? "failed"
            : log.status === "running" ? "running"
            : "pending";
          const duration = log.started_at && log.completed_at
            ? Math.round((log.completed_at - log.started_at) * 1000)
            : undefined;
          map.set(key, {
            status: status as StepStatus["status"],
            startedAt: log.started_at ? new Date(log.started_at * 1000).toISOString() : undefined,
            completedAt: log.completed_at ? new Date(log.completed_at * 1000).toISOString() : undefined,
            error: log.error ?? undefined,
            data: { ...log.metadata, duration_ms: duration },
          });
        }

        if (!cancelled) setPipelineSteps(map);
      } catch {
        // silent — metrics panel will show error if needed
      }
    }

    load();
    return () => { cancelled = true; };
  }, [pipelineRunId]);

  const resizingRef = useRef(false);
  const startXRef = useRef(0);
  const startWidthRef = useRef(DEFAULT_PANEL_WIDTH);
  const viewportApiRef = useRef<SigmaViewportApi | null>(null);
  const dagApiRef = useRef<AgentDAGApi | null>(null);
  const didReadUrlParam = useRef(false);

  useEffect(() => {
    if (didReadUrlParam.current) return;
    didReadUrlParam.current = true;
    const ontologyParam = searchParams.get("ontologyId");
    if (ontologyParam && !selectedOntologyId) {
      setSelectedOntologyId(ontologyParam);
    }
    // H.7 deep-link: ``/workspace?ontologyId=X&overlay=dependencies``
    // auto-opens the imports dependency overlay. Used by the library
    // aside ("Dependencies" link) so users go straight from the
    // legacy library page into the workspace overlay.
    const overlayParam = searchParams.get("overlay");
    if (overlayParam === "dependencies" && ontologyParam) {
      setDependencyOverlay({ key: ontologyParam, name: ontologyParam });
    }
  }, [searchParams, selectedOntologyId]);

  const handleViewportApi = useCallback((api: SigmaViewportApi | null) => {
    viewportApiRef.current = api;
  }, []);

  useEffect(() => {
    if (!selectedOntologyId) {
      setOntologyName(null);
      setOntologyTier(null);
      return;
    }

    let cancelled = false;
    async function loadName() {
      try {
        const res = await api.get<PaginatedResponse<OntologyRegistryEntry>>(
          "/api/v1/ontology/library",
        );
        const match = res.data.find((o) => o._key === selectedOntologyId);
        if (!cancelled) {
          if (match) {
            const display =
              (match.name?.trim() || match.label?.trim() || match._key).trim();
            setOntologyName(display);
            setOntologyTier(match.tier ?? null);
          } else {
            setOntologyTier(null);
          }
        }
      } catch {
        // non-critical — fall back to ID display
      }
    }
    loadName();
    return () => { cancelled = true; };
  }, [selectedOntologyId, explorerLibraryNonce]);

  const fetchGraphData = useCallback(async (ontologyId: string) => {
    setGraphLoading(true);
    setGraphError(null);
    try {
      // Single round-trip to the effective-graph endpoint (Stream 1
      // H.12). When the ontology has no imports, the response is shaped
      // identically to ``/{id}/classes`` + ``/{id}/edges`` -- every
      // entity carries ``is_imported: false`` and ``source_ontology_id``
      // equal to the target. When the ontology DOES import others, the
      // canvas (H.15) reads the new annotation fields to render imported
      // entities with a dashed border + dimmed fill and to swap the
      // context menu to "Open Source Ontology" (no Approve/Reject/Delete
      // on entities the target ontology does not own).
      //
      // ?include=summary drops evidence[] / parent_evidence[] from the
      // wire response (same projection that ``/classes?include=summary``
      // uses), so the canvas-bound payload stays small even with imports
      // expanded. Detail panels and exports continue to fetch
      // ``?include=full`` via the single-item endpoints.
      //
      // fetchOntologyData wraps the request in a module-level cache
      // keyed on (ontologyId, "effective", "summary"). Selecting an
      // ontology we have already loaded in this session returns the
      // cached response synchronously. Mutations (approve / reject /
      // delete) call ``invalidateOntologyKind(_, "effective")`` (alongside
      // the existing ``classes`` / ``edges`` invalidations) so a future
      // selection refetches the server's authoritative view.
      const effectiveRes = await fetchOntologyData(
        ontologyId,
        "effective",
        "summary",
        () =>
          api.get<EffectiveOntologyResponse>(
            `/api/v1/ontology/${ontologyId}/effective?include=summary`,
          ),
      );
      setClasses(effectiveRes.classes ?? []);
      setEdges(effectiveRes.edges ?? []);
      setEffectiveSources(effectiveRes.sources ?? []);
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
      setEffectiveSources([]);
      setGraphError(null);
      setOntologyTier(null);
      return;
    }
    fetchGraphData(selectedOntologyId);
  }, [selectedOntologyId, fetchGraphData]);

  // Fetch properties when box-arrow mode is active
  useEffect(() => {
    if (graphViewMode !== "box-arrow" || !selectedOntologyId) {
      setProperties([]);
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        // Cached the same way as classes/edges -- toggling between
        // network and box-arrow views, or coming back to box-arrow
        // after switching ontologies, should not pay the WAN cost again.
        const res = await fetchOntologyData(
          selectedOntologyId,
          "properties",
          "full",
          () =>
            api.get<{ data: OntologyProperty[] }>(
              `/api/v1/ontology/${selectedOntologyId}/properties`,
            ),
        );
        if (cancelled) return;
        const list = Array.isArray(res) ? res : res.data;
        setProperties(list);
      } catch {
        if (!cancelled) setProperties([]);
      }
    })();
    return () => { cancelled = true; };
  }, [graphViewMode, selectedOntologyId]);

  const classPropertiesMap = useMemo<Record<string, ClassBoxProperty[]>>(() => {
    if (properties.length === 0) return {};

    const propByKey = new Map<string, OntologyProperty>();
    for (const prop of properties) {
      propByKey.set(prop._key, prop);
    }

    // Build property→class mapping from rdfs_domain edges
    // rdfs_domain: _from = property doc ID, _to = class doc ID
    const map: Record<string, ClassBoxProperty[]> = {};
    for (const edge of edges) {
      const edgeType = ((edge as unknown as Record<string, unknown>).edge_type ?? edge.type) as string;
      if (edgeType !== "rdfs_domain") continue;

      const propKey = edge._from.split("/").pop() ?? edge._from;
      const classKey = edge._to.split("/").pop() ?? edge._to;
      const prop = propByKey.get(propKey);
      if (!prop) continue;

      if (!map[classKey]) map[classKey] = [];
      if (map[classKey].some((p) => p._key === prop._key)) continue;
      map[classKey].push({
        _key: prop._key,
        label: prop.label,
        range_datatype: prop.range_type ?? (prop as unknown as Record<string, unknown>).range_datatype as string | undefined,
        status: prop.status,
      });
    }
    return map;
  }, [properties, edges]);

  /**
   * Whether the current canvas payload contains at least one entity
   * annotated as imported via the effective-graph endpoint (Stream 1
   * H.12 / H.15). The legend reads this to surface the "imported"
   * swatch row only when it is meaningful — for ontologies with no
   * imports, the row is suppressed so the legend stays compact.
   *
   * O(n+m) but cheap (each entity has one boolean field), and re-fires
   * only when ``classes`` / ``edges`` references swap (mutation-driven
   * via ``setClasses`` / ``setEdges``).
   */
  const canvasHasImported = useMemo(() => {
    for (const c of classes) {
      if (c.is_imported) return true;
    }
    for (const e of edges) {
      if (e.is_imported) return true;
    }
    return false;
  }, [classes, edges]);

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

      // W.7: Arrow Up/Down navigates between sidebar rows. Only
      // fires when focus is already on a `[data-sidebar-row]`
      // button so it never steals plain page scroll or canvas
      // navigation. Rows are tagged in AssetExplorer
      // (`class:<oid>:<key>` and `edge:<oid>:<key>`); the queryAll
      // preserves DOM order which matches the user's visual order
      // under the collapsible ontology accordions, including only
      // currently-rendered rows (collapsed ontologies skip
      // themselves). The pure decision lives in
      // `lib/sidebarKeyboardNav.ts` so the next-focus computation is
      // unit-testable in isolation.
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        const active = document.activeElement as HTMLElement | null;
        if (!active || !active.matches?.("[data-sidebar-row]")) return;
        const rows = Array.from(
          document.querySelectorAll<HTMLElement>("[data-sidebar-row]"),
        );
        const nextRow = computeNextSidebarRow(e.key, active, rows);
        if (nextRow) {
          e.preventDefault();
          nextRow.focus();
        }
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

  const handleSelectOntology = useCallback((ontologyId: string, displayName?: string) => {
    setSelectedNodeKey(null);
    setSelectedEdgeKey(null);
    setDetailPanelOpen(false);
    setGraphError(null);
    setInfoPanelItem(null);
    setPipelineRunId(null);
    if (ontologyId === selectedOntologyId) {
      fetchGraphData(ontologyId);
    } else {
      // Set the display name synchronously from the explorer's known label
      // so the loading spinner shows the right ontology immediately. The
      // background library fetch (in the loadName effect) still runs to
      // refresh tier and to handle cases where displayName is absent
      // (URL-param selection, run-completion auto-select). Without this,
      // the spinner displays the previously selected ontology's name for
      // the duration of the library round-trip -- the bug where switching
      // to "WTW Ontology" briefly read "Loading Best Practices in
      // Healthcare Survey Results Slides...".
      setOntologyName(displayName ?? null);
      setOntologyTier(null);
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

  const handleSelectClassFromSidebar = useCallback((classKey: string, _ontologyId: string) => {
    setSelectedNodeKey(classKey);
    setSelectedEdgeKey(null);
    setDetailPanelOpen(true);
    viewportApiRef.current?.focusNode(classKey);
  }, []);

  const handleSelectEdgeFromSidebar = useCallback((edgeKey: string, _ontologyId: string) => {
    setSelectedEdgeKey(edgeKey);
    setSelectedNodeKey(null);
    setDetailPanelOpen(true);
    viewportApiRef.current?.focusEdge(edgeKey);
  }, []);

  const [infoPanelItem, setInfoPanelItem] = useState<{
    type: "document" | "ontology" | "run";
    data: Record<string, unknown>;
  } | null>(null);

  const [qualityOverlay, setQualityOverlay] = useState<{
    name: string;
    data: PerOntologyQualityApiShape;
  } | null>(null);

  const handleSelectDocument = useCallback(async (docId: string) => {
    try {
      const doc = await api.get<Record<string, unknown>>(`/api/v1/documents/${docId}`);
      setInfoPanelItem({ type: "document", data: doc });
    } catch {
      setInfoPanelItem({ type: "document", data: { _key: docId } });
    }
  }, []);

  const handleSelectRun = useCallback((runId: string, ontologyId?: string) => {
    setPipelineRunId(runId);
    setVcrTimestamp(null);
    setInfoPanelItem(null);
    if (ontologyId && ontologyId !== selectedOntologyId) {
      // Clear the previous ontology's name so the canvas's loading
      // spinner falls back to the id rather than displaying the OLD
      // ontology's name while the library fetch resolves the new one.
      // Same race the explorer-click path used to hit; the run-card
      // click path doesn't have the displayName in scope so we fall
      // back to ``selectedOntologyId`` in the Loading text.
      setOntologyName(null);
      setOntologyTier(null);
      setSelectedOntologyId(ontologyId);
    }
  }, [selectedOntologyId]);

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

  const handleDagContextMenu = useCallback(
    (e: React.MouseEvent, type: "step" | "pipeline_canvas", data?: Record<string, unknown>) => {
      setContextMenu({ x: e.clientX, y: e.clientY, type, data: data ?? {} });
    },
    [],
  );

  const handleDagApi = useCallback((a: AgentDAGApi | null) => {
    dagApiRef.current = a;
  }, []);

  const deleteRun = useCallback(async (key: string) => {
    try {
      await api.del(`/api/v1/extraction/runs/${key}`);
      if (pipelineRunId === key) {
        setPipelineRunId(null);
      }
      // Deleting a run can change the live class/edge set for the
      // ontology that run produced. We do not have the run -> ontology
      // mapping in scope here, so invalidate the currently-selected
      // ontology if any (the most likely target of the user's interest)
      // -- if the run belonged to a different ontology, that one's
      // cache will rebuild on next visit.
      if (selectedOntologyId) invalidateOntology(selectedOntologyId);
    } catch (err) {
      console.error("Failed to delete run", err);
    }
  }, [pipelineRunId, selectedOntologyId]);

  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  const refreshGraph = useCallback(() => {
    if (!selectedOntologyId) return;
    // Force refresh: drop the cache for this ontology before refetching so
    // the user gets authoritative server data (the cache is the whole point
    // of the back-and-forth fast-path -- the refresh button explicitly
    // wants to bypass it).
    invalidateOntology(selectedOntologyId);
    fetchGraphData(selectedOntologyId);
  }, [selectedOntologyId, fetchGraphData]);

  /**
   * Stream 1 H.16: remove a single ``imports`` edge from the open
   * ontology and refresh the canvas. Used by both the undo affordance
   * on the "Imported …" success toast (so the user can revert a misclick
   * inside the toast lifetime) and by the per-entity "Remove Import"
   * context-menu entry on imported classes / edges. The backend
   * soft-deletes via temporal expiry, so a future "undo the undo" path
   * is technically possible — out of scope here, tracked as a follow-up
   * to the global undo-toast system.
   */
  const removeImportEdge = useCallback(
    async (importedOntologyId: string, importedOntologyName: string) => {
      if (!selectedOntologyId) return;
      try {
        await api.del(
          `/api/v1/ontology/${encodeURIComponent(selectedOntologyId)}/imports/${encodeURIComponent(importedOntologyId)}`,
        );
        invalidateOntology(selectedOntologyId);
        fetchGraphData(selectedOntologyId);
        // Bump the explorer's library nonce so the imports-graph DAG
        // overlay (H.7) and any other library-driven UI re-reads.
        setExplorerLibraryNonce((n) => n + 1);
        pushToast({
          message: `Removed import "${importedOntologyName}".`,
          kind: "success",
          durationMs: 4000,
        });
      } catch (err) {
        const message =
          err instanceof ApiError
            ? err.body.message
            : err instanceof Error
              ? err.message
              : "Failed to remove import";
        pushToast({
          message: `Could not remove "${importedOntologyName}": ${message}`,
          kind: "error",
        });
      }
    },
    [selectedOntologyId, fetchGraphData],
  );

  /**
   * Stream 1 H.16: add a new ``imports`` edge from the open ontology to
   * ``draggedOntologyId`` (the row the user dragged from the explorer).
   * The pre-check (``checkImportDragCandidate``) catches self-imports
   * and duplicates without a round-trip; cycle detection lives on the
   * backend (10-hop OUTBOUND BFS) and surfaces here as a 400.
   *
   * Success path emits an undo-toast that calls ``removeImportEdge`` —
   * matches ``ui-architecture.mdc`` §18 ("Reversible destructive:
   * undo-over-confirm is the default"; adding an import is the inverse
   * direction but the user-revert pattern is the same: act immediately,
   * give the user a one-click rollback before they have to dig into
   * Manage Imports).
   */
  const addImportEdge = useCallback(
    async (draggedOntologyId: string, draggedOntologyName: string) => {
      const precheck = checkImportDragCandidate({
        currentOntologyId: selectedOntologyId,
        draggedOntologyId,
        draggedOntologyName,
        effectiveSources,
      });
      if (!precheck.ok) {
        pushToast({
          message: precheck.message,
          kind: "warning",
          durationMs: 4000,
        });
        return;
      }
      if (!selectedOntologyId) return; // narrowed by pre-check; defensive.
      try {
        await api.post(
          `/api/v1/ontology/${encodeURIComponent(selectedOntologyId)}/imports`,
          { target_ontology_id: draggedOntologyId },
        );
        invalidateOntology(selectedOntologyId);
        fetchGraphData(selectedOntologyId);
        setExplorerLibraryNonce((n) => n + 1);
        // Capture identifiers in the closure so the undo button still
        // works after the user has moved on to another ontology.
        const undoTargetId = draggedOntologyId;
        const undoTargetName = draggedOntologyName;
        const undoSourceId = selectedOntologyId;
        const undoSourceName = ontologyName ?? selectedOntologyId;
        pushToast({
          message: `Imported "${draggedOntologyName}" into ${undoSourceName}.`,
          kind: "success",
          durationMs: 8000,
          action: {
            label: "Undo",
            onClick: async () => {
              try {
                await api.del(
                  `/api/v1/ontology/${encodeURIComponent(undoSourceId)}/imports/${encodeURIComponent(undoTargetId)}`,
                );
                invalidateOntology(undoSourceId);
                if (selectedOntologyId === undoSourceId) {
                  fetchGraphData(undoSourceId);
                }
                setExplorerLibraryNonce((n) => n + 1);
                pushToast({
                  message: `Undid import of "${undoTargetName}".`,
                  kind: "info",
                  durationMs: 3500,
                });
              } catch (err) {
                const message =
                  err instanceof ApiError
                    ? err.body.message
                    : err instanceof Error
                      ? err.message
                      : "Failed to undo import";
                pushToast({ message, kind: "error" });
              }
            },
          },
        });
      } catch (err) {
        const message =
          err instanceof ApiError
            ? err.body.message
            : err instanceof Error
              ? err.message
              : "Failed to add import";
        pushToast({
          message: `Could not import "${draggedOntologyName}": ${message}`,
          kind: "error",
        });
      }
    },
    [
      selectedOntologyId,
      effectiveSources,
      fetchGraphData,
      ontologyName,
    ],
  );

  /**
   * H.16 canvas drop handler. Bound to the ``<main>`` canvas wrapper so
   * any drop on the canvas pane (Sigma or box-arrow) registers — the
   * "drop anywhere" UX agreed in the H.16 design.
   *
   * We always ``preventDefault`` on ``dragover`` so the cursor advertises
   * a drop is possible (without that the browser refuses to fire
   * ``drop``). The ``drop`` handler reads the payload via
   * ``readImportDragPayload`` — returns ``null`` for any drag that did
   * not come from an ontology row (e.g. a browser-native file drag),
   * so unrelated drags fall through without a toast.
   */
  const handleCanvasDragOver = useCallback((e: React.DragEvent) => {
    if (!e.dataTransfer.types.includes("application/x-aoe-ontology")) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "copy";
  }, []);

  const handleCanvasDrop = useCallback(
    (e: React.DragEvent) => {
      const payload = readImportDragPayload(e.dataTransfer);
      if (!payload) return;
      e.preventDefault();
      void addImportEdge(payload.ontologyId, payload.ontologyName);
    },
    [addImportEdge],
  );

  const approveClass = useCallback(async (key: string) => {
    if (!selectedOntologyId) return;
    setClasses((prev) =>
      prev.map((c) =>
        c._key === key ? { ...c, status: "approved" as const } : c,
      ),
    );
    try {
      await api.put(`/api/v1/ontology/${selectedOntologyId}/classes/${key}`, { status: "approved" });
      // Drop the cached classes + effective entries so a future
      // ontology selection refetches the server's authoritative view
      // rather than serving the pre-mutation cached payload. Local
      // state already reflects the optimistic update, so no immediate
      // refetch is needed. ``effective`` is invalidated alongside
      // ``classes`` because the canvas now reads its payload from the
      // effective endpoint (Stream 1 H.12 / H.15).
      invalidateOntologyKind(selectedOntologyId, "classes");
      invalidateOntologyKind(selectedOntologyId, "effective");
    } catch (err) {
      console.error("Failed to approve class", err);
      // refreshGraph() invalidates and refetches -- correctly drops the
      // optimistic update if the server rejected it.
      refreshGraph();
    }
  }, [selectedOntologyId, refreshGraph]);

  const rejectClass = useCallback(async (key: string) => {
    if (!selectedOntologyId) return;
    setClasses((prev) =>
      prev.map((c) =>
        c._key === key ? { ...c, status: "rejected" as const } : c,
      ),
    );
    try {
      await api.put(`/api/v1/ontology/${selectedOntologyId}/classes/${key}`, { status: "rejected" });
      invalidateOntologyKind(selectedOntologyId, "classes");
      invalidateOntologyKind(selectedOntologyId, "effective");
    } catch (err) {
      console.error("Failed to reject class", err);
      refreshGraph();
    }
  }, [selectedOntologyId, refreshGraph]);

  const approveEdge = useCallback(async (key: string) => {
    if (!selectedOntologyId) return;
    setEdges((prev) =>
      prev.map((e) =>
        e._key === key ? { ...e, status: "approved" as const } : e,
      ),
    );
    try {
      await api.put(`/api/v1/ontology/${selectedOntologyId}/edges/${key}`, {
        status: "approved",
      });
      invalidateOntologyKind(selectedOntologyId, "edges");
      invalidateOntologyKind(selectedOntologyId, "effective");
    } catch (err) {
      console.error("Failed to approve edge", err);
      refreshGraph();
    }
  }, [selectedOntologyId, refreshGraph]);

  const rejectEdge = useCallback(async (key: string) => {
    if (!selectedOntologyId) return;
    setEdges((prev) =>
      prev.map((e) =>
        e._key === key ? { ...e, status: "rejected" as const } : e,
      ),
    );
    try {
      await api.put(`/api/v1/ontology/${selectedOntologyId}/edges/${key}`, {
        status: "rejected",
      });
      invalidateOntologyKind(selectedOntologyId, "edges");
      invalidateOntologyKind(selectedOntologyId, "effective");
    } catch (err) {
      console.error("Failed to reject edge", err);
      refreshGraph();
    }
  }, [selectedOntologyId, refreshGraph]);

  const approveProperty = useCallback(async (key: string, ontologyId?: string) => {
    const oid = ontologyId ?? selectedOntologyId;
    if (!oid) return;
    try {
      await api.put(`/api/v1/ontology/${oid}/properties/${key}`, { status: "approved" });
      invalidateOntologyKind(oid, "properties");
      // ``/effective`` carries properties[] too (Stream 1 H.12), so the
      // next consumer of the effective payload (canvas refresh, H.17
      // extraction context serializer) sees the curated status.
      invalidateOntologyKind(oid, "effective");
    } catch (err) {
      console.error("Failed to approve property", err);
    }
  }, [selectedOntologyId]);

  const rejectProperty = useCallback(async (key: string, ontologyId?: string) => {
    const oid = ontologyId ?? selectedOntologyId;
    if (!oid) return;
    try {
      await api.put(`/api/v1/ontology/${oid}/properties/${key}`, { status: "rejected" });
      invalidateOntologyKind(oid, "properties");
      invalidateOntologyKind(oid, "effective");
    } catch (err) {
      console.error("Failed to reject property", err);
    }
  }, [selectedOntologyId]);

  const deleteClass = useCallback(async (key: string) => {
    if (!selectedOntologyId) return;
    try {
      await api.del(`/api/v1/ontology/${selectedOntologyId}/classes/${key}`);
      // Deleting a class can break edges that referenced it (rdfs_domain,
      // rdfs_range_class, subclass_of), so invalidate both kinds, not
      // just classes. ``effective`` is invalidated alongside because the
      // canvas reads its merged payload (Stream 1 H.15). refreshGraph
      // then refetches the authoritative view from the server.
      invalidateOntologyKind(selectedOntologyId, "classes");
      invalidateOntologyKind(selectedOntologyId, "edges");
      invalidateOntologyKind(selectedOntologyId, "effective");
      refreshGraph();
    } catch (err) {
      console.error("Failed to delete class", err);
    }
  }, [selectedOntologyId, refreshGraph]);

  // Plain delete-and-cleanup for an ontology. The user-facing typed-name
  // confirmation lives in ``contextMenus/ontology.ts``; this callback is
  // only invoked after that gate has been satisfied. Side-panel "Delete"
  // buttons, if added later, MUST also gate on requestConfirm rather than
  // calling this directly.
  const deleteOntology = useCallback(async (key: string) => {
    try {
      await api.del(`/api/v1/ontology/library/${key}?confirm=true&hard_delete=true`);
      // Drop every cached entry for the deleted ontology -- if a future
      // import recreates the same _key, we must not serve the old graph
      // from cache.
      invalidateOntology(key);
      if (selectedOntologyId === key) {
        setSelectedOntologyId(null);
        setOntologyName(null);
        setOntologyTier(null);
        setClasses([]);
        setProperties([]);
        setEdges([]);
      }
      setExplorerLibraryNonce((n) => n + 1);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        if (selectedOntologyId === key) {
          setSelectedOntologyId(null);
          setOntologyName(null);
          setOntologyTier(null);
          setClasses([]);
          setProperties([]);
          setEdges([]);
        }
        setExplorerLibraryNonce((n) => n + 1);
        return;
      }
      console.error("Failed to delete ontology", err);
    }
  }, [selectedOntologyId]);

  const deleteDocument = useCallback(async (key: string) => {
    try {
      await api.del(`/api/v1/documents/${key}?confirm=true`);
      setInfoPanelItem((current) => (
        current?.type === "document" && current.data._key === key ? null : current
      ));
      setExplorerLibraryNonce((n) => n + 1);
    } catch (err) {
      console.error("Failed to delete document", err);
    }
  }, []);

  const exportOntology = useCallback(async (key: string, format: string) => {
    try {
      const url = `/api/v1/ontology/${key}/export?format=${format}`;
      window.open(`${window.location.origin}${withBasePath(url)}`, "_blank");
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

  const fetchOntologyQualityReport = useCallback(
    async (ontologyData: Record<string, unknown>) => {
      const base = { ...ontologyData };
      const id = String(base._key ?? base.ontology_id ?? "").trim();
      const name = String(base.label ?? base.name ?? id);
      if (!id) return;
      try {
        const quality = await api.get<PerOntologyQualityApiShape>(
          `/api/v1/quality/${encodeURIComponent(id)}`,
        );
        setQualityOverlay({ name, data: quality });
      } catch (err) {
        const message =
          err instanceof ApiError
            ? err.body.message
            : err instanceof Error
              ? err.message
              : "Failed to load quality report";
        console.error("Quality report error:", message);
      }
    },
    [],
  );

  /**
   * Context-menu action bundle handed to per-entity builders under
   * ``components/workspace/contextMenus/``. Built fresh on every menu open so
   * each builder closes over the latest state values (``activeLens``,
   * ``graphViewMode``, ``pipelineRunId``, ``selectedOntologyId``); the
   * function references inside are stable ``useCallback`` results from above.
   */
  const buildContextMenuActions = (): WorkspaceContextMenuActions => ({
    handleNodeSelect,
    handleEdgeSelect,
    handleSelectOntology,
    handleSelectRun,
    setInfoPanelItem,
    setDetailPanelOpen,
    setQualityOverlay,
    fetchOntologyQualityReport,
    approveClass,
    rejectClass,
    approveEdge,
    rejectEdge,
    approveProperty,
    rejectProperty,
    deleteClass,
    deleteOntology,
    deleteDocument,
    deleteRun,
    requestConfirm,
    setOntologyDelete,
    setRenameOntology,
    setReleaseOntology,
    setShowCreateOntology,
    setShowCatalogBrowser,
    setManageImports,
    setDependencyOverlay,
    setFeedbackLearning,
    setEdgeRepair,
    setRevisionsInbox,
    setMergeCandidates,
    exportOntology,
    removeImportEdge,
    retryRun,
    pipelineRunId,
    activeLens,
    setActiveLens,
    graphViewMode,
    setGraphViewMode,
    fitAllNodes: () => viewportApiRef.current?.fitAll(),
    centerView: () => viewportApiRef.current?.centerView(),
    relayout: (mode) => viewportApiRef.current?.relayout(mode),
    setEdgeStyle: (style) => viewportApiRef.current?.setEdgeStyle(style),
    fitPipelineView: () => dagApiRef.current?.fitView(),
    centerPipelineView: () => dagApiRef.current?.centerView(),
    closeContextMenu,
    selectedOntologyId,
  });

  function getContextMenuItems(): ContextMenuItem[] {
    if (!contextMenu) return [];

    const { type, data } = contextMenu;

    const builder = CONTEXT_MENU_BUILDERS[type];
    if (builder) {
      return builder(data, buildContextMenuActions());
    }

    return [];
  }

  return (
    <div className="h-screen flex flex-col overflow-hidden bg-[#12121f]">
      {/* Toast host — bottom-centre overlay, mounted once at the page
          root so any module (drag-and-drop import, future undo-toast
          migrations) can ``pushToast`` without threading context. */}
      <ToastHost />

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
            selectedRunId={pipelineRunId}
            onContextMenu={handleAssetContextMenu}
            libraryReloadNonce={explorerLibraryNonce}
            selectedClassKey={selectedNodeKey}
            onSelectClass={handleSelectClassFromSidebar}
            selectedEdgeKey={selectedEdgeKey}
            onSelectEdge={handleSelectEdgeFromSidebar}
            onOpenCatalogBrowser={() => setShowCatalogBrowser(true)}
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
        <main
          className="flex-1 flex flex-col relative min-w-0 min-h-0 outline-none"
          onDragOver={handleCanvasDragOver}
          onDrop={handleCanvasDrop}
          data-testid="workspace-canvas-pane"
          // W.7: tabIndex makes the canvas pane reachable via Tab so
          // keyboard users can cycle sidebar -> canvas without
          // tabbing through every sidebar row. Once the canvas pane
          // has focus, Sigma's own pointer/keyboard handlers take
          // over (drag to pan, scroll to zoom). `outline-none` keeps
          // the visual chrome quiet -- the focus ring on the
          // currently-selected node already tells the user where
          // their selection is.
          tabIndex={0}
        >
          {/* Graph Canvas area */}
          <div className="flex-1 relative overflow-hidden min-h-0">
            {pipelineRunId && !graphLoading ? (
              <div className="h-full flex flex-col bg-white overflow-hidden">
                {/* Header */}
                <div className="px-4 py-2 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
                  <div className="flex items-center gap-2">
                    <span className="text-xs px-2 py-0.5 rounded-full bg-violet-50 text-violet-700 font-medium">
                      Pipeline
                    </span>
                    <span className="text-xs text-gray-500 font-mono">{pipelineRunId}</span>
                  </div>
                  <button
                    onClick={() => { setPipelineRunId(null); }}
                    className="text-xs text-gray-400 hover:text-gray-600"
                  >
                    &times; Close
                  </button>
                </div>
                {/* DAG + Metrics with draggable vertical divider */}
                <PipelineSplitPane
                  top={
                    <AgentDAG
                      steps={filterStepsByTimestamp(pipelineSteps, vcrTimestamp)}
                      onContextMenu={handleDagContextMenu}
                      onApi={handleDagApi}
                    />
                  }
                  bottom={<RunMetrics runId={pipelineRunId} />}
                />
              </div>
            ) : selectedOntologyId ? (
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
                    onClick={refreshGraph}
                    className="text-xs text-indigo-400 hover:text-indigo-300 underline"
                  >
                    Retry
                  </button>
                </div>
              ) : (
                <>
                  {graphViewMode === "box-arrow" ? (
                    <BoxArrowCanvas
                      classes={classes}
                      edges={edges}
                      activeLens={activeLens}
                      ontologyTier={ontologyTier}
                      onNodeSelect={handleNodeSelect}
                      onEdgeSelect={handleEdgeSelect}
                      onContextMenu={handleSigmaContextMenu}
                      onViewportApi={handleViewportApi}
                      visibleNodeKeys={mergedVisibleNodeKeys}
                      selectedNodeKey={selectedNodeKey}
                      selectedEdgeKey={selectedEdgeKey}
                      classProperties={classPropertiesMap}
                    />
                  ) : (
                    <SigmaCanvas
                      classes={classes}
                      edges={edges}
                      activeLens={activeLens}
                      ontologyTier={ontologyTier}
                      onNodeSelect={handleNodeSelect}
                      onEdgeSelect={handleEdgeSelect}
                      onContextMenu={handleSigmaContextMenu}
                      onViewportApi={handleViewportApi}
                      visibleNodeKeys={mergedVisibleNodeKeys}
                      visibleEdgeKeys={confidenceVisibleEdges}
                      selectedNodeKey={selectedNodeKey}
                      selectedEdgeKey={selectedEdgeKey}
                    />
                  )}
                  {graphViewMode !== "box-arrow" && (
                    <CanvasLensLegend
                      activeLens={activeLens}
                      timelineActive={timelineVisibleKeys != null}
                      hasImported={canvasHasImported}
                    />
                  )}
                </>

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
                mainColumnLeftInset={assetExplorerWidth + 4}
                onClose={() => setInfoPanelItem(null)}
                onReloadQualityReport={fetchOntologyQualityReport}
                onOpenOntology={(key) => {
                  setInfoPanelItem(null);
                  handleSelectOntology(key);
                }}
              />
            )}
          </div>

          {/* Confidence-threshold slider — sibling to the VCR timeline,
              shown only in the Confidence lens (workspace rule §6: lens /
              graph style / layout are three separate axes; this is a filter,
              not a lens, but it only encodes confidence). */}
          {selectedOntologyId &&
            activeLens === "confidence" &&
            graphViewMode !== "box-arrow" && (
              <div className="h-auto min-h-[56px] border-t border-gray-800 bg-[#16162a] px-4 py-2 flex-shrink-0">
                <ConfidenceThresholdSlider
                  classes={classes}
                  edges={edges}
                  onVisibleClassesChange={setConfidenceVisibleClasses}
                  onVisibleEdgesChange={setConfidenceVisibleEdges}
                />
              </div>
            )}

          {/* Bottom: VCR Timeline */}
          {selectedOntologyId && (
            <div className="h-auto min-h-[56px] border-t border-gray-800 bg-[#16162a] px-4 py-2 flex-shrink-0">
              <VCRTimeline
                ontologyId={selectedOntologyId}
                onTimestampChange={setVcrTimestamp}
                onVisibleEntitiesChange={setTimelineVisibleKeys}
                injectedEvents={stepTimelineEvents}
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

      {renameOntology && (
        <OntologyRenameDialog
          open
          ontologyKey={renameOntology.key}
          initialName={renameOntology.name}
          initialDescription={renameOntology.description}
          onClose={() => setRenameOntology(null)}
          onSaved={(displayName, key) => {
            setExplorerLibraryNonce((n) => n + 1);
            if (selectedOntologyId === key) {
              setOntologyName(displayName);
            }
          }}
        />
      )}

      {releaseOntology && (
        <OntologyReleaseDialog
          open
          ontologyKey={releaseOntology.key}
          currentReleaseVersion={releaseOntology.currentReleaseVersion}
          onClose={() => setReleaseOntology(null)}
          onReleased={() => setExplorerLibraryNonce((n) => n + 1)}
        />
      )}

      {qualityOverlay && (
        <QualityReportOverlay
          name={qualityOverlay.name}
          data={qualityOverlay.data}
          onClose={() => setQualityOverlay(null)}
          onShowInbox={(ontologyId, ontologyName) => {
            setRevisionsInbox({ key: ontologyId, name: ontologyName });
          }}
        />
      )}

      <CreateOntologyDialog
        open={showCreateOntology}
        onClose={() => setShowCreateOntology(false)}
        onCreated={(id) => {
          setExplorerLibraryNonce((n) => n + 1);
          handleSelectOntology(id);
        }}
      />

      {showCatalogBrowser && (
        <CatalogBrowserOverlay
          onClose={() => setShowCatalogBrowser(false)}
          onImported={(newOntologyId) => {
            setExplorerLibraryNonce((n) => n + 1);
            handleSelectOntology(newOntologyId);
          }}
        />
      )}

      {dependencyOverlay && (
        <ImportsDependencyOverlay
          ontologyId={dependencyOverlay.key}
          ontologyName={dependencyOverlay.name}
          onClose={() => setDependencyOverlay(null)}
          onNavigate={(id, name) => {
            setDependencyOverlay(null);
            handleSelectOntology(id, name);
          }}
        />
      )}

      {manageImports && (
        <ManageImportsOverlay
          ontologyId={manageImports.key}
          ontologyName={manageImports.name}
          onClose={() => setManageImports(null)}
          onChanged={() => setExplorerLibraryNonce((n) => n + 1)}
        />
      )}

      {edgeRepair && (
        <EdgeRepairOverlay
          ontologyId={edgeRepair.key}
          ontologyName={edgeRepair.name}
          onClose={() => setEdgeRepair(null)}
          onApplied={() => {
            // Re-fetch the canvas so the newly-inserted rdfs_range_class
            // edges become visible without a full page reload.
            refreshGraph();
            setExplorerLibraryNonce((n) => n + 1);
          }}
        />
      )}

      {revisionsInbox && (
        <RevisionsInboxOverlay
          ontologyId={revisionsInbox.key}
          ontologyName={revisionsInbox.name}
          onClose={() => setRevisionsInbox(null)}
          onChanged={() => {
            // Refresh the canvas so any auto-applied (REINFORCE/REVISE/
            // GAP_FILL/RETRACT) decisions show up immediately. The
            // explorer also gets a nonce bump so per-ontology badges
            // refresh.
            refreshGraph();
            setExplorerLibraryNonce((n) => n + 1);
          }}
        />
      )}

      {mergeCandidates && (
        <MergeCandidatesOverlay
          ontologyId={mergeCandidates.key}
          ontologyName={mergeCandidates.name}
          onClose={() => setMergeCandidates(null)}
          onChanged={() => {
            // Accepted merges expire the losing class via the temporal
            // pattern, so the canvas needs to re-fetch to drop it.
            // Rejected merges only soft-mark the similarTo edge so the
            // canvas itself is unchanged -- but refreshing is cheap and
            // keeps the behaviour symmetric with the revisions inbox.
            refreshGraph();
            setExplorerLibraryNonce((n) => n + 1);
          }}
        />
      )}

      {feedbackLearning && (
        <FeedbackLearningOverlay
          ontologyId={feedbackLearning.ontologyId}
          ontologyName={feedbackLearning.ontologyName}
          onClose={() => setFeedbackLearning(null)}
        />
      )}

      {pendingConfirm && (
        <ConfirmDialog
          open
          title={pendingConfirm.title}
          message={pendingConfirm.message}
          confirmLabel={pendingConfirm.confirmLabel}
          cancelLabel={pendingConfirm.cancelLabel}
          danger={pendingConfirm.danger}
          typedName={pendingConfirm.typedName}
          onConfirm={() => {
            const fn = pendingConfirm.onConfirm;
            setPendingConfirm(null);
            fn();
          }}
          onClose={() => setPendingConfirm(null)}
        />
      )}

      {ontologyDelete && (
        <OntologyDeleteDialog
          ontologyId={ontologyDelete.key}
          ontologyName={ontologyDelete.name}
          onClose={() => setOntologyDelete(null)}
          onConfirm={(key) => {
            setOntologyDelete(null);
            void deleteOntology(key);
          }}
        />
      )}
    </div>
  );
}

/* ── Asset info panel (left-click detail overlay) ───── */

const ASSET_INFO_PANEL_WIDTH = 360;

function AssetInfoPanel({
  type,
  data,
  mainColumnLeftInset,
  onClose,
  onOpenOntology,
  onReloadQualityReport,
}: {
  type: "document" | "ontology" | "run";
  data: Record<string, unknown>;
  /** Left edge of main column (explorer + separator) so the panel clears the sidebar. */
  mainColumnLeftInset: number;
  onClose: () => void;
  onOpenOntology: (key: string) => void;
  onReloadQualityReport?: (ontologyData: Record<string, unknown>) => void | Promise<void>;
}) {
  const { panelRef, panelStyle, dragHandleProps } = useDraggablePanel(ASSET_INFO_PANEL_WIDTH, {
    placement: "mainColumnTopLeft",
    mainColumnLeftInset,
  });
  const { className: dragHandleClassName, ...dragHandleEvents } = dragHandleProps;

  const extractedClasses = Array.isArray(data.classes) ? (data.classes as Record<string, unknown>[]) : [];
  const extractedProperties = Array.isArray(data.properties) ? (data.properties as Record<string, unknown>[]) : [];
  const hasExtractedEntities = extractedClasses.length > 0 || extractedProperties.length > 0;

  const [activeTab, setActiveTab] = useState<"info" | "entities">(
    hasExtractedEntities ? "entities" : "info",
  );

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
      { label: "Health Score", value: formatOntologyHealthSummary(data.health_score) },
      { label: "Created", value: data.created_at as string },
    );
  } else if (type === "run") {
    const stats = (data.stats ?? {}) as Record<string, unknown>;
    const rawStart = data.started_at;
    const rawEnd = data.completed_at;
    const toSeconds = (v: unknown): number | null => {
      if (v == null) return null;
      if (typeof v === "number") return v < 1e12 ? v : v / 1000;
      const ms = new Date(v as string).getTime();
      return isNaN(ms) ? null : ms / 1000;
    };
    const startSec = toSeconds(rawStart);
    const endSec = toSeconds(rawEnd);
    const duration = startSec != null && endSec != null
      ? `${Math.round(endSec - startSec)}s`
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
      { label: "Classes Extracted", value: extractedClasses.length || (data.classes_extracted as number ?? stats.classes_extracted as number) },
      { label: "Properties Extracted", value: extractedProperties.length || (data.properties_extracted as number ?? stats.properties_extracted as number) },
      { label: "Total Tokens", value: totalTokens },
      { label: "Estimated Cost", value: stats.estimated_cost != null ? `$${(stats.estimated_cost as number).toFixed(4)}` : undefined },
      { label: "Agreement Rate", value: stats.pass_agreement_rate != null ? `${((stats.pass_agreement_rate as number) * 100).toFixed(1)}%` : undefined },
    );
  }

  const filteredRows = rows.filter((r) => r.value != null && r.value !== "");

  return (
    <div
      ref={panelRef}
      style={panelStyle}
      className="max-h-[70vh] bg-white rounded-xl border border-gray-200 shadow-xl overflow-hidden flex flex-col"
      role="dialog"
      aria-label={`${titleMap[type]} info panel`}
    >
      <div
        className={`flex items-center justify-between px-4 py-3 border-b border-gray-100 flex-shrink-0 ${dragHandleClassName}`}
        {...dragHandleEvents}
      >
        <div className="flex items-center gap-2 min-w-0">
          <PanelDragGrip />
          <span className="text-xs px-2 py-0.5 rounded-full bg-blue-50 text-blue-600 font-medium flex-shrink-0">
            {titleMap[type]}
          </span>
          <span className="text-sm font-semibold text-gray-800 truncate">
            {(data.name ?? data.filename ?? data.document_name ?? data._key) as string}
          </span>
        </div>
        <button
          type="button"
          onPointerDown={(e) => e.stopPropagation()}
          onClick={onClose}
          className="text-gray-400 hover:text-gray-600 text-lg leading-none ml-2 flex-shrink-0 cursor-pointer"
          aria-label="Close info panel"
        >
          &times;
        </button>
      </div>

      {/* Tab bar for run panels with extracted entities */}
      {type === "run" && hasExtractedEntities && (
        <div className="flex border-b border-gray-100 px-4 flex-shrink-0">
          <button
            onClick={() => setActiveTab("info")}
            className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
              activeTab === "info"
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            Run Info
          </button>
          <button
            onClick={() => setActiveTab("entities")}
            className={`px-3 py-2 text-xs font-medium border-b-2 transition-colors ${
              activeTab === "entities"
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            Extracted Entities ({extractedClasses.length + extractedProperties.length})
          </button>
        </div>
      )}

      <div className="flex-1 overflow-y-auto p-4 space-y-3">
        {/* Entities tab */}
        {activeTab === "entities" && hasExtractedEntities ? (
          <ExtractedEntitiesView classes={extractedClasses} properties={extractedProperties} />
        ) : (
          <>
        {filteredRows.map((row) => (
          <div key={row.label}>
            <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-0.5">
              {row.label}
            </dt>
            <dd className="text-sm text-gray-700">{String(row.value)}</dd>
          </div>
        ))}

        {/* Quality Report (when loaded via "View Quality Report") */}
        {type === "ontology" && typeof data._qualityReport === "object" && data._qualityReport != null && (
          <QualityReportSection report={data._qualityReport as Record<string, unknown>} />
        )}

        {/* Provenance chunks */}
        {Array.isArray(data._provenance) && (data._provenance as Record<string, unknown>[]).length > 0 && (
          <div className="border-t border-gray-100 pt-3">
            <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
              Source Chunks ({(data._provenance as unknown[]).length})
            </dt>
            <p className="text-[10px] leading-snug text-gray-500 mb-2">
              Classes link to whole documents; chunks here are from those documents. Highlights match
              the class name heuristically — exact extraction spans are not stored.
            </p>
            <div className="space-y-2 max-h-[300px] overflow-y-auto">
              {(data._provenance as Record<string, unknown>[]).map((chunk, idx) => (
                <div key={(chunk._key as string) ?? idx} className="text-xs bg-amber-50 rounded-md p-2 border border-amber-100">
                  {typeof chunk.section_heading === "string" && chunk.section_heading && (
                    <div className="font-medium text-amber-800 mb-1">{chunk.section_heading}</div>
                  )}
                  <div className="text-gray-600 whitespace-pre-wrap break-words">
                    <HighlightedText
                      text={((chunk.text as string) ?? "").slice(0, 500)}
                      highlight={(data.name as string) ?? ""}
                    />
                    {((chunk.text as string) ?? "").length > 500 && "…"}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Version History */}
        {Array.isArray(data._history) && (data._history as Record<string, unknown>[]).length > 0 && (
          <div className="border-t border-gray-100 pt-3">
            <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
              Version History ({(data._history as unknown[]).length})
            </dt>
            <div className="space-y-1.5 max-h-[250px] overflow-y-auto">
              {(data._history as Record<string, unknown>[]).map((ver, idx) => {
                const created = ver.created as number | undefined;
                const label = (ver.label ?? ver._key) as string;
                const ts = created ? new Date(created * 1000).toLocaleString() : "—";
                return (
                  <div key={idx} className="flex items-baseline gap-2 text-xs bg-gray-50 rounded-md px-2.5 py-1.5">
                    <span className="text-gray-400 font-mono text-[10px] flex-shrink-0">v{(data._history as unknown[]).length - idx}</span>
                    <span className="font-medium text-gray-800 truncate">{label}</span>
                    <span className="text-gray-400 ml-auto flex-shrink-0">{ts}</span>
                  </div>
                );
              })}
            </div>
          </div>
        )}
          </>
        )}
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

function ExtractedEntitiesView({
  classes,
  properties,
}: {
  classes: Record<string, unknown>[];
  properties: Record<string, unknown>[];
}) {
  const [expandedClass, setExpandedClass] = useState<string | null>(null);

  const propsByClass = useMemo(() => {
    const map = new Map<string, Record<string, unknown>[]>();
    for (const prop of properties) {
      const domain = (prop.domain ?? prop.class_name ?? "Unknown") as string;
      if (!map.has(domain)) map.set(domain, []);
      map.get(domain)!.push(prop);
    }
    return map;
  }, [properties]);

  if (classes.length === 0 && properties.length === 0) {
    return <p className="text-sm text-gray-400">No entities extracted.</p>;
  }

  return (
    <div className="space-y-1">
      <div className="text-xs text-gray-500 mb-2">
        {classes.length} classes, {properties.length} properties
      </div>
      {classes.map((cls) => {
        const name = (cls.label ?? cls.name ?? cls._key ?? "Unnamed") as string;
        const key = (cls._key ?? cls.name ?? name) as string;
        const isExpanded = expandedClass === key;
        const classProps = propsByClass.get(name) ?? [];
        const confidence = cls.confidence as number | undefined;
        const description = (cls.description ?? cls.rdfs_comment) as string | undefined;

        return (
          <div key={key} className="border border-gray-100 rounded-lg overflow-hidden">
            <button
              onClick={() => setExpandedClass(isExpanded ? null : key)}
              className="w-full text-left px-3 py-2 flex items-center gap-2 hover:bg-gray-50 transition-colors"
            >
              <span className="text-xs text-gray-400">{isExpanded ? "▾" : "▸"}</span>
              <span className="text-sm font-medium text-gray-800 flex-1 truncate">{name}</span>
              {classProps.length > 0 && (
                <span className="text-[10px] text-gray-400">{classProps.length} props</span>
              )}
              {confidence != null && (
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${
                  confidence >= 0.8 ? "bg-green-50 text-green-700" :
                  confidence >= 0.5 ? "bg-yellow-50 text-yellow-700" :
                  "bg-red-50 text-red-700"
                }`}>
                  {(confidence * 100).toFixed(0)}%
                </span>
              )}
            </button>
            {isExpanded && (
              <div className="px-3 pb-2 space-y-1.5 border-t border-gray-50">
                {description && (
                  <p className="text-xs text-gray-500 mt-1.5 italic">{description}</p>
                )}
                {classProps.length > 0 ? (
                  classProps.map((prop, idx) => {
                    const propName = (prop.label ?? prop.name ?? prop._key) as string;
                    const propRange = (prop.range ?? prop.datatype ?? prop.type) as string | undefined;
                    return (
                      <div key={idx} className="flex items-baseline gap-2 text-xs bg-gray-50 rounded px-2 py-1">
                        <span className="font-mono text-gray-700">{propName}</span>
                        {propRange && <span className="text-gray-400 ml-auto">{propRange}</span>}
                      </div>
                    );
                  })
                ) : (
                  <p className="text-[11px] text-gray-400 mt-1">No properties</p>
                )}
              </div>
            )}
          </div>
        );
      })}
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

function PipelineSplitPane({
  top,
  bottom,
}: {
  top: React.ReactNode;
  bottom: React.ReactNode;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [topFraction, setTopFraction] = useState(0.55);
  const draggingRef = useRef(false);

  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    draggingRef.current = true;
    document.body.style.cursor = "row-resize";
    document.body.style.userSelect = "none";

    function onMove(ev: MouseEvent) {
      if (!draggingRef.current || !containerRef.current) return;
      const rect = containerRef.current.getBoundingClientRect();
      const y = ev.clientY - rect.top;
      const fraction = Math.min(0.85, Math.max(0.2, y / rect.height));
      setTopFraction(fraction);
    }

    function onUp() {
      draggingRef.current = false;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
      document.removeEventListener("mousemove", onMove);
      document.removeEventListener("mouseup", onUp);
    }

    document.addEventListener("mousemove", onMove);
    document.addEventListener("mouseup", onUp);
  }, []);

  return (
    <div ref={containerRef} className="flex-1 flex flex-col min-h-0 overflow-hidden">
      <div className="overflow-hidden" style={{ flex: `0 0 ${topFraction * 100}%` }}>
        {top}
      </div>
      <div
        className="h-1.5 cursor-row-resize hover:bg-indigo-400 active:bg-indigo-500 bg-gray-200 flex-shrink-0 transition-colors"
        onMouseDown={handleMouseDown}
        role="separator"
        aria-orientation="horizontal"
        aria-label="Resize pipeline panes"
      />
      <div className="flex-1 overflow-y-auto min-h-0">
        {bottom}
      </div>
    </div>
  );
}

function QualityReportSection({ report }: { report: Record<string, unknown> }) {
  const metrics: { label: string; value: string; color?: string }[] = [];

  const fmt = (v: unknown, pct = false) => {
    if (v == null) return "—";
    const n = Number(v);
    if (isNaN(n)) return String(v);
    return pct ? `${(n * 100).toFixed(1)}%` : n.toFixed(2);
  };

  const scoreColor = (v: unknown) => {
    const n = Number(v);
    if (isNaN(n)) return "text-gray-600";
    if (n >= 0.7) return "text-green-600";
    if (n >= 0.5) return "text-yellow-600";
    return "text-red-600";
  };

  if (report.health_score != null) metrics.push({ label: "Health Score", value: fmt(report.health_score, true), color: scoreColor(report.health_score) });
  if (report.avg_confidence != null) metrics.push({ label: "Avg Confidence", value: fmt(report.avg_confidence, true), color: scoreColor(report.avg_confidence) });
  if (report.avg_faithfulness != null) metrics.push({ label: "Faithfulness", value: fmt(report.avg_faithfulness, true), color: scoreColor(report.avg_faithfulness) });
  if (report.avg_semantic_validity != null) metrics.push({ label: "Semantic Validity", value: fmt(report.avg_semantic_validity, true), color: scoreColor(report.avg_semantic_validity) });
  if (report.completeness != null) metrics.push({ label: "Completeness", value: fmt(report.completeness, true) });
  if (report.connectivity != null) metrics.push({ label: "Connectivity", value: fmt(report.connectivity, true) });
  if (report.orphan_count != null) metrics.push({ label: "Orphan Classes", value: String(report.orphan_count) });
  if (report.has_cycles != null) metrics.push({ label: "Has Cycles", value: report.has_cycles ? "Yes" : "No", color: report.has_cycles ? "text-red-600" : "text-green-600" });
  if (report.relationship_count != null) metrics.push({ label: "Relationships", value: String(report.relationship_count) });
  if (report.estimated_cost != null) metrics.push({ label: "Extraction Cost", value: `$${Number(report.estimated_cost).toFixed(4)}` });

  if (metrics.length === 0) return null;

  return (
    <div className="border-t border-gray-100 pt-3">
      <dt className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-2">
        Quality Report
      </dt>
      <div className="grid grid-cols-2 gap-2">
        {metrics.map((m) => (
          <div key={m.label} className="bg-gray-50 rounded-md px-2.5 py-1.5">
            <div className="text-[10px] text-gray-500 uppercase">{m.label}</div>
            <div className={`text-sm font-semibold ${m.color ?? "text-gray-800"}`}>{m.value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function HighlightedText({ text, highlight }: { text: string; highlight: string }) {
  if (!highlight || highlight.length < 2) return <>{text}</>;
  const parts = splitTextByKeywordAlternation(text, termsFromEntityLabel(highlight));
  return (
    <>
      {parts.map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="bg-yellow-200 text-yellow-900 rounded-sm px-0.5">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}
