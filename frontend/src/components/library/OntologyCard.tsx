"use client";

import type { OntologyRegistryEntry } from "@/types/curation";

interface OntologyCardProps {
  ontology: OntologyRegistryEntry;
  onClick?: (key: string) => void;
}

const TIER_CONFIG: Record<
  string,
  { label: string; bg: string; text: string }
> = {
  domain: { label: "Domain", bg: "bg-blue-50", text: "text-blue-700" },
  local: { label: "Local", bg: "bg-purple-50", text: "text-purple-700" },
};

const STATUS_CONFIG: Record<
  string,
  { label: string; dot: string }
> = {
  draft: { label: "Draft", dot: "bg-gray-400" },
  active: { label: "Active", dot: "bg-green-500" },
  deprecated: { label: "Deprecated", dot: "bg-red-400" },
};

function formatRelativeTime(value: string | number | undefined): string {
  if (value == null) return "N/A";
  const ts = typeof value === "number" ? value * 1000 : new Date(value).getTime();
  if (Number.isNaN(ts)) return "N/A";
  const diff = Date.now() - ts;
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return new Date(ts).toLocaleDateString();
}

export default function OntologyCard({ ontology, onClick }: OntologyCardProps) {
  const tier = TIER_CONFIG[ontology.tier] ?? TIER_CONFIG.domain;
  const status = STATUS_CONFIG[ontology.status] ?? STATUS_CONFIG.draft;

  return (
    <button
      onClick={() => onClick?.(ontology._key)}
      className="group block w-full text-left bg-white rounded-xl border border-gray-200 shadow-sm hover:shadow-md hover:border-blue-300 cursor-pointer transition-all overflow-hidden"
      data-testid={`ontology-card-${ontology._key}`}
      title="Click to explore class hierarchy"
    >
      <div className="h-1 bg-gradient-to-r from-blue-500 to-emerald-500" />
      <div className="p-5">
        <div className="flex items-start justify-between mb-2">
          <h3 className="font-semibold text-gray-900 group-hover:text-blue-700 transition-colors">
            {ontology.name}
          </h3>
          <span
            className={`text-xs font-medium px-2 py-0.5 rounded-full ${tier.bg} ${tier.text}`}
            data-testid="tier-badge"
          >
            {tier.label}
          </span>
        </div>

        <p className="text-sm text-gray-500 mb-3 line-clamp-2">
          {ontology.description || "No description available."}
        </p>

        {/* Stats */}
        <div className="flex gap-4 text-xs text-gray-500 mb-3">
          <span>
            <span className="font-semibold text-gray-700">
              {ontology.class_count}
            </span>{" "}
            classes
          </span>
          <span>
            <span className="font-semibold text-gray-700">
              {ontology.property_count}
            </span>{" "}
            properties
          </span>
          <span>
            <span className="font-semibold text-gray-700">
              {ontology.edge_count}
            </span>{" "}
            edges
          </span>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between text-xs text-gray-400">
          <div className="flex items-center gap-1.5">
            <span
              className={`inline-block h-1.5 w-1.5 rounded-full ${status.dot}`}
            />
            <span>{status.label}</span>
          </div>
          <span>Updated {formatRelativeTime(
            (ontology as Record<string, unknown>).updated_at as string
            ?? ontology.last_updated
            ?? ontology.created_at
          )}</span>
        </div>
        <p className="text-xs text-gray-300 group-hover:text-blue-400 mt-3 text-center transition-colors">
          Click to explore →
        </p>
      </div>
    </button>
  );
}
