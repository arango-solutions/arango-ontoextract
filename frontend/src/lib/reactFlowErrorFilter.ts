/**
 * React Flow `onError` filter.
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
 * Forwarding to `console.warn` for every other code preserves
 * legitimate React Flow diagnostics; only `'002'` is silenced.
 *
 * Usage:
 *   <ReactFlow ... onError={reactFlowErrorFilter} />
 *
 * The filter is exported as a stable module-scope function so passing
 * it as a prop does not itself trigger React Flow's reference checks.
 */

const SUPPRESSED_CODES = new Set<string>(["002"]);

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
