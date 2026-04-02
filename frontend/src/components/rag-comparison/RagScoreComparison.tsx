"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from "recharts";
import type { RagMetricSummary } from "@/types/curation";

interface Props {
  graphRag: RagMetricSummary;
  vectorRag: RagMetricSummary;
}

export default function RagScoreComparison({ graphRag, vectorRag }: Props) {
  const data = [
    {
      metric: "Faithfulness",
      GraphRAG: graphRag.answer_faithfulness,
      VectorRAG: vectorRag.answer_faithfulness,
    },
    {
      metric: "Relevance",
      GraphRAG: graphRag.answer_relevance,
      VectorRAG: vectorRag.answer_relevance,
    },
    {
      metric: "Ctx Precision",
      GraphRAG: graphRag.context_precision,
      VectorRAG: vectorRag.context_precision,
    },
    {
      metric: "Ctx Recall",
      GraphRAG: graphRag.context_recall,
      VectorRAG: vectorRag.context_recall,
    },
  ];

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">
        Quality Score Comparison
      </h3>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data} barGap={4} barCategoryGap="25%">
          <CartesianGrid strokeDasharray="3 3" vertical={false} />
          <XAxis
            dataKey="metric"
            tick={{ fontSize: 11, fill: "#6b7280" }}
            axisLine={false}
            tickLine={false}
          />
          <YAxis
            domain={[0, 1]}
            tick={{ fontSize: 10, fill: "#9ca3af" }}
            tickCount={6}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip
            contentStyle={{ fontSize: 12, borderRadius: 8 }}
            formatter={(value) =>
              typeof value === "number" ? value.toFixed(2) : String(value ?? "")
            }
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Bar
            dataKey="GraphRAG"
            fill="#6366f1"
            radius={[4, 4, 0, 0]}
            maxBarSize={36}
          />
          <Bar
            dataKey="VectorRAG"
            fill="#f97316"
            radius={[4, 4, 0, 0]}
            maxBarSize={36}
          />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
