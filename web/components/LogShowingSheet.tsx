"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ChipGroup, Sheet } from "@/components/Sheet";
import { clockTime, money } from "@/lib/format";
import { INTEREST_LEVELS, type Paged, type Property } from "@/lib/types";

type Level = (typeof INTEREST_LEVELS)[number]["value"];

/**
 * Log that a property was shown to a client.
 *
 * This is the record the owner's "who showed what to whom" view is built from,
 * so it is one screen and one action: pick the property, pick what happened.
 * Who showed it is taken from the session, never asked for and never editable.
 */
export function LogShowingSheet({
  contactId,
  contactName,
  open,
  onClose,
  presetPropertyId,
  presetPropertyLabel,
}: {
  contactId: number;
  contactName: string;
  open: boolean;
  onClose: () => void;
  presetPropertyId?: number;
  presetPropertyLabel?: string;
}) {
  const router = useRouter();
  const [level, setLevel] = useState<Level>("site_visit_done");
  const [propertyId, setPropertyId] = useState<number | null>(
    presetPropertyId ?? null,
  );
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<Property[]>([]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  useEffect(() => {
    if (!open || presetPropertyId) return;
    const timer = setTimeout(async () => {
      const res = await fetch(
        `/api/crm/properties?limit=8${query ? `&q=${encodeURIComponent(query)}` : ""}`,
      ).catch(() => null);
      if (!res?.ok) return;
      const data = (await res.json()) as Paged<Property>;
      setResults(data.items);
    }, 220);
    return () => clearTimeout(timer);
  }, [query, open, presetPropertyId]);

  async function submit() {
    if (!propertyId) {
      setError("Pick the property you showed.");
      return;
    }
    setBusy(true);
    setError(null);

    const res = await fetch("/api/crm/property-interests", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        contact_id: contactId,
        property_id: propertyId,
        interest_level: level,
        note: note.trim() || null,
      }),
    }).catch(() => null);

    if (!res || !res.ok) {
      const body = await res?.json().catch(() => null);
      setError(body?.error?.message ?? "Could not save. Check your connection.");
      setBusy(false);
      return;
    }

    const data = await res.json();
    setSaved(`Logged at ${clockTime(data.shown_at)} under your name`);
    setBusy(false);
    router.refresh();
    setTimeout(() => {
      setSaved(null);
      onClose();
    }, 1400);
  }

  const selected = results.find((p) => p.id === propertyId);

  return (
    <Sheet
      open={open}
      onClose={onClose}
      title="Log site visit"
      subtitle={contactName}
    >
      {saved ? (
        <div className="flex flex-col items-center gap-2 py-8 text-center">
          <span className="flex h-12 w-12 items-center justify-center rounded-full bg-teal text-white">
            <svg viewBox="0 0 24 24" className="h-6 w-6" aria-hidden>
              <path
                d="M20 6 9 17l-5-5"
                fill="none"
                stroke="currentColor"
                strokeWidth="3"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
          <p className="font-display text-lg text-ink">Visit logged</p>
          <p className="text-sm text-slate">{saved}</p>
        </div>
      ) : (
        <div className="space-y-5">
          {presetPropertyId ? (
            <div className="rounded-tile border border-hairline bg-card px-4 py-3">
              <p className="text-xs font-semibold text-slate">Property</p>
              <p className="mt-0.5 text-sm font-semibold text-ink">
                {presetPropertyLabel}
              </p>
            </div>
          ) : (
            <div>
              <label
                htmlFor="property-search"
                className="mb-2 block text-xs font-semibold text-slate"
              >
                Property shown
              </label>
              <input
                id="property-search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search building or location"
                className="tap w-full rounded-tile border border-hairline bg-card px-4 text-[16px] outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft"
              />
              <div className="mt-2 max-h-52 space-y-1.5 overflow-y-auto">
                {results.map((p) => {
                  const active = p.id === propertyId;
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => setPropertyId(p.id)}
                      className={`flex w-full items-center justify-between gap-3 rounded-tile border px-3 py-2.5 text-left transition-colors ${
                        active
                          ? "border-ink bg-ink text-white"
                          : "border-hairline bg-card"
                      }`}
                    >
                      <span className="min-w-0">
                        <span className="block truncate text-sm font-semibold">
                          {p.title ?? p.building ?? "Listing"}
                        </span>
                        <span
                          className={`block truncate text-xs ${active ? "text-ink-dim" : "text-slate"}`}
                        >
                          {p.location}
                        </span>
                      </span>
                      <span className="tabular shrink-0 text-xs">
                        {money(p.price)}
                      </span>
                    </button>
                  );
                })}
                {results.length === 0 && (
                  <p className="px-1 py-2 text-xs text-slate">
                    No matching inventory. Try a building or locality name.
                  </p>
                )}
              </div>
            </div>
          )}

          <ChipGroup
            label="What happened"
            options={INTEREST_LEVELS}
            value={level}
            onChange={(v) => v && setLevel(v)}
          />

          <div>
            <label
              htmlFor="visit-note"
              className="mb-2 block text-xs font-semibold text-slate"
            >
              Note (optional)
            </label>
            <textarea
              id="visit-note"
              rows={2}
              value={note}
              onChange={(e) => setNote(e.target.value)}
              placeholder="Client reaction, objections, next step"
              className="w-full resize-none rounded-tile border border-hairline bg-card px-4 py-3 text-[16px] outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft"
            />
          </div>

          {error && (
            <p role="alert" className="rounded-tile bg-signal-soft px-4 py-3 text-sm text-signal">
              {error}
            </p>
          )}

          <button
            type="button"
            onClick={submit}
            disabled={busy || (!propertyId && !presetPropertyId)}
            className="tap w-full rounded-pill bg-sandstone px-5 text-[15px] font-semibold text-white transition-opacity disabled:opacity-50"
          >
            {busy ? "Saving…" : "Save site visit"}
          </button>

          <p className="text-center text-[11px] leading-relaxed text-slate">
            Recorded as shown by you{selected ? ` · ${selected.location}` : ""}, and
            visible to the owner.
          </p>
        </div>
      )}
    </Sheet>
  );
}
