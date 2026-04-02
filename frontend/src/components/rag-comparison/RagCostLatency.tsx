"use client";

import type { RagMetricSummary, RagIndexBuildCost } from "@/types/curation";

interface Props {
  graphRag: RagMetricSummary;
  vectorRag: RagMetricSummary;
  indexCost: {
    graph_rag: RagIndexBuildCost;
    vector_rag: RagIndexBuildCost;
  };
  queryCount: number;
}

function Row({
  label,
  graphVal,
  vectorVal,
  highlight,
}: {
  label: string;
  graphVal: string;
  vectorVal: string;
  highlight?: "graph" | "vector";
}) {
  return (
    <tr className="border-b border-gray-50 last:border-0">
      <td className="py-2.5 pr-4 text-sm text-gray-600">{label}</td>
      <td
        className={`py-2.5 text-sm font-medium text-center ${
          highlight === "graph" ? "text-green-700 bg-green-50/50" : "text-gray-800"
        }`}
      >
        {graphVal}
      </td>
      <td
        className={`py-2.5 text-sm font-medium text-center ${
          highlight === "vector" ? "text-green-700 bg-green-50/50" : "text-gray-800"
        }`}
      >
        {vectorVal}
      </td>
    </tr>
  );
}

export default function RagCostLatency({
  graphRag,
  vectorRag,
  indexCost,
  queryCount,
}: Props) {
  const totalGraphCost =
    indexCost.graph_rag.cost_usd + graphRag.avg_cost_per_query * queryCount;
  const totalVectorCost =
    indexCost.vector_rag.cost_usd + vectorRag.avg_cost_per_query * queryCount;

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
      <h3 className="text-sm font-semibold text-gray-700 mb-4">
        Cost &amp; Latency Analysis
      </h3>

      <table className="w-full">
        <thead>
          <tr className="border-b border-gray-200">
            <th className="text-left text-xs font-semibold text-gray-400 uppercase tracking-wide pb-2">
              Metric
            </th>
            <th className="text-center text-xs font-semibold text-indigo-500 uppercase tracking-wide pb-2">
              GraphRAG
            </th>
            <th className="text-center text-xs font-semibold text-orange-500 uppercase tracking-wide pb-2">
              VectorRAG
            </th>
          </tr>
        </thead>
        <tbody>
          <Row
            label="Index Build Time"
            graphVal={`${indexCost.graph_rag.time_s}s`}
            vectorVal={`${indexCost.vector_rag.time_s}s`}
            highlight="vector"
          />
          <Row
            label="Index Build Cost"
            graphVal={`$${indexCost.graph_rag.cost_usd.toFixed(2)}`}
            vectorVal={`$${indexCost.vector_rag.cost_usd.toFixed(2)}`}
            highlight="vector"
          />
          <Row
            label="Storage"
            graphVal={`${indexCost.graph_rag.storage_mb} MB`}
            vectorVal={`${indexCost.vector_rag.storage_mb} MB`}
            highlight="vector"
          />
          <Row
            label="Avg Query Latency"
            graphVal={`${graphRag.avg_latency_ms.toLocaleString()}ms`}
            vectorVal={`${vectorRag.avg_latency_ms.toLocaleString()}ms`}
            highlight="vector"
          />
          <Row
            label="Avg Tokens / Query"
            graphVal={graphRag.avg_tokens_used.toLocaleString()}
            vectorVal={vectorRag.avg_tokens_used.toLocaleString()}
            highlight="vector"
          />
          <Row
            label="Cost / Query"
            graphVal={`$${graphRag.avg_cost_per_query.toFixed(4)}`}
            vectorVal={`$${vectorRag.avg_cost_per_query.toFixed(4)}`}
            highlight="vector"
          />
          <Row
            label={`Total Cost (${queryCount} queries)`}
            graphVal={`$${totalGraphCost.toFixed(2)}`}
            vectorVal={`$${totalVectorCost.toFixed(2)}`}
            highlight={totalGraphCost < totalVectorCost ? "graph" : "vector"}
          />
        </tbody>
      </table>

      <div className="mt-4 p-3 bg-gray-50 rounded-lg">
        <p className="text-xs text-gray-500">
          GraphRAG has higher upfront cost ({((indexCost.graph_rag.cost_usd / indexCost.vector_rag.cost_usd)).toFixed(1)}x build cost) but delivers{" "}
          <span className="font-semibold text-indigo-600">
            {(((graphRag.answer_faithfulness - vectorRag.answer_faithfulness) / vectorRag.answer_faithfulness) * 100).toFixed(0)}% higher faithfulness
          </span>{" "}
          and{" "}
          <span className="font-semibold text-indigo-600">
            {(((graphRag.context_recall - vectorRag.context_recall) / vectorRag.context_recall) * 100).toFixed(0)}% better context recall
          </span>.
        </p>
      </div>
    </div>
  );
}
