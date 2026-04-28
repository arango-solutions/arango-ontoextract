/**
 * Populated from repo-root ``SERVICE_URL_PATH_PREFIX`` via ``frontend/next.config.js``
 * (``env.NEXT_PUBLIC_BASE_PATH``). Must match backend ``Settings.service_url_path_prefix``.
 */

export function getBasePath(): string {
  return (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/$/, "");
}

/**
 * Prefix an app-relative path for ``window.location`` / ``window.open``.
 * Next ``Link`` / ``router.*`` already respect ``basePath`` from ``next.config.js``.
 *
 * Idempotent if ``path`` already starts with the configured base path.
 */
export function withBasePath(path: string): string {
  const base = getBasePath();
  const qIdx = path.indexOf("?");
  const pathOnly = qIdx >= 0 ? path.slice(0, qIdx) : path;
  const query = qIdx >= 0 ? path.slice(qIdx) : "";
  const raw = pathOnly.startsWith("/") ? pathOnly : `/${pathOnly}`;

  if (!base) {
    return raw + query;
  }
  if (raw === base || raw.startsWith(`${base}/`)) {
    return raw + query;
  }
  return `${base}${raw}${query}`;
}

/** After login: query ``redirect`` must stay same-origin path segments only; applies ``withBasePath``. */
export function resolvedPostLoginHref(raw: string): string {
  const target =
    raw.startsWith("/") && !raw.startsWith("//") ? raw : "/";
  return withBasePath(target);
}
