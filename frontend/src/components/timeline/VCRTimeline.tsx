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

  // Latch that the next time ``events`` becomes non-empty, the slider
  // should jump to the rightmost position. Re-armed on initial mount,
  // on every ontology switch, and after every ``fetchTimeline``
  // completion. Consumed (cleared) by the snap effect below once it
  // has actually applied the snap. A flag-based design beats comparing
  // ``events.length`` to a per-mount/per-ontology snapshot, which is
  // racy: on ontology switch the snap effect sees the STALE events
  // closure (still the previous ontology's data) before
  // ``setFetchedEvents([])`` flushes, so any condition keyed on
  // ``events.length`` would fire prematurely against old data and
  // never re-fire when the new fetch resolves.
  const needsSnapToLastRef = useRef(true);

  const fetchTimeline = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await api.get<TimelineEvent[] | { data: TimelineEvent[] }>(
        `/api/v1/ontology/${ontologyId}/timeline`,
      );
      const raw: TimelineEvent[] = Array.isArray(res) ? res : (res.data ?? []);
      setFetchedEvents(sortByTimestamp(raw));
      // Re-arm so the snap effect lands on the latest event for this
      // ontology once the merged ``events`` list (fetched +
      // injected) is recomputed on the next render.
      needsSnapToLastRef.current = true;
      setPlaying(false);
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

  // When the parent switches to a different ontology, drop the previous
  // ontology's events so the loading state appears immediately instead
  // of flashing the stale dataset, reset playback, and re-arm the
  // snap-to-last latch. Without the snap re-arm, switching to a new
  // ontology with MORE events than the previous one would leave the
  // slider mid-history, which combined with
  // ``onVisibleEntitiesChange`` filters the canvas to a partial
  // ontology -- the user's exact complaint.
  useEffect(() => {
    setFetchedEvents([]);
    setCurrentIndex(0);
    setPlaying(false);
    needsSnapToLastRef.current = true;
  }, [ontologyId]);

  // Snap to the latest event when the latch is armed and events are
  // available. Bounds-clamp for the shrink case (an entity was deleted
  // mid-session, or ``injectedEvents`` were removed) -- without this
  // ``currentIndex`` could point past ``events.length - 1`` and
  // crash the safeIndex math below.
  useEffect(() => {
    if (events.length === 0) return;
    if (needsSnapToLastRef.current) {
      setCurrentIndex(events.length - 1);
      needsSnapToLastRef.current = false;
    } else if (currentIndex >= events.length) {
      setCurrentIndex(events.length - 1);
    }
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

  const safeIndex = Math.min(currentIndex, events.length - 1);
  const currentEvent = events[safeIndex];
  if (!currentEvent) return null;

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
            value={safeIndex}
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
                  className={`inline-block w-0.5 h-1.5 rounded-full ${i === safeIndex ? "bg-blue-600" : "bg-gray-300"}`}
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
          {safeIndex + 1} / {events.length}
        </span>
      </div>
    </div>
  );
}
