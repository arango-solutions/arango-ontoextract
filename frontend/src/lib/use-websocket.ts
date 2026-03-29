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

const BACKEND_TO_FRONTEND_STEP: Record<string, PipelineStep> = {
  strategy_selector: "strategy_selector",
  extractor: "extraction_agent",
  consistency_checker: "consistency_checker",
  er_agent: "entity_resolution_agent",
  filter: "pre_curation_filter",
};

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

async function fetchStepsFromRest(
  runId: string,
): Promise<Map<string, StepStatus> | null> {
  try {
    const baseUrl =
      process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8001";
    const res = await fetch(`${baseUrl}/api/v1/extraction/runs/${runId}`);
    if (!res.ok) return null;
    const run = await res.json();

    const stepLogs: {
      step: string;
      status: string;
      started_at?: number;
      completed_at?: number;
      error?: string | null;
      metadata?: Record<string, unknown>;
      tokens?: Record<string, unknown>;
    }[] = run?.stats?.step_logs ?? [];

    if (stepLogs.length === 0) return null;

    const map = buildInitialSteps();

    for (const log of stepLogs) {
      const frontendStep = BACKEND_TO_FRONTEND_STEP[log.step] ?? log.step;
      if (!map.has(frontendStep)) continue;

      let status: StepStatusValue = "pending";
      if (log.status === "completed") status = "completed";
      else if (log.status === "failed") status = "failed";
      else if (log.status === "running") status = "running";
      else if (log.status === "skipped") status = "completed";

      map.set(frontendStep, {
        status,
        startedAt: log.started_at
          ? new Date(log.started_at * 1000).toISOString()
          : undefined,
        completedAt: log.completed_at
          ? new Date(log.completed_at * 1000).toISOString()
          : undefined,
        error: log.error ?? undefined,
        data: { ...log.metadata, ...log.tokens },
      });
    }

    return map;
  } catch {
    return null;
  }
}

const MAX_WS_RETRIES = 2;

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
  const restFetchedRef = useRef(false);

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

  // REST API fallback: fetch step data when WS isn't available
  useEffect(() => {
    if (!runId) return;
    restFetchedRef.current = false;

    const timer = setTimeout(async () => {
      if (!mountedRef.current || restFetchedRef.current) return;
      const restSteps = await fetchStepsFromRest(runId);
      if (restSteps && mountedRef.current && !restFetchedRef.current) {
        restFetchedRef.current = true;
        setSteps(restSteps);
      }
    }, 500);

    return () => clearTimeout(timer);
  }, [runId]);

  useEffect(() => {
    if (!runId) {
      setSteps(buildInitialSteps());
      setIsConnected(false);
      setError(null);
      return;
    }

    function connect() {
      if (!mountedRef.current || !runId) return;

      if (retriesRef.current >= MAX_WS_RETRIES) {
        setError(null);
        return;
      }

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
          // ignore parse errors
        }
      };

      ws.onerror = () => {
        // silently handled by onclose
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setIsConnected(false);
        wsRef.current = null;

        retriesRef.current += 1;
        if (retriesRef.current < MAX_WS_RETRIES) {
          timerRef.current = setTimeout(connect, 2000);
        }
      };
    }

    setSteps(buildInitialSteps());
    retriesRef.current = 0;
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
