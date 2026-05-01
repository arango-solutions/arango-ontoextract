"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import dynamic from "next/dynamic";
import { api } from "@/lib/api-client";
import { withBasePath } from "@/lib/base-path";
import RunList from "@/components/pipeline/RunList";
import RunMetrics from "@/components/pipeline/RunMetrics";
import ErrorLog from "@/components/pipeline/ErrorLog";
import RunTimeline from "@/components/pipeline/RunTimeline";
import PipelineHistorySlider from "@/components/pipeline/PipelineHistorySlider";
import { useExtractionSocket } from "@/lib/use-websocket";

const AgentDAG = dynamic(() => import("@/components/pipeline/AgentDAG"), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full text-gray-400 animate-pulse">
      Loading pipeline graph…
    </div>
  ),
});

type DetailTab = "metrics" | "errors" | "timeline";

export default function PipelineMonitor() {
  return (
    <Suspense>
      <PipelineMonitorInner />
    </Suspense>
  );
}

function PipelineMonitorInner() {
  const searchParams = useSearchParams();
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);

  // Sync from URL search params (runs after hydration, avoiding SSR mismatch)
  useEffect(() => {
    const runIdParam = searchParams.get("runId");
    if (runIdParam !== selectedRunId) {
      setSelectedRunId(runIdParam);
    }
  }, [searchParams, selectedRunId]);
  const [activeTab, setActiveTab] = useState<DetailTab>("metrics");
  const { steps, isConnected, error: wsError } = useExtractionSocket(selectedRunId);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [resetBusy, setResetBusy] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [runListKey, setRunListKey] = useState(0);

  async function handleReset(full: boolean) {
    const msg = full
      ? "This will delete ALL data including documents and chunks. Continue?"
      : "This will delete all ontology data (classes, properties, edges, runs, registry). Documents and chunks are preserved so you can re-extract. Continue?";
    if (!confirm(msg)) return;
    setResetBusy(true);
    try {
      const endpoint = full ? "/api/v1/admin/reset/full" : "/api/v1/admin/reset";
      const result = await api.post<{ reset: boolean; collections_truncated: string[] }>(endpoint);
      alert(`Reset complete. Truncated: ${result.collections_truncated.join(", ")}`);
      setSelectedRunId(null);
      setRunListKey((k) => k + 1);
    } catch (err) {
      alert(`Reset failed: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setResetBusy(false);
    }
  }

  // Stable handler so child components (RunList, PipelineHistorySlider) don't
  // see a new reference on every parent render — which would re-fire their
  // dependent effects and (combined with bidirectional sync) used to spin the
  // page into a render loop.
  const handleSelectRun = useCallback((id: string) => {
    setSelectedRunId(id);
    setSidebarOpen(false);
  }, []);

  const tabs: { key: DetailTab; label: string }[] = [
    { key: "metrics", label: "Metrics" },
    { key: "errors", label: "Errors" },
    { key: "timeline", label: "Timeline" },
  ];

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-[1600px] mx-auto px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              Pipeline Monitor
            </h1>
            <p className="text-sm text-gray-500">
              Real-time extraction pipeline dashboard
            </p>
          </div>
          <div className="flex items-center gap-3">
            {selectedRunId && (
              <div className="flex items-center gap-2 text-xs">
                <span
                  className={`inline-block h-2 w-2 rounded-full ${isConnected ? "bg-green-500" : "bg-gray-300"}`}
                />
                <span className="text-gray-500">
                  {isConnected ? "Live" : "Disconnected"}
                </span>
              </div>
            )}
            <div className="relative">
              <button
                disabled={resetBusy}
                onClick={() => setResetOpen((v) => !v)}
                onBlur={() => setTimeout(() => setResetOpen(false), 150)}
                className="text-xs px-3 py-1.5 border border-red-200 text-red-500 rounded-lg hover:bg-red-50 disabled:opacity-40 transition-colors"
              >
                {resetBusy ? "Resetting\u2026" : "Reset \u25BE"}
              </button>
              {resetOpen && (
                <div className="absolute right-0 mt-1 w-56 bg-white border border-gray-200 rounded-lg shadow-lg z-20">
                  <button
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => { setResetOpen(false); handleReset(false); }}
                    disabled={resetBusy}
                    className="w-full text-left px-3 py-2 text-xs text-gray-700 hover:bg-gray-50 rounded-t-lg"
                  >
                    Reset Ontology Data
                    <span className="block text-gray-400 mt-0.5">Keeps documents &amp; chunks</span>
                  </button>
                  <button
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => { setResetOpen(false); handleReset(true); }}
                    disabled={resetBusy}
                    className="w-full text-left px-3 py-2 text-xs text-red-600 hover:bg-red-50 border-t border-gray-100 rounded-b-lg"
                  >
                    Full Reset
                    <span className="block text-red-400 mt-0.5">Deletes everything</span>
                  </button>
                </div>
              )}
            </div>
            <button
              onClick={() => setSidebarOpen(!sidebarOpen)}
              className="md:hidden text-sm px-3 py-1.5 border border-gray-300 rounded-lg hover:bg-gray-50"
            >
              {sidebarOpen ? "Hide Runs" : "Show Runs"}
            </button>
            <Link
              href="/workspace"
              className="text-sm font-medium text-indigo-600 hover:text-indigo-800"
            >
              Workspace
            </Link>
            <Link
              href="/dashboard"
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Dashboard
            </Link>
            {/* Raw <a> so the trailing slash survives — Next <Link href="/"> drops it. */}
            <a
              href={withBasePath("/")}
              className="text-sm text-gray-500 hover:text-gray-700"
            >
              Home
            </a>
          </div>
        </div>
      </header>

      <div className="max-w-[1600px] mx-auto flex flex-col md:flex-row">
        {/* Sidebar: Run List */}
        <aside
          className={`${sidebarOpen ? "block" : "hidden"} md:block w-full md:w-[350px] flex-shrink-0 bg-white border-r border-gray-200 md:min-h-[calc(100vh-73px)]`}
        >
          <RunList
            key={runListKey}
            onSelectRun={handleSelectRun}
            selectedRunId={selectedRunId}
          />
        </aside>

        {/* Main content area */}
        <div className="flex-1 flex flex-col min-h-[calc(100vh-73px)]">
          {/* Pipeline history slider — always visible */}
          <PipelineHistorySlider
            onSelectRun={handleSelectRun}
            selectedRunId={selectedRunId}
          />

          {!selectedRunId ? (
            <div className="flex-1 flex items-center justify-center p-8">
              <div className="text-center">
                <div className="text-4xl text-gray-300 mb-3">
                  {"\u2B50"}
                </div>
                <p className="text-gray-500 text-lg">
                  Select an extraction run to view its pipeline
                </p>
                <p className="text-gray-400 text-sm mt-1">
                  Choose from the run list on the left
                </p>
              </div>
            </div>
          ) : (
            <>
              {/* WebSocket error banner */}
              {wsError && (
                <div className="mx-4 mt-4 px-4 py-2 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-800">
                  WebSocket: {wsError}
                </div>
              )}

              {/* Agent DAG */}
              <div className="flex-1 p-4 min-h-[400px]">
                <div className="bg-white rounded-xl border border-gray-200 shadow-sm h-full overflow-hidden">
                  <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
                    <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide">
                      Agent Pipeline
                    </h2>
                    <div className="flex items-center gap-3">
                      <span className="text-xs text-gray-400 font-mono">
                        {selectedRunId}
                      </span>
                      <a
                        href={withBasePath(`/workspace?ontologyId=${selectedRunId}`)}
                        className="text-xs px-3 py-1 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors"
                      >
                        Open in Workspace
                      </a>
                      <a
                        href={withBasePath(`/curation?runId=${selectedRunId}`)}
                        className="text-xs px-3 py-1 border border-gray-200 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
                      >
                        Curate (Legacy)
                      </a>
                    </div>
                  </div>
                  <div className="h-[calc(100%-48px)]">
                    <AgentDAG steps={steps} />
                  </div>
                </div>
              </div>

              {/* Tabs: Metrics / Errors / Timeline */}
              <div className="border-t border-gray-200 bg-white">
                <div className="flex border-b border-gray-200 px-4">
                  {tabs.map((tab) => (
                    <button
                      key={tab.key}
                      onClick={() => setActiveTab(tab.key)}
                      className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                        activeTab === tab.key
                          ? "border-blue-500 text-blue-600"
                          : "border-transparent text-gray-500 hover:text-gray-700"
                      }`}
                    >
                      {tab.label}
                    </button>
                  ))}
                </div>

                <div className="max-h-[300px] overflow-y-auto">
                  {activeTab === "metrics" && (
                    <RunMetrics runId={selectedRunId} />
                  )}
                  {activeTab === "errors" && (
                    <ErrorLog steps={steps} runId={selectedRunId} />
                  )}
                  {activeTab === "timeline" && (
                    <RunTimeline steps={steps} />
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </main>
  );
}
