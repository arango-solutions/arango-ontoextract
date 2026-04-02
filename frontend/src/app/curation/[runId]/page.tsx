"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { api, ApiError } from "@/lib/api-client";
import type {
  StagingGraph,
  OntologyClass,
  OntologyEdge,
  CurationDecisionType,
  EdgeType,
} from "@/types/curation";
import type { TemporalSnapshot } from "@/types/timeline";
import type { TemporalDiff } from "@/types/timeline";
import NodeDetail from "@/components/curation/NodeDetail";
import NodeActions from "@/components/curation/NodeActions";
import EdgeActions from "@/components/curation/EdgeActions";
import BatchActions from "@/components/curation/BatchActions";
import ProvenancePanel from "@/components/curation/ProvenancePanel";
import DiffView from "@/components/curation/DiffView";
import PromotePanel from "@/components/curation/PromotePanel";
import EntityHistory from "@/components/timeline/EntityHistory";

const GraphCanvas = dynamic(
  () => import("@/components/graph/GraphCanvas"),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center h-full text-gray-400 animate-pulse">
        Loading graph...
      </div>
    ),
  },
);

const VCRTimeline = dynamic(
  () => import("@/components/timeline/VCRTimeline"),
  { ssr: false },
);

const DiffOverlay = dynamic(
  () => import("@/components/graph/DiffOverlay"),
  { ssr: false },
);

type SidePanel = "detail" | "provenance" | "diff" | "promote" | "history";

export default function CurationPage() {
  const params = useParams();
  const runId = params.runId as string;

  const [graph, setGraph] = useState<StagingGraph | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [selectedNodeKey, setSelectedNodeKey] = useState<string | null>(null);
  const [selectedEdgeKey, setSelectedEdgeKey] = useState<string | null>(null);
  const [multiSelected, setMultiSelected] = useState<string[]>([]);
  const [activePanel, setActivePanel] = useState<SidePanel>("detail");
  const [colorMode, setColorMode] = useState<"confidence" | "status">("confidence");
  const [timelineOpen, setTimelineOpen] = useState(false);
  const [snapshotTimestamp, setSnapshotTimestamp] = useState<number | null>(null);
  const [snapshotLoading, setSnapshotLoading] = useState(false);
  const [diffData, setDiffData] = useState<TemporalDiff | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [diffError, setDiffError] = useState<string | null>(null);

  const fetchGraph = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<StagingGraph>(
        `/api/v1/ontology/staging/${runId}`,
      );
      setGraph(res);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.body.message
          : "Failed to load staging graph",
      );
    } finally {
      setLoading(false);
    }
  }, [runId]);

  useEffect(() => {
    fetchGraph();
  }, [fetchGraph]);

  const selectedNode = useMemo(
    () => graph?.classes.find((c) => c._key === selectedNodeKey) ?? null,
    [graph, selectedNodeKey],
  );

  const selectedEdge = useMemo(
    () => graph?.edges.find((e) => e._key === selectedEdgeKey) ?? null,
    [graph, selectedEdgeKey],
  );

  const handleNodeSelect = useCallback((key: string) => {
    setSelectedNodeKey(key);
    setSelectedEdgeKey(null);
    setActivePanel("detail");
  }, []);

  const handleEdgeSelect = useCallback((key: string) => {
    setSelectedEdgeKey(key);
    setSelectedNodeKey(null);
  }, []);

  const handleSelectionChange = useCallback((keys: string[]) => {
    setMultiSelected(keys);
  }, []);

  const handleNodeDecision = useCallback(
    (key: string, decision: CurationDecisionType) => {
      setGraph((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          classes: prev.classes.map((c) =>
            c._key === key
              ? {
                  ...c,
                  status:
                    decision === "approve"
                      ? "approved"
                      : decision === "reject"
                        ? "rejected"
                        : c.status,
                }
              : c,
          ),
        };
      });
    },
    [],
  );

  const handleEdgeDecision = useCallback(
    (key: string, decision: CurationDecisionType) => {
      setGraph((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          edges: prev.edges.map((e) =>
            e._key === key
              ? {
                  ...e,
                  status:
                    decision === "approve"
                      ? "approved"
                      : decision === "reject"
                        ? "rejected"
                        : e.status,
                }
              : e,
          ),
        };
      });
    },
    [],
  );

  const handleBatchDecision = useCallback(
    (keys: string[], decision: CurationDecisionType) => {
      setGraph((prev) => {
        if (!prev) return prev;
        const keySet = new Set(keys);
        return {
          ...prev,
          classes: prev.classes.map((c) =>
            keySet.has(c._key)
              ? {
                  ...c,
                  status:
                    decision === "approve"
                      ? "approved"
                      : decision === "reject"
                        ? "rejected"
                        : c.status,
                }
              : c,
          ),
        };
      });
      setMultiSelected([]);
    },
    [],
  );

  const handleDescriptionChange = useCallback(
    (key: string, description: string) => {
      setGraph((prev) => {
        if (!prev) return prev;
        return {
          ...prev,
          classes: prev.classes.map((c) =>
            c._key === key ? { ...c, description } : c,
          ),
        };
      });
      api
        .post("/api/v1/curation/decide", {
          run_id: runId,
          entity_key: key,
          entity_type: "class",
          decision: "edit",
          after_state: { description },
        })
        .catch(() => {});
    },
    [runId],
  );

  const ontologyId = graph?.ontology_id ?? graph?.classes[0]?.ontology_id ?? "";
  const hasData = graph != null && graph.classes.length > 0;

  const handleTimestampChange = useCallback(
    async (timestamp: number) => {
      if (!ontologyId) return;
      setSnapshotLoading(true);
      try {
        const snapshot = await api.get<TemporalSnapshot>(
          `/api/v1/ontology/${ontologyId}/snapshot?at=${timestamp}`,
        );
        setGraph((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            classes: snapshot.classes,
            properties: snapshot.properties,
            edges: snapshot.edges,
          };
        });
        setSnapshotTimestamp(timestamp);
      } catch (err) {
        setError(
          err instanceof ApiError
            ? err.body.message
            : "Failed to load snapshot",
        );
      } finally {
        setSnapshotLoading(false);
      }
    },
    [ontologyId],
  );

  const returnToCurrent = useCallback(() => {
    setSnapshotTimestamp(null);
    fetchGraph();
  }, [fetchGraph]);

  const fetchDiff = useCallback(async () => {
    if (!ontologyId) return;
    setDiffLoading(true);
    setDiffError(null);
    try {
      const diff = await api.get<TemporalDiff>(
        `/api/v1/curation/diff/${runId}?ontology_id=${encodeURIComponent(ontologyId)}`,
      );
      setDiffData(diff);
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setDiffError("Diff not available for this run.");
      } else {
        setDiffError(
          err instanceof ApiError
            ? err.body.message
            : "Failed to load diff data",
        );
      }
      setDiffData(null);
    } finally {
      setDiffLoading(false);
    }
  }, [runId, ontologyId]);

  useEffect(() => {
    if (activePanel === "diff" && ontologyId) {
      fetchDiff();
    }
  }, [activePanel, ontologyId, fetchDiff]);

  const handleRevert = useCallback(
    (_classKey: string, _versionNumber: number) => {
      fetchGraph();
    },
    [fetchGraph],
  );

  const activeNodeKeys = useMemo(() => {
    if (!graph) return new Set<string>();
    return new Set(graph.classes.map((c) => c._key));
  }, [graph]);

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      {/* Header */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-[1600px] mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              Visual Curation
            </h1>
            <p className="text-sm text-gray-500">
              Staging run{" "}
              <span className="font-mono text-gray-600">{runId}</span>
            </p>
          </div>
          <div className="flex items-center gap-3">
            <div className="flex rounded-lg border border-gray-200 overflow-hidden">
              <button
                onClick={() => setColorMode("confidence")}
                disabled={!hasData}
                className={`text-xs px-3 py-1.5 ${colorMode === "confidence" ? "bg-blue-50 text-blue-700 font-medium" : "text-gray-500 hover:bg-gray-50"} disabled:opacity-40 disabled:cursor-not-allowed`}
              >
                Confidence
              </button>
              <button
                onClick={() => setColorMode("status")}
                disabled={!hasData}
                className={`text-xs px-3 py-1.5 border-l border-gray-200 ${colorMode === "status" ? "bg-blue-50 text-blue-700 font-medium" : "text-gray-500 hover:bg-gray-50"} disabled:opacity-40 disabled:cursor-not-allowed`}
              >
                Status
              </button>
            </div>
            <button
              onClick={() => setTimelineOpen(!timelineOpen)}
              disabled={!hasData}
              className={`text-xs px-3 py-1.5 border rounded-lg transition-colors ${timelineOpen ? "bg-violet-50 text-violet-700 border-violet-200" : "border-gray-200 text-gray-500 hover:bg-gray-50"} disabled:opacity-40 disabled:cursor-not-allowed`}
            >
              VCR Timeline
            </button>
            <button
              onClick={() => setActivePanel("diff")}
              disabled={!hasData}
              className="text-xs px-3 py-1.5 border border-gray-200 rounded-lg text-gray-500 hover:bg-gray-50 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Diff View
            </button>
            <button
              onClick={() => setActivePanel("promote")}
              disabled={!hasData}
              className="text-xs px-3 py-1.5 bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              Promote
            </button>
            <a
              href="/dashboard"
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Dashboard
            </a>
            <a
              href="/library"
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Library
            </a>
            <Link
              href="/"
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Home
            </Link>
          </div>
        </div>
      </header>

      {/* Historical snapshot banner */}
      {snapshotTimestamp && (
        <div className="bg-amber-50 border-b border-amber-200" data-testid="snapshot-banner">
          <div className="max-w-[1600px] mx-auto px-6 py-2 flex items-center justify-between">
            <div className="flex items-center gap-2 text-sm text-amber-800">
              <span className="inline-block h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
              Viewing historical snapshot at{" "}
              <span className="font-mono font-medium">
                {new Date(snapshotTimestamp * 1000).toLocaleString()}
              </span>
              {snapshotLoading && (
                <span className="text-amber-500 animate-pulse ml-2">Loading...</span>
              )}
            </div>
            <button
              onClick={returnToCurrent}
              className="text-xs px-3 py-1.5 bg-amber-600 text-white rounded-lg hover:bg-amber-700"
              data-testid="return-to-current"
            >
              Return to current
            </button>
          </div>
        </div>
      )}

      {/* Main content */}
      <div className="max-w-[1600px] mx-auto flex flex-col">
        <div className="flex flex-1 min-h-[calc(100vh-73px)]">
          {/* Graph viewport (~70%) */}
          <div className="flex-[7] flex flex-col">
            {loading && (
              <div className="flex-1 flex items-center justify-center">
                <p className="text-gray-400 animate-pulse">
                  Loading staging graph...
                </p>
              </div>
            )}

            {error && (
              <div className="flex-1 flex items-center justify-center p-8">
                <div className="text-center">
                  <p className="text-red-500 text-lg mb-2">{error}</p>
                  <button
                    onClick={fetchGraph}
                    className="text-sm px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                  >
                    Retry
                  </button>
                </div>
              </div>
            )}

            {!loading && !error && !hasData && (
              <div className="flex-1 flex items-center justify-center p-8">
                <div className="text-center max-w-md">
                  <div className="text-4xl text-gray-300 mb-4">
                    {"\u{1F50D}"}
                  </div>
                  <h2 className="text-lg font-semibold text-gray-700 mb-2">
                    No ontology data for this run
                  </h2>
                  <p className="text-sm text-gray-500 mb-4">
                    This extraction run does not have any materialized ontology classes.
                    It may have been created before auto-registration was enabled,
                    or the extraction may not have produced results.
                  </p>
                  <div className="flex gap-3 justify-center">
                    <a
                      href="/pipeline"
                      className="text-sm px-4 py-2 border border-gray-300 rounded-lg text-gray-600 hover:bg-gray-50"
                    >
                      Back to Pipeline
                    </a>
                    <a
                      href="/library"
                      className="text-sm px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                    >
                      Browse Library
                    </a>
                  </div>
                </div>
              </div>
            )}

            {!loading && !error && hasData && (
              <div className="flex-1 bg-white m-4 rounded-xl border border-gray-200 shadow-sm overflow-hidden relative">
                <GraphCanvas
                  classes={graph.classes}
                  properties={graph.properties}
                  edges={graph.edges}
                  selectedNodes={
                    selectedNodeKey ? [selectedNodeKey] : multiSelected
                  }
                  onNodeSelect={handleNodeSelect}
                  onEdgeSelect={handleEdgeSelect}
                  onSelectionChange={handleSelectionChange}
                  colorMode={colorMode}
                />
                {activePanel === "diff" && (
                  <DiffOverlay
                    diff={diffData}
                    activeNodeKeys={activeNodeKeys}
                  />
                )}
              </div>
            )}

            {/* VCR Timeline */}
            {timelineOpen && ontologyId && hasData && (
              <div className="mx-4 mb-4">
                <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
                  <VCRTimeline
                    ontologyId={ontologyId}
                    onTimestampChange={handleTimestampChange}
                  />
                </div>
              </div>
            )}
          </div>

          {/* Side panel (~30%) */}
          <aside className="flex-[3] bg-white border-l border-gray-200 overflow-y-auto">
            <div className="p-4 space-y-4">
              {activePanel === "detail" && selectedNode && (
                <>
                  <NodeDetail
                    node={selectedNode}
                    onDescriptionChange={handleDescriptionChange}
                    onShowProvenance={() => setActivePanel("provenance")}
                    onShowHistory={() => setActivePanel("history")}
                  />
                  <div className="border-t border-gray-100 pt-4">
                    <NodeActions
                      entityKey={selectedNode._key}
                      entityType="class"
                      runId={runId}
                      currentStatus={selectedNode.status}
                      onDecision={handleNodeDecision}
                    />
                  </div>
                </>
              )}

              {activePanel === "detail" && selectedEdge && (
                <EdgeActions
                  edgeKey={selectedEdge._key}
                  runId={runId}
                  currentType={selectedEdge.type}
                  currentLabel={selectedEdge.label}
                  onDecision={handleEdgeDecision}
                />
              )}

              {activePanel === "detail" && !selectedNode && !selectedEdge && (
                <div className="py-12 text-center">
                  <p className="text-gray-400 text-sm">
                    Select a node or edge to view details
                  </p>
                </div>
              )}

              {activePanel === "provenance" && selectedNode && (
                <ProvenancePanel
                  entityKey={selectedNode._key}
                  entityLabel={selectedNode.label}
                  onClose={() => setActivePanel("detail")}
                />
              )}

              {activePanel === "diff" && graph && (
                <>
                  <DiffView
                    runId={runId}
                    ontologyId={ontologyId}
                    onClose={() => setActivePanel("detail")}
                  />
                  {diffLoading && (
                    <div className="py-4 text-center text-sm text-gray-400 animate-pulse">
                      Loading diff overlay...
                    </div>
                  )}
                  {diffError && (
                    <div className="py-3 px-3 text-sm text-amber-700 bg-amber-50 rounded-lg">
                      {diffError}
                    </div>
                  )}
                </>
              )}

              {activePanel === "history" && selectedNode && (
                <EntityHistory
                  classKey={selectedNode._key}
                  onClose={() => setActivePanel("detail")}
                  onRevert={handleRevert}
                />
              )}

              {activePanel === "history" && !selectedNode && (
                <div className="py-12 text-center">
                  <p className="text-gray-400 text-sm">
                    Select a node to view its version history
                  </p>
                </div>
              )}

              {activePanel === "promote" && graph && (
                <PromotePanel
                  runId={runId}
                  classes={graph.classes}
                  onPromoted={() => fetchGraph()}
                />
              )}
            </div>
          </aside>
        </div>
      </div>

      {/* Batch actions bar */}
      <BatchActions
        selectedKeys={multiSelected}
        entityType="class"
        runId={runId}
        onBatchDecision={handleBatchDecision}
        onClearSelection={() => setMultiSelected([])}
      />
    </main>
  );
}
