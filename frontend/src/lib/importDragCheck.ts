/**
 * Client-side pre-check for the H.16 drag-and-drop import flow.
 *
 * The backend (``POST /api/v1/ontology/{id}/imports``) authoritatively
 * rejects self-imports (400), duplicates (409), and circular dependencies
 * (400, 10-hop OUTBOUND BFS). That validation MUST be the source of
 * truth — the UI does not get to skip it. This module is the *pre-check*
 * that catches the obvious cases before we round-trip:
 *
 * * ``self-import`` — dragging an ontology onto its own canvas
 * * ``no-canvas`` — dropping while no ontology is selected
 * * ``duplicate`` — the target is already in the open ontology's
 *   transitive ``imports`` closure (we have the closure in state from
 *   ``/effective``'s ``sources[]`` so this check is free)
 *
 * Cycles that don't trip the cheap duplicate check require knowing the
 * *target's* ancestors, which we do not have locally. Those fall through
 * to the backend, which returns ``ValidationError("Adding this import
 * would create a circular dependency")`` and we surface that as a toast.
 *
 * The function is pure and synchronous so callers can fire it inside the
 * native ``drop`` handler (no awaits) and decide whether to even attempt
 * the network call. That keeps the rejection feel snappy — the user sees
 * "Already imported" the instant they release the mouse.
 */

import type { EffectiveSource } from "@/types/curation";

export type ImportDragRejectionReason =
  | "no-canvas"
  | "self-import"
  | "duplicate";

export type ImportDragCheckResult =
  | { ok: true }
  | { ok: false; reason: ImportDragRejectionReason; message: string };

export interface ImportDragCheckArgs {
  /** Key of the ontology currently open on the canvas. ``null`` when no
   *  ontology is selected — the empty-canvas state. */
  currentOntologyId: string | null;
  /** Key of the ontology being dragged from the explorer. */
  draggedOntologyId: string;
  /** Display name of the dragged ontology — purely for the message. */
  draggedOntologyName?: string | null;
  /** The current ontology's effective-graph sources (self + every
   *  imported ancestor at any depth). Comes from
   *  ``/api/v1/ontology/{id}/effective``'s ``sources[]``. May be
   *  ``null`` when the effective payload has not yet loaded — in that
   *  case we skip the duplicate check and let the backend catch it. */
  effectiveSources: EffectiveSource[] | null;
}

export function checkImportDragCandidate(
  args: ImportDragCheckArgs,
): ImportDragCheckResult {
  const { currentOntologyId, draggedOntologyId, effectiveSources } = args;
  const draggedName = args.draggedOntologyName?.trim() || draggedOntologyId;

  if (!currentOntologyId) {
    return {
      ok: false,
      reason: "no-canvas",
      message:
        "Open an ontology first — then drag another ontology onto the canvas to import it.",
    };
  }

  if (currentOntologyId === draggedOntologyId) {
    return {
      ok: false,
      reason: "self-import",
      message: `Cannot import "${draggedName}" into itself.`,
    };
  }

  if (effectiveSources && effectiveSources.length > 0) {
    const alreadyImported = effectiveSources.some(
      (s) => s._key === draggedOntologyId,
    );
    if (alreadyImported) {
      return {
        ok: false,
        reason: "duplicate",
        message: `"${draggedName}" is already imported (directly or transitively).`,
      };
    }
  }

  return { ok: true };
}

/**
 * MIME type used by the drag-and-drop import flow. Keeping it as a named
 * constant means the drag source (`AssetExplorer`'s ontology rows) and
 * the drop target (`page.tsx`'s canvas container) cannot drift — both
 * import the same symbol.
 *
 * The ``x-aoe-`` prefix is the project namespace (``arango-ontoextract``);
 * the format is JSON so downstream consumers can ``JSON.parse`` without
 * URL-decoding.
 */
export const IMPORT_DRAG_MIME = "application/x-aoe-ontology" as const;

/** Payload shape carried by the drag's ``dataTransfer``. Authored by
 *  `AssetExplorer` and consumed by the canvas drop handler. Both sides
 *  reference this type so a field rename surfaces at compile time. */
export interface ImportDragPayload {
  ontologyId: string;
  ontologyName: string;
}

/** Serialize a payload onto a ``DataTransfer`` instance. Centralised
 *  here so both the drag source and tests use the exact same encoding. */
export function writeImportDragPayload(
  transfer: DataTransfer,
  payload: ImportDragPayload,
): void {
  transfer.setData(IMPORT_DRAG_MIME, JSON.stringify(payload));
  // ``effectAllowed = "copy"`` so the cursor advertises a copy rather
  // than a move — we are not removing the dragged ontology from the
  // explorer, just creating an `imports` edge.
  transfer.effectAllowed = "copy";
}

/** Read an ``ImportDragPayload`` from a ``DataTransfer``. Returns
 *  ``null`` on any malformed input rather than throwing, so a stray
 *  drag from another app (browser-native text drag, file drag, etc.)
 *  cannot crash the drop handler. */
export function readImportDragPayload(
  transfer: DataTransfer,
): ImportDragPayload | null {
  const raw = transfer.getData(IMPORT_DRAG_MIME);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (
      parsed != null
      && typeof parsed === "object"
      && typeof (parsed as ImportDragPayload).ontologyId === "string"
      && typeof (parsed as ImportDragPayload).ontologyName === "string"
    ) {
      return parsed as ImportDragPayload;
    }
    return null;
  } catch {
    return null;
  }
}
