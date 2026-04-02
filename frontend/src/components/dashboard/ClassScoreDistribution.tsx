"use client";

import { useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { api } from "@/lib/api-client";
import type { ClassScore } from "@/types/curation";

interface Props {
  ontologyId: string;
}

const BUCKETS = [
  { label: "0-0.2", min: 0, max: 0.2 },
  { label: "0.2-0.4", min: 0.2, max: 0.4 },
  { label: "0.4-0.6", min: 0.4, max: 0.6 },
  { label: "0.6-0.8", min: 0.6, max: 0.8 },
  { label: "0.8-1.0", min: 0.8, max: 1.01 },
];

function isLowScore(value: number | null | undefined): boolean {
  return value !== null && value !== undefined && value < 0.4;
}

function bucketize(scores: ClassScore[], field: "faithfulness_score" | "semantic_validity_score") {
  return BUCKETS.map((b) => ({
    range: b.label,
    count: scores.filter((s) => {
      const v = s[field] ?? 0;
      return v >= b.min && v < b.max;
    }).length,
  }));
}

export default function ClassScoreDistribution({ ontologyId }: Props) {
  const [scores, setScores] = useState<ClassScore[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .get<{ scores: ClassScore[] }>(`/api/v1/quality/${ontologyId}/class-scores`)
      .then((res) => setScores(res.scores))
      .catch(() => setScores([]))
      .finally(() => setLoading(false));
  }, [ontologyId]);

  if (loading) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
        <p className="text-sm text-gray-400 animate-pulse">Loading class scores...</p>
      </div>
    );
  }

  if (scores.length === 0) {
    return null;
  }

  const faithData = bucketize(scores, "faithfulness_score");
  const validityData = bucketize(scores, "semantic_validity_score");

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-4">Class Score Distributions</h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Faithfulness distribution */}
        <div>
          <h4 className="text-xs font-medium text-gray-500 mb-2">Faithfulness Scores</h4>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={faithData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="range" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
              <Tooltip contentStyle={{ fontSize: 12 }} />
              <Bar dataKey="count" fill="#6366f1" radius={[4, 4, 0, 0]} name="Classes" />
            </BarChart>
          </ResponsiveContainer>
        </div>

        {/* Semantic validity distribution */}
        <div>
          <h4 className="text-xs font-medium text-gray-500 mb-2">Semantic Validity Scores</h4>
          <ResponsiveContainer width="100%" height={180}>
            <BarChart data={validityData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="range" tick={{ fontSize: 10 }} />
              <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
              <Tooltip contentStyle={{ fontSize: 12 }} />
              <Bar dataKey="count" fill="#10b981" radius={[4, 4, 0, 0]} name="Classes" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Flagged classes */}
      {scores.filter((s) => isLowScore(s.faithfulness_score) || isLowScore(s.semantic_validity_score)).length > 0 && (
        <div className="mt-4 border-t border-gray-100 pt-3">
          <h4 className="text-xs font-medium text-red-600 mb-2">Flagged Classes (score &lt; 0.4)</h4>
          <div className="space-y-1">
            {scores
              .filter((s) => isLowScore(s.faithfulness_score) || isLowScore(s.semantic_validity_score))
              .map((s) => {
                const faithfulness = s.faithfulness_score;
                const validity = s.semantic_validity_score;

                return (
                  <div key={s._key} className="text-xs bg-red-50 border border-red-100 rounded px-3 py-1.5 flex items-center gap-3">
                    <span className="font-medium text-gray-700">{s.label}</span>
                    {faithfulness !== null && faithfulness < 0.4 && (
                      <span className="text-red-600">Faith: {faithfulness.toFixed(2)}</span>
                    )}
                    {validity !== null && validity < 0.4 && (
                      <span className="text-red-600">Validity: {validity.toFixed(2)}</span>
                    )}
                  </div>
                );
              })}
          </div>
        </div>
      )}
    </div>
  );
}
