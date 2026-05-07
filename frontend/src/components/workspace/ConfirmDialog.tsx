"use client";

import { useEffect, useRef, useState } from "react";

/**
 * In-app confirmation overlay used in place of ``window.confirm`` for
 * destructive workspace operations, per ``ui-architecture.mdc`` §18.
 *
 * Two modes are supported on the same component because the dialog only
 * differs by a single field — keeping them unified avoids divergent close /
 * accessibility / styling code:
 *
 *   - **plain** (default): a Cancel button and a danger-styled Confirm button.
 *     Suitable for ops where the cost of an accidental click is bounded
 *     (e.g. delete a run — easy to re-create).
 *
 *   - **typed-name**: adds a text input the user must fill with
 *     ``typedName.expected`` before Confirm enables. Suitable for ops with a
 *     blast radius that warrants real friction (delete an ontology, which
 *     cascades into classes / properties / edges).
 *
 * Visual / a11y conventions match ``OntologyRenameDialog``:
 *
 *   - ``role="dialog"`` with ``aria-labelledby`` + ``aria-describedby``
 *   - z-index 200, backdrop ``black/50``, close on backdrop click + Escape
 *   - Confirm button initial focus when not typed-name; the input gets focus
 *     when typed-name (so the user can't accidentally confirm with Enter)
 */

export type ConfirmDialogMode = "plain" | "typed-name";

export interface ConfirmDialogTypedName {
  /** The exact string the user must type to enable Confirm. */
  expected: string;
  /** Label rendered above the input ("Type 'foo' to confirm"). */
  label: string;
  /** Optional placeholder shown inside the input (defaults to ``expected``). */
  placeholder?: string;
}

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  /** Message body — pre-formatted text. May include ``\\n`` for line breaks. */
  message: string;
  /** Confirm button label (default "Confirm"). */
  confirmLabel?: string;
  /** Cancel button label (default "Cancel"). */
  cancelLabel?: string;
  /** When true, Confirm is rendered with red danger styling (the default for
   *  this component, since it exists primarily for destructive ops). */
  danger?: boolean;
  /** When set, switches to typed-name mode. */
  typedName?: ConfirmDialogTypedName;
  /** Fired when the user clicks Confirm (and, in typed-name mode, after the
   *  expected string has been typed). */
  onConfirm: () => void;
  /** Fired on Cancel click, backdrop click, Escape key, or × button. */
  onClose: () => void;
}

export default function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  danger = true,
  typedName,
  onConfirm,
  onClose,
}: ConfirmDialogProps) {
  const [typed, setTyped] = useState("");
  const inputRef = useRef<HTMLInputElement | null>(null);
  const confirmButtonRef = useRef<HTMLButtonElement | null>(null);

  // Reset the typed-name input every time the dialog re-opens. Without this,
  // a prior dialog session's value would leak in and could pre-enable
  // Confirm on the next open.
  useEffect(() => {
    if (open) {
      setTyped("");
    }
  }, [open]);

  // Initial focus: input in typed-name mode (forces the user past the gate),
  // confirm button otherwise (preserves keyboard ergonomics).
  useEffect(() => {
    if (!open) return;
    const target = typedName ? inputRef.current : confirmButtonRef.current;
    target?.focus();
  }, [open, typedName]);

  // Escape closes the dialog. We register on document so it works even when
  // focus is inside a non-form descendant.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onClose();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  if (!open) return null;

  const typedMatches = typedName ? typed === typedName.expected : true;
  const confirmDisabled = !typedMatches;

  const titleId = "confirm-dialog-title";
  const messageId = "confirm-dialog-message";

  const confirmClass = danger
    ? "px-3 py-1.5 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50 disabled:cursor-not-allowed"
    : "px-3 py-1.5 text-sm bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed";

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
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={messageId}
        className="bg-white rounded-xl shadow-xl border border-gray-200 w-full max-w-md p-6"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between mb-3">
          <h2 id={titleId} className="text-lg font-semibold text-gray-900">
            {title}
          </h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-gray-400 hover:text-gray-600 -mt-1 -mr-2 px-2 py-1 text-lg leading-none"
          >
            ×
          </button>
        </div>

        <p
          id={messageId}
          className="text-sm text-gray-700 whitespace-pre-line mb-4"
        >
          {message}
        </p>

        {typedName && (
          <div className="mb-4">
            <label
              htmlFor="confirm-dialog-typed-name"
              className="block text-xs font-medium text-gray-600 mb-1"
            >
              {typedName.label}
            </label>
            <input
              ref={inputRef}
              id="confirm-dialog-typed-name"
              type="text"
              value={typed}
              onChange={(e) => setTyped(e.target.value)}
              placeholder={typedName.placeholder ?? typedName.expected}
              autoComplete="off"
              autoCorrect="off"
              autoCapitalize="off"
              spellCheck={false}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono"
              onKeyDown={(e) => {
                if (e.key === "Enter" && typedMatches) {
                  e.preventDefault();
                  onConfirm();
                }
              }}
            />
          </div>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <button
            type="button"
            onClick={onClose}
            className="px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-100 rounded-lg"
          >
            {cancelLabel}
          </button>
          <button
            ref={confirmButtonRef}
            type="button"
            onClick={onConfirm}
            disabled={confirmDisabled}
            className={confirmClass}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
