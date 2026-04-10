"use client";

import { useState, useEffect } from "react";
import { api, ApiError } from "@/lib/api-client";

export interface OntologyRenameDialogProps {
  open: boolean;
  ontologyKey: string;
  initialName: string;
  initialDescription: string;
  onClose: () => void;
  /** Called after a successful save with the new display name and registry key. */
  onSaved: (displayName: string, ontologyKey: string) => void;
}

/**
 * Modal to rename an ontology and edit description (PUT /api/v1/ontology/library/{id}).
 */
export default function OntologyRenameDialog({
  open,
  ontologyKey,
  initialName,
  initialDescription,
  onClose,
  onSaved,
}: OntologyRenameDialogProps) {
  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState(initialDescription);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) {
      setName(initialName);
      setDescription(initialDescription);
      setError(null);
    }
  }, [open, initialName, initialDescription]);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = name.trim();
    if (!trimmed) {
      setError("Name is required");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await api.put(`/api/v1/ontology/library/${encodeURIComponent(ontologyKey)}`, {
        name: trimmed,
        description: description.trim() || "",
      });
      onSaved(trimmed, ontologyKey);
      onClose();
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.body.message
          : err instanceof Error
            ? err.message
            : "Save failed",
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[200] flex items-center justify-center p-4 bg-black/50"
      role="presentation"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-labelledby="ontology-rename-title"
        className="bg-white rounded-xl shadow-xl border border-gray-200 w-full max-w-md p-6"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <h2 id="ontology-rename-title" className="text-lg font-semibold text-gray-900 mb-1">
          Ontology name & description
        </h2>
        <p className="text-xs text-gray-500 mb-4">
          Registry id: <code className="bg-gray-100 px-1 rounded">{ontologyKey}</code> (unchanged)
        </p>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="ont-rename-name" className="block text-xs font-medium text-gray-600 mb-1">
              Display name
            </label>
            <input
              id="ont-rename-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm"
              autoComplete="off"
              disabled={saving}
            />
          </div>
          <div>
            <label htmlFor="ont-rename-desc" className="block text-xs font-medium text-gray-600 mb-1">
              Description
            </label>
            <textarea
              id="ont-rename-desc"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm resize-y min-h-[72px]"
              disabled={saving}
            />
          </div>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-lg"
              disabled={saving}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-3 py-1.5 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50"
              disabled={saving}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
