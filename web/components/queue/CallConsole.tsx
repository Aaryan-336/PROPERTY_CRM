"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ChevronRight, PhoneIcon } from "@/components/icons";
import { InkCard, StatusPill } from "@/components/ui";
import { clockTime, relativeTime } from "@/lib/format";
import { CALL_OUTCOMES, TEMPERATURES, type QueueItem } from "@/lib/types";

type Outcome = (typeof CALL_OUTCOMES)[number]["value"];
type Temperature = (typeof TEMPERATURES)[number]["value"];

/**
 * The cold caller's working screen: one lead at a time, log, advance.
 *
 * The queue page is for browsing; this is for volume. The difference that
 * matters is that it never navigates — logging a call advances to the next
 * lead in place, so a caller working eighty leads does it without a single
 * page load or a trip back to a list to find their place.
 *
 * DESIGN_RULES.md asks for the calmest screen in the app here, so there is one
 * card, one primary action, and no competing panels. It also asks for the
 * primary action in the bottom third on mobile — the dial button and the
 * outcome chips both sit below the lead detail for that reason.
 */
export function CallConsole({
  queue: initial,
  total,
}: {
  queue: QueueItem[];
  total: number;
}) {
  const router = useRouter();
  const [queue, setQueue] = useState<QueueItem[]>(initial);
  const [index, setIndex] = useState(0);
  const [loadingMore, setLoadingMore] = useState(false);
  const [outcome, setOutcome] = useState<Outcome>("connected");
  const [temperature, setTemperature] = useState<Temperature | null>(null);
  const [notes, setNotes] = useState("");
  const [flagged, setFlagged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [logged, setLogged] = useState<{ at: string; name: string } | null>(null);
  // Counted locally so the caller sees their own progress build through a
  // session without waiting on a refetch after every single call.
  const [doneThisSession, setDoneThisSession] = useState(0);

  const item = queue[index];
  // Against the real queue size, not the page in hand — a caller handed 281
  // imported leads needs to see 281, not 50.
  const remaining = total - index;

  /**
   * Pull the next page in before the caller reaches the end of this one.
   *
   * The per-request cap is an anti-scraping control and stays; this just means
   * a long queue can actually be worked through, without the caller hitting an
   * invisible wall at 50 and assuming the rest were never assigned.
   */
  async function loadMore() {
    if (loadingMore || queue.length >= total) return;
    setLoadingMore(true);
    const res = await fetch(`/api/crm/call-queue?limit=50&offset=${queue.length}`)
      .catch(() => null);
    if (res?.ok) {
      const page = (await res.json()) as { items: QueueItem[] };
      // De-dupe by id: logging a call reorders the server-side queue, so a
      // later page can repeat someone already in hand.
      setQueue((current) => {
        const seen = new Set(current.map((q) => q.contact.id));
        return [...current, ...page.items.filter((q) => !seen.has(q.contact.id))];
      });
    }
    setLoadingMore(false);
  }

  useEffect(() => {
    // Five from the end is enough warning at calling pace.
    if (queue.length - index <= 5) void loadMore();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [index, queue.length]);

  function resetForm() {
    setOutcome("connected");
    setTemperature(null);
    setNotes("");
    setFlagged(false);
    setError(null);
  }

  function advance() {
    resetForm();
    setIndex((i) => i + 1);
  }

  async function save() {
    if (!item) return;
    setBusy(true);
    setError(null);

    const res = await fetch("/api/crm/calls", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        contact_id: item.contact.id,
        outcome,
        temperature,
        notes: notes.trim() || null,
        flagged_for_owner: flagged,
      }),
    }).catch(() => null);

    if (!res || !res.ok) {
      const body = await res?.json().catch(() => null);
      setError(
        body?.error?.message ??
          "Could not save — you may be offline. This call has not been logged.",
      );
      setBusy(false);
      return;
    }

    const data = await res.json();
    setLogged({
      at: clockTime(data.call.created_at),
      name: `${item.contact.first_name} ${item.contact.last_name ?? ""}`.trim(),
    });
    setDoneThisSession((n) => n + 1);
    setBusy(false);

    // Advance immediately; the confirmation rides along on the next card so
    // the caller is never left waiting on a toast before they can dial again.
    advance();
    setTimeout(() => setLogged(null), 3500);
  }

  if (!item) {
    return (
      <div className="mx-auto max-w-lg space-y-5">
        <InkCard className="p-6 text-center">
          <p className="text-[11px] uppercase tracking-[0.18em] text-ink-muted">
            Queue
          </p>
          <h1 className="font-display mt-2 text-2xl text-white">
            {doneThisSession > 0 ? "Queue cleared" : "Nothing to call"}
          </h1>
          <p className="mt-2 text-sm text-ink-dim">
            {doneThisSession > 0
              ? `You logged ${doneThisSession} call${doneThisSession === 1 ? "" : "s"} this session.`
              : "Leads assigned to you will appear here in priority order."}
          </p>
        </InkCard>
        <div className="flex gap-3">
          <Link
            href="/"
            className="tap flex flex-1 items-center justify-center rounded-pill bg-ink text-sm font-semibold text-white"
          >
            Back to home
          </Link>
          <button
            type="button"
            onClick={() => router.refresh()}
            className="tap flex flex-1 items-center justify-center rounded-pill border border-hairline bg-card text-sm font-semibold text-ink"
          >
            Refresh queue
          </button>
        </div>
      </div>
    );
  }

  const contact = item.contact;
  const name = `${contact.first_name} ${contact.last_name ?? ""}`.trim();
  const phone = contact.phone?.replace(/[^\d+]/g, "");

  return (
    <div className="mx-auto max-w-lg space-y-4 pb-4">
      {/* Progress strip. Deliberately the only "dashboard" on this screen. */}
      <div className="flex items-center justify-between">
        <div>
          <p className="tabular text-xs text-slate">
            {remaining} left · {doneThisSession} logged
          </p>
          <div className="mt-1.5 h-1 w-32 overflow-hidden rounded-pill bg-hairline">
            <div
              className="h-full rounded-pill bg-sandstone transition-all"
              style={{
                width: `${total ? (index / total) * 100 : 0}%`,
              }}
            />
          </div>
        </div>
        <Link href="/queue" className="text-xs font-semibold text-sandstone-deep">
          Full queue
        </Link>
      </div>

      {logged && (
        <p className="rounded-tile bg-teal-soft px-4 py-2.5 text-xs text-teal">
          {logged.name} logged at {logged.at}
        </p>
      )}

      <InkCard className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] uppercase tracking-[0.18em] text-ink-muted">
              {item.reason}
            </p>
            <h1 className="font-display mt-1 truncate text-2xl leading-tight text-white">
              {name}
            </h1>
          </div>
          {/* Only when it is a broken promise — otherwise the eyebrow above
              already says why this lead surfaced, and repeating it is noise. */}
          {item.priority === 1 && <StatusPill label="Overdue" tone="signal" />}
        </div>

        {/* Name and number only. Budget, areas and stage are not needed to
            place a call, and the queue endpoint does not return them. */}
        <p className="tabular mt-3 text-lg text-white">
          {contact.phone ?? "No number on this lead"}
        </p>

        {item.due_at && (
          <p className="tabular mt-2 text-xs text-ink-muted">
            Callback due {relativeTime(item.due_at)}
          </p>
        )}
      </InkCard>

      {/* Primary action, in the bottom third on a phone. */}
      {phone ? (
        <a
          href={`tel:${phone}`}
          className="tap flex items-center justify-center gap-2 rounded-pill bg-teal px-5 text-base font-semibold text-white"
        >
          <PhoneIcon className="h-5 w-5" />
          <span className="tabular">{contact.phone}</span>
        </a>
      ) : (
        <p className="rounded-tile bg-parchment-deep px-4 py-3 text-center text-sm text-slate">
          No phone number on this lead.
        </p>
      )}

      <div className="rounded-card border border-hairline bg-card p-4">
        <p className="mb-2 text-xs font-semibold text-slate">Outcome</p>
        <div className="grid grid-cols-2 gap-2">
          {CALL_OUTCOMES.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={outcome === option.value}
              onClick={() => setOutcome(option.value)}
              className={`tap rounded-tile border px-3 text-sm font-semibold transition-colors ${
                outcome === option.value
                  ? "border-ink bg-ink text-white"
                  : "border-hairline bg-card text-ink"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>

        <p className="mb-2 mt-4 text-xs font-semibold text-slate">
          Temperature (optional)
        </p>
        <div className="grid grid-cols-3 gap-2">
          {TEMPERATURES.map((option) => (
            <button
              key={option.value}
              type="button"
              aria-pressed={temperature === option.value}
              onClick={() =>
                setTemperature(temperature === option.value ? null : option.value)
              }
              className={`tap rounded-tile border px-3 text-sm font-semibold transition-colors ${
                temperature === option.value
                  ? "border-ink bg-ink text-white"
                  : "border-hairline bg-card text-ink"
              }`}
            >
              {option.label}
            </button>
          ))}
        </div>

        <textarea
          rows={2}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Remark (optional)"
          aria-label="Remark"
          className="mt-4 w-full resize-none rounded-tile border border-hairline bg-card px-4 py-3 text-[16px] outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft"
        />

        <button
          type="button"
          onClick={() => setFlagged(!flagged)}
          aria-pressed={flagged}
          className={`tap mt-3 flex w-full items-center justify-between rounded-tile border px-4 text-sm font-semibold transition-colors ${
            flagged
              ? "border-signal bg-signal-soft text-signal"
              : "border-hairline bg-card text-ink"
          }`}
        >
          <span>Flag for owner</span>
          <span
            className={`flex h-6 w-11 shrink-0 items-center rounded-pill px-0.5 transition-colors ${
              flagged ? "bg-signal" : "bg-hairline"
            }`}
          >
            <span
              className={`h-5 w-5 rounded-full bg-white transition-transform ${
                flagged ? "translate-x-5" : ""
              }`}
            />
          </span>
        </button>
      </div>

      {error && (
        <p role="alert" className="rounded-tile bg-signal-soft px-4 py-3 text-sm text-signal">
          {error}
        </p>
      )}

      <div className="flex gap-3">
        <button
          type="button"
          onClick={advance}
          disabled={busy}
          className="tap flex shrink-0 items-center justify-center rounded-pill border border-hairline bg-card px-5 text-sm font-semibold text-slate disabled:opacity-50"
        >
          Skip
        </button>
        <button
          type="button"
          onClick={save}
          disabled={busy}
          className="tap flex flex-1 items-center justify-center gap-1 rounded-pill bg-sandstone px-5 text-[15px] font-semibold text-white disabled:opacity-60"
        >
          {busy ? "Saving…" : "Log and next"}
          {!busy && <ChevronRight className="h-4 w-4" />}
        </button>
      </div>

      <p className="text-center text-[11px] text-slate">
        Every call is timestamped to you and visible to the owner.
      </p>
    </div>
  );
}

