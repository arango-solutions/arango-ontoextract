"use client";

import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api-client";

interface HealthStatus {
  status: string;
  database?: string;
}

interface LibraryStats {
  total_count: number;
}

type ConnectionState = "loading" | "connected" | "error";

export default function Home() {
  const [health, setHealth] = useState<ConnectionState>("loading");
  const [healthDetail, setHealthDetail] = useState("");
  const [ontologyCount, setOntologyCount] = useState<number | null>(null);
  const [statsError, setStatsError] = useState(false);

  useEffect(() => {
    // Same-origin `/ready` → Next rewrites to FastAPI (avoids cross-origin / CORS to :8010).
    fetch("/ready")
      .then(async (r) => {
        if (!r.ok) {
          throw new Error(`HTTP ${r.status}`);
        }
        return r.json() as Promise<HealthStatus>;
      })
      .then((data: HealthStatus) => {
        setHealth(data.status === "ready" ? "connected" : "error");
        setHealthDetail(data.database ?? data.status);
      })
      .catch((err) => {
        setHealth("error");
        setHealthDetail(err instanceof ApiError ? err.body.message : String(err));
      });

    api
      .get<LibraryStats>("/api/v1/ontology/library?limit=1")
      .then((data) => {
        setOntologyCount(data.total_count);
      })
      .catch(() => {
        setStatsError(true);
      });
  }, []);

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      {/* Header */}
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-5xl mx-auto px-6 py-8">
          <h1 className="text-3xl font-bold tracking-tight">
            Arango-OntoExtract
          </h1>
          <p className="mt-2 text-gray-500 text-lg">
            LLM-driven ontology extraction and curation platform built on
            ArangoDB.
          </p>
        </div>
      </header>

      <div className="max-w-5xl mx-auto px-6 py-10 space-y-8">
        {/* Status row */}
        <section className="grid grid-cols-1 sm:grid-cols-2 gap-6">
          {/* Health indicator */}
          <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
              Backend Status
            </h2>
            <div className="flex items-center gap-3">
              <span
                className={`inline-block h-3 w-3 rounded-full ${
                  health === "loading"
                    ? "bg-yellow-400 animate-pulse"
                    : health === "connected"
                      ? "bg-green-500"
                      : "bg-red-500"
                }`}
              />
              <span className="text-lg font-medium capitalize">
                {health === "loading"
                  ? "Checking\u2026"
                  : health === "connected"
                    ? "Connected"
                    : "Unavailable"}
              </span>
            </div>
            {health === "error" && healthDetail && (
              <p className="mt-2 text-sm text-red-600">{healthDetail}</p>
            )}
          </div>

          {/* System stats */}
          <div className="bg-white rounded-xl border border-gray-200 p-6 shadow-sm">
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
              System Stats
            </h2>
            {statsError ? (
              <p className="text-sm text-gray-400">
                Stats unavailable — backend may be offline.
              </p>
            ) : ontologyCount === null ? (
              <p className="text-sm text-gray-400 animate-pulse">Loading…</p>
            ) : (
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-bold">{ontologyCount}</span>
                <span className="text-gray-500">
                  registered{" "}
                  {ontologyCount === 1 ? "ontology" : "ontologies"}
                </span>
              </div>
            )}
          </div>
        </section>

        {/* Quick actions */}
        <section>
          <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
            Quick Actions
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            <ActionCard
              title="Workspace"
              description="Unified graph canvas for viewing, editing, and curating ontologies."
              href="/workspace"
              accentColor="bg-indigo-600"
            />
            <ActionCard
              title="Upload Document"
              description="Ingest a PDF, DOCX, or Markdown file for ontology extraction."
              href="/upload"
              accentColor="bg-blue-600"
            />
            <ActionCard
              title="View Ontologies"
              description="Browse the ontology library and explore class hierarchies."
              href="/library"
              accentColor="bg-emerald-600"
            />
            <ActionCard
              title="Pipeline Monitor"
              description="Track extraction runs, agent steps, and pipeline health."
              href="/pipeline"
              accentColor="bg-violet-600"
            />
            <ActionCard
              title="Quality Dashboard"
              description="View quality metrics, LLM-as-judge scores, and ontology health."
              href="/dashboard"
              accentColor="bg-amber-600"
            />
          </div>
        </section>
      </div>
    </main>
  );
}

function ActionCard({
  title,
  description,
  href,
  accentColor,
}: {
  title: string;
  description: string;
  href: string;
  accentColor: string;
}) {
  return (
    <a
      href={href}
      className="group block bg-white rounded-xl border border-gray-200 shadow-sm hover:shadow-md transition-shadow overflow-hidden"
    >
      <div className={`${accentColor} h-1`} />
      <div className="p-5">
        <h3 className="font-semibold text-gray-900 group-hover:text-gray-700">
          {title}
        </h3>
        <p className="mt-1 text-sm text-gray-500">{description}</p>
      </div>
    </a>
  );
}
