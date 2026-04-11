import { filterStepsByTimestamp } from "../filterStepsByTimestamp";
import type { StepStatus } from "@/types/pipeline";

function makeSteps(): Map<string, StepStatus> {
  const m = new Map<string, StepStatus>();
  m.set("strategy_selector", {
    status: "completed",
    startedAt: "2026-04-09T10:00:00.000Z",
    completedAt: "2026-04-09T10:00:01.000Z",
  });
  m.set("extraction_agent", {
    status: "completed",
    startedAt: "2026-04-09T10:00:01.000Z",
    completedAt: "2026-04-09T10:00:25.000Z",
  });
  m.set("consistency_checker", {
    status: "completed",
    startedAt: "2026-04-09T10:00:25.000Z",
    completedAt: "2026-04-09T10:00:26.000Z",
  });
  m.set("quality_judge", {
    status: "completed",
    startedAt: "2026-04-09T10:00:26.000Z",
    completedAt: "2026-04-09T10:00:38.000Z",
  });
  m.set("entity_resolution_agent", {
    status: "completed",
    startedAt: "2026-04-09T10:00:26.000Z",
    completedAt: "2026-04-09T10:00:27.000Z",
  });
  m.set("pre_curation_filter", {
    status: "completed",
    startedAt: "2026-04-09T10:00:38.000Z",
    completedAt: "2026-04-09T10:00:39.000Z",
  });
  return m;
}

// Unix seconds for 2026-04-09T10:00:00.000Z + offset
const BASE_TS = new Date("2026-04-09T10:00:00.000Z").getTime() / 1000;
const T = (seconds: number) => BASE_TS + seconds;

describe("filterStepsByTimestamp", () => {
  it("returns original steps when timestamp is null", () => {
    const steps = makeSteps();
    const result = filterStepsByTimestamp(steps, null);
    expect(result).toBe(steps);
  });

  it("shows all steps as pending before the pipeline started", () => {
    const result = filterStepsByTimestamp(makeSteps(), T(-10));
    result.forEach((step) => {
      expect(step.status).toBe("pending");
    });
  });

  it("shows first step as running during its execution window", () => {
    const result = filterStepsByTimestamp(makeSteps(), T(0.5));
    expect(result.get("strategy_selector")!.status).toBe("running");
    expect(result.get("extraction_agent")!.status).toBe("pending");
    expect(result.get("consistency_checker")!.status).toBe("pending");
  });

  it("shows first step completed and second running mid-extraction", () => {
    const result = filterStepsByTimestamp(makeSteps(), T(10));
    expect(result.get("strategy_selector")!.status).toBe("completed");
    expect(result.get("extraction_agent")!.status).toBe("running");
    expect(result.get("consistency_checker")!.status).toBe("pending");
    expect(result.get("quality_judge")!.status).toBe("pending");
  });

  it("shows parallel steps (quality_judge + ER) as running simultaneously", () => {
    const result = filterStepsByTimestamp(makeSteps(), T(26.5));
    expect(result.get("strategy_selector")!.status).toBe("completed");
    expect(result.get("extraction_agent")!.status).toBe("completed");
    expect(result.get("consistency_checker")!.status).toBe("completed");
    expect(result.get("quality_judge")!.status).toBe("running");
    expect(result.get("entity_resolution_agent")!.status).toBe("running");
    expect(result.get("pre_curation_filter")!.status).toBe("pending");
  });

  it("shows all steps completed after the pipeline finished", () => {
    const result = filterStepsByTimestamp(makeSteps(), T(60));
    result.forEach((step) => {
      expect(step.status).toBe("completed");
    });
  });

  it("clears startedAt/completedAt for pending steps", () => {
    const result = filterStepsByTimestamp(makeSteps(), T(-10));
    const step = result.get("extraction_agent")!;
    expect(step.startedAt).toBeUndefined();
    expect(step.completedAt).toBeUndefined();
  });

  it("clears completedAt for running steps", () => {
    const result = filterStepsByTimestamp(makeSteps(), T(10));
    const step = result.get("extraction_agent")!;
    expect(step.status).toBe("running");
    expect(step.startedAt).toBeDefined();
    expect(step.completedAt).toBeUndefined();
  });

  it("handles steps with no startedAt as always pending", () => {
    const steps = new Map<string, StepStatus>();
    steps.set("pending_step", { status: "pending" });
    const result = filterStepsByTimestamp(steps, T(100));
    expect(result.get("pending_step")!.status).toBe("pending");
  });

  it("preserves failed status for completed-with-failure steps", () => {
    const steps = new Map<string, StepStatus>();
    steps.set("failed_step", {
      status: "failed",
      startedAt: "2026-04-09T10:00:01.000Z",
      completedAt: "2026-04-09T10:00:05.000Z",
      error: "something broke",
    });

    const after = filterStepsByTimestamp(steps, T(10));
    expect(after.get("failed_step")!.status).toBe("failed");
    expect(after.get("failed_step")!.error).toBe("something broke");

    const during = filterStepsByTimestamp(steps, T(3));
    expect(during.get("failed_step")!.status).toBe("running");
  });
});
