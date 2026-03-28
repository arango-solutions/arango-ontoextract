"use client";

import { useEffect, useRef, useCallback, useState } from "react";
import type {
  StepStatus,
  StepStatusValue,
  WebSocketEvent,
  PipelineStep,
} from "@/types/pipeline";
import { PIPELINE_STEPS } from "@/types/pipeline";

interface UseExtractionSocketReturn {
  steps: Map<string, StepStatus>;
  isConnected: boolean;
  error: string | null;
}

function buildInitialSteps(): Map<string, StepStatus> {
  const map = new Map<string, StepStatus>();
  for (const step of PIPELINE_STEPS) {
    map.set(step, { status: "pending" });
  }
  return map;
}

function resolveWsUrl(runId: string): string {
  if (typeof window === "undefined") return "";
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const apiBase =
    process.env.NEXT_PUBLIC_API_URL ?? `${protocol}//${window.location.host}`;
  const wsBase = apiBase.replace(/^http/, "ws");
  return `${wsBase}/ws/extraction/${runId}`;
}

const MIN_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 30_000;

export function useExtractionSocket(
  runId: string | null,
): UseExtractionSocketReturn {
  const [steps, setSteps] = useState<Map<string, StepStatus>>(buildInitialSteps);
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<WebSocket | null>(null);
  const retriesRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const clearTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const applyEvent = useCallback((evt: WebSocketEvent) => {
    setSteps((prev) => {
      const next = new Map(prev);
      const stepName = evt.step as PipelineStep | undefined;
      if (!stepName) return next;

      const current = next.get(stepName) ?? { status: "pending" as StepStatusValue };

      switch (evt.type) {
        case "step_started":
          next.set(stepName, {
            ...current,
            status: "running",
            startedAt: evt.timestamp,
            data: evt.data,
          });
          break;
        case "step_completed":
          next.set(stepName, {
            ...current,
            status: "completed",
            completedAt: evt.timestamp,
            data: evt.data,
          });
          break;
        case "step_failed":
          next.set(stepName, {
            ...current,
            status: "failed",
            completedAt: evt.timestamp,
            error: evt.error,
            data: evt.data,
          });
          break;
        case "pipeline_paused":
          next.set(stepName, {
            ...current,
            status: "paused",
            data: evt.data,
          });
          break;
        case "completed":
          break;
      }

      return next;
    });
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    if (!runId) {
      setSteps(buildInitialSteps());
      setIsConnected(false);
      setError(null);
      return;
    }

    function connect() {
      if (!mountedRef.current || !runId) return;

      const url = resolveWsUrl(runId);
      const ws = new WebSocket(url);
      wsRef.current = ws;

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setIsConnected(true);
        setError(null);
        retriesRef.current = 0;
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
        try {
          const parsed = JSON.parse(event.data) as WebSocketEvent;
          applyEvent(parsed);
        } catch {
          setError("Failed to parse WebSocket message");
        }
      };

      ws.onerror = () => {
        if (!mountedRef.current) return;
        setError("WebSocket connection error");
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setIsConnected(false);
        wsRef.current = null;

        const backoff = Math.min(
          MIN_BACKOFF_MS * Math.pow(2, retriesRef.current),
          MAX_BACKOFF_MS,
        );
        retriesRef.current += 1;
        timerRef.current = setTimeout(connect, backoff);
      };
    }

    setSteps(buildInitialSteps());
    connect();

    return () => {
      clearTimer();
      if (wsRef.current) {
        wsRef.current.onclose = null;
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [runId, applyEvent, clearTimer]);

  return { steps, isConnected, error };
}
