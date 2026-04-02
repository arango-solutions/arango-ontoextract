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

class ApiClient {
  private readonly baseUrl: string;

  constructor(baseUrl?: string) {
    this.baseUrl = resolveApiBaseUrl(
      baseUrl ?? process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
    );
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
    body?: unknown
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const init: RequestInit = {
      method,
      headers: this.getHeaders(),
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

  async get<T>(path: string): Promise<T> {
    return this.request<T>("GET", path);
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>("POST", path, body);
  }

  async put<T>(path: string, body?: unknown): Promise<T> {
    return this.request<T>("PUT", path, body);
  }

  async del(path: string): Promise<void> {
    await this.request<void>("DELETE", path);
  }
}

export const api = new ApiClient();

/** Resolve the backend API base URL (no trailing slash). */
export function getApiBaseUrl(): string {
  return resolveApiBaseUrl(
    process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000",
  );
}
