/**
 * Next.js middleware — auth redirect for unauthenticated users.
 *
 * In dev mode (NEXT_PUBLIC_DEV_MODE=true), auth checks are skipped.
 * In production, requests without a valid token cookie/header are
 * redirected to /login.
 */

import { NextRequest, NextResponse } from "next/server";

const BASE_PATH = (process.env.NEXT_PUBLIC_BASE_PATH || "").replace(/\/$/, "");

const PUBLIC_PATHS = new Set([
  "/login",
  "/logout",
  "/health",
  "/ready",
  "/_next",
  "/favicon.ico",
]);

function isPublicPath(pathname: string): boolean {
  if (PUBLIC_PATHS.has(pathname)) return true;
  for (const prefix of PUBLIC_PATHS) {
    if (pathname.startsWith(prefix + "/")) return true;
  }
  if (pathname.startsWith("/api/")) return true;
  return false;
}

export function middleware(request: NextRequest): NextResponse | undefined {
  const { pathname } = request.nextUrl;

  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  const devMode = process.env.NEXT_PUBLIC_DEV_MODE === "true";
  if (devMode) {
    return NextResponse.next();
  }

  const token =
    request.cookies.get("aoe_auth_token")?.value ??
    request.headers.get("authorization")?.replace("Bearer ", "");

  if (!token) {
    const loginUrl = request.nextUrl.clone();
    loginUrl.pathname = BASE_PATH ? `${BASE_PATH}/login` : "/login";
    loginUrl.searchParams.set("redirect", pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
