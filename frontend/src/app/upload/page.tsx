"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "@/lib/api-client";

interface UploadResult {
  doc_id: string;
  filename: string;
  status: string;
}

interface DocumentEntry {
  _key: string;
  filename: string;
  status: string;
  mime_type: string;
  upload_date: string;
  chunk_count: number;
}

interface OntologyOption {
  _key: string;
  name: string;
  class_count: number;
  tier: string;
}

type UploadState = "idle" | "uploading" | "extracting" | "success" | "error";

export default function UploadPage() {
  const fileRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [uploadState, setUploadState] = useState<UploadState>("idle");
  const [result, setResult] = useState<UploadResult | null>(null);
  const [extractionRunId, setExtractionRunId] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState("");
  const [documents, setDocuments] = useState<DocumentEntry[]>([]);
  const [docsLoaded, setDocsLoaded] = useState(false);
  const [extractingDocs, setExtractingDocs] = useState<Set<string>>(new Set());
  const [ontologyOptions, setOntologyOptions] = useState<OntologyOption[]>([]);
  const [targetOntologyId, setTargetOntologyId] = useState<string>("");

  const loadDocuments = useCallback(async () => {
    try {
      const res = await api.get<{ data: DocumentEntry[] }>("/api/v1/documents");
      setDocuments(res.data ?? []);
      setDocsLoaded(true);
    } catch {
      setDocsLoaded(true);
    }
  }, []);

  const loadOntologies = useCallback(async () => {
    try {
      const res = await api.get<{ data: OntologyOption[] }>(
        "/api/v1/ontology/library?limit=100",
      );
      setOntologyOptions(res.data ?? []);
    } catch {
      /* non-critical */
    }
  }, []);

  useEffect(() => {
    loadDocuments();
    loadOntologies();
  }, [loadDocuments, loadOntologies]);

  const triggerExtraction = async (
    docId: string,
    ontologyId?: string,
  ): Promise<string | null> => {
    try {
      const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const payload: Record<string, unknown> = { document_id: docId };
      if (ontologyId) {
        payload.target_ontology_id = ontologyId;
      }
      const res = await fetch(`${baseUrl}/api/v1/extraction/run`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) return null;
      const data = await res.json();
      return data.run_id ?? null;
    } catch {
      return null;
    }
  };

  const extractDocument = async (docId: string) => {
    setExtractingDocs((prev) => new Set(prev).add(docId));
    const runId = await triggerExtraction(
      docId,
      targetOntologyId || undefined,
    );
    setExtractingDocs((prev) => {
      const next = new Set(prev);
      next.delete(docId);
      return next;
    });
    if (runId) {
      window.location.href = `/pipeline`;
    }
  };

  const waitForDocumentReady = async (
    docId: string,
    maxWaitMs = 120_000,
  ): Promise<void> => {
    const baseUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    const start = Date.now();
    const pollInterval = 1500;

    while (Date.now() - start < maxWaitMs) {
      try {
        const res = await fetch(`${baseUrl}/api/v1/documents/${docId}`);
        if (res.ok) {
          const doc = await res.json();
          const status = doc.status ?? doc.data?.status;
          if (status === "ready") return;
          if (status === "failed") {
            const errMsg = doc.error_message ?? doc.data?.error_message ?? "Ingestion failed";
            throw new Error(`Document processing failed: ${errMsg}`);
          }
        }
      } catch (err) {
        if (err instanceof Error && err.message.startsWith("Document processing failed")) {
          throw err;
        }
      }
      await new Promise((r) => setTimeout(r, pollInterval));
    }
    throw new Error("Document processing timed out — please try extracting manually once it's ready.");
  };

  const uploadFile = async (file: File) => {
    setUploadState("uploading");
    setErrorMsg("");
    setResult(null);
    setExtractionRunId(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const baseUrl =
        process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
      const res = await fetch(`${baseUrl}/api/v1/documents/upload`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(
          err.detail ?? err.error?.message ?? `Upload failed (${res.status})`
        );
      }

      const data: UploadResult = await res.json();
      setResult(data);
      loadDocuments();

      // Wait for ingestion pipeline (parse → chunk → embed) to finish
      await waitForDocumentReady(data.doc_id);
      loadDocuments();

      setUploadState("extracting");
      const runId = await triggerExtraction(
        data.doc_id,
        targetOntologyId || undefined,
      );
      setExtractionRunId(runId);
      setUploadState("success");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : String(err));
      setUploadState("error");
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) uploadFile(file);
  };

  return (
    <main className="min-h-screen bg-gray-50 text-gray-900">
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-4xl mx-auto px-6 py-6 flex items-center gap-4">
          <a href="/" className="text-gray-400 hover:text-gray-600 text-sm">
            ← Home
          </a>
          <h1 className="text-2xl font-bold">Upload Document</h1>
        </div>
      </header>

      <div className="max-w-4xl mx-auto px-6 py-10 space-y-8">
        {/* Target ontology selector */}
        <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-5">
          <label
            htmlFor="target-ontology"
            className="block text-sm font-medium text-gray-700 mb-2"
          >
            Target Ontology
          </label>
          <select
            id="target-ontology"
            value={targetOntologyId}
            onChange={(e) => setTargetOntologyId(e.target.value)}
            className="w-full rounded-lg border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          >
            <option value="">Create New Ontology</option>
            {ontologyOptions.map((o) => (
              <option key={o._key} value={o._key}>
                {o.name} ({o.class_count} classes)
              </option>
            ))}
          </select>
          <p className="mt-1.5 text-xs text-gray-400">
            {targetOntologyId
              ? "Extraction results will be merged into the selected ontology."
              : "A new ontology will be created from the extraction results."}
          </p>
        </div>

        {/* Drop zone */}
        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragActive(true);
          }}
          onDragLeave={() => setDragActive(false)}
          onDrop={handleDrop}
          onClick={() => fileRef.current?.click()}
          className={`
            border-2 border-dashed rounded-xl p-12 text-center cursor-pointer
            transition-colors
            ${
              dragActive
                ? "border-blue-500 bg-blue-50"
                : "border-gray-300 bg-white hover:border-gray-400"
            }
          `}
        >
          <input
            ref={fileRef}
            type="file"
            accept=".pdf,.docx,.md"
            onChange={handleFileSelect}
            className="hidden"
          />
          <div className="text-4xl mb-3">📄</div>
          <p className="text-lg font-medium text-gray-700">
            Drop a file here or click to browse
          </p>
          <p className="mt-1 text-sm text-gray-400">
            Supported formats: PDF, DOCX, Markdown
          </p>
        </div>

        {/* Upload status */}
        {uploadState === "uploading" && (
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 flex items-center gap-3">
            <div className="h-5 w-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-blue-700 font-medium">
              Uploading and processing document (parsing, chunking, embedding)…
            </p>
          </div>
        )}

        {uploadState === "extracting" && (
          <div className="bg-violet-50 border border-violet-200 rounded-lg p-4 flex items-center gap-3">
            <div className="h-5 w-5 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
            <p className="text-violet-700 font-medium">
              Starting ontology extraction…
            </p>
          </div>
        )}

        {uploadState === "success" && result && (
          <div className="bg-green-50 border border-green-200 rounded-lg p-4">
            <p className="text-green-700 font-medium">
              Upload successful — extraction {extractionRunId ? "started" : "queued"}
            </p>
            <div className="mt-2 text-sm text-green-600 space-y-1">
              <p>
                <span className="font-mono">doc_id:</span> {result.doc_id}
              </p>
              <p>
                <span className="font-mono">filename:</span> {result.filename}
              </p>
              {extractionRunId && (
                <p>
                  <span className="font-mono">run_id:</span> {extractionRunId}
                </p>
              )}
            </div>
            <div className="mt-3 flex gap-3">
              <a
                href="/pipeline"
                className="text-sm px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors"
              >
                View Extraction Pipeline →
              </a>
              <a
                href="/library"
                className="text-sm px-4 py-2 border border-gray-300 text-gray-600 rounded-lg hover:bg-gray-50 transition-colors"
              >
                Ontology Library
              </a>
            </div>
          </div>
        )}

        {uploadState === "error" && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-4">
            <p className="text-red-700 font-medium">Upload failed</p>
            <p className="mt-1 text-sm text-red-600">{errorMsg}</p>
          </div>
        )}

        {/* Document list */}
        {docsLoaded && (
          <section>
            <h2 className="text-sm font-semibold text-gray-500 uppercase tracking-wide mb-4">
              Recent Documents ({documents.length})
            </h2>
            {documents.length === 0 ? (
              <p className="text-gray-400 text-sm">
                No documents uploaded yet.
              </p>
            ) : (
              <div className="bg-white rounded-xl border border-gray-200 divide-y divide-gray-100 shadow-sm">
                {documents.map((doc) => (
                  <div
                    key={doc._key}
                    className="px-5 py-4 flex items-center justify-between"
                  >
                    <div>
                      <p className="font-medium text-gray-900">
                        {doc.filename}
                      </p>
                      <p className="text-xs text-gray-400 mt-0.5">
                        {doc.mime_type} · {doc.chunk_count} chunks ·{" "}
                        {doc.upload_date
                          ? new Date(doc.upload_date).toLocaleDateString()
                          : ""}
                      </p>
                    </div>
                    <div className="flex items-center gap-2">
                      {(doc.status === "ready" || doc.status === "processed") && (
                        extractingDocs.has(doc._key) ? (
                          <span className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 bg-violet-100 text-violet-700 rounded-lg font-medium">
                            <span className="h-3 w-3 border-2 border-violet-500 border-t-transparent rounded-full animate-spin" />
                            Extracting…
                          </span>
                        ) : (
                          <button
                            onClick={() => extractDocument(doc._key)}
                            className="text-xs px-3 py-1.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors font-medium"
                          >
                            Extract
                          </button>
                        )
                      )}
                      <span
                        className={`text-xs font-medium px-2.5 py-1 rounded-full ${
                          doc.status === "processed" || doc.status === "ready"
                            ? "bg-green-100 text-green-700"
                            : doc.status === "processing"
                              ? "bg-yellow-100 text-yellow-700"
                              : doc.status === "error"
                                ? "bg-red-100 text-red-700"
                                : "bg-gray-100 text-gray-600"
                        }`}
                      >
                        {doc.status}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        )}
      </div>
    </main>
  );
}
