"use client";

import {
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  ResponsiveContainer,
  Legend,
  Tooltip,
} from "recharts";
import type { RagQueryTypeBreakdown } from "@/types/curation";

interface Props {
  breakdown: RagQueryTypeBreakdown[];
}

export default function RagQueryTypeRadar({ breakdown }: Props) {
  const data = breakdown.map((b) => ({
    query_type: `${b.query_type} (${b.count})`,
    GraphRAG: Math.round(b.graph_avg_score * 100) / 100,
    VectorRAG: Math.round(b.vector_avg_score * 100) / 100,
  }));

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">
        Performance by Query Type
      </h3>
      <ResponsiveContainer width="100%" height={300}>
        <RadarChart data={data} cx="50%" cy="48%" outerRadius="68%">
          <PolarGrid strokeDasharray="3 3" />
          <PolarAngleAxis
            dataKey="query_type"
            tick={{ fontSize: 10, fill: "#6b7280" }}
          />
          <PolarRadiusAxis
            angle={90}
            domain={[0, 1]}
            tick={{ fontSize: 10, fill: "#9ca3af" }}
            tickCount={5}
          />
          <Radar
            name="GraphRAG"
            dataKey="GraphRAG"
            stroke="#6366f1"
            fill="#6366f1"
            fillOpacity={0.15}
            strokeWidth={2}
          />
          <Radar
            name="VectorRAG"
            dataKey="VectorRAG"
            stroke="#f97316"
            fill="#f97316"
            fillOpacity={0.15}
            strokeWidth={2}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Tooltip
            contentStyle={{ fontSize: 12 }}
            formatter={(value) =>
              typeof value === "number" ? value.toFixed(2) : String(value ?? "")
            }
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}
