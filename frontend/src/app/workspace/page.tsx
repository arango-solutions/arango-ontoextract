"use client";

import { useState, useCallback, useEffect, useRef, useMemo, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import LensToolbar, { type LensType } from "@/components/workspace/LensToolbar";
import AssetExplorer from "@/components/workspace/AssetExplorer";
import OntologyRenameDialog from "@/components/workspace/OntologyRenameDialog";
import OntologyReleaseDialog from "@/components/workspace/OntologyReleaseDialog";
import CreateOntologyDialog from "@/components/workspace/CreateOntologyDialog";
import ManageImportsOverlay from "@/components/workspace/ManageImportsOverlay";
import FeedbackLearningOverlay from "@/components/workspace/FeedbackLearningOverlay";
import CanvasLensLegend from "@/components/workspace/CanvasLensLegend";
import EmptyCanvasState from "@/components/workspace/EmptyCanvasState";
import FloatingDetailPanel from "@/components/workspace/FloatingDetailPanel";
import ContextMenu, { type ContextMenuItem } from "@/components/workspace/ContextMenu";
import { api, ApiError, type PaginatedResponse } from "@/lib/api-client";
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
} from "@/types/curation";
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
  const [manageImports, setManageImports] = useState<{
    key: string;
    name: string;
  } | null>(null);
  const [feedbackLearning, setFeedbackLearning] = useState<{
    ontologyId?: string | null;
    ontologyName?: string | null;
  } | null>(null);

  const [classes, setClasses] = useState<OntologyClass[]>([]);
  const [properties, setProperties] = useState<OntologyProperty[]>([]);
  const [edges, setEdges] = useState<OntologyEdge[]>([]);
  const [graphLoading, setGraphLoading] = useState(false);
  const [graphError, setGraphError] = useState<string | null>(null);
  const [timelineVisibleKeys, setTimelineVisibleKeys] = useState<Set<string> | null>(null);

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
        const res = await api.get<{ data: OntologyProperty[] }>(
          `/api/v1/ontology/${selectedOntologyId}/properties`,
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
    setPipelineRunId(null);
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
    } catch (err) {
      console.error("Failed to delete run", err);
    }
  }, [pipelineRunId]);

  const closeContextMenu = useCallback(() => setContextMenu(null), []);

  const refreshGraph = useCallback(() => {
    if (selectedOntologyId) fetchGraphData(selectedOntologyId);
  }, [selectedOntologyId, fetchGraphData]);

  const approveClass = useCallback(async (key: string) => {
    if (!selectedOntologyId) return;
    setClasses((prev) =>
      prev.map((c) =>
        c._key === key ? { ...c, status: "approved" as const } : c,
      ),
    );
    try {
      await api.put(`/api/v1/ontology/${selectedOntologyId}/classes/${key}`, { status: "approved" });
    } catch (err) {
      console.error("Failed to approve class", err);
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
    } catch (err) {
      console.error("Failed to approve property", err);
    }
  }, [selectedOntologyId]);

  const rejectProperty = useCallback(async (key: string, ontologyId?: string) => {
    const oid = ontologyId ?? selectedOntologyId;
    if (!oid) return;
    try {
      await api.put(`/api/v1/ontology/${oid}/properties/${key}`, { status: "rejected" });
    } catch (err) {
      console.error("Failed to reject property", err);
    }
  }, [selectedOntologyId]);

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
      const confirmed = confirm(
        `Delete ontology "${key}"? This removes it from the ontology list and expires its contents.`,
      );
      if (!confirmed) {
        return;
      }
      await api.del(`/api/v1/ontology/library/${key}?confirm=true&hard_delete=true`);
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
            onClick: async () => {
              try {
                const history = await api.get<Record<string, unknown>[]>(
                  `/api/v1/ontology/class/${classKey}/history`,
                );
                setInfoPanelItem({
                  type: "ontology",
                  data: { _key: classKey, name: classLabel, _history: history },
                });
              } catch {
                handleNodeSelect(classKey);
              }
            },
          },
          {
            label: "View Provenance", icon: "🔗",
            onClick: async () => {
              try {
                const prov = await api.get<{ data: Record<string, unknown>[] }>(
                  `/api/v1/ontology/class/${classKey}/provenance`,
                );
                setInfoPanelItem({
                  type: "ontology",
                  data: { _key: classKey, name: classLabel, _provenance: prov.data },
                });
              } catch {
                handleNodeSelect(classKey);
              }
            },
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
          { label: "separator0", separator: true },
          {
            label: "Approve edge", icon: "✅",
            onClick: () => { approveEdge(edgeKey); },
          },
          {
            label: "Reject edge", icon: "❌",
            onClick: () => { rejectEdge(edgeKey); },
          },
          { label: "separator1", separator: true },
          {
            label: "Delete", icon: "🗑️", danger: true,
            disabled: true,
          },
        ];
      }
      case "property": {
        const propKey = (data._key ?? data.key) as string;
        const propLabel = (data.label ?? propKey) as string;
        const propOntologyId = (data.ontology_id ?? selectedOntologyId) as string;
        const propRange = (data.range_datatype ?? data.range ?? (data.target_class as Record<string, unknown> | undefined)?.label ?? "") as string;
        const propStatus = data.status as string | undefined;

        return [
          {
            label: propLabel, icon: "🔍",
            onClick: () => {
              setInfoPanelItem({
                type: "run",
                data: {
                  _key: propKey,
                  name: propLabel,
                  status: propStatus,
                  range: propRange,
                  ontology_id: propOntologyId,
                  ...data,
                },
              });
            },
          },
          { label: "separator0", separator: true },
          {
            label: "Approve", icon: "✅",
            disabled: propStatus === "approved",
            onClick: () => { approveProperty(propKey, propOntologyId); },
          },
          {
            label: "Reject", icon: "❌",
            disabled: propStatus === "rejected",
            onClick: () => { rejectProperty(propKey, propOntologyId); },
          },
          { label: "separator1", separator: true },
          {
            label: "Copy URI", icon: "📋",
            disabled: !data.uri,
            onClick: () => {
              if (data.uri) navigator.clipboard.writeText(data.uri as string).catch(() => {});
            },
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
        const ontKey = String(data._key ?? data.ontology_id ?? "").trim();
        return [
          {
            label: "Open in Canvas", icon: "🔷",
            onClick: () => {
              if (ontKey) handleSelectOntology(ontKey);
            },
          },
          {
            label: "View Info", icon: "ℹ️",
            onClick: () => { setInfoPanelItem({ type: "ontology", data }); },
          },
          {
            label: "Edit name & description", icon: "✏️",
            onClick: () => {
              if (!ontKey) return;
              const n = String(data.name ?? data.label ?? ontKey).trim();
              const d = typeof data.description === "string" ? data.description : "";
              setRenameOntology({ key: ontKey, name: n || ontKey, description: d });
            },
          },
          {
            label: "Release",
            icon: "🚀",
            disabled: data.status === "deprecated",
            onClick: () => {
              if (!ontKey || data.status === "deprecated") return;
              const cur =
                typeof data.current_release_version === "string"
                  ? data.current_release_version
                  : null;
              setReleaseOntology({ key: ontKey, currentReleaseVersion: cur });
            },
          },
          {
            label: "Manage Imports", icon: "🔗",
            onClick: () => {
              if (!ontKey) return;
              const n = String(data.name ?? data.label ?? ontKey).trim();
              setManageImports({ key: ontKey, name: n });
            },
          },
          {
            label: "View Quality Report", icon: "📊",
            onClick: () => fetchOntologyQualityReport(data),
          },
          {
            label: "View Feedback Learning", icon: "📊",
            onClick: () => {
              setFeedbackLearning({
                ontologyId: ontKey || null,
                ontologyName: String(data.name ?? data.label ?? ontKey),
              });
            },
          },
          {
            label: "Export",
            icon: "📤",
            submenu: [
              { label: "Turtle (.ttl)", onClick: () => { if (ontKey) exportOntology(ontKey, "turtle"); } },
              { label: "JSON-LD", onClick: () => { if (ontKey) exportOntology(ontKey, "jsonld"); } },
              { label: "CSV", onClick: () => { if (ontKey) exportOntology(ontKey, "csv"); } },
            ],
          },
          { label: "separator1", separator: true },
          {
            label: "Delete", icon: "🗑️", danger: true,
            onClick: () => { if (ontKey) deleteOntology(ontKey); },
          },
        ];
      }
      case "run": {
        const runKey = (data._key) as string;
        return [
          {
            label: "View Pipeline & Metrics", icon: "⚡",
            onClick: () => { handleSelectRun(runKey); },
          },
          {
            label: "Copy Run ID", icon: "📋",
            onClick: () => { navigator.clipboard.writeText(runKey).catch(() => {}); },
          },
          {
            label: "View Run Info", icon: "ℹ️",
            onClick: async () => {
              try {
                const run = await api.get<Record<string, unknown>>(
                  `/api/v1/extraction/runs/${runKey}`,
                );
                setInfoPanelItem({ type: "run", data: run });
              } catch (err) {
                console.error("Failed to load run info", err);
              }
            },
          },
          {
            label: "View Extracted Entities", icon: "📊",
            onClick: async () => {
              try {
                const results = await api.get<Record<string, unknown>>(
                  `/api/v1/extraction/runs/${runKey}/results`,
                );
                setInfoPanelItem({
                  type: "run",
                  data: { _key: runKey, name: "Extracted Entities", ...results },
                });
              } catch (err) {
                console.error("Failed to load run results", err);
              }
            },
          },
          { label: "separator", separator: true },
          {
            label: "Retry Run", icon: "🔄",
            onClick: () => { retryRun(runKey); },
          },
          {
            label: "Delete Run", icon: "🗑️", danger: true,
            onClick: () => {
              if (confirm(`Delete run ${runKey}? This cannot be undone.`)) {
                deleteRun(runKey);
              }
            },
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
            label: "Graph Style",
            icon: "📐",
            submenu: [
              {
                label: "Network (circles)",
                checked: graphViewMode === "network",
                onClick: () => setGraphViewMode("network"),
              },
              {
                label: "Box & Arrow (UML)",
                checked: graphViewMode === "box-arrow",
                onClick: () => setGraphViewMode("box-arrow"),
              },
            ],
          },
          ...(graphViewMode === "network" ? [
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
          ] as ContextMenuItem[] : []),
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
          { label: "sep-new-ont", separator: true },
          {
            label: "New Ontology…",
            icon: "➕",
            onClick: () => setShowCreateOntology(true),
          },
          {
            label: "Review Feedback Learning",
            icon: "📊",
            onClick: () => setFeedbackLearning({ ontologyId: null, ontologyName: null }),
          },
        ];
      case "step": {
        const stepKey = data.stepKey as string;
        const stepLabel = data.label as string;
        const stepStatus = data.status as string;
        const stepError = data.error as string | undefined;
        const stepStartedAt = data.startedAt as string | undefined;
        const stepCompletedAt = data.completedAt as string | undefined;
        const stepData = data.data as Record<string, unknown> | undefined;
        const durationMs = stepData?.duration_ms as number | undefined;

        const items: ContextMenuItem[] = [
          {
            label: "View Step Details", icon: "🔍",
            onClick: () => {
              setInfoPanelItem({
                type: "run",
                data: {
                  _key: `step:${stepKey}`,
                  name: stepLabel,
                  status: stepStatus,
                  started_at: stepStartedAt,
                  completed_at: stepCompletedAt,
                  duration_ms: durationMs,
                  ...stepData,
                },
              });
            },
          },
        ];

        if (stepError) {
          items.push({
            label: "Copy Error", icon: "📋",
            onClick: () => {
              navigator.clipboard.writeText(stepError).catch(() => {});
            },
          });
        }

        items.push({ label: "sep0", separator: true });

        if (pipelineRunId) {
          items.push({
            label: "View Run Results", icon: "📊",
            onClick: async () => {
              try {
                const results = await api.get<Record<string, unknown>>(
                  `/api/v1/extraction/runs/${pipelineRunId}/results`,
                );
                setInfoPanelItem({
                  type: "run",
                  data: {
                    _key: pipelineRunId,
                    name: `Results — ${stepLabel}`,
                    ...results,
                  },
                });
              } catch (err) {
                console.error("Failed to load run results", err);
              }
            },
          });

          items.push({ label: "sep1", separator: true });

          items.push({
            label: "Retry Run", icon: "🔄",
            disabled: stepStatus !== "failed",
            onClick: () => { if (pipelineRunId) retryRun(pipelineRunId); },
          });
        }

        return items;
      }

      case "pipeline_canvas": {
        const items: ContextMenuItem[] = [
          {
            label: "Fit All Nodes", icon: "⬜",
            onClick: () => {
              closeContextMenu();
              dagApiRef.current?.fitView();
            },
          },
          {
            label: "Center View", icon: "🎯",
            onClick: () => {
              closeContextMenu();
              dagApiRef.current?.centerView();
            },
          },
        ];

        if (pipelineRunId) {
          items.push({ label: "sep0", separator: true });
          items.push({
            label: "Copy Run ID", icon: "📋",
            onClick: () => {
              if (pipelineRunId) {
                navigator.clipboard.writeText(pipelineRunId).catch(() => {});
              }
            },
          });
          items.push({
            label: "View Run Info", icon: "ℹ️",
            onClick: async () => {
              try {
                const res = await fetch(backendUrl(`/api/v1/extraction/runs/${pipelineRunId}`));
                if (res.ok) {
                  const run = await res.json();
                  setInfoPanelItem({ type: "run", data: run });
                }
              } catch (err) {
                console.error("Failed to load run info", err);
              }
            },
          });
          items.push({
            label: "View Extracted Entities", icon: "📊",
            onClick: async () => {
              try {
                const results = await api.get<Record<string, unknown>>(
                  `/api/v1/extraction/runs/${pipelineRunId}/results`,
                );
                setInfoPanelItem({
                  type: "run",
                  data: { _key: pipelineRunId, name: "Extracted Entities", ...results },
                });
              } catch (err) {
                console.error("Failed to load run results", err);
              }
            },
          });

          items.push({ label: "sep1", separator: true });

          items.push({
            label: "Retry Run", icon: "🔄",
            onClick: () => { if (pipelineRunId) retryRun(pipelineRunId); },
          });
          items.push({
            label: "Delete Run", icon: "🗑️", danger: true,
            onClick: () => {
              if (pipelineRunId && confirm(`Delete run ${pipelineRunId}? This cannot be undone.`)) {
                deleteRun(pipelineRunId);
              }
            },
          });
        }

        return items;
      }

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
            selectedRunId={pipelineRunId}
            onContextMenu={handleAssetContextMenu}
            libraryReloadNonce={explorerLibraryNonce}
            selectedClassKey={selectedNodeKey}
            onSelectClass={handleSelectClassFromSidebar}
            selectedEdgeKey={selectedEdgeKey}
            onSelectEdge={handleSelectEdgeFromSidebar}
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
                    onClick={() => selectedOntologyId && fetchGraphData(selectedOntologyId)}
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
                      visibleNodeKeys={timelineVisibleKeys}
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
                      visibleNodeKeys={timelineVisibleKeys}
                      selectedNodeKey={selectedNodeKey}
                      selectedEdgeKey={selectedEdgeKey}
                    />
                  )}
                  {graphViewMode !== "box-arrow" && (
                    <CanvasLensLegend
                      activeLens={activeLens}
                      timelineActive={timelineVisibleKeys != null}
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

      {manageImports && (
        <ManageImportsOverlay
          ontologyId={manageImports.key}
          ontologyName={manageImports.name}
          onClose={() => setManageImports(null)}
          onChanged={() => setExplorerLibraryNonce((n) => n + 1)}
        />
      )}

      {feedbackLearning && (
        <FeedbackLearningOverlay
          ontologyId={feedbackLearning.ontologyId}
          ontologyName={feedbackLearning.ontologyName}
          onClose={() => setFeedbackLearning(null)}
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
