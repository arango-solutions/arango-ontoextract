"use client";

import { useState } from "react";
import type { RagQueryResult } from "@/types/curation";

interface Props {
  queries: RagQueryResult[];
}

const TYPE_LABELS: Record<string, string> = {
  multi_hop: "Multi-Hop",
  factual: "Factual",
  aggregation: "Aggregation",
  comparison: "Comparison",
  temporal: "Temporal",
};

const TYPE_COLORS: Record<string, string> = {
  multi_hop: "bg-purple-50 text-purple-700",
  factual: "bg-blue-50 text-blue-700",
  aggregation: "bg-amber-50 text-amber-700",
  comparison: "bg-emerald-50 text-emerald-700",
  temporal: "bg-rose-50 text-rose-700",
};

const WINNER_BADGE: Record<string, string> = {
  graph: "bg-indigo-100 text-indigo-700",
  vector: "bg-orange-100 text-orange-700",
  tie: "bg-gray-100 text-gray-600",
};

function scoreColor(v: number): string {
  if (v >= 0.8) return "text-green-700";
  if (v >= 0.6) return "text-yellow-600";
  return "text-red-600";
}

function ScorePill({ label, graph, vector }: { label: string; graph: number; vector: number }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-20 text-gray-500">{label}</span>
      <span className={`font-semibold ${scoreColor(graph)}`}>{graph.toFixed(2)}</span>
      <span className="text-gray-300">vs</span>
      <span className={`font-semibold ${scoreColor(vector)}`}>{vector.toFixed(2)}</span>
    </div>
  );
}

export default function RagQueryTable({ queries }: Props) {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<string>("all");
  const [winnerFilter, setWinnerFilter] = useState<string>("all");

  const filtered = queries.filter((q) => {
    if (typeFilter !== "all" && q.query_type !== typeFilter) return false;
    if (winnerFilter !== "all" && q.winner !== winnerFilter) return false;
    return true;
  });

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm">
      <div className="px-6 py-4 border-b border-gray-100 flex items-center justify-between flex-wrap gap-3">
        <h3 className="text-sm font-semibold text-gray-700">
          Per-Query Results{" "}
          <span className="text-gray-400 font-normal">({filtered.length})</span>
        </h3>
        <div className="flex items-center gap-2">
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 text-gray-600 bg-white"
          >
            <option value="all">All Types</option>
            <option value="multi_hop">Multi-Hop</option>
            <option value="factual">Factual</option>
            <option value="aggregation">Aggregation</option>
            <option value="comparison">Comparison</option>
            <option value="temporal">Temporal</option>
          </select>
          <select
            value={winnerFilter}
            onChange={(e) => setWinnerFilter(e.target.value)}
            className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 text-gray-600 bg-white"
          >
            <option value="all">All Winners</option>
            <option value="graph">GraphRAG Wins</option>
            <option value="vector">VectorRAG Wins</option>
            <option value="tie">Ties</option>
          </select>
        </div>
      </div>

      <div className="divide-y divide-gray-50">
        {filtered.map((q) => {
          const expanded = expandedId === q.id;
          return (
            <div key={q.id}>
              {/* Row header */}
              <button
                onClick={() => setExpandedId(expanded ? null : q.id)}
                className="w-full px-6 py-3 flex items-start gap-3 text-left hover:bg-gray-50/50 transition"
              >
                <span className="mt-0.5 text-gray-400 text-xs">
                  {expanded ? "▼" : "▶"}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm text-gray-800 truncate">{q.query}</p>
                  <div className="flex items-center gap-2 mt-1">
                    <span
                      className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                        TYPE_COLORS[q.query_type] ?? "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {TYPE_LABELS[q.query_type] ?? q.query_type}
                    </span>
                    <span
                      className={`text-[10px] font-medium px-1.5 py-0.5 rounded ${
                        WINNER_BADGE[q.winner]
                      }`}
                    >
                      {q.winner === "graph"
                        ? "GraphRAG"
                        : q.winner === "vector"
                          ? "VectorRAG"
                          : "Tie"}
                    </span>
                  </div>
                </div>
                <div className="flex gap-4 shrink-0">
                  <div className="text-right">
                    <p className="text-[10px] text-indigo-500 font-medium">GraphRAG</p>
                    <p className={`text-sm font-bold ${scoreColor(q.graph_rag.faithfulness)}`}>
                      {q.graph_rag.faithfulness.toFixed(2)}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="text-[10px] text-orange-500 font-medium">VectorRAG</p>
                    <p className={`text-sm font-bold ${scoreColor(q.vector_rag.faithfulness)}`}>
                      {q.vector_rag.faithfulness.toFixed(2)}
                    </p>
                  </div>
                </div>
              </button>

              {/* Expanded detail */}
              {expanded && (
                <div className="px-6 pb-5 pt-1 bg-gray-50/30">
                  {/* Ground truth */}
                  <div className="mb-4 p-3 bg-emerald-50 border border-emerald-100 rounded-lg">
                    <p className="text-xs font-semibold text-emerald-700 mb-1">
                      Ground Truth
                    </p>
                    <p className="text-sm text-emerald-900">{q.ground_truth}</p>
                  </div>

                  <div className="grid md:grid-cols-2 gap-4">
                    {/* GraphRAG side */}
                    <div className="border border-indigo-100 rounded-lg p-4 bg-white">
                      <p className="text-xs font-semibold text-indigo-600 mb-2">
                        GraphRAG Answer
                      </p>
                      <p className="text-sm text-gray-800 mb-3">
                        {q.graph_rag.answer}
                      </p>
                      <div className="space-y-1.5 mb-3">
                        <ScorePill label="Faithful" graph={q.graph_rag.faithfulness} vector={q.vector_rag.faithfulness} />
                        <ScorePill label="Relevant" graph={q.graph_rag.relevance} vector={q.vector_rag.relevance} />
                        <ScorePill label="Ctx Prec" graph={q.graph_rag.context_precision} vector={q.vector_rag.context_precision} />
                        <ScorePill label="Ctx Recall" graph={q.graph_rag.context_recall} vector={q.vector_rag.context_recall} />
                      </div>
                      <p className="text-[10px] text-gray-400">
                        {q.graph_rag.latency_ms}ms · {q.graph_rag.tokens_used} tokens
                      </p>
                      <div className="mt-2">
                        <p className="text-[10px] font-semibold text-gray-400 uppercase mb-1">
                          Retrieved Context
                        </p>
                        {q.graph_rag.context_snippets.map((s, i) => (
                          <p
                            key={i}
                            className="text-xs text-gray-600 border-l-2 border-indigo-200 pl-2 mb-1"
                          >
                            {s}
                          </p>
                        ))}
                      </div>
                    </div>

                    {/* VectorRAG side */}
                    <div className="border border-orange-100 rounded-lg p-4 bg-white">
                      <p className="text-xs font-semibold text-orange-600 mb-2">
                        VectorRAG Answer
                      </p>
                      <p className="text-sm text-gray-800 mb-3">
                        {q.vector_rag.answer}
                      </p>
                      <div className="space-y-1.5 mb-3">
                        <ScorePill label="Faithful" graph={q.graph_rag.faithfulness} vector={q.vector_rag.faithfulness} />
                        <ScorePill label="Relevant" graph={q.graph_rag.relevance} vector={q.vector_rag.relevance} />
                        <ScorePill label="Ctx Prec" graph={q.graph_rag.context_precision} vector={q.vector_rag.context_precision} />
                        <ScorePill label="Ctx Recall" graph={q.graph_rag.context_recall} vector={q.vector_rag.context_recall} />
                      </div>
                      <p className="text-[10px] text-gray-400">
                        {q.vector_rag.latency_ms}ms · {q.vector_rag.tokens_used} tokens
                      </p>
                      <div className="mt-2">
                        <p className="text-[10px] font-semibold text-gray-400 uppercase mb-1">
                          Retrieved Context
                        </p>
                        {q.vector_rag.context_snippets.map((s, i) => (
                          <p
                            key={i}
                            className="text-xs text-gray-600 border-l-2 border-orange-200 pl-2 mb-1"
                          >
                            {s}
                          </p>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}

        {filtered.length === 0 && (
          <p className="px-6 py-8 text-center text-sm text-gray-400">
            No queries match the current filters.
          </p>
        )}
      </div>
    </div>
  );
}
