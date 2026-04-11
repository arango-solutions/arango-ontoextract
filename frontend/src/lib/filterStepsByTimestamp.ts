import type { StepStatus } from "@/types/pipeline";

/**
 * Given the full set of pipeline steps and a VCR timestamp (Unix seconds),
 * return a new Map where each step's status reflects what it would have been
 * at that point in time:
 *
 *   - timestamp < startedAt  →  pending
 *   - startedAt <= timestamp < completedAt  →  running
 *   - timestamp >= completedAt  →  original status (completed / failed)
 *
 * When `timestamp` is null the original steps are returned unchanged.
 */
export function filterStepsByTimestamp(
  steps: Map<string, StepStatus>,
  timestamp: number | null,
): Map<string, StepStatus> {
  if (timestamp == null) return steps;

  const tsMs = timestamp * 1000;
  const filtered = new Map<string, StepStatus>();

  steps.forEach((step, key) => {
    if (!step.startedAt) {
      filtered.set(key, { ...step, status: "pending" });
      return;
    }

    const startMs = new Date(step.startedAt).getTime();

    if (tsMs < startMs) {
      filtered.set(key, {
        ...step,
        status: "pending",
        startedAt: undefined,
        completedAt: undefined,
      });
      return;
    }

    if (step.completedAt) {
      const endMs = new Date(step.completedAt).getTime();
      if (tsMs < endMs) {
        filtered.set(key, {
          ...step,
          status: "running",
          completedAt: undefined,
        });
        return;
      }
    }

    filtered.set(key, step);
  });

  return filtered;
}
