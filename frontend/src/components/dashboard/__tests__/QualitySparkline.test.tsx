/**
 * Tests for ``QualitySparkline`` (Q.3).
 *
 * Verifies the lazy fetch + render path, the loading skeleton, the
 * "no data" / single-snapshot edge cases, the trend arrow direction,
 * the event-source dot accent (extraction_completion / promotion),
 * the module-level cache (one fetch per ontology id even when
 * mounted twice), and accessibility metadata.
 */

import { render, screen, waitFor } from "@testing-library/react";

import QualitySparkline, {
  _resetSparklineCacheForTests,
} from "../QualitySparkline";

const loadQualityHistory = jest.fn();

jest.mock("@/lib/qualityHistory", () => ({
  loadQualityHistory: (...args: unknown[]) => loadQualityHistory(...args),
}));

beforeEach(() => {
  loadQualityHistory.mockReset();
  _resetSparklineCacheForTests();
});

function snap(
  partial: Partial<{
    health_score: number;
    timestamp: string;
    source: string;
  }> = {},
) {
  return {
    ontology_id: "onto_1",
    timestamp: partial.timestamp ?? "2026-05-01T00:00:00+00:00",
    health_score: partial.health_score ?? 70,
    source: partial.source,
  };
}

describe("QualitySparkline", () => {
  it("renders a loading skeleton, then the polyline + arrow when data arrives", async () => {
    loadQualityHistory.mockResolvedValue({
      ontology_id: "onto_1",
      count: 3,
      snapshots: [
        snap({ health_score: 60 }),
        snap({ health_score: 70 }),
        snap({ health_score: 80 }),
      ],
    });

    const { container } = render(<QualitySparkline ontologyId="onto_1" />);

    expect(container.querySelector('[aria-label="Loading trend"]')).toBeInTheDocument();

    const sparkline = await screen.findByTestId("quality-sparkline");
    expect(sparkline).toBeInTheDocument();
    expect(sparkline.getAttribute("title")).toMatch(/health score: 60 → 80/);

    const polyline = sparkline.querySelector("polyline");
    expect(polyline).not.toBeNull();
    const points = polyline!.getAttribute("points")!.split(" ");
    expect(points).toHaveLength(3);

    // Up trend ⇒ ↑ arrow with emerald color class.
    const arrow = sparkline.querySelector("span.text-emerald-600");
    expect(arrow?.textContent).toBe("↑");
  });

  it("renders a downward arrow in rose when the trend declines", async () => {
    loadQualityHistory.mockResolvedValue({
      ontology_id: "onto_dn",
      count: 3,
      snapshots: [
        snap({ health_score: 90 }),
        snap({ health_score: 75 }),
        snap({ health_score: 50 }),
      ],
    });

    render(<QualitySparkline ontologyId="onto_dn" />);
    const sparkline = await screen.findByTestId("quality-sparkline");
    const arrow = sparkline.querySelector("span.text-rose-600");
    expect(arrow?.textContent).toBe("↓");
  });

  it("renders a flat dot when only a single snapshot exists", async () => {
    loadQualityHistory.mockResolvedValue({
      ontology_id: "onto_one",
      count: 1,
      snapshots: [snap({ health_score: 65 })],
    });

    const { container } = render(<QualitySparkline ontologyId="onto_one" />);
    await waitFor(() =>
      expect(container.querySelector("circle")).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("quality-sparkline")).toBeNull();
    expect(
      container.querySelector('[aria-label="Trend: single snapshot at 65"]'),
    ).toBeInTheDocument();
  });

  it("renders an em dash when no usable data exists", async () => {
    loadQualityHistory.mockResolvedValue({
      ontology_id: "onto_empty",
      count: 0,
      snapshots: [],
    });

    render(<QualitySparkline ontologyId="onto_empty" />);
    await waitFor(() =>
      expect(screen.getByLabelText(/No trend data/)).toBeInTheDocument(),
    );
  });

  it("renders an em dash on fetch error (never throws)", async () => {
    loadQualityHistory.mockRejectedValue(new Error("network down"));

    render(<QualitySparkline ontologyId="onto_err" />);
    await waitFor(() =>
      expect(screen.getByLabelText(/Trend unavailable/)).toBeInTheDocument(),
    );
  });

  it("marks extraction_completion + promotion datapoints with accent dots", async () => {
    loadQualityHistory.mockResolvedValue({
      ontology_id: "onto_ev",
      count: 3,
      snapshots: [
        snap({ health_score: 60, source: "quality_api" }),
        snap({ health_score: 70, source: "extraction_completion" }),
        snap({ health_score: 80, source: "promotion" }),
      ],
    });

    const sparkline = await (async () => {
      render(<QualitySparkline ontologyId="onto_ev" />);
      return screen.findByTestId("quality-sparkline");
    })();

    const dots = Array.from(sparkline.querySelectorAll("circle"));
    expect(dots.length).toBe(2);
    const sources = dots.map((c) => c.getAttribute("data-source"));
    expect(sources).toContain("extraction_completion");
    expect(sources).toContain("promotion");
  });

  it("caches results so two mounts with the same ontology id only fetch once", async () => {
    loadQualityHistory.mockResolvedValue({
      ontology_id: "onto_cached",
      count: 2,
      snapshots: [snap({ health_score: 55 }), snap({ health_score: 65 })],
    });

    const { unmount } = render(<QualitySparkline ontologyId="onto_cached" />);
    await screen.findByTestId("quality-sparkline");
    unmount();

    render(<QualitySparkline ontologyId="onto_cached" />);
    await screen.findByTestId("quality-sparkline");

    expect(loadQualityHistory).toHaveBeenCalledTimes(1);
  });

  it("scales acceptance_rate from ratio to percent before rendering", async () => {
    loadQualityHistory.mockResolvedValue({
      ontology_id: "onto_ar",
      count: 2,
      snapshots: [
        { ontology_id: "onto_ar", timestamp: "t1", acceptance_rate: 0.4 },
        { ontology_id: "onto_ar", timestamp: "t2", acceptance_rate: 0.9 },
      ],
    });

    const { container } = render(
      <QualitySparkline ontologyId="onto_ar" metric="acceptance_rate" />,
    );
    await waitFor(() =>
      expect(container.querySelector("polyline")).toBeInTheDocument(),
    );
    // Title encodes the rendered values; 0.4 → 40 and 0.9 → 90.
    const sparkline = screen.getByTestId("quality-sparkline");
    expect(sparkline.getAttribute("title")).toMatch(/acceptance rate: 40 → 90/);
  });
});
