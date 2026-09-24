"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { currencyAmount } from "@/lib/format";
import type { MetaCampaign } from "@/lib/types";

type Pending =
  | { kind: "status"; to: "ACTIVE" | "PAUSED" }
  | { kind: "budget"; to: string }
  | null;

/**
 * Pause/resume and daily-budget edits. Nothing is sent to Meta until the
 * person has read back exactly what will change and pressed Confirm; the API
 * refuses the call without `confirm: true` as well, and audits it either way.
 */
export function CampaignControls({
  campaign,
  currency,
}: {
  campaign: MetaCampaign;
  currency: string | null;
}) {
  const router = useRouter();
  const [pending, setPending] = useState<Pending>(null);
  const [editingBudget, setEditingBudget] = useState(false);
  const [draft, setDraft] = useState(campaign.daily_budget ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const active = campaign.status === "ACTIVE";
  const canBudget = campaign.daily_budget !== null;

  async function send() {
    if (!pending) return;
    setBusy(true);
    setError(null);
    const path =
      pending.kind === "status"
        ? `/api/crm/meta-ads/campaigns/${campaign.id}/status`
        : `/api/crm/meta-ads/campaigns/${campaign.id}/budget`;
    const body =
      pending.kind === "status"
        ? { status: pending.to, confirm: true }
        : { daily_budget: pending.to, confirm: true };
    const res = await fetch(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).catch(() => null);
    const json = res ? await res.json().catch(() => null) : null;
    setBusy(false);
    if (!res?.ok) {
      setError(json?.error?.message ?? "Meta did not accept the change. Nothing was updated.");
      return;
    }
    setPending(null);
    setEditingBudget(false);
    router.refresh();
  }

  function askBudget() {
    const n = Number(draft);
    if (!draft || Number.isNaN(n) || n <= 0) {
      setError("Enter a daily budget above zero.");
      return;
    }
    setError(null);
    setPending({ kind: "budget", to: n.toFixed(2) });
  }

  if (pending) {
    const summary =
      pending.kind === "status"
        ? `${pending.to === "PAUSED" ? "Pause" : "Resume"} “${campaign.name}”?${
            pending.to === "PAUSED" ? " Ads stop delivering within minutes." : " Ads start spending again."
          }`
        : `Change the daily budget of “${campaign.name}” from ${currencyAmount(
            campaign.daily_budget,
            currency,
            { exact: true },
          )} to ${currencyAmount(pending.to, currency, { exact: true })}?`;
    return (
      <div className="rounded-tile bg-sandstone-soft px-3.5 py-3">
        <p className="text-xs leading-relaxed text-sandstone-deep">{summary}</p>
        {error && <p className="mt-2 text-xs font-semibold text-signal">{error}</p>}
        <div className="mt-2.5 flex gap-2">
          <button
            type="button"
            onClick={send}
            disabled={busy}
            className="tap rounded-pill bg-ink px-4 text-xs font-semibold text-white disabled:opacity-60"
          >
            {busy ? "Sending to Meta…" : "Confirm"}
          </button>
          <button
            type="button"
            onClick={() => {
              setPending(null);
              setError(null);
            }}
            disabled={busy}
            className="tap rounded-pill border border-hairline bg-card px-4 text-xs font-semibold text-ink"
          >
            Cancel
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {(active || campaign.status === "PAUSED") && (
        <button
          type="button"
          onClick={() => setPending({ kind: "status", to: active ? "PAUSED" : "ACTIVE" })}
          className={`press tap rounded-pill px-4 text-xs font-semibold ${
            active ? "border border-hairline bg-card text-ink" : "bg-teal text-white"
          }`}
        >
          {active ? "Pause" : "Resume"}
        </button>
      )}
      {canBudget &&
        (editingBudget ? (
          <span className="flex items-center gap-2">
            <label className="sr-only" htmlFor={`budget-${campaign.id}`}>
              Daily budget
            </label>
            <input
              id={`budget-${campaign.id}`}
              type="number"
              inputMode="decimal"
              min="1"
              step="1"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="tap w-28 rounded-tile border border-hairline bg-card px-2 text-sm"
            />
            <button
              type="button"
              onClick={askBudget}
              className="tap rounded-pill bg-ink px-4 text-xs font-semibold text-white"
            >
              Review
            </button>
            <button
              type="button"
              onClick={() => {
                setEditingBudget(false);
                setDraft(campaign.daily_budget ?? "");
                setError(null);
              }}
              className="tap px-2 text-xs font-semibold text-slate"
            >
              Cancel
            </button>
          </span>
        ) : (
          <button
            type="button"
            onClick={() => setEditingBudget(true)}
            className="tap px-2 text-xs font-semibold text-sandstone underline-offset-4 hover:underline"
          >
            Edit daily budget
          </button>
        ))}
      {error && <p className="w-full text-xs font-semibold text-signal">{error}</p>}
    </div>
  );
}
