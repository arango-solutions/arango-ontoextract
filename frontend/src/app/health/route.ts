import { NextResponse } from "next/server";
import { getBackendProxyTarget } from "@/lib/backendProxyTarget";

export const dynamic = "force-dynamic";

export async function GET() {
  const base = getBackendProxyTarget();
  try {
    const r = await fetch(`${base}/health`, { cache: "no-store" });
    const body = await r.text();
    return new NextResponse(body, {
      status: r.status,
      headers: {
        "content-type": r.headers.get("content-type") || "application/json",
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    return NextResponse.json(
      {
        status: "proxy_error",
        detail: `Cannot reach API at ${base}.`,
        error: message,
      },
      { status: 502 },
    );
  }
}
