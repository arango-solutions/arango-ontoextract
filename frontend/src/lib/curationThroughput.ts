/**
 * Q.5 — Client-side curator throughput tracking.
 *
 * Why client-side, not server-side?
 *   We want "concepts reviewed per hour" to mean "active curation time"
 *   — not "wall-clock time including idle minutes". The server only
 *   sees ``created_at`` timestamps and cannot distinguish a 30-second
 *   gap (deciding on a hard case) from a 30-minute gap (lunch). The
 *   client measures the gap between consecutive submit clicks and
 *   sends it as ``decision_latency_ms`` on the decide call. The
 *   backend persists it and exposes a derived ``decisions_per_hour``
 *   from those measurements.
 *
 * Surface:
 *   - ``recordCurationDecision(payload)`` — drop-in replacement for the
 *     direct ``api.post("/api/v1/curation/decide", payload)`` call. Adds
 *     ``decision_latency_ms`` (computed from previous decision or
 *     session start), updates the local throughput state, and notifies
 *     subscribers.
 *   - ``recordCurationDecisionLatencyOnly()`` — same accounting, no
 *     network call. Use this when the caller already POSTed (e.g. the
 *     decision was driven by another endpoint such as
 *     ``/api/v1/revisions/.../accept``) but should still count toward
 *     "concepts reviewed per hour".
 *   - ``subscribeCurationThroughput(cb)`` — returns unsubscribe fn.
 *   - ``getCurationThroughputState()`` — current snapshot.
 *   - ``resetCurationSession()`` — call on curation page mount.
 *
 * State shape is intentionally tiny (just count + latency sums) so the
 * counter component can derive both "session" and "trailing window"
 * rates without re-rendering the page on every keystroke.
 */

import { api } from "@/lib/api-client";

export interface CurationThroughputState {
  sessionStartMs: number;
  lastDecisionMs: number | null;
  /** Total decisions recorded this session. */
  decisionCount: number;
  /** Sum of measured latencies (ms from previous decision or session
   *  start) — i.e. "active curation time". */
  activeTimeMs: number;
  /** Trailing window of (timestampMs, latencyMs) tuples for "last 5 min"
   *  style derived rates. Capped at 60 entries. */
  recent: { atMs: number; latencyMs: number }[];
}

const RECENT_CAP = 60;

let state: CurationThroughputState = freshState();
const listeners = new Set<(s: CurationThroughputState) => void>();

function freshState(): CurationThroughputState {
  return {
    sessionStartMs: Date.now(),
    lastDecisionMs: null,
    decisionCount: 0,
    activeTimeMs: 0,
    recent: [],
  };
}

function notify(): void {
  // Snapshot so subscribers can rely on referential equality
  // checks against the previous snapshot.
  const snap: CurationThroughputState = {
    ...state,
    recent: state.recent.slice(),
  };
  listeners.forEach((cb) => cb(snap));
}

export function getCurationThroughputState(): CurationThroughputState {
  return { ...state, recent: state.recent.slice() };
}

export function subscribeCurationThroughput(
  cb: (s: CurationThroughputState) => void,
): () => void {
  listeners.add(cb);
  return () => listeners.delete(cb);
}

export function resetCurationSession(): void {
  state = freshState();
  notify();
}

/** Record a decision's latency without making any network call. */
export function recordCurationDecisionLatencyOnly(): number {
  const now = Date.now();
  const prev = state.lastDecisionMs ?? state.sessionStartMs;
  // Cap a single-decision latency at 30 minutes so a "got coffee, came
  // back, made one decision" outlier cannot blow up the active-time
  // sum and produce a "1 concept/hour" reading. Tunable.
  const latencyMs = Math.min(now - prev, 30 * 60 * 1000);

  state = {
    ...state,
    lastDecisionMs: now,
    decisionCount: state.decisionCount + 1,
    activeTimeMs: state.activeTimeMs + latencyMs,
    recent: [...state.recent, { atMs: now, latencyMs }].slice(-RECENT_CAP),
  };
  notify();
  return latencyMs;
}

/**
 * Drop-in replacement for ``api.post("/api/v1/curation/decide", body)``.
 * Adds ``decision_latency_ms`` and accounts for the decision in the
 * client-side throughput tracker.
 */
export async function recordCurationDecision<T = unknown>(
  body: Record<string, unknown>,
  options: { endpoint?: string } = {},
): Promise<T> {
  const latencyMs = recordCurationDecisionLatencyOnly();
  const endpoint = options.endpoint ?? "/api/v1/curation/decide";
  return api.post<T>(endpoint, {
    ...body,
    decision_latency_ms: latencyMs,
  });
}

/**
 * Batch variant for ``POST /api/v1/curation/batch``. The user only
 * clicked once, so we attribute one tick of elapsed time to the batch
 * as a whole, then split it evenly across the ``decisions`` so each
 * item's ``decision_latency_ms`` is comparable to single-decide rows.
 *
 * Pass the request body in the same shape the backend expects (with a
 * ``decisions`` array). The wrapper mutates that array to add per-item
 * ``decision_latency_ms`` values and records the batch as ``N``
 * separate ticks in the client tracker.
 */
export async function recordCurationBatchDecision<T = unknown>(
  body: { decisions: Array<Record<string, unknown>>; [k: string]: unknown },
  options: { endpoint?: string } = {},
): Promise<T> {
  const decisions = Array.isArray(body.decisions) ? body.decisions : [];
  const totalLatency = recordCurationDecisionLatencyOnly();
  const remainder = decisions.length > 0 ? Math.max(0, decisions.length - 1) : 0;
  // Account for the (N-1) phantom ticks (latency 0) so the count rises by
  // N total. The first tick already used the real elapsed time above.
  for (let i = 0; i < remainder; i += 1) {
    state = {
      ...state,
      decisionCount: state.decisionCount + 1,
      recent: [...state.recent, { atMs: Date.now(), latencyMs: 0 }].slice(
        -RECENT_CAP,
      ),
    };
  }
  if (remainder > 0) notify();

  const perItemLatency =
    decisions.length > 0 ? Math.round(totalLatency / decisions.length) : 0;
  const annotated = decisions.map((d) => ({
    ...d,
    decision_latency_ms: perItemLatency,
  }));

  const endpoint = options.endpoint ?? "/api/v1/curation/batch";
  return api.post<T>(endpoint, {
    ...body,
    decisions: annotated,
  });
}

/** Concepts-reviewed-per-hour derived from active curation time.
 *  Returns ``null`` when there is no usable measurement yet. */
export function deriveConceptsPerHour(s: CurationThroughputState): number | null {
  if (s.decisionCount === 0) return null;
  if (s.activeTimeMs <= 0) return null;
  return s.decisionCount / (s.activeTimeMs / 3_600_000);
}

/** Concepts/hour over the trailing N decisions (default 10). Useful for
 *  "am I speeding up or slowing down" without the session average
 *  damping the signal. */
export function deriveTrailingRate(
  s: CurationThroughputState,
  trailingCount = 10,
): number | null {
  if (s.recent.length === 0) return null;
  const window = s.recent.slice(-trailingCount);
  const sumMs = window.reduce((a, r) => a + r.latencyMs, 0);
  if (sumMs <= 0) return null;
  return window.length / (sumMs / 3_600_000);
}
