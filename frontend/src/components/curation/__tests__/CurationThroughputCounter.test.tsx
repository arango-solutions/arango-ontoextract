/**
 * Tests for ``CurationThroughputCounter`` (Q.5).
 *
 * Verifies the badge:
 *   - Shows an "—" placeholder before any decisions are recorded.
 *   - Updates live when the throughput tracker emits new state.
 *   - Renders an arrow hint when trailing rate diverges from session
 *     rate by ≥ 10 %.
 */

import { act, render, screen } from "@testing-library/react";

import CurationThroughputCounter from "../CurationThroughputCounter";
import {
  recordCurationDecisionLatencyOnly,
  resetCurationSession,
} from "@/lib/curationThroughput";

jest.mock("@/lib/api-client", () => ({
  api: { post: jest.fn().mockResolvedValue({ ok: true }) },
}));

beforeEach(() => {
  jest.useFakeTimers();
  jest.setSystemTime(new Date("2026-05-01T00:00:00Z"));
  resetCurationSession();
});

afterEach(() => {
  jest.useRealTimers();
});

function tick(ms: number) {
  jest.setSystemTime(Date.now() + ms);
}

describe("CurationThroughputCounter", () => {
  it("renders an em-dash placeholder with no data", () => {
    render(<CurationThroughputCounter />);
    const badge = screen.getByTestId("curation-throughput-counter");
    expect(badge.textContent).toContain("—");
    expect(badge.getAttribute("aria-label")).toMatch(/no data/i);
  });

  it("updates after a decision is recorded", () => {
    render(<CurationThroughputCounter />);

    // 60 s active time × 1 decision ⇒ 60/h
    act(() => {
      tick(60_000);
      recordCurationDecisionLatencyOnly();
    });

    const badge = screen.getByTestId("curation-throughput-counter");
    expect(badge.textContent).toContain("60");
    expect(badge.getAttribute("aria-label")).toMatch(/concepts per hour/);
  });

  it("renders the up arrow when trailing rate exceeds session rate", () => {
    render(<CurationThroughputCounter />);

    act(() => {
      // 15 slow decisions (60 s each) so the trailing-10 window does
      // not include any of them — session rate is dominated by the
      // slow ones (~60/h).
      for (let i = 0; i < 15; i += 1) {
        tick(60_000);
        recordCurationDecisionLatencyOnly();
      }
      // 10 fast decisions (5 s each) — these fully populate trailing-10
      // ⇒ trailing rate ≈ 720/h, well above session ⇒ ↑.
      for (let i = 0; i < 10; i += 1) {
        tick(5_000);
        recordCurationDecisionLatencyOnly();
      }
    });

    const badge = screen.getByTestId("curation-throughput-counter");
    const upArrow = badge.querySelector("span.text-emerald-600");
    expect(upArrow?.textContent).toBe("↑");
  });

  it("renders the down arrow when trailing rate falls below session rate", () => {
    render(<CurationThroughputCounter />);

    act(() => {
      // 15 fast decisions (5 s each) — session rate ≈ 720/h.
      for (let i = 0; i < 15; i += 1) {
        tick(5_000);
        recordCurationDecisionLatencyOnly();
      }
      // 10 slow decisions (60 s each) fully populate trailing-10
      // ⇒ trailing rate ≈ 60/h, well below session ⇒ ↓.
      for (let i = 0; i < 10; i += 1) {
        tick(60_000);
        recordCurationDecisionLatencyOnly();
      }
    });

    const badge = screen.getByTestId("curation-throughput-counter");
    const downArrow = badge.querySelector("span.text-rose-600");
    expect(downArrow?.textContent).toBe("↓");
  });

  it("renders the full variant with extra breakdown copy", () => {
    render(<CurationThroughputCounter variant="full" />);
    act(() => {
      tick(30_000);
      recordCurationDecisionLatencyOnly();
    });

    const card = screen.getByTestId("curation-throughput-counter");
    expect(card.textContent).toContain("Throughput");
    expect(card.textContent).toContain("session");
    expect(card.textContent).toContain("decisions");
  });
});
