"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ChipGroup, Sheet } from "@/components/Sheet";
import { clockTime } from "@/lib/format";
import { CALL_OUTCOMES, TEMPERATURES } from "@/lib/types";

type Outcome = (typeof CALL_OUTCOMES)[number]["value"];
type Temperature = (typeof TEMPERATURES)[number]["value"];

/**
 * One-tap call logging — the fastest action in the app, and the one the whole
 * visibility model depends on. Under 15 seconds is the bar, so: outcome
 * pre-selected to the most common answer, everything else optional, one
 * primary button.
 */
export function LogCallSheet({
  contactId,
  contactName,
  phone,
  open,
  onClose,
}: {
  contactId: number;
  contactName: string;
  phone?: string | null;
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  // Defaults to the most common outcome rather than an empty state, so the
  // fastest path through this form is a single tap on "Save".
  const [outcome, setOutcome] = useState<Outcome>("connected");
  const [temperature, setTemperature] = useState<Temperature | null>(null);
  const [notes, setNotes] = useState("");
  const [flagged, setFlagged] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  async function submit() {
    setBusy(true);
    setError(null);

    const res = await fetch("/api/crm/calls", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        contact_id: contactId,
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
          "Could not save — you may be offline. This call has not been logged yet.",
      );
      setBusy(false);
      return;
    }

    const data = await res.json();
    // Trust and transparency: say plainly what was recorded and when, so
    // logging reads as part of the job rather than as covert monitoring.
    setSaved(
      `Logged at ${clockTime(data.call.created_at)}${
        data.follow_up_task ? " · follow-up reminder created" : ""
      }${flagged ? " · owner notified" : ""}`,
    );
    setBusy(false);
    router.refresh();

    setTimeout(() => {
      setSaved(null);
      reset();
      onClose();
    }, 1400);
  }

  function reset() {
    setOutcome("connected");
    setTemperature(null);
    setNotes("");
    setFlagged(false);
    setError(null);
  }

  return (
    <Sheet
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title="Log call"
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
          <p className="font-display text-lg text-ink">Call logged</p>
          <p className="text-sm text-slate">{saved}</p>
        </div>
      ) : (
        <div className="space-y-5">
          {phone && (
            <a
              href={`tel:${phone.replace(/[^\d+]/g, "")}`}
              className="tap flex items-center justify-center gap-2 rounded-pill bg-teal px-5 text-sm font-semibold text-white"
            >
              <svg viewBox="0 0 24 24" className="h-4 w-4" aria-hidden>
                <path
                  d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8.1 9.9a16 16 0 0 0 6 6l1.3-1.2a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2Z"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="1.8"
                />
              </svg>
              <span className="tabular">{phone}</span>
            </a>
          )}

          <ChipGroup
            label="Outcome"
            options={CALL_OUTCOMES}
            value={outcome}
            onChange={(v) => v && setOutcome(v)}
          />

          <ChipGroup
            label="Temperature (optional)"
            options={TEMPERATURES}
            value={temperature}
            onChange={setTemperature}
            columns={3}
            allowClear
          />

          <div>
            <label
              htmlFor="notes"
              className="mb-2 block text-xs font-semibold text-slate"
            >
              Notes (optional)
            </label>
            <textarea
              id="notes"
              rows={3}
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="What did they say?"
              className="w-full resize-none rounded-tile border border-hairline bg-card px-4 py-3 text-[16px] outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft"
            />
          </div>

          <button
            type="button"
            onClick={() => setFlagged(!flagged)}
            aria-pressed={flagged}
            className={`tap flex w-full items-center justify-between rounded-tile border px-4 text-sm font-semibold transition-colors ${
              flagged
                ? "border-signal bg-signal-soft text-signal"
                : "border-hairline bg-card text-ink"
            }`}
          >
            <span className="text-left">
              Flag for owner
              <span className="block text-xs font-normal opacity-70">
                Sends this straight to the owner&rsquo;s inbox
              </span>
            </span>
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

          {error && (
            <p role="alert" className="rounded-tile bg-signal-soft px-4 py-3 text-sm text-signal">
              {error}
            </p>
          )}

          <button
            type="button"
            onClick={submit}
            disabled={busy}
            className="tap w-full rounded-pill bg-sandstone px-5 text-[15px] font-semibold text-white transition-opacity disabled:opacity-60"
          >
            {busy ? "Saving…" : "Save call log"}
          </button>

          <p className="text-center text-[11px] leading-relaxed text-slate">
            This log is timestamped to you and visible to the owner.
          </p>
        </div>
      )}
    </Sheet>
  );
}
