"use client";

import { useEffect } from "react";
import { clearToken } from "@/lib/auth";

export default function LogoutPage() {
  useEffect(() => {
    clearToken();
    window.location.href = "/login";
  }, []);

  return (
    <main className="min-h-screen flex items-center justify-center">
      <p className="text-gray-500">Signing out…</p>
    </main>
  );
}
