/**
 * Minimal app-wide toast surface.
 *
 * Why this exists
 * ---------------
 *
 * `ui-architecture.mdc` §18 mandates undo-toasts for reversible
 * destructive ops (delete, reject, remove-import) — but until H.16 the
 * codebase had no toast host. `contextMenus/class.ts` documents the gap
 * explicitly: "the rule's preferred undo-toast pattern requires
 * deferred-delete + a global toast host that don't exist yet". H.16's
 * drag-and-drop import flow needs the undo affordance immediately, so
 * this module ships the host alongside the feature.
 *
 * Design
 * ------
 *
 * * **Module-level singleton** so any component can `pushToast(...)`
 *   without threading a React context. A single `<ToastHost />` mounted
 *   in `workspace/page.tsx` subscribes to the event stream and renders.
 * * **Stable shape** so the host (and tests) don't have to defend
 *   against missing fields. Every toast has `id`, `message`, `kind`,
 *   `createdAt`, optional `action` (label + onClick), and optional
 *   `durationMs` (defaults to 5000; pass 0 for "sticky until dismissed").
 * * **Auto-dismiss is the host's job**, not this module's, because
 *   timers tied to React render lifecycle belong with the renderer (so
 *   they get cancelled on unmount). This module owns the data; the
 *   host owns the presentation.
 * * **Subscribe / unsubscribe** mirrors the pattern other apps use for
 *   event-bus-style state outside React (e.g. SWR's mutation events).
 *   No external dependency.
 *
 * Not React Context because
 * -------------------------
 *
 * `pushToast` callers include pure helpers (e.g. `class.ts` context-menu
 * builders) that have no React tree access. The singleton+event pattern
 * keeps the API the same everywhere.
 */

export type ToastKind = "info" | "success" | "warning" | "error";

export interface ToastAction {
  /** Button label, e.g. "Undo" or "Open". */
  label: string;
  /** Fired when the action button is clicked. The host dismisses the
   *  toast automatically after `onClick` returns. */
  onClick: () => void | Promise<void>;
}

export interface Toast {
  /** Stable identifier, unique per toast. Callers can capture it to
   *  programmatically `dismissToast(id)` (e.g. when an async operation
   *  the toast represents completes). */
  id: string;
  message: string;
  kind: ToastKind;
  /** Auto-dismiss timeout in ms. Defaults to 5000. Pass 0 to keep the
   *  toast on screen until the user clicks × or the action fires. */
  durationMs: number;
  /** When set, the host renders an action button next to the dismiss ×. */
  action?: ToastAction;
  /** Epoch ms — useful for ordering tests and for the host's "oldest
   *  first" stacking. */
  createdAt: number;
}

export type ToastInput = Omit<Toast, "id" | "createdAt" | "kind" | "durationMs"> & {
  kind?: ToastKind;
  durationMs?: number;
};

type Listener = (toasts: Toast[]) => void;

const listeners = new Set<Listener>();
let queue: Toast[] = [];
let nextSeq = 1;

function emit(): void {
  const snapshot = queue.slice();
  for (const l of listeners) {
    try {
      l(snapshot);
    } catch (err) {
      // A misbehaving subscriber must not poison the rest of the chain.
      // The host is in-app code we author, so a thrown error here is a
      // bug to surface in the dev console, not silently swallow.
      console.error("toast listener threw", err);
    }
  }
}

/**
 * Push a new toast onto the stack. Returns the generated `id` so callers
 * can `dismissToast(id)` programmatically (the common case is "the
 * pending action this toast represents completed faster than its
 * timeout — drop the toast"). Defaults: kind=`info`, durationMs=5000.
 */
export function pushToast(input: ToastInput): string {
  const id = `toast-${nextSeq++}`;
  const toast: Toast = {
    id,
    message: input.message,
    kind: input.kind ?? "info",
    durationMs: input.durationMs ?? 5000,
    action: input.action,
    createdAt: Date.now(),
  };
  queue = [...queue, toast];
  emit();
  return id;
}

/** Remove one toast by id. Idempotent — dismissing a non-existent id is
 *  a no-op so callers don't have to guard against races (e.g. the host's
 *  auto-dismiss timer racing with the action button). */
export function dismissToast(id: string): void {
  const next = queue.filter((t) => t.id !== id);
  if (next.length === queue.length) return;
  queue = next;
  emit();
}

/** Subscribe to the toast queue. Returns an unsubscribe function. The
 *  initial call delivers the current queue synchronously so React effects
 *  can hydrate without a flash of empty state. A throwing listener on
 *  the initial delivery is logged and ignored — same isolation policy
 *  as ``emit`` so a buggy subscriber cannot crash the registration call. */
export function subscribeToasts(listener: Listener): () => void {
  listeners.add(listener);
  try {
    listener(queue.slice());
  } catch (err) {
    console.error("toast listener threw on initial delivery", err);
  }
  return () => {
    listeners.delete(listener);
  };
}

/** Drop every queued toast. Used by tests and (defensively) by the
 *  logout flow so a stale undo button can't fire across sessions. */
export function clearToasts(): void {
  if (queue.length === 0) return;
  queue = [];
  emit();
}

/** Diagnostic — tests use this to assert "queue is empty / queue has N".
 *  Returns a fresh array; callers cannot mutate the internal state. */
export function getToastsSnapshot(): Toast[] {
  return queue.slice();
}
