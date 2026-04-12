import { buildStepTimelineEvents } from "../buildStepTimelineEvents";
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

describe("buildStepTimelineEvents", () => {
  it("creates two events (started + completed) per step with timestamps", () => {
    const events = buildStepTimelineEvents(makeSteps());
    expect(events).toHaveLength(12);
  });

  it("uses step_started and step_completed event types", () => {
    const events = buildStepTimelineEvents(makeSteps());
    const started = events.filter((e) => e.event_type === "step_started");
    const completed = events.filter((e) => e.event_type === "step_completed");
    expect(started).toHaveLength(6);
    expect(completed).toHaveLength(6);
  });

  it("uses human-readable labels from STEP_LABELS", () => {
    const events = buildStepTimelineEvents(makeSteps());
    const labels = events.map((e) => e.entity_label);
    expect(labels).toContain("Strategy Selector");
    expect(labels).toContain("Extraction Agent");
    expect(labels).toContain("Pre-Curation Filter");
  });

  it("converts ISO timestamps to Unix seconds", () => {
    const events = buildStepTimelineEvents(makeSteps());
    const stratStart = events.find((e) => e.entity_key === "step:strategy_selector:started");
    const expected = new Date("2026-04-09T10:00:00.000Z").getTime() / 1000;
    expect(stratStart!.timestamp).toBe(expected);
  });

  it("tags events with collection=pipeline_steps", () => {
    const events = buildStepTimelineEvents(makeSteps());
    expect(events.every((e) => e.collection === "pipeline_steps")).toBe(true);
  });

  it("skips steps that have no timestamps", () => {
    const steps = new Map<string, StepStatus>();
    steps.set("strategy_selector", { status: "pending" });
    steps.set("extraction_agent", {
      status: "running",
      startedAt: "2026-04-09T10:00:01.000Z",
    });
    const events = buildStepTimelineEvents(steps);
    expect(events).toHaveLength(1);
    expect(events[0].event_type).toBe("step_started");
    expect(events[0].entity_label).toBe("Extraction Agent");
  });

  it("returns empty array for empty steps map", () => {
    expect(buildStepTimelineEvents(new Map())).toEqual([]);
  });
});
