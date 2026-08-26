"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

/**
 * Re-fetch the inventory list without a full page load.
 *
 * The data itself is never stale on the server — every API call is
 * `cache: "no-store"`. What goes stale is the rendered page the browser is
 * still showing: inventory arrives on its own from the WhatsApp feed, so a
 * screen left open during a busy morning quietly falls behind, and nothing on
 * it suggests that. Navigating away and back does not necessarily help either,
 * because the App Router serves that from its client-side cache.
 *
 * `router.refresh()` re-runs the server component and discards that cache,
 * which is the only thing that reliably shows listings that arrived after the
 * page was drawn.
 */
export function RefreshInventory({ newest }: { newest: string | null }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [refreshedAt, setRefreshedAt] = useState<number | null>(null);

  function refresh() {
    startTransition(() => {
      router.refresh();
      setRefreshedAt(Date.now());
    });
  }

  return (
    <button
      type="button"
      onClick={refresh}
      disabled={pending}
      aria-label="Check for new listings"
      className="tap flex items-center gap-2 rounded-pill border border-hairline bg-card px-4 text-sm font-semibold text-ink disabled:opacity-60"
    >
      <RefreshIcon spinning={pending} />
      <span className="hidden sm:inline">
        {pending ? "Checking…" : refreshedAt ? "Up to date" : "Refresh"}
      </span>
    </button>
  );
}

function RefreshIcon({ spinning }: { spinning: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      className={`h-4 w-4 ${spinning ? "animate-spin" : ""}`}
      aria-hidden="true"
    >
      <path d="M21 12a9 9 0 1 1-2.64-6.36" />
      <path d="M21 3v6h-6" />
    </svg>
  );
}
