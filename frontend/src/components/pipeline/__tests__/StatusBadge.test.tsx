import { render, screen } from "@testing-library/react";
import StatusBadge from "@/components/ui/StatusBadge";
import type { RunStatus } from "@/types/pipeline";

describe("StatusBadge", () => {
  const statuses: RunStatus[] = [
    "queued",
    "running",
    "completed",
    "failed",
    "paused",
  ];

  it.each(statuses)("renders badge for status '%s'", (status) => {
    render(<StatusBadge status={status} />);
    const badge = screen.getByTestId(`status-badge-${status}`);
    expect(badge).toBeInTheDocument();
  });

  it("displays the correct label for each status", () => {
    const expectedLabels: Record<RunStatus, string> = {
      queued: "Queued",
      running: "Running",
      completed: "Completed",
      failed: "Failed",
      paused: "Paused",
    };

    for (const status of statuses) {
      const { unmount } = render(<StatusBadge status={status} />);
      expect(screen.getByText(expectedLabels[status])).toBeInTheDocument();
      unmount();
    }
  });

  it("applies sm size classes when size='sm'", () => {
    render(<StatusBadge status="completed" size="sm" />);
    const badge = screen.getByTestId("status-badge-completed");
    expect(badge.className).toContain("text-xs");
  });

  it("applies md size classes by default", () => {
    render(<StatusBadge status="completed" />);
    const badge = screen.getByTestId("status-badge-completed");
    expect(badge.className).toContain("text-sm");
  });

  it("applies green styling for completed", () => {
    render(<StatusBadge status="completed" />);
    const badge = screen.getByTestId("status-badge-completed");
    expect(badge.className).toContain("bg-green-50");
    expect(badge.className).toContain("text-green-700");
  });

  it("applies red styling for failed", () => {
    render(<StatusBadge status="failed" />);
    const badge = screen.getByTestId("status-badge-failed");
    expect(badge.className).toContain("bg-red-50");
    expect(badge.className).toContain("text-red-700");
  });

  it("applies animate-pulse for running status", () => {
    render(<StatusBadge status="running" />);
    const badge = screen.getByTestId("status-badge-running");
    const dot = badge.querySelector("span:first-child");
    expect(dot?.className).toContain("animate-pulse");
  });

  it("does not apply animate-pulse for non-running statuses", () => {
    render(<StatusBadge status="completed" />);
    const badge = screen.getByTestId("status-badge-completed");
    const dot = badge.querySelector("span:first-child");
    expect(dot?.className).not.toContain("animate-pulse");
  });
});
