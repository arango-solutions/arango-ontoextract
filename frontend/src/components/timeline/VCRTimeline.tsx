"use client";

import { useEffect, useState, useCallback, useRef, useMemo } from "react";
import { api, ApiError } from "@/lib/api-client";
import type { TimelineEvent } from "@/types/timeline";

interface VCRTimelineProps {
  ontologyId: string;
  onTimestampChange?: (timestamp: number) => void;
  onVisibleEntitiesChange?: (entityKeys: Set<string>) => void;
  /** Extra events (e.g. pipeline step boundaries) merged into the timeline. */
  injectedEvents?: TimelineEvent[];
}

const PLAYBACK_SPEEDS = [0.5, 1, 2, 4];

function formatTimestamp(ts: string | number): string {
  const ms = typeof ts === "number" ? ts * 1000 : new Date(ts).getTime();
  const d = new Date(ms);
  if (isNaN(d.getTime())) return String(ts);
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function VCRTimeline({
  ontologyId,
  onTimestampChange,
  onVisibleEntitiesChange,
  injectedEvents,
}: VCRTimelineProps) {
  const [fetchedEvents, setFetchedEvents] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [currentIndex, setCurrentIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speedIdx, setSpeedIdx] = useState(1);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const speed = PLAYBACK_SPEEDS[speedIdx];

  const sortByTimestamp = useCallback((list: TimelineEvent[]): TimelineEvent[] => {
    return [...list].sort((a, b) => {
      const ta = typeof a.timestamp === "number" ? a.timestamp : new Date(a.timestamp).getTime() / 1000;
      const tb = typeof b.timestamp === "number" ? b.timestamp : new Date(b.timestamp).getTime() / 1000;
      return ta - tb;
    });
  }, []);

  const events = useMemo(() => {
    if (!injectedEvents || injectedEvents.length === 0) return fetchedEvents;
    return sortByTimestamp([...fetchedEvents, ...injectedEvents]);
  }, [fetchedEvents, injectedEvents, sortByTimestamp]);

  const fetchTimeline = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<TimelineEvent[] | { data: TimelineEvent[] }>(
        `/api/v1/ontology/${ontologyId}/timeline`,
      );
      const raw: TimelineEvent[] = Array.isArray(res) ? res : (res.data ?? []);
      setFetchedEvents(sortByTimestamp(raw));
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.body.message
          : "Failed to load timeline",
      );
    } finally {
      setLoading(false);
    }
  }, [ontologyId, sortByTimestamp]);

  useEffect(() => {
    fetchTimeline();
  }, [fetchTimeline]);

  const prevEventsLenRef = useRef(0);
  useEffect(() => {
    if (events.length > 0 && prevEventsLenRef.current === 0) {
      setCurrentIndex(events.length - 1);
    }
    if (currentIndex >= events.length && events.length > 0) {
      setCurrentIndex(events.length - 1);
    }
    prevEventsLenRef.current = events.length;
  }, [events.length, currentIndex]);

  useEffect(() => {
    if (events.length > 0 && events[currentIndex]) {
      onTimestampChange?.(events[currentIndex].timestamp);
      if (onVisibleEntitiesChange) {
        const visible = new Set<string>();
        for (let i = 0; i <= currentIndex; i++) {
          if (events[i]?.entity_key) {
            visible.add(events[i].entity_key);
          }
        }
        onVisibleEntitiesChange(visible);
      }
    }
  }, [currentIndex, events, onTimestampChange, onVisibleEntitiesChange]);

  // Playback logic
  useEffect(() => {
    if (playing && events.length > 0) {
      intervalRef.current = setInterval(
        () => {
          setCurrentIndex((prev) => {
            if (prev >= events.length - 1) {
              setPlaying(false);
              return prev;
            }
            return prev + 1;
          });
        },
        1000 / speed,
      );
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [playing, speed, events.length]);

  const handleSliderChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const idx = parseInt(e.target.value, 10);
      setCurrentIndex(idx);
      setPlaying(false);
    },
    [],
  );

  const handleRewind = useCallback(() => {
    setCurrentIndex((prev) => Math.max(0, prev - 1));
    setPlaying(false);
  }, []);

  const handleFastForward = useCallback(() => {
    setCurrentIndex((prev) => Math.min(events.length - 1, prev + 1));
    setPlaying(false);
  }, [events.length]);

  const handlePlayPause = useCallback(() => {
    if (currentIndex >= events.length - 1) {
      setCurrentIndex(0);
      setPlaying(true);
    } else {
      setPlaying((prev) => !prev);
    }
  }, [currentIndex, events.length]);

  const cycleSpeed = useCallback(() => {
    setSpeedIdx((prev) => (prev + 1) % PLAYBACK_SPEEDS.length);
  }, []);

  if (loading) {
    return (
      <div className="text-center text-sm text-gray-400 py-3 animate-pulse" data-testid="timeline-loading">
        Loading timeline...
      </div>
    );
  }

  if (error) {
    return (
      <div className="text-center text-sm text-red-500 py-3" data-testid="timeline-error">
        {error}
      </div>
    );
  }

  if (events.length === 0) {
    return (
      <div className="text-center text-sm text-gray-400 py-3" data-testid="timeline-empty">
        No timeline events found.
      </div>
    );
  }

  const currentEvent = events[currentIndex];
  const minTs = events[0].timestamp;
  const maxTs = events[events.length - 1].timestamp;

  return (
    <div className="space-y-3" data-testid="vcr-timeline">
      {/* Controls row */}
      <div className="flex items-center gap-3">
        {/* VCR Buttons */}
        <div className="flex items-center gap-1">
          <button
            onClick={handleRewind}
            disabled={currentIndex === 0}
            className="p-1.5 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed text-gray-600"
            title="Previous event"
            data-testid="timeline-rewind"
          >
            <span className="text-sm">&#9664;&#9664;</span>
          </button>
          <button
            onClick={handlePlayPause}
            className="p-1.5 px-2.5 rounded-lg bg-blue-600 text-white hover:bg-blue-700 text-sm"
            data-testid="timeline-play-pause"
          >
            {playing ? "\u23F8" : "\u25B6"}
          </button>
          <button
            onClick={handleFastForward}
            disabled={currentIndex >= events.length - 1}
            className="p-1.5 rounded hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed text-gray-600"
            title="Next event"
            data-testid="timeline-ff"
          >
            <span className="text-sm">&#9654;&#9654;</span>
          </button>
        </div>

        {/* Slider */}
        <div className="flex-1 relative">
          <input
            type="range"
            min={0}
            max={events.length - 1}
            value={currentIndex}
            onChange={handleSliderChange}
            className="w-full h-2 bg-gray-200 rounded-full appearance-none cursor-pointer accent-blue-600"
            data-testid="timeline-slider"
          />
          {/* Tick marks */}
          <div className="absolute top-3 left-0 right-0 flex justify-between pointer-events-none">
            {events.length <= 50 &&
              events.map((_, i) => (
                <span
                  key={i}
                  className={`inline-block w-0.5 h-1.5 rounded-full ${i === currentIndex ? "bg-blue-600" : "bg-gray-300"}`}
                />
              ))}
          </div>
        </div>

        {/* Timestamp */}
        <div className="text-xs text-gray-600 font-mono whitespace-nowrap min-w-[180px] text-right" data-testid="timeline-timestamp">
          {formatTimestamp(currentEvent.timestamp)}
        </div>

        {/* Speed */}
        <button
          onClick={cycleSpeed}
          className="text-xs px-2 py-1 border border-gray-200 rounded text-gray-500 hover:bg-gray-50"
          title="Playback speed"
          data-testid="timeline-speed"
        >
          {speed}x
        </button>
      </div>

      {/* Current event info */}
      <div className="flex items-center gap-2 text-xs text-gray-500">
        <span className="inline-block h-1.5 w-1.5 rounded-full bg-blue-500" />
        <span className="font-medium text-gray-700">
          {currentEvent.entity_label}
        </span>
        <span className="text-gray-400">&mdash;</span>
        <span>{currentEvent.event_type.replace(/_/g, " ")}</span>
        <span className="text-gray-400">in {currentEvent.collection}</span>
        <span className="ml-auto text-gray-400">
          {currentIndex + 1} / {events.length}
        </span>
      </div>
    </div>
  );
}
