/**
 * Tests for ``curationThroughput`` (Q.5).
 *
 * The module owns a singleton state, so every test resets the session
 * via ``resetCurationSession`` and stubs ``api.post`` so no network
 * traffic happens.
 */

import {
  deriveConceptsPerHour,
  deriveTrailingRate,
  getCurationThroughputState,
  recordCurationBatchDecision,
  recordCurationDecision,
  recordCurationDecisionLatencyOnly,
  resetCurationSession,
  subscribeCurationThroughput,
} from "../curationThroughput";

const apiPost = jest.fn();

jest.mock("@/lib/api-client", () => ({
  api: {
    post: (...args: unknown[]) => apiPost(...args),
  },
}));

beforeEach(() => {
  apiPost.mockReset();
  apiPost.mockResolvedValue({ ok: true });
  resetCurationSession();
});

afterEach(() => {
  jest.useRealTimers();
});

function advanceMockedClock(ms: number) {
  jest.setSystemTime(Date.now() + ms);
}

describe("recordCurationDecisionLatencyOnly", () => {
  it("returns latency from session start on first call", () => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2026-05-01T00:00:00Z"));
    resetCurationSession();

    advanceMockedClock(2_000);
    const latency = recordCurationDecisionLatencyOnly();
    expect(latency).toBe(2_000);

    const s = getCurationThroughputState();
    expect(s.decisionCount).toBe(1);
    expect(s.activeTimeMs).toBe(2_000);
    expect(s.recent).toHaveLength(1);
  });

  it("measures latency from previous decision after the first", () => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2026-05-01T00:00:00Z"));
    resetCurationSession();

    advanceMockedClock(1_000);
    recordCurationDecisionLatencyOnly();
    advanceMockedClock(3_000);
    const second = recordCurationDecisionLatencyOnly();

    expect(second).toBe(3_000);
    expect(getCurationThroughputState().activeTimeMs).toBe(4_000);
  });

  it("caps a single latency at 30 minutes so an outlier doesn't blow up the average", () => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2026-05-01T00:00:00Z"));
    resetCurationSession();

    advanceMockedClock(60 * 60 * 1000); // 1 hour idle
    const latency = recordCurationDecisionLatencyOnly();
    expect(latency).toBe(30 * 60 * 1000);
  });

  it("notifies subscribers on every record", () => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2026-05-01T00:00:00Z"));
    resetCurationSession();

    const spy = jest.fn();
    const unsubscribe = subscribeCurationThroughput(spy);
    advanceMockedClock(500);
    recordCurationDecisionLatencyOnly();
    advanceMockedClock(500);
    recordCurationDecisionLatencyOnly();
    expect(spy).toHaveBeenCalledTimes(2);
    unsubscribe();
  });
});

describe("recordCurationDecision", () => {
  it("posts the decide payload with decision_latency_ms attached", async () => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2026-05-01T00:00:00Z"));
    resetCurationSession();

    advanceMockedClock(1_500);
    await recordCurationDecision({
      run_id: "r1",
      entity_key: "c1",
      entity_type: "class",
      decision: "approve",
    });

    expect(apiPost).toHaveBeenCalledTimes(1);
    const [endpoint, body] = apiPost.mock.calls[0];
    expect(endpoint).toBe("/api/v1/curation/decide");
    expect(body).toMatchObject({
      run_id: "r1",
      entity_key: "c1",
      entity_type: "class",
      decision: "approve",
      decision_latency_ms: 1_500,
    });
  });
});

describe("recordCurationBatchDecision", () => {
  it("counts all batch items and splits latency evenly across them", async () => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2026-05-01T00:00:00Z"));
    resetCurationSession();

    advanceMockedClock(900);
    await recordCurationBatchDecision({
      run_id: "r1",
      decisions: [
        { entity_key: "a" },
        { entity_key: "b" },
        { entity_key: "c" },
      ],
    });

    const [endpoint, body] = apiPost.mock.calls[0];
    expect(endpoint).toBe("/api/v1/curation/batch");
    // 900 / 3 = 300 ms per item.
    body.decisions.forEach((d: Record<string, unknown>) => {
      expect(d.decision_latency_ms).toBe(300);
    });

    const state = getCurationThroughputState();
    // The first record contributed real latency (900 ms); the 2 phantom
    // ticks contributed 0 ms each. Count rises by 3.
    expect(state.decisionCount).toBe(3);
    expect(state.activeTimeMs).toBe(900);
  });

  it("handles empty batches without crashing", async () => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2026-05-01T00:00:00Z"));
    resetCurationSession();

    await recordCurationBatchDecision({ run_id: "r1", decisions: [] });
    const [, body] = apiPost.mock.calls[0];
    expect(body.decisions).toEqual([]);
  });
});

describe("derived rates", () => {
  it("returns null until at least one decision has been recorded", () => {
    expect(deriveConceptsPerHour(getCurationThroughputState())).toBeNull();
    expect(deriveTrailingRate(getCurationThroughputState())).toBeNull();
  });

  it("computes a per-hour rate from active time", () => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2026-05-01T00:00:00Z"));
    resetCurationSession();

    // 12 decisions, 60 s of active time each ⇒ 12 minutes total ⇒ 60/h.
    for (let i = 0; i < 12; i += 1) {
      advanceMockedClock(60_000);
      recordCurationDecisionLatencyOnly();
    }
    const rate = deriveConceptsPerHour(getCurationThroughputState());
    expect(rate).toBeCloseTo(60, 5);
  });

  it("trailing rate reflects the most recent N decisions only", () => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2026-05-01T00:00:00Z"));
    resetCurationSession();

    // 5 slow decisions (60 s each), then 5 fast decisions (5 s each).
    for (let i = 0; i < 5; i += 1) {
      advanceMockedClock(60_000);
      recordCurationDecisionLatencyOnly();
    }
    for (let i = 0; i < 5; i += 1) {
      advanceMockedClock(5_000);
      recordCurationDecisionLatencyOnly();
    }

    const trailing = deriveTrailingRate(getCurationThroughputState(), 5);
    // 5 decisions / 25 s = 720/h
    expect(trailing).toBeCloseTo(720, 1);
  });
});

describe("resetCurationSession", () => {
  it("zeroes the counters and notifies subscribers", () => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2026-05-01T00:00:00Z"));
    resetCurationSession();

    advanceMockedClock(500);
    recordCurationDecisionLatencyOnly();
    expect(getCurationThroughputState().decisionCount).toBe(1);

    const spy = jest.fn();
    const unsubscribe = subscribeCurationThroughput(spy);
    resetCurationSession();
    expect(spy).toHaveBeenCalledTimes(1);
    expect(getCurationThroughputState().decisionCount).toBe(0);
    expect(getCurationThroughputState().activeTimeMs).toBe(0);
    unsubscribe();
  });
});
