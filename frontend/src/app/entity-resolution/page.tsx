"use client";

import { useEffect, useState, useCallback, useMemo } from "react";
import dynamic from "next/dynamic";
import { api, ApiError } from "@/lib/api-client";
import type { PaginatedResponse } from "@/lib/api-client";
import type {
  OntologyClass,
  OntologyProperty,
  OntologyEdge,
} from "@/types/curation";
import type {
  MergeCandidate,
  ERCluster,
  CrossTierDuplicate,
  EntityDetail,
  MergeResult,
  ExtractionClassification,
} from "@/types/entity-resolution";
import MergeCandidates from "@/components/curation/MergeCandidates";
import MergeExecutor from "@/components/curation/MergeExecutor";

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

type ActiveTab = "candidates" | "clusters" | "cross-tier";

interface GraphData {
  classes: OntologyClass[];
  properties: OntologyProperty[];
  edges: OntologyEdge[];
}

export default function EntityResolutionPage() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("candidates");
  const [selectedCandidate, setSelectedCandidate] = useState<MergeCandidate | null>(null);
  const [hoveredCandidate, setHoveredCandidate] = useState<MergeCandidate | null>(null);

  // Graph data for cluster visualization
  const [graphData, setGraphData] = useState<GraphData>({
    classes: [],
    properties: [],
    edges: [],
  });
  const [graphLoading, setGraphLoading] = useState(true);
  const [graphError, setGraphError] = useState<string | null>(null);

  // Clusters
  const [clusters, setClusters] = useState<ERCluster[]>([]);
  const [clustersLoading, setClustersLoading] = useState(false);

  // Cross-tier
  const [crossTierDuplicates, setCrossTierDuplicates] = useState<CrossTierDuplicate[]>([]);
  const [crossTierLoading, setCrossTierLoading] = useState(false);

  // Merge executor state
  const [entityLeft, setEntityLeft] = useState<EntityDetail | null>(null);
  const [entityRight, setEntityRight] = useState<EntityDetail | null>(null);
  const [entitiesLoading, setEntitiesLoading] = useState(false);

  const [allCandidates, setAllCandidates] = useState<MergeCandidate[]>([]);

  const handleCandidatesLoaded = useCallback((candidates: MergeCandidate[]) => {
    setAllCandidates(candidates);
  }, []);

  const fetchGraphData = useCallback(async () => {
    setGraphLoading(true);
    setGraphError(null);
    try {
      const res = await api.get<PaginatedResponse<OntologyClass>>(
        "/api/v1/er/graph",
      );
      setGraphData({
        classes: res.data,
        properties: [],
        edges: [],
      });
    } catch (err) {
      setGraphError(
        err instanceof ApiError
          ? err.body.message
          : "Failed to load graph data",
      );
    } finally {
      setGraphLoading(false);
    }
  }, []);

  const fetchClusters = useCallback(async () => {
    setClustersLoading(true);
    try {
      const res = await api.get<PaginatedResponse<ERCluster>>(
        "/api/v1/er/clusters",
      );
      setClusters(res.data);
    } catch {
      /* silent */
    } finally {
      setClustersLoading(false);
    }
  }, []);

  const fetchCrossTier = useCallback(async () => {
    setCrossTierLoading(true);
    try {
      const res = await api.get<PaginatedResponse<CrossTierDuplicate>>(
        "/api/v1/er/cross-tier",
      );
      setCrossTierDuplicates(res.data);
    } catch {
      /* silent */
    } finally {
      setCrossTierLoading(false);
    }
  }, []);

  const fetchEntityDetails = useCallback(async (candidate: MergeCandidate) => {
    setEntitiesLoading(true);
    try {
      const [left, right] = await Promise.all([
        api.get<EntityDetail>(
          `/api/v1/er/entity/${candidate.entity_1.key}`,
        ),
        api.get<EntityDetail>(
          `/api/v1/er/entity/${candidate.entity_2.key}`,
        ),
      ]);
      setEntityLeft(left);
      setEntityRight(right);
    } catch {
      setEntityLeft(null);
      setEntityRight(null);
    } finally {
      setEntitiesLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchGraphData();
  }, [fetchGraphData]);

  useEffect(() => {
    if (activeTab === "clusters") fetchClusters();
    if (activeTab === "cross-tier") fetchCrossTier();
  }, [activeTab, fetchClusters, fetchCrossTier]);

  const handleAcceptMerge = useCallback(
    (candidate: MergeCandidate) => {
      setSelectedCandidate(candidate);
      fetchEntityDetails(candidate);
    },
    [fetchEntityDetails],
  );

  const handleMerged = useCallback(
    (_result: MergeResult) => {
      setSelectedCandidate(null);
      setEntityLeft(null);
      setEntityRight(null);
      fetchGraphData();
    },
    [fetchGraphData],
  );

  const handleCloseExecutor = useCallback(() => {
    setSelectedCandidate(null);
    setEntityLeft(null);
    setEntityRight(null);
  }, []);

  const candidateMergePairs = useMemo(() => {
    if (hoveredCandidate) return [hoveredCandidate];
    return allCandidates;
  }, [hoveredCandidate, allCandidates]);

  const classificationMap = useMemo(() => {
    const map: Record<string, ExtractionClassification> = {};
    for (const cls of graphData.classes) {
      const raw = (cls as unknown as Record<string, unknown>).classification;
      if (raw === "EXISTING" || raw === "EXTENSION" || raw === "NEW") {
        map[cls._key] = raw;
      }
    }
    return map;
  }, [graphData.classes]);

  const tierMap = useMemo(() => {
    const map: Record<string, "domain" | "local"> = {};
    for (const cls of graphData.classes) {
      const raw = (cls as unknown as Record<string, unknown>).tier;
      if (raw === "domain" || raw === "local") {
        map[cls._key] = raw;
      }
    }
    return map;
  }, [graphData.classes]);

  const TABS: { id: ActiveTab; label: string }[] = [
    { id: "candidates", label: "Candidates" },
    { id: "clusters", label: "Clusters" },
    { id: "cross-tier", label: "Cross-Tier" },
  ];

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      {/* Header */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-[1600px] mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              Entity Resolution
            </h1>
            <p className="text-sm text-gray-500">
              Detect duplicates, review merge candidates, and manage clusters
            </p>
          </div>
          <div className="flex items-center gap-3">
            {/* Tab switcher */}
            <div className="flex rounded-lg border border-gray-200 overflow-hidden">
              {TABS.map((tab) => (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id)}
                  className={`text-xs px-3 py-1.5 ${
                    activeTab === tab.id
                      ? "bg-blue-50 text-blue-700 font-medium"
                      : "text-gray-500 hover:bg-gray-50"
                  } ${tab.id !== "candidates" ? "border-l border-gray-200" : ""}`}
                  data-testid={`tab-${tab.id}`}
                >
                  {tab.label}
                </button>
              ))}
            </div>
            <a
              href="/"
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Home
            </a>
          </div>
        </div>
      </header>

      {/* Main content */}
      <div className="max-w-[1600px] mx-auto flex min-h-[calc(100vh-73px)]">
        {/* Left panel: candidates / clusters / cross-tier list */}
        <aside className="w-[360px] border-r border-gray-200 bg-white overflow-y-auto">
          {activeTab === "candidates" && (
            <MergeCandidates
              onAcceptMerge={handleAcceptMerge}
              onCandidateHover={setHoveredCandidate}
              onCandidatesLoaded={handleCandidatesLoaded}
            />
          )}

          {activeTab === "clusters" && (
            <ClustersPanel
              clusters={clusters}
              loading={clustersLoading}
            />
          )}

          {activeTab === "cross-tier" && (
            <CrossTierPanel
              duplicates={crossTierDuplicates}
              loading={crossTierLoading}
            />
          )}
        </aside>

        {/* Center: Graph */}
        <div className="flex-1 flex flex-col">
          {graphLoading && (
            <div className="flex-1 flex items-center justify-center">
              <p className="text-gray-400 animate-pulse">
                Loading graph...
              </p>
            </div>
          )}

          {graphError && (
            <div className="flex-1 flex items-center justify-center p-8">
              <div className="text-center">
                <p className="text-red-500 text-lg mb-2">{graphError}</p>
                <button
                  onClick={fetchGraphData}
                  className="text-sm px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700"
                >
                  Retry
                </button>
              </div>
            </div>
          )}

          {!graphLoading && !graphError && (
            <div className="flex-1 m-4 bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
              <GraphCanvas
                classes={graphData.classes}
                properties={graphData.properties}
                edges={graphData.edges}
                colorMode={activeTab === "cross-tier" ? "tier" : "classification"}
                mergeCandidates={candidateMergePairs}
                showMergeCandidates={
                  activeTab === "candidates" && candidateMergePairs.length > 0
                }
                classificationMap={classificationMap}
                tierMap={tierMap}
              />
            </div>
          )}
        </div>

        {/* Right panel: Merge executor */}
        {selectedCandidate && (
          <aside className="w-[400px] border-l border-gray-200 bg-white overflow-y-auto">
            <MergeExecutor
              candidate={selectedCandidate}
              entityLeft={entityLeft}
              entityRight={entityRight}
              loading={entitiesLoading}
              onMerged={handleMerged}
              onClose={handleCloseExecutor}
            />
          </aside>
        )}
      </div>
    </main>
  );
}

// --- Clusters Panel ---

function ClustersPanel({
  clusters,
  loading,
}: {
  clusters: ERCluster[];
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="p-8 text-center">
        <p className="text-sm text-gray-400 animate-pulse">
          Loading clusters...
        </p>
      </div>
    );
  }

  if (clusters.length === 0) {
    return (
      <div className="p-8 text-center" data-testid="no-clusters">
        <p className="text-sm text-gray-400">No entity clusters found</p>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-3" data-testid="clusters-panel">
      <h2 className="text-sm font-semibold text-gray-900 mb-2">
        Entity Clusters ({clusters.length})
      </h2>
      {clusters.map((cluster) => (
        <div
          key={cluster.cluster_id}
          className="bg-gray-50 rounded-lg border border-gray-200 p-3"
          data-testid={`cluster-${cluster.cluster_id}`}
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs font-medium text-gray-700">
              Cluster {cluster.cluster_id}
            </span>
            <span className="text-xs text-gray-400">
              {cluster.entities.length} entities
            </span>
          </div>
          {cluster.golden_record_key && (
            <div className="mb-2">
              <span className="text-[10px] text-green-600 bg-green-50 px-1.5 py-0.5 rounded">
                Golden record: {cluster.golden_record_key}
              </span>
            </div>
          )}
          <ul className="space-y-1">
            {cluster.entities.map((entity) => (
              <li
                key={entity.key}
                className="flex items-center gap-2 text-xs"
              >
                <span
                  className={`h-1.5 w-1.5 rounded-full ${
                    entity.key === cluster.golden_record_key
                      ? "bg-green-500"
                      : "bg-gray-400"
                  }`}
                />
                <span className="text-gray-700 truncate flex-1">
                  {entity.label}
                </span>
                <span className="text-gray-400 font-mono text-[10px]">
                  {entity.key}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

// --- Cross-Tier Panel ---

function CrossTierPanel({
  duplicates,
  loading,
}: {
  duplicates: CrossTierDuplicate[];
  loading: boolean;
}) {
  if (loading) {
    return (
      <div className="p-8 text-center">
        <p className="text-sm text-gray-400 animate-pulse">
          Loading cross-tier duplicates...
        </p>
      </div>
    );
  }

  if (duplicates.length === 0) {
    return (
      <div className="p-8 text-center" data-testid="no-cross-tier">
        <p className="text-sm text-gray-400">No cross-tier duplicates found</p>
      </div>
    );
  }

  return (
    <div className="p-4 space-y-3" data-testid="cross-tier-panel">
      <h2 className="text-sm font-semibold text-gray-900 mb-2">
        Cross-Tier Duplicates ({duplicates.length})
      </h2>
      {duplicates.map((dup) => (
        <div
          key={dup.pair_id}
          className="bg-gray-50 rounded-lg border border-gray-200 p-3"
          data-testid={`cross-tier-${dup.pair_id}`}
        >
          <div className="flex items-center gap-2 mb-2">
            <div className="flex-1">
              <span className="text-[10px] text-blue-500 block">
                Domain (Tier 1)
              </span>
              <span className="text-sm font-medium text-gray-800">
                {dup.domain_entity.label}
              </span>
            </div>
            <span className="text-xs text-gray-400">&#8596;</span>
            <div className="flex-1 text-right">
              <span className="text-[10px] text-purple-500 block">
                Local (Tier 2)
              </span>
              <span className="text-sm font-medium text-gray-800">
                {dup.local_entity.label}
              </span>
            </div>
          </div>

          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1.5">
              <div className="w-16 h-1.5 bg-gray-200 rounded-full overflow-hidden">
                <div
                  className={`h-full rounded-full ${dup.overall_score >= 0.8 ? "bg-green-500" : dup.overall_score >= 0.5 ? "bg-yellow-500" : "bg-red-500"}`}
                  style={{ width: `${dup.overall_score * 100}%` }}
                />
              </div>
              <span className="text-xs font-mono text-gray-600">
                {(dup.overall_score * 100).toFixed(0)}%
              </span>
            </div>
            <span
              className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                dup.suggested_relation === "owl:equivalentClass"
                  ? "bg-blue-50 text-blue-700"
                  : "bg-purple-50 text-purple-700"
              }`}
            >
              {dup.suggested_relation}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}
