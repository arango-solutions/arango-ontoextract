import type { RunStatus } from "@/types/pipeline";

interface StatusBadgeProps {
  status: RunStatus;
  size?: "sm" | "md";
}

const STATUS_CONFIG: Record<
  RunStatus,
  { label: string; bg: string; text: string; dot: string; pulse?: boolean }
> = {
  queued: {
    label: "Queued",
    bg: "bg-gray-100",
    text: "text-gray-700",
    dot: "bg-gray-400",
  },
  running: {
    label: "Running",
    bg: "bg-blue-50",
    text: "text-blue-700",
    dot: "bg-blue-500",
    pulse: true,
  },
  completed: {
    label: "Completed",
    bg: "bg-green-50",
    text: "text-green-700",
    dot: "bg-green-500",
  },
  failed: {
    label: "Failed",
    bg: "bg-red-50",
    text: "text-red-700",
    dot: "bg-red-500",
  },
  paused: {
    label: "Paused",
    bg: "bg-yellow-50",
    text: "text-yellow-700",
    dot: "bg-yellow-500",
  },
};

export default function StatusBadge({ status, size = "md" }: StatusBadgeProps) {
  const config = STATUS_CONFIG[status];
  const sizeClasses =
    size === "sm" ? "text-xs px-1.5 py-0.5 gap-1" : "text-sm px-2 py-1 gap-1.5";
  const dotSize = size === "sm" ? "h-1.5 w-1.5" : "h-2 w-2";

  return (
    <span
      className={`inline-flex items-center rounded-full font-medium ${config.bg} ${config.text} ${sizeClasses}`}
      data-testid={`status-badge-${status}`}
    >
      <span
        className={`inline-block rounded-full ${config.dot} ${dotSize} ${config.pulse ? "animate-pulse" : ""}`}
      />
      {config.label}
    </span>
  );
}
