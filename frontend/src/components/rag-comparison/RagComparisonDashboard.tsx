"use client";

import { useState, useMemo } from "react";
import dynamic from "next/dynamic";
import type { RagComparisonData } from "@/types/curation";
import { MOCK_DATASETS, getMockRagComparison } from "@/lib/mock-rag-data";
import RagComparisonSummary from "./RagComparisonSummary";
import RagCostLatency from "./RagCostLatency";
import RagQueryTable from "./RagQueryTable";

const RagScoreComparison = dynamic(() => import("./RagScoreComparison"), {
  ssr: false,
});
const RagQueryTypeRadar = dynamic(() => import("./RagQueryTypeRadar"), {
  ssr: false,
});
const RagWinLoss = dynamic(() => import("./RagWinLoss"), { ssr: false });

export default function RagComparisonDashboard() {
  const [datasetId, setDatasetId] = useState(MOCK_DATASETS[0].id);

  const data: RagComparisonData = useMemo(
    () => getMockRagComparison(datasetId),
    [datasetId],
  );

  return (
    <div className="space-y-6">
      {/* Dataset selector + info */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm px-6 py-4 flex items-center justify-between flex-wrap gap-4">
        <div>
          <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
            Evaluation Dataset
          </p>
          <p className="text-sm text-gray-600 mt-0.5">
            {data.dataset.description} &middot;{" "}
            <span className="font-medium">{data.dataset.query_count} queries</span>
          </p>
        </div>
        <select
          value={datasetId}
          onChange={(e) => setDatasetId(e.target.value)}
          className="text-sm border border-gray-200 rounded-lg px-3 py-2 text-gray-700 bg-white"
        >
          {MOCK_DATASETS.map((ds) => (
            <option key={ds.id} value={ds.id}>
              {ds.name}
            </option>
          ))}
        </select>
      </div>

      {/* Top-level headline cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <HeadlineCard
          label="GraphRAG Avg Score"
          value={avgQuality(data.graph_rag_summary).toFixed(2)}
          color="text-indigo-700"
        />
        <HeadlineCard
          label="VectorRAG Avg Score"
          value={avgQuality(data.vector_rag_summary).toFixed(2)}
          color="text-orange-600"
        />
        <HeadlineCard
          label="GraphRAG Win Rate"
          value={`${((data.win_loss.graph_wins / data.dataset.query_count) * 100).toFixed(0)}%`}
          color="text-indigo-700"
        />
        <HeadlineCard
          label="Cost Premium"
          value={`${((data.graph_rag_summary.avg_cost_per_query / data.vector_rag_summary.avg_cost_per_query - 1) * 100).toFixed(0)}%`}
          color="text-gray-700"
          subtitle="per query"
        />
      </div>

      {/* Charts row */}
      <div className="grid gap-6 lg:grid-cols-2">
        <RagScoreComparison
          graphRag={data.graph_rag_summary}
          vectorRag={data.vector_rag_summary}
        />
        <RagQueryTypeRadar breakdown={data.query_type_breakdown} />
      </div>

      {/* Metrics + Win/Loss + Cost row */}
      <div className="grid gap-6 lg:grid-cols-[1fr_280px]">
        <RagComparisonSummary
          graphRag={data.graph_rag_summary}
          vectorRag={data.vector_rag_summary}
        />
        <div className="space-y-6">
          <RagWinLoss winLoss={data.win_loss} />
          <RagCostLatency
            graphRag={data.graph_rag_summary}
            vectorRag={data.vector_rag_summary}
            indexCost={data.index_build_cost}
            queryCount={data.dataset.query_count}
          />
        </div>
      </div>

      {/* Per-query table */}
      <RagQueryTable queries={data.queries} />
    </div>
  );
}

/* ── Helpers ─────────────────────────────────────────── */

function avgQuality(s: RagComparisonData["graph_rag_summary"]): number {
  return (
    (s.answer_faithfulness +
      s.answer_relevance +
      s.context_precision +
      s.context_recall) /
    4
  );
}

function HeadlineCard({
  label,
  value,
  color,
  subtitle,
}: {
  label: string;
  value: string;
  color: string;
  subtitle?: string;
}) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
      <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
        {label}
      </p>
      <p className={`mt-2 text-2xl font-bold ${color}`}>{value}</p>
      {subtitle && <p className="mt-1 text-xs text-gray-400">{subtitle}</p>}
    </div>
  );
}
