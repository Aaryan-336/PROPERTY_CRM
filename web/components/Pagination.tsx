"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";

/**
 * Pages are capped server-side at 50 rows as a security control, so this is
 * never a "load everything" button — deliberately.
 */
export function Pagination({
  total,
  limit,
  offset,
}: {
  total: number;
  limit: number;
  offset: number;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();

  if (total <= limit) return null;

  const page = Math.floor(offset / limit) + 1;
  const pages = Math.ceil(total / limit);

  function go(nextOffset: number) {
    const next = new URLSearchParams(params.toString());
    if (nextOffset <= 0) next.delete("offset");
    else next.set("offset", String(nextOffset));
    router.replace(`${pathname}?${next.toString()}`, { scroll: true });
  }

  return (
    <nav
      aria-label="Pagination"
      className="mt-4 flex items-center justify-between gap-3"
    >
      <button
        onClick={() => go(offset - limit)}
        disabled={offset === 0}
        className="tap rounded-pill border border-hairline bg-card px-5 text-sm font-semibold text-ink disabled:opacity-40"
      >
        Previous
      </button>
      <span className="tabular text-xs text-slate">
        Page {page} of {pages}
      </span>
      <button
        onClick={() => go(offset + limit)}
        disabled={offset + limit >= total}
        className="tap rounded-pill border border-hairline bg-card px-5 text-sm font-semibold text-ink disabled:opacity-40"
      >
        Next
      </button>
    </nav>
  );
}
