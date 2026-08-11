"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

import { SearchIcon } from "@/components/icons";

export type FilterSelect = {
  name: string;
  label: string;
  options: readonly { value: string; label: string }[];
};

/**
 * Every list is filterable from a visible control, never from a settings menu.
 * Filters live in the URL so a view can be shared, bookmarked and reloaded.
 */
export function FilterBar({
  searchPlaceholder = "Search",
  selects = [],
  showSearch = true,
}: {
  searchPlaceholder?: string;
  selects?: FilterSelect[];
  showSearch?: boolean;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const [, startTransition] = useTransition();
  const [query, setQuery] = useState(params.get("q") ?? "");

  useEffect(() => {
    setQuery(params.get("q") ?? "");
  }, [params]);

  function apply(next: URLSearchParams) {
    next.delete("offset");
    startTransition(() => {
      router.replace(`${pathname}?${next.toString()}`, { scroll: false });
    });
  }

  useEffect(() => {
    const current = params.get("q") ?? "";
    if (query === current) return;
    const timer = setTimeout(() => {
      const next = new URLSearchParams(params.toString());
      if (query) next.set("q", query);
      else next.delete("q");
      apply(next);
    }, 300);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query]);

  function setParam(name: string, value: string) {
    const next = new URLSearchParams(params.toString());
    if (value) next.set(name, value);
    else next.delete(name);
    apply(next);
  }

  const activeCount = selects.filter((s) => params.get(s.name)).length;

  return (
    <div className="mb-4 space-y-2.5">
      {showSearch && (
        <div className="relative">
          <SearchIcon className="pointer-events-none absolute left-3.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            className="tap w-full rounded-pill border border-hairline bg-card pl-10 pr-4 text-[16px] outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft"
          />
        </div>
      )}

      {selects.length > 0 && (
        <div className="no-scrollbar flex gap-2 overflow-x-auto pb-0.5">
          {selects.map((select) => {
            const value = params.get(select.name) ?? "";
            return (
              <label key={select.name} className="relative shrink-0">
                <span className="sr-only">{select.label}</span>
                <select
                  value={value}
                  onChange={(e) => setParam(select.name, e.target.value)}
                  className={`tap appearance-none rounded-pill border px-4 pr-9 text-sm font-semibold outline-none ${
                    value
                      ? "border-ink bg-ink text-white"
                      : "border-hairline bg-card text-ink"
                  }`}
                >
                  <option value="">{select.label}</option>
                  {select.options.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </select>
                <svg
                  viewBox="0 0 24 24"
                  className={`pointer-events-none absolute right-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 ${value ? "text-white" : "text-slate"}`}
                  aria-hidden
                >
                  <path
                    d="m6 9 6 6 6-6"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.2"
                    strokeLinecap="round"
                  />
                </svg>
              </label>
            );
          })}

          {(activeCount > 0 || query) && (
            <button
              onClick={() => {
                setQuery("");
                startTransition(() => router.replace(pathname, { scroll: false }));
              }}
              className="tap shrink-0 rounded-pill px-3 text-sm font-semibold text-sandstone-deep"
            >
              Clear
            </button>
          )}
        </div>
      )}
    </div>
  );
}
