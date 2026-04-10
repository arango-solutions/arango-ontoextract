"use client";

import { Suspense, useEffect, useState, useCallback } from "react";
import Link from "next/link";
import dynamic from "next/dynamic";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { QualityDashboard, OntologyScorecard } from "@/types/curation";
import { api, ApiError } from "@/lib/api-client";
import SummaryCards from "@/components/dashboard/SummaryCards";
import OntologyScoreTable from "@/components/dashboard/OntologyScoreTable";
import MetricCards from "@/components/dashboard/MetricCards";
import AlertsFlags from "@/components/dashboard/AlertsFlags";
import StrengthsWeaknesses from "@/components/dashboard/StrengthsWeaknesses";
import SchemaMetricsPanel from "@/components/dashboard/SchemaMetricsPanel";
import PerOntologyQualityReport from "@/components/dashboard/PerOntologyQualityReport";

/** Dashboard aggregates every ontology with many AQL queries each; short client timeouts were aborting healthy backends. */
const DASHBOARD_FETCH_TIMEOUT_MS = 120_000;

const RadarMetricChart = dynamic(
  () => import("@/components/dashboard/RadarMetricChart"),
  { ssr: false },
);

const ClassScoreDistribution = dynamic(
  () => import("@/components/dashboard/ClassScoreDistribution"),
  { ssr: false },
);

type DashboardTab = "quality" | "per-ontology-quality";

export default function DashboardPage() {
  return (
    <Suspense fallback={<main className="min-h-screen bg-gray-50 flex items-center justify-center text-gray-500">Loading…</main>}>
      <DashboardPageInner />
    </Suspense>
  );
}

function DashboardPageInner() {
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const tabFromUrl = searchParams.get("tab");
  const [activeTab, setActiveTab] = useState<DashboardTab>(() =>
    tabFromUrl === "per-ontology-quality" || tabFromUrl === "rag-comparison"
      ? "per-ontology-quality"
      : "quality",
  );
  const [data, setData] = useState<QualityDashboard | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const fetchDashboard = useCallback(async () => {
    setLoading(true);
    setError(null);
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), DASHBOARD_FETCH_TIMEOUT_MS);
    try {
      const json = await api.get<QualityDashboard>("/api/v1/quality/dashboard", {
        signal: controller.signal,
      });
      setData(json);
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        setError(
          `Request timed out after ${DASHBOARD_FETCH_TIMEOUT_MS / 1000}s. The server builds scores for every ontology and can take a while. If the backend is running, try Refresh or reduce workloads.`,
        );
      } else if (err instanceof ApiError) {
        setError(err.body.message || `Request failed (${err.status})`);
      } else {
        setError("Failed to load dashboard data. Is the backend running?");
      }
    } finally {
      clearTimeout(timeout);
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeTab !== "quality") return;
    void fetchDashboard();
  }, [fetchDashboard, activeTab]);

  useEffect(() => {
    if (tabFromUrl === "per-ontology-quality" || tabFromUrl === "rag-comparison") {
      setActiveTab("per-ontology-quality");
    } else if (tabFromUrl === "quality") {
      setActiveTab("quality");
    }
  }, [tabFromUrl]);

  const setDashboardTab = useCallback(
    (key: DashboardTab) => {
      setActiveTab(key);
      const params = new URLSearchParams(searchParams.toString());
      if (key === "per-ontology-quality") {
        params.set("tab", "per-ontology-quality");
      } else {
        params.delete("tab");
      }
      const q = params.toString();
      router.replace(q ? `${pathname}?${q}` : pathname, { scroll: false });
    },
    [pathname, router, searchParams],
  );

  const selectedOntology: OntologyScorecard | null =
    data?.ontologies.find((o) => o.ontology_id === selectedId) ?? null;

  const TABS: { key: DashboardTab; label: string; subtitle: string }[] = [
    {
      key: "quality",
      label: "Quality Dashboard",
      subtitle: "Ontology quality scores, LLM-as-judge metrics, and extraction cost",
    },
    {
      key: "per-ontology-quality",
      label: "Per-Ontology Quality",
      subtitle: "Live six-dimension radar, score cards, and schema metrics per ontology",
    },
  ];

  const currentTab = TABS.find((t) => t.key === activeTab)!;

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      {/* Header */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-[1600px] mx-auto px-6 pt-4">
          <div className="flex items-center justify-between mb-3">
            <div>
              <h1 className="text-xl font-bold tracking-tight">
                {currentTab.label}
              </h1>
              <p className="text-sm text-gray-500">{currentTab.subtitle}</p>
            </div>
            <div className="flex items-center gap-3">
              {activeTab === "quality" && (
                <button
                  onClick={fetchDashboard}
                  disabled={loading}
                  className="text-xs px-3 py-1.5 border border-gray-200 rounded-lg text-gray-500 hover:bg-gray-50 disabled:opacity-40"
                >
                  Refresh
                </button>
              )}
              <Link href="/workspace" className="text-sm font-medium text-indigo-600 hover:text-indigo-800">
                Workspace
              </Link>
              <Link href="/library" className="text-sm text-gray-500 hover:text-gray-700">
                Library
              </Link>
              <Link href="/" className="text-sm text-gray-500 hover:text-gray-700">
                Home
              </Link>
            </div>
          </div>

          {/* Tab bar */}
          <nav className="flex gap-0 -mb-px">
            {TABS.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setDashboardTab(tab.key)}
                className={`px-4 py-2.5 text-sm font-medium border-b-2 transition-colors ${
                  activeTab === tab.key
                    ? "border-indigo-600 text-indigo-700"
                    : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
      </header>

      <div className="max-w-[1600px] mx-auto px-6 py-6 space-y-6">
        {/* ── Per-ontology quality (restored from pre-mock dashboard) ── */}
        {activeTab === "per-ontology-quality" && <PerOntologyQualityReport />}

        {/* ── Quality Tab ───────────────────────────────── */}
        {activeTab === "quality" && (
          <>
            {/* Loading */}
            {loading && !data && (
              <div className="flex flex-col items-center justify-center py-20 gap-2">
                <p className="text-gray-400 animate-pulse">Loading dashboard…</p>
                <p className="text-xs text-gray-400 max-w-md text-center">
                  Computing quality for each ontology can take up to a few minutes on large libraries.
                </p>
              </div>
            )}

            {/* Error */}
            {error && (
              <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center">
                <p className="text-red-600 mb-3">{error}</p>
                <button
                  onClick={fetchDashboard}
                  className="text-sm px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700"
                >
                  Retry
                </button>
              </div>
            )}

            {data && (
              <>
                {/* Summary cards */}
                <SummaryCards summary={data.summary} />

                {/* Alerts */}
                <AlertsFlags alerts={data.alerts} />

                {selectedOntology ? (
                  <section className="space-y-6">
                    <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
                      <div className="border-b border-gray-100 px-6 py-5">
                        <div className="flex items-start justify-between gap-6">
                          <div>
                            <button
                              onClick={() => setSelectedId(null)}
                              className="text-sm font-medium text-gray-500 transition hover:text-gray-800"
                            >
                              ← Back to Per-Ontology Scores
                            </button>
                            <p className="mt-4 text-xs font-semibold uppercase tracking-[0.18em] text-gray-400">
                              Ontology Detail
                            </p>
                            <h2 className="mt-1 text-2xl font-bold tracking-tight text-gray-900">
                              {selectedOntology.name}
                            </h2>
                            <p className="mt-1 text-sm text-gray-500">
                              {selectedOntology.class_count} classes, {selectedOntology.property_count} properties
                            </p>
                          </div>
                          <div className="flex items-center gap-3">
                            <span
                              className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                                selectedOntology.tier === "domain"
                                  ? "bg-blue-50 text-blue-700"
                                  : "bg-purple-50 text-purple-700"
                              }`}
                            >
                              {selectedOntology.tier}
                            </span>
                            {selectedOntology.health_score !== null && (
                              <span
                                className={`text-sm font-bold px-2.5 py-0.5 rounded-full ${
                                  selectedOntology.health_score >= 70
                                    ? "bg-green-100 text-green-800"
                                    : selectedOntology.health_score >= 50
                                      ? "bg-yellow-100 text-yellow-800"
                                      : "bg-red-100 text-red-800"
                                }`}
                              >
                                {selectedOntology.health_score}
                              </span>
                            )}
                          </div>
                        </div>
                      </div>

                      <div className="space-y-6 p-6">
                        <MetricCards ontology={selectedOntology} />
                        <SchemaMetricsPanel schemaMetrics={selectedOntology.schema_metrics} />

                        <div className="grid gap-6 xl:grid-cols-[minmax(0,1.15fr)_minmax(0,0.85fr)]">
                          <div className="space-y-6">
                            <RadarMetricChart
                              ontologies={data.ontologies}
                              selectedIds={[selectedOntology.ontology_id]}
                            />
                            <ClassScoreDistribution ontologyId={selectedOntology.ontology_id} />
                          </div>
                          <StrengthsWeaknesses ontologyId={selectedOntology.ontology_id} />
                        </div>
                      </div>
                    </div>
                  </section>
                ) : (
                  <OntologyScoreTable
                    ontologies={data.ontologies}
                    selectedId={selectedId}
                    onSelect={setSelectedId}
                  />
                )}
              </>
            )}
          </>
        )}
      </div>
    </main>
  );
}
