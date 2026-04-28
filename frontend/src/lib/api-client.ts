/**
 * Typed fetch wrapper for all AOE backend API calls.
 *
 * Handles the standard pagination envelope and error format
 * defined in PRD Section 7.8.
 */

import { getToken } from "@/lib/auth";

// --- Response types -------------------------------------------------------

export interface PaginatedResponse<T> {
  data: T[];
  cursor: string | null;
  has_more: boolean;
  total_count: number;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  details?: Record<string, unknown>;
  request_id?: string;
}

// --- Error class ----------------------------------------------------------

export class ApiError extends Error {
  public readonly status: number;
  public readonly body: ApiErrorBody;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

// --- Client ---------------------------------------------------------------

/**
 * When `NEXT_PUBLIC_API_URL` is unset in the browser, the client uses same-origin
 * `/api/*` paths; `next.config.js` rewrites those to this FastAPI origin.
 * Port 8010 avoids common conflicts with other services on :8000.
 */
export const DEFAULT_BACKEND_ORIGIN = "http://127.0.0.1:8010";

/**
 * Use same-origin `/api/*` (Next.js rewrite → FastAPI) when local dev would
 * otherwise send traffic to port 8000 — commonly occupied by a non-AOE service.
 * Set NEXT_PUBLIC_API_FORCE_URL=1 to disable and honor NEXT_PUBLIC_API_URL exactly.
 */
function shouldUseSameOriginApiProxy(envUrl: string | undefined): boolean {
  if (typeof window === "undefined") return false;
  const h = window.location.hostname;
  if (h !== "localhost" && h !== "127.0.0.1") return false;
  if (process.env.NEXT_PUBLIC_API_FORCE_URL === "1") return false;
  if (envUrl === undefined || envUrl.trim() === "") return true;
  try {
    return new URL(envUrl).port === "8000";
  } catch {
    return false;
  }
}

/** Next.js ``basePath`` (baked at build). Same value as backend ``SERVICE_URL_PATH_PREFIX`` when bundling. */
function nextPublicBasePath(): string {
  return (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/$/, "");
}

/**
 * Resolved API base for HTTP ``fetch`` / relative URLs.
 *
 * - Local dev: same-origin ``/api`` proxy (empty string) when applicable.
 * - Static bundle behind ``SERVICE_URL_PATH_PREFIX``: ``origin + NEXT_PUBLIC_BASE_PATH``.
 * - Otherwise: ``NEXT_PUBLIC_API_URL`` or default dev origin.
 */
function effectiveApiBaseUrl(): string {
  const envUrl = process.env.NEXT_PUBLIC_API_URL;
  const trimmed = typeof envUrl === "string" ? envUrl.trim() : "";

  if (shouldUseSameOriginApiProxy(trimmed || undefined)) {
    return "";
  }

  const basePath = nextPublicBasePath();
  if (!trimmed && basePath && typeof window !== "undefined") {
    return resolveApiBaseUrl(`${window.location.origin}${basePath}`);
  }

  return resolveApiBaseUrl(
    trimmed.length > 0 ? trimmed : DEFAULT_BACKEND_ORIGIN,
  );
}

function resolveApiBaseUrl(baseUrl: string): string {
  if (typeof window === "undefined") {
    return baseUrl;
  }

  try {
    const url = new URL(baseUrl);
    const isLocalFrontendHost =
      window.location.hostname === "localhost" ||
      window.location.hostname === "127.0.0.1";

    if (isLocalFrontendHost && url.hostname === "localhost") {
      url.hostname = "127.0.0.1";
    }

    return url.toString().replace(/\/$/, "");
  } catch {
    return baseUrl;
  }
}

/** Join base URL with an API path, avoiding duplicate `/api/v1` when base already ends with it. */
export function buildApiUrl(baseUrl: string, path: string): string {
  const base = baseUrl.replace(/\/$/, "");
  const p = path.startsWith("/") ? path : `/${path}`;
  const dup = "/api/v1";
  if (base.endsWith(dup) && p.startsWith(`${dup}/`)) {
    return `${base}${p.slice(dup.length)}`;
  }
  return `${base}${p}`;
}

class ApiClient {
  private readonly baseUrl: string;

  constructor(baseUrl?: string) {
    if (baseUrl !== undefined) {
      const t = baseUrl.trim();
      if (shouldUseSameOriginApiProxy(t || undefined)) {
        this.baseUrl = "";
      } else {
        this.baseUrl = resolveApiBaseUrl(t.length > 0 ? t : DEFAULT_BACKEND_ORIGIN);
      }
      return;
    }
    this.baseUrl = effectiveApiBaseUrl();
  }

  private getHeaders(): Record<string, string> {
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
    };
    const token = getToken();
    if (token) {
      headers["Authorization"] = `Bearer ${token}`;
    }
    return headers;
  }

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    signal?: AbortSignal,
  ): Promise<T> {
    const url = buildApiUrl(this.baseUrl, path);
    const init: RequestInit = {
      method,
      headers: this.getHeaders(),
      signal,
    };
    if (body !== undefined) {
      init.body = JSON.stringify(body);
    }

    const res = await fetch(url, init);

    if (!res.ok) {
      let errorBody: ApiErrorBody;
      try {
        const json = await res.json();
        errorBody = json.error ?? {
          code: "UNKNOWN_ERROR",
          message: json.detail ?? res.statusText,
        };
      } catch {
        errorBody = { code: "UNKNOWN_ERROR", message: res.statusText };
      }
      throw new ApiError(res.status, errorBody);
    }

    return res.json() as Promise<T>;
  }

  async get<T>(path: string, opts?: { signal?: AbortSignal }): Promise<T> {
    return this.request<T>("GET", path, undefined, opts?.signal);
  }

  async post<T>(path: string, body?: unknown, opts?: { signal?: AbortSignal }): Promise<T> {
    return this.request<T>("POST", path, body, opts?.signal);
  }

  async put<T>(path: string, body?: unknown, opts?: { signal?: AbortSignal }): Promise<T> {
    return this.request<T>("PUT", path, body, opts?.signal);
  }

  async del(path: string, opts?: { signal?: AbortSignal }): Promise<void> {
    await this.request<void>("DELETE", path, undefined, opts?.signal);
  }
}

export const api = new ApiClient();

/**
 * Base URL prefix for browser `fetch(...)` to the API.
 *
 * Returns `""` when the Next.js same-origin rewrite should be used (the
 * default in local dev) so callers end up with relative `/api/...` paths and
 * avoid cross-origin/CORS entirely. Returns an absolute origin otherwise.
 *
 * For WebSocket URLs (which need an absolute `ws://` / `wss://`), use
 * `getApiOrigin()` instead.
 */
export function getApiBaseUrl(): string {
  return effectiveApiBaseUrl();
}

/**
 * Always-absolute API origin (protocol + host + port, no trailing slash).
 *
 * Use this when you need a real URL — e.g. building a WebSocket URL — rather
 * than a fetch prefix. Browser HTTP callers should prefer `getApiBaseUrl()`
 * so the Next.js rewrite handles CORS.
 */
export function getApiOrigin(): string {
  const direct = effectiveApiBaseUrl();
  if (direct !== "") {
    return direct;
  }
  const envUrl = process.env.NEXT_PUBLIC_API_URL?.trim();
  return resolveApiBaseUrl(
    envUrl && envUrl.length > 0 ? envUrl : DEFAULT_BACKEND_ORIGIN,
  );
}
