"use client";

import { useEffect, useRef, useState } from "react";

import {
  dismissToast,
  subscribeToasts,
  type Toast,
  type ToastKind,
} from "@/lib/toast";

/**
 * Bottom-centre toast surface for the workspace (`ui-architecture.mdc` §18).
 *
 * Behaviour
 * ---------
 *
 * * Subscribes to the module-level toast queue and renders the stack
 *   bottom-up (oldest at the top of the visible stack), so a brand-new
 *   toast pops in at the bottom where the user's eye is.
 * * Auto-dismisses each toast after `durationMs` unless `durationMs ===
 *   0` (sticky). The timer is owned by this component (not the toast
 *   module) so unmount cancels every pending timer — no leaks, no
 *   "toast disappears 5s after the user logged out" footguns.
 * * Action button (when provided) fires the toast's `onClick` and
 *   then dismisses the toast. Async actions are awaited so the toast
 *   stays visible while the user's revert is in flight.
 * * Keyboard: a per-toast × button is always rendered so the toast is
 *   never undismissable. Per workspace rule §18 we deliberately do NOT
 *   reach for `window.confirm` here.
 *
 * Not framework-managed because
 * -----------------------------
 *
 * The host is the only renderer of the singleton queue; we don't need
 * portals or context. The fixed-positioned wrapper sits above every
 * canvas overlay (z-[10000] so it clears `ManageImportsOverlay`'s
 * `z-[9999]`).
 */
export default function ToastHost() {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const timers = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  useEffect(() => {
    const unsubscribe = subscribeToasts((next) => {
      setToasts(next);
    });
    // Snapshot the ref so cleanup is defensive against a later
    // reassignment (react-hooks/exhaustive-deps). In practice the Map
    // instance is stable for the host's lifetime, so this snapshot
    // points at the same object the timer-scheduling effect mutates.
    const timerMap = timers.current;
    return () => {
      unsubscribe();
      for (const handle of timerMap.values()) clearTimeout(handle);
      timerMap.clear();
    };
  }, []);

  useEffect(() => {
    const seen = new Set(toasts.map((t) => t.id));

    // Schedule auto-dismiss timers for new (durationMs > 0) toasts. We
    // reschedule lazily — a toast already in `timers` keeps its handle.
    for (const t of toasts) {
      if (t.durationMs <= 0) continue;
      if (timers.current.has(t.id)) continue;
      const handle = setTimeout(() => {
        dismissToast(t.id);
        timers.current.delete(t.id);
      }, t.durationMs);
      timers.current.set(t.id, handle);
    }

    // Drop handles for toasts that were dismissed externally (via the
    // action button or `dismissToast` from another module) so we don't
    // leak the entries.
    for (const id of [...timers.current.keys()]) {
      if (!seen.has(id)) {
        clearTimeout(timers.current.get(id)!);
        timers.current.delete(id);
      }
    }
  }, [toasts]);

  if (toasts.length === 0) return null;

  return (
    <div
      className="fixed bottom-6 left-1/2 -translate-x-1/2 z-[10000] flex flex-col gap-2 items-center pointer-events-none"
      data-testid="toast-host"
      aria-live="polite"
      role="status"
    >
      {toasts.map((t) => (
        <ToastItem key={t.id} toast={t} />
      ))}
    </div>
  );
}

function ToastItem({ toast }: { toast: Toast }) {
  const [working, setWorking] = useState(false);

  const handleAction = async () => {
    if (!toast.action) return;
    setWorking(true);
    try {
      await toast.action.onClick();
    } finally {
      // Always dismiss after the action completes, success or failure.
      // Failure cases should push their own follow-up "couldn't undo"
      // toast rather than keep this one alive.
      dismissToast(toast.id);
    }
  };

  return (
    <div
      className={`pointer-events-auto rounded-lg shadow-lg backdrop-blur-sm flex items-center gap-3 px-4 py-2.5 min-w-[280px] max-w-[480px] border ${KIND_CLASSES[toast.kind]}`}
      data-testid={`toast-${toast.id}`}
      data-toast-kind={toast.kind}
    >
      <span className="text-sm flex-1">{toast.message}</span>
      {toast.action && (
        <button
          type="button"
          onClick={handleAction}
          disabled={working}
          className="text-xs font-semibold underline underline-offset-2 hover:no-underline disabled:opacity-50"
        >
          {working ? "…" : toast.action.label}
        </button>
      )}
      <button
        type="button"
        onClick={() => dismissToast(toast.id)}
        aria-label="Dismiss"
        className="text-lg leading-none opacity-70 hover:opacity-100"
      >
        ×
      </button>
    </div>
  );
}

const KIND_CLASSES: Record<ToastKind, string> = {
  info: "bg-slate-900/95 border-slate-700 text-slate-100",
  success: "bg-emerald-900/95 border-emerald-700 text-emerald-50",
  warning: "bg-amber-900/95 border-amber-700 text-amber-50",
  error: "bg-red-900/95 border-red-700 text-red-50",
};
