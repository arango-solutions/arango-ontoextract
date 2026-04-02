"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api-client";
import type { QualitativeEvaluation } from "@/types/curation";

interface Props {
  ontologyId: string;
}

function renderInlineMarkdown(text: string) {
  const normalized = text.replace(/^\s*[-*]\s+/, "");
  const parts = normalized.split(/(\*\*.*?\*\*)/g).filter(Boolean);

  return parts.map((part, idx) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={idx}>{part.slice(2, -2)}</strong>;
    }
    return <span key={idx}>{part}</span>;
  });
}

export default function StrengthsWeaknesses({ ontologyId }: Props) {
  const [data, setData] = useState<QualitativeEvaluation | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api
      .get<QualitativeEvaluation>(`/api/v1/quality/${ontologyId}/evaluation`)
      .then(setData)
      .catch(() => setData(null))
      .finally(() => setLoading(false));
  }, [ontologyId]);

  if (loading) {
    return (
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
        <p className="text-sm text-gray-400 animate-pulse">Loading evaluation...</p>
      </div>
    );
  }

  if (!data || data.status === "not_available") {
    return (
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
        <h3 className="text-sm font-semibold text-gray-700 mb-2">Qualitative Evaluation</h3>
        <p className="text-xs text-gray-400">
          Not available for this extraction run.
        </p>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">Qualitative Evaluation</h3>
      <div className="space-y-5">
        <section>
          <h4 className="text-xs font-semibold text-green-700 uppercase tracking-wide mb-2">
            Strengths
          </h4>
          {data.strengths.length > 0 ? (
            <ul className="list-disc pl-5 space-y-2 text-xs text-gray-700">
              {data.strengths.map((s, i) => (
                <li key={i} className="leading-relaxed marker:text-green-600">
                  {renderInlineMarkdown(s)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-gray-400">None identified</p>
          )}
        </section>

        <section>
          <h4 className="text-xs font-semibold text-amber-700 uppercase tracking-wide mb-2">
            Weaknesses
          </h4>
          {data.weaknesses.length > 0 ? (
            <ul className="list-disc pl-5 space-y-2 text-xs text-gray-700">
              {data.weaknesses.map((w, i) => (
                <li key={i} className="leading-relaxed marker:text-amber-600">
                  {renderInlineMarkdown(w)}
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-gray-400">None identified</p>
          )}
        </section>
      </div>
    </div>
  );
}
