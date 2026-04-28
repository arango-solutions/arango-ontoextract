"use client";

import { useEffect } from "react";
import { clearToken } from "@/lib/auth";
import { withBasePath } from "@/lib/base-path";

export default function LogoutPage() {
  useEffect(() => {
    clearToken();
    window.location.href = withBasePath("/login");
  }, []);

  return (
    <main className="min-h-screen flex items-center justify-center">
      <p className="text-gray-500">Signing out…</p>
    </main>
  );
}
