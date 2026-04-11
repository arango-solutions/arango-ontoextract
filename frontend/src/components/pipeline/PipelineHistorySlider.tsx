"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { api } from "@/lib/api-client";
import type { PaginatedResponse } from "@/lib/api-client";
import type { ExtractionRun } from "@/types/pipeline";

interface PipelineHistorySliderProps {
  onSelectRun: (runId: string) => void;
  selectedRunId?: string | null;
}

const PLAYBACK_SPEEDS = [0.5, 1, 2, 4];

const STATUS_COLORS: Record<string, string> = {
  completed: "#22c55e",
  completed_with_errors: "#f59e0b",
  running: "#3b82f6",
  queued: "#9ca3af",
  failed: "#ef4444",
  paused: "#eab308",
};

function formatRelativeTime(value: string | number | undefined): string {
  if (value == null) return "";
  const now = Date.now();
  const then =
    typeof value === "number" ? value * 1000 : new Date(value).getTime();
  if (Number.isNaN(then)) return "";
  const diffMs = now - then;
  if (diffMs < 0) return "just now";
  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

function formatDuration(ms: number | undefined): string {
  if (ms == null) return "\u2014";
  if (ms < 1000) return `${ms}ms`;
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

export default function PipelineHistorySlider({
  onSelectRun,
  selectedRunId,
}: PipelineHistorySliderProps) {
  const [runs, setRuns] = useState<ExtractionRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [currentIndex, setCurrentIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speedIdx, setSpeedIdx] = useState(1);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const speed = PLAYBACK_SPEEDS[speedIdx];

  const fetchAllRuns = useCallback(async () => {
    setLoading(true);
    try {
      const params = new URLSearchParams({
        sort: "created_at",
        order: "asc",
        limit: "100",
      });
      const res = await api.get<PaginatedResponse<ExtractionRun>>(
        `/api/v1/extraction/runs?${params.toString()}`,
      );
      setRuns(res.data);
      if (res.data.length > 0) {
        setCurrentIndex(res.data.length - 1);
      }
    } catch {
      // keep whatever we have
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchAllRuns();
  }, [fetchAllRuns]);

  useEffect(() => {
    if (selectedRunId && runs.length > 0) {
      const idx = runs.findIndex((r) => r._key === selectedRunId);
      if (idx >= 0 && idx !== currentIndex) {
        setCurrentIndex(idx);
      }
    }
  }, [selectedRunId, runs, currentIndex]);

  useEffect(() => {
    if (playing && runs.length > 0) {
      intervalRef.current = setInterval(() => {
        setCurrentIndex((prev) => {
          if (prev >= runs.length - 1) {
            setPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, 1500 / speed);
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [playing, speed, runs.length]);

  useEffect(() => {
    if (runs.length > 0 && runs[currentIndex]) {
      const run = runs[currentIndex];
      if (run._key !== selectedRunId) {
        onSelectRun(run._key);
      }
    }
  }, [currentIndex, runs, selectedRunId, onSelectRun]);

  const handleSliderChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      setCurrentIndex(parseInt(e.target.value, 10));
      setPlaying(false);
    },
    [],
  );

  const handleRewind = useCallback(() => {
    setCurrentIndex((prev) => Math.max(0, prev - 1));
    setPlaying(false);
  }, []);

  const handleFastForward = useCallback(() => {
    setCurrentIndex((prev) => Math.min(runs.length - 1, prev + 1));
    setPlaying(false);
  }, [runs.length]);

  const handlePlayPause = useCallback(() => {
    if (currentIndex >= runs.length - 1) {
      setCurrentIndex(0);
      setPlaying(true);
    } else {
      setPlaying((prev) => !prev);
    }
  }, [currentIndex, runs.length]);

  const cycleSpeed = useCallback(() => {
    setSpeedIdx((prev) => (prev + 1) % PLAYBACK_SPEEDS.length);
  }, []);

  if (loading) {
    return (
      <div
        className="px-4 py-2 text-xs text-gray-400 animate-pulse"
        data-testid="history-slider-loading"
      >
        Loading run history…
      </div>
    );
  }

  if (runs.length === 0) {
    return (
      <div
        className="px-4 py-2 text-xs text-gray-400"
        data-testid="history-slider-empty"
      >
        No extraction runs to display.
      </div>
    );
  }

  const currentRun = runs[currentIndex];
  const statusColor = STATUS_COLORS[currentRun.status] ?? "#9ca3af";

  return (
    <div
      className="bg-white border-b border-gray-200 px-4 py-3 space-y-2"
      data-testid="pipeline-history-slider"
    >
      {/* Controls row */}
      <div className="flex items-center gap-3">
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">
          Run History
        </span>

        {/* VCR buttons */}
        <div className="flex items-center gap-1">
          <button
            onClick={handleRewind}
            disabled={currentIndex === 0}
            className="p-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed text-gray-600"
            title="Previous run"
            data-testid="history-rewind"
          >
            <span className="text-xs">&#9664;&#9664;</span>
          </button>
          <button
            onClick={handlePlayPause}
            className="p-1 px-2 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 text-xs"
            data-testid="history-play-pause"
          >
            {playing ? "\u23F8" : "\u25B6"}
          </button>
          <button
            onClick={handleFastForward}
            disabled={currentIndex >= runs.length - 1}
            className="p-1 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed text-gray-600"
            title="Next run"
            data-testid="history-ff"
          >
            <span className="text-xs">&#9654;&#9654;</span>
          </button>
        </div>

        {/* Slider */}
        <div className="flex-1 relative">
          <input
            type="range"
            min={0}
            max={runs.length - 1}
            value={currentIndex}
            onChange={handleSliderChange}
            className="w-full h-1.5 bg-gray-200 rounded-full appearance-none cursor-pointer accent-indigo-600"
            data-testid="history-slider"
          />
          {/* Status color ticks */}
          {runs.length <= 80 && (
            <div className="absolute top-2.5 left-0 right-0 flex justify-between pointer-events-none px-[2px]">
              {runs.map((run, i) => (
                <span
                  key={run._key}
                  className="inline-block w-1 h-1.5 rounded-full"
                  style={{
                    backgroundColor:
                      i === currentIndex
                        ? statusColor
                        : STATUS_COLORS[run.status] ?? "#d1d5db",
                    opacity: i === currentIndex ? 1 : 0.5,
                  }}
                />
              ))}
            </div>
          )}
        </div>

        {/* Position counter */}
        <span
          className="text-xs text-gray-400 tabular-nums whitespace-nowrap"
          data-testid="history-counter"
        >
          {currentIndex + 1} / {runs.length}
        </span>

        {/* Speed */}
        <button
          onClick={cycleSpeed}
          className="text-xs px-1.5 py-0.5 border border-gray-200 rounded text-gray-500 hover:bg-gray-50"
          title="Playback speed"
          data-testid="history-speed"
        >
          {speed}x
        </button>
      </div>

      {/* Current run summary strip */}
      <div className="flex items-center gap-3 text-xs text-gray-600">
        <span
          className="inline-block h-2 w-2 rounded-full flex-shrink-0"
          style={{ backgroundColor: statusColor }}
        />
        <span className="font-medium text-gray-800 truncate max-w-[200px]">
          {currentRun.document_name || currentRun._key}
        </span>
        <span className="capitalize text-gray-500">{currentRun.status.replace(/_/g, " ")}</span>
        {currentRun.classes_extracted != null && currentRun.classes_extracted > 0 && (
          <span>{currentRun.classes_extracted} classes</span>
        )}
        {currentRun.duration_ms != null && currentRun.duration_ms > 0 && (
          <span>{formatDuration(currentRun.duration_ms)}</span>
        )}
        <span className="ml-auto text-gray-400 whitespace-nowrap">
          {formatRelativeTime(currentRun.started_at ?? currentRun.created_at)}
        </span>
      </div>
    </div>
  );
}
