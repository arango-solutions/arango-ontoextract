"use client";

import { useState, useMemo } from "react";
import type { OntologyScorecard } from "@/types/curation";
import { withBasePath } from "@/lib/base-path";

interface Props {
  ontologies: OntologyScorecard[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

type SortKey = keyof OntologyScorecard;

function healthBg(score: number | null): string {
  if (score === null) return "bg-gray-100";
  if (score >= 70) return "bg-green-100 text-green-800";
  if (score >= 50) return "bg-yellow-100 text-yellow-800";
  return "bg-red-100 text-red-800";
}

function fmt(val: number | null, decimals = 2): string {
  if (val === null || val === undefined) return "-";
  return val.toFixed(decimals);
}

const COLUMNS: { key: SortKey; label: string; align?: string }[] = [
  { key: "name", label: "Name" },
  { key: "tier", label: "Tier" },
  { key: "health_score", label: "Health" },
  { key: "avg_confidence", label: "Confidence" },
  { key: "avg_faithfulness", label: "Faithfulness" },
  { key: "avg_semantic_validity", label: "Sem. Validity" },
  { key: "completeness", label: "Completeness" },
  { key: "connectivity", label: "Connectivity" },
  { key: "orphan_count", label: "Orphans" },
  { key: "has_cycles", label: "Cycles" },
  { key: "estimated_cost", label: "Cost ($)", align: "right" },
];

export default function OntologyScoreTable({ ontologies, selectedId, onSelect }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>("health_score");
  const [sortAsc, setSortAsc] = useState(false);
  const [filter, setFilter] = useState("");

  const sorted = useMemo(() => {
    const filtered = filter
      ? ontologies.filter((o) => o.name.toLowerCase().includes(filter.toLowerCase()))
      : ontologies;

    return [...filtered].sort((a, b) => {
      const av = a[sortKey];
      const bv = b[sortKey];
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      if (av < bv) return sortAsc ? -1 : 1;
      if (av > bv) return sortAsc ? 1 : -1;
      return 0;
    });
  }, [ontologies, sortKey, sortAsc, filter]);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortAsc(!sortAsc);
    } else {
      setSortKey(key);
      setSortAsc(false);
    }
  };

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
      <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-700">Per-Ontology Scores</h3>
        <input
          type="text"
          placeholder="Filter by name..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="text-xs px-3 py-1.5 border border-gray-200 rounded-lg focus:outline-none focus:ring-1 focus:ring-blue-400 w-48"
        />
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-100 bg-gray-50">
              {COLUMNS.map((col) => (
                <th
                  key={col.key}
                  onClick={() => toggleSort(col.key)}
                  className={`px-3 py-2 text-xs font-medium text-gray-500 uppercase tracking-wide cursor-pointer hover:text-gray-700 whitespace-nowrap ${col.align === "right" ? "text-right" : "text-left"}`}
                >
                  {col.label}
                  {sortKey === col.key && (
                    <span className="ml-1">{sortAsc ? "\u25B2" : "\u25BC"}</span>
                  )}
                </th>
              ))}
              <th className="px-3 py-2 text-xs font-medium text-gray-500 uppercase tracking-wide text-center whitespace-nowrap">
                Actions
              </th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((o) => (
              <tr
                key={o.ontology_id}
                onClick={() => onSelect(o.ontology_id)}
                className={`border-b border-gray-50 cursor-pointer transition-colors ${
                  selectedId === o.ontology_id
                    ? "bg-blue-50"
                    : "hover:bg-gray-50"
                }`}
              >
                <td className="px-3 py-2.5 font-medium text-gray-900 max-w-[200px] truncate">
                  {o.name}
                </td>
                <td className="px-3 py-2.5">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${
                    o.tier === "domain"
                      ? "bg-blue-50 text-blue-700"
                      : "bg-purple-50 text-purple-700"
                  }`}>
                    {o.tier}
                  </span>
                </td>
                <td className="px-3 py-2.5">
                  <span className={`text-xs px-2 py-0.5 rounded-full font-bold ${healthBg(o.health_score)}`}>
                    {o.health_score ?? "-"}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-gray-600">{fmt(o.avg_confidence)}</td>
                <td className="px-3 py-2.5 text-gray-600">{fmt(o.avg_faithfulness)}</td>
                <td className="px-3 py-2.5 text-gray-600">{fmt(o.avg_semantic_validity)}</td>
                <td className="px-3 py-2.5 text-gray-600">{fmt(o.completeness, 0)}%</td>
                <td className="px-3 py-2.5 text-gray-600">{fmt(o.connectivity, 0)}%</td>
                <td className="px-3 py-2.5 text-gray-600">{o.orphan_count}</td>
                <td className="px-3 py-2.5">
                  {o.has_cycles ? (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700 font-medium">Yes</span>
                  ) : (
                    <span className="text-xs text-gray-400">No</span>
                  )}
                </td>
                <td className="px-3 py-2.5 text-right text-gray-600 font-mono text-xs">
                  {o.estimated_cost !== null ? `$${o.estimated_cost.toFixed(4)}` : "-"}
                </td>
                <td className="px-3 py-2.5 text-center">
                  <a
                    href={withBasePath(`/workspace?ontologyId=${o.ontology_id}`)}
                    onClick={(e) => e.stopPropagation()}
                    className="text-xs px-2 py-1 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 rounded-md transition-colors font-medium"
                  >
                    Workspace
                  </a>
                </td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={COLUMNS.length + 1} className="px-3 py-8 text-center text-gray-400 text-sm">
                  No ontologies found
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
