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
import type { OntologyScorecard } from "@/types/curation";

interface Props {
  ontologies: OntologyScorecard[];
  selectedIds: string[];
}

const COLORS = [
  "#6366f1", // indigo
  "#f97316", // orange
  "#10b981", // emerald
  "#ec4899", // pink
  "#8b5cf6", // violet
  "#14b8a6", // teal
];

function structuralIntegrity(o: OntologyScorecard): number {
  const cyclePenalty = o.has_cycles ? 0.3 : 0;
  const orphanRatio = o.class_count > 0 ? o.orphan_count / o.class_count : 0;
  return Math.max(0, 1.0 - cyclePenalty - orphanRatio);
}

const AXES = [
  { key: "faithfulness", label: "Faithfulness" },
  { key: "semantic_validity", label: "Semantic Validity" },
  { key: "completeness", label: "Completeness" },
  { key: "connectivity", label: "Connectivity" },
  { key: "structural", label: "Structural Integrity" },
];

export default function RadarMetricChart({ ontologies, selectedIds }: Props) {
  const selected = ontologies.filter((o) => selectedIds.includes(o.ontology_id));
  if (selected.length === 0) return null;

  const data = AXES.map((axis) => {
    const point: Record<string, string | number> = { metric: axis.label };
    selected.forEach((o) => {
      let value = 0;
      switch (axis.key) {
        case "faithfulness":
          value = o.avg_faithfulness ?? 0;
          break;
        case "semantic_validity":
          value = o.avg_semantic_validity ?? 0;
          break;
        case "completeness":
          value = o.completeness / 100;
          break;
        case "connectivity":
          value = o.connectivity / 100;
          break;
        case "structural":
          value = structuralIntegrity(o);
          break;
      }
      point[o.ontology_id] = Math.round(value * 100) / 100;
    });
    return point;
  });

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">LLM-as-Judge Quality Radar</h3>
      <ResponsiveContainer width="100%" height={260}>
        <RadarChart data={data} cx="50%" cy="48%" outerRadius="68%">
          <PolarGrid strokeDasharray="3 3" />
          <PolarAngleAxis
            dataKey="metric"
            tick={{ fontSize: 11, fill: "#6b7280" }}
          />
          <PolarRadiusAxis
            angle={90}
            domain={[0, 1]}
            tick={{ fontSize: 10, fill: "#9ca3af" }}
            tickCount={5}
          />
          {selected.map((o, i) => (
            <Radar
              key={o.ontology_id}
              name={o.name}
              dataKey={o.ontology_id}
              stroke={COLORS[i % COLORS.length]}
              fill={COLORS[i % COLORS.length]}
              fillOpacity={0.15}
              strokeWidth={2}
            />
          ))}
          <Legend wrapperStyle={{ fontSize: 11 }} />
          <Tooltip
            contentStyle={{ fontSize: 12 }}
            formatter={(value) => typeof value === "number" ? value.toFixed(2) : String(value ?? "")}
          />
        </RadarChart>
      </ResponsiveContainer>
    </div>
  );
}
