/**
 * React Flow `onError` filter + global `console.warn` shim.
 *
 * React Flow v11 has a known false-positive in dev: error code `'002'`
 * ("It looks like you've created a new nodeTypes or edgeTypes object…")
 * fires under React 18 Strict Mode even when the consumer correctly
 * defines `nodeTypes`/`edgeTypes` at module scope.
 *
 * Cause: in `useNodeOrEdgeTypes` (see
 * `node_modules/@reactflow/core/dist/esm/index.js` around the
 * `useNodeOrEdgeTypes` definition), the warn check fires whenever the
 * inner `useMemo` body re-runs AND the keys are still equal. React 18
 * Strict Mode intentionally discards cached `useMemo` values to test
 * purity, which makes the body re-run with the same module-scoped
 * object reference, the keys match, and the warning fires.
 *
 * Two suppression layers, because React Flow uses two emit paths:
 *
 *   1. **`onError` prop path.** When the consumer passes
 *      `<ReactFlow onError={reactFlowErrorFilter} ...>`, the store's
 *      `onError` slot is replaced and `useNodeOrEdgeTypes` calls
 *      `store.getState().onError?.('002', ...)`, hitting our filter.
 *      That works for the steady-state case.
 *
 *   2. **`devWarn` direct path.** On the FIRST render, the store's
 *      `onError` slot still holds React Flow's default `devWarn`
 *      because the user-supplied `onError` is applied via a
 *      `useEffect` that fires AFTER the initial `useNodeOrEdgeTypes`
 *      runs. `devWarn` calls `console.warn(...)` directly, bypassing
 *      the filter entirely. This is the path that produced the
 *      warning the user saw on the Pipeline Monitor after the prior
 *      fix shipped. Patching `console.warn` once at module load
 *      catches it -- the install must happen before any `<ReactFlow>`
 *      mounts, which is guaranteed because every consumer imports
 *      both `reactflow` and this file (Tree-shaking-safe: the
 *      imports' execution order matches their declaration order).
 *
 * The console shim suppresses ONLY the exact 002 message so we don't
 * accidentally hide legitimate React Flow diagnostics (e.g. the
 * "edge source not found" 008 message that surfaces real bugs).
 *
 * Usage:
 *   <ReactFlow ... onError={reactFlowErrorFilter} />
 *
 * Just importing this module is enough to install the console shim;
 * the prop wiring on top is a defence-in-depth for non-strict-mode
 * paths.
 */

const SUPPRESSED_CODES = new Set<string>(["002"]);

/**
 * Substring match on the exact text React Flow's `devWarn` emits
 * for the 002 code (see `node_modules/@reactflow/core/dist/esm/index.mjs`
 * `error002` template). The message is stable across the v11 minors
 * we depend on; pinning a substring instead of a regex keeps us
 * resilient to whitespace tweaks while still being narrow enough to
 * never match unrelated warnings.
 */
const RF_002_NEEDLE =
  "It looks like you've created a new nodeTypes or edgeTypes object";

/**
 * Install the `console.warn` shim exactly once. Safe to call from any
 * import order; idempotent across hot-reloads (the marker prop on the
 * patched function prevents double-wrapping, which would otherwise
 * grow a chain of forwarders on every dev-mode HMR cycle).
 *
 * SSR no-op: skips entirely when `console` is unavailable (it isn't,
 * in Node, but the guard keeps the module fully tree-shake-safe and
 * defends against exotic runtimes).
 */
function installConsoleWarnShim(): void {
  if (typeof console === "undefined" || typeof console.warn !== "function") {
    return;
  }
  // Idempotency marker -- avoids stacking forwarders on HMR.
  type MarkedWarn = typeof console.warn & { __aoeRfShimInstalled?: true };
  const current = console.warn as MarkedWarn;
  if (current.__aoeRfShimInstalled === true) return;

  const original = console.warn.bind(console);
  const wrapped: MarkedWarn = ((...args: unknown[]) => {
    // React Flow's devWarn always passes a single string argument.
    // Defensive: only inspect when the first arg is a string so we
    // don't pay a stringify cost (and risk false matches on object
    // toString forms) for ordinary object-arg warnings.
    const first = args[0];
    if (typeof first === "string" && first.includes(RF_002_NEEDLE)) {
      // Strict-mode false positive -- see file header for rationale.
      return;
    }
    original(...(args as Parameters<typeof console.warn>));
  }) as MarkedWarn;
  wrapped.__aoeRfShimInstalled = true;
  console.warn = wrapped;
}

installConsoleWarnShim();

export function reactFlowErrorFilter(id: string, message: string): void {
  if (SUPPRESSED_CODES.has(id)) {
    // Strict-mode false positive — see file header.
    return;
  }
  if (process.env.NODE_ENV === "development") {
    console.warn(
      `[React Flow]: ${message} Help: https://reactflow.dev/error#${id}`,
    );
  }
}
