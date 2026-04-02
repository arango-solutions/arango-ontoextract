"use client";

import type { RagMetricSummary } from "@/types/curation";

interface Props {
  graphRag: RagMetricSummary;
  vectorRag: RagMetricSummary;
}

function delta(g: number, v: number): { pct: string; positive: boolean } {
  const diff = ((g - v) / v) * 100;
  return { pct: `${diff > 0 ? "+" : ""}${diff.toFixed(1)}%`, positive: diff > 0 };
}

function MetricRow({
  label,
  subtitle,
  graphVal,
  vectorVal,
  format,
  higherIsBetter = true,
}: {
  label: string;
  subtitle: string;
  graphVal: number;
  vectorVal: number;
  format: (v: number) => string;
  higherIsBetter?: boolean;
}) {
  const d = delta(graphVal, vectorVal);
  const isGood = higherIsBetter ? d.positive : !d.positive;

  return (
    <div className="grid grid-cols-[1fr_100px_100px_80px] items-center gap-2 py-3 border-b border-gray-50 last:border-0">
      <div>
        <p className="text-sm font-medium text-gray-800">{label}</p>
        <p className="text-xs text-gray-400">{subtitle}</p>
      </div>
      <p className="text-sm font-semibold text-center text-indigo-700">
        {format(graphVal)}
      </p>
      <p className="text-sm font-semibold text-center text-orange-600">
        {format(vectorVal)}
      </p>
      <p
        className={`text-xs font-medium text-center px-2 py-0.5 rounded-full ${
          isGood
            ? "bg-green-50 text-green-700"
            : "bg-red-50 text-red-600"
        }`}
      >
        {d.pct}
      </p>
    </div>
  );
}

const fmtScore = (v: number) => v.toFixed(2);
const fmtMs = (v: number) => `${v.toLocaleString()}ms`;
const fmtTokens = (v: number) => v.toLocaleString();
const fmtCost = (v: number) => `$${v.toFixed(4)}`;

export default function RagComparisonSummary({ graphRag, vectorRag }: Props) {
  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6">
      <h3 className="text-sm font-semibold text-gray-700 mb-4">
        Head-to-Head Metrics
      </h3>

      {/* Column headers */}
      <div className="grid grid-cols-[1fr_100px_100px_80px] gap-2 pb-2 border-b border-gray-200 mb-1">
        <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide">
          Metric
        </p>
        <p className="text-xs font-semibold text-center text-indigo-500 uppercase tracking-wide">
          GraphRAG
        </p>
        <p className="text-xs font-semibold text-center text-orange-500 uppercase tracking-wide">
          VectorRAG
        </p>
        <p className="text-xs font-semibold text-center text-gray-400 uppercase tracking-wide">
          Delta
        </p>
      </div>

      <MetricRow
        label="Answer Faithfulness"
        subtitle="Grounded in retrieved context"
        graphVal={graphRag.answer_faithfulness}
        vectorVal={vectorRag.answer_faithfulness}
        format={fmtScore}
      />
      <MetricRow
        label="Answer Relevance"
        subtitle="Addresses the question directly"
        graphVal={graphRag.answer_relevance}
        vectorVal={vectorRag.answer_relevance}
        format={fmtScore}
      />
      <MetricRow
        label="Context Precision"
        subtitle="Retrieved context is relevant"
        graphVal={graphRag.context_precision}
        vectorVal={vectorRag.context_precision}
        format={fmtScore}
      />
      <MetricRow
        label="Context Recall"
        subtitle="All necessary context retrieved"
        graphVal={graphRag.context_recall}
        vectorVal={vectorRag.context_recall}
        format={fmtScore}
      />
      <MetricRow
        label="Avg Latency"
        subtitle="End-to-end query time"
        graphVal={graphRag.avg_latency_ms}
        vectorVal={vectorRag.avg_latency_ms}
        format={fmtMs}
        higherIsBetter={false}
      />
      <MetricRow
        label="Avg Tokens"
        subtitle="Tokens per query"
        graphVal={graphRag.avg_tokens_used}
        vectorVal={vectorRag.avg_tokens_used}
        format={fmtTokens}
        higherIsBetter={false}
      />
      <MetricRow
        label="Avg Cost / Query"
        subtitle="LLM inference cost"
        graphVal={graphRag.avg_cost_per_query}
        vectorVal={vectorRag.avg_cost_per_query}
        format={fmtCost}
        higherIsBetter={false}
      />
    </div>
  );
}
