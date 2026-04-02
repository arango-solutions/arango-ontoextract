"use client";

import type { DashboardAlert } from "@/types/curation";

interface Props {
  alerts: DashboardAlert[];
}

const FLAG_LABELS: Record<string, string> = {
  has_cycles: "Circular subclass references detected",
  high_orphan_ratio: "Over 30% orphan classes (disconnected)",
  low_confidence: "Average confidence below 0.5",
  low_faithfulness: "Average faithfulness below 0.4",
  zero_completeness: "No classes have properties",
  low_semantic_validity: "Average semantic validity below 0.5",
};

export default function AlertsFlags({ alerts }: Props) {
  if (alerts.length === 0) return null;

  return (
    <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-4">
      <h3 className="text-sm font-semibold text-gray-700 mb-3">Flags &amp; Alerts</h3>
      <div className="space-y-2">
        {alerts.map((alert, i) => (
          <div
            key={`${alert.ontology_id}-${alert.flag}-${i}`}
            className={`flex items-center gap-3 text-xs px-3 py-2 rounded-lg border ${
              alert.severity === "red"
                ? "bg-red-50 border-red-200 text-red-800"
                : "bg-yellow-50 border-yellow-200 text-yellow-800"
            }`}
          >
            <span className={`inline-block h-2 w-2 rounded-full flex-shrink-0 ${
              alert.severity === "red" ? "bg-red-500" : "bg-yellow-500"
            }`} />
            <span className="font-medium">{alert.name}</span>
            <span className="text-gray-500">-</span>
            <span>{FLAG_LABELS[alert.flag] ?? alert.flag}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
