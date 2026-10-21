"use client";

import { useEffect, useState } from "react";

import { Card, EmptyState, SectionHeading, StatusPill, type Tone } from "@/components/ui";
import { currencyAmount } from "@/lib/format";
import type { MetaLeadForm, MetaReel, MetaReelSuggestions } from "@/lib/types";

const VERDICT: Record<MetaReel["verdict"], [string, Tone]> = {
  strong: ["Strong", "positive"],
  decent: ["Decent", "neutral"],
  weak: ["Weak", "warning"],
  not_enough_data: ["Too new to judge", "neutral"],
  skip: ["Skip", "neutral"],
};

type Plan = { reel: MetaReel; formId: string; budget: string; name: string };

/**
 * Your Instagram reels, ranked, with a suggested campaign for the best. Press
 * "Create paused campaign" and it is built on Meta in a PAUSED state: nothing
 * spends until you switch it on from the campaign list below.
 */
export function ReelSuggestions({
  currency,
  canManage,
  forms,
}: {
  currency: string | null;
  canManage: boolean;
  forms: MetaLeadForm[];
}) {
  const [data, setData] = useState<MetaReelSuggestions | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<{ url: string; name: string } | null>(null);

  useEffect(() => {
    let alive = true;
    fetch("/api/crm/meta-ads/reels/suggestions")
      .then(async (res) => {
        const json = await res.json().catch(() => null);
        if (!alive) return;
        if (!res.ok) setError(json?.error?.message ?? "Could not load your reels.");
        else setData(json);
      })
      .catch(() => alive && setError("Could not load your reels."));
    return () => {
      alive = false;
    };
  }, []);

  async function create() {
    if (!plan) return;
    setBusy(true);
    setError(null);
    const res = await fetch(`/api/crm/meta-ads/reels/${plan.reel.media_id}/campaign`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        form_id: plan.formId,
        daily_budget: plan.budget,
        name: plan.name,
        cities: plan.reel.campaign?.cities ?? [],
        age_min: plan.reel.campaign?.age_min ?? 25,
        age_max: plan.reel.campaign?.age_max ?? 55,
        confirm: true,
      }),
    }).catch(() => null);
    const json = res ? await res.json().catch(() => null) : null;
    setBusy(false);
    if (!res?.ok) {
      setError(json?.error?.message ?? "Meta did not create the campaign. Nothing was left behind.");
      return;
    }
    setDone({ url: json.ads_manager_url, name: plan.name });
    setPlan(null);
  }

  return (
    <section>
      <SectionHeading
        title="Campaign ideas from your reels"
        hint={
          data?.instagram_username
            ? `Ranked from @${data.instagram_username}'s own results, matched to the areas your leads ask for.`
            : "Ranked from your Instagram results, matched to the areas your leads ask for."
        }
      />
      {done && (
        <p className="mb-3 rounded-tile bg-teal-soft px-3.5 py-2.5 text-xs font-semibold text-teal">
          “{done.name}” was created <b>paused</b>.{" "}
          <a className="underline" href={done.url} target="_blank" rel="noreferrer">
            Review it in Ads Manager
          </a>
          , then resume it from the campaign list when you are ready to spend.
        </p>
      )}
      {error && <Card className="p-4 text-sm text-signal">{error}</Card>}
      {!data && !error && <Card className="p-5 text-sm text-slate">Reading your reels…</Card>}
      {data && data.reels.length === 0 && (
        <EmptyState title="No reels found on this Instagram account yet." />
      )}
      <ul className="space-y-3">
        {data?.reels.slice(0, 8).map((r) => {
          const [label, tone] = VERDICT[r.verdict];
          const open = plan?.reel.media_id === r.media_id;
          return (
            <Card as="li" key={r.media_id} className="p-4">
              <div className="flex gap-3">
                {r.thumbnail_url && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={r.thumbnail_url} alt="" className="h-20 w-14 shrink-0 rounded-tile object-cover" />
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-start justify-between gap-2">
                    <p className="line-clamp-2 text-sm font-semibold text-ink">{r.caption || "Untitled reel"}</p>
                    <StatusPill label={r.score === null ? label : `${label} · ${r.score}`} tone={tone} />
                  </div>
                  <dl className="tabular mt-2 grid grid-cols-4 gap-2 text-xs">
                    {[
                      ["Views", r.views.toLocaleString("en-IN")],
                      ["Reach", r.reach.toLocaleString("en-IN")],
                      ["Shares", String(r.shares)],
                      ["Saves", String(r.saved)],
                    ].map(([k, v]) => (
                      <div key={k}>
                        <dt className="text-[10px] uppercase tracking-[0.1em] text-slate">{k}</dt>
                        <dd className="font-semibold text-ink">{v}</dd>
                      </div>
                    ))}
                  </dl>
                </div>
              </div>
              <ul className="mt-3 list-disc space-y-0.5 pl-5 text-xs text-slate">
                {r.reasons.map((x) => (
                  <li key={x}>{x}</li>
                ))}
              </ul>

              {r.campaign && canManage && !open && (
                <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-tile bg-sandstone-soft px-3.5 py-3">
                  <p className="text-xs text-sandstone-deep">
                    Suggested: <b>{currencyAmount(r.campaign.daily_budget, r.campaign.currency)}</b>/day · Leads form ·{" "}
                    {r.campaign.cities.join(", ")} · ages {r.campaign.age_min}–{r.campaign.age_max}
                  </p>
                  <button
                    type="button"
                    disabled={forms.length === 0}
                    onClick={() =>
                      setPlan({
                        reel: r,
                        formId: forms[0]?.id ?? "",
                        budget: String(r.campaign!.daily_budget),
                        name: r.campaign!.name,
                      })
                    }
                    className="press tap rounded-pill bg-ink px-4 text-xs font-semibold text-white disabled:opacity-50"
                  >
                    {forms.length === 0 ? "Create a lead form first" : "Set up campaign"}
                  </button>
                </div>
              )}

              {open && plan && (
                <div className="mt-3 space-y-3 rounded-tile border border-hairline bg-card px-3.5 py-3">
                  <label className="block text-xs text-slate">
                    Campaign name
                    <input
                      value={plan.name}
                      onChange={(e) => setPlan({ ...plan, name: e.target.value })}
                      className="tap mt-1 w-full rounded-tile border border-hairline bg-card px-2 text-sm text-ink"
                    />
                  </label>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="block text-xs text-slate">
                      Lead form
                      <select
                        value={plan.formId}
                        onChange={(e) => setPlan({ ...plan, formId: e.target.value })}
                        className="tap mt-1 w-full rounded-tile border border-hairline bg-card px-2 text-sm text-ink"
                      >
                        {forms.map((f) => (
                          <option key={f.id} value={f.id}>
                            {f.name}
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="block text-xs text-slate">
                      Daily budget ({currency ?? "INR"})
                      <input
                        type="number"
                        min="1"
                        value={plan.budget}
                        onChange={(e) => setPlan({ ...plan, budget: e.target.value })}
                        className="tap mt-1 w-full rounded-tile border border-hairline bg-card px-2 text-sm text-ink"
                      />
                    </label>
                  </div>
                  <p className="text-xs text-slate">
                    This creates the campaign, ad set and ad on Meta as <b>paused</b>. Nothing is charged
                    until you resume it.
                  </p>
                  <div className="flex gap-2">
                    <button
                      type="button"
                      onClick={create}
                      disabled={busy || !plan.formId || !plan.name.trim() || Number(plan.budget) <= 0}
                      className="tap rounded-pill bg-ink px-4 text-xs font-semibold text-white disabled:opacity-60"
                    >
                      {busy ? "Creating on Meta…" : "Create paused campaign"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setPlan(null)}
                      disabled={busy}
                      className="tap rounded-pill border border-hairline bg-card px-4 text-xs font-semibold text-ink"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              )}
            </Card>
          );
        })}
      </ul>
    </section>
  );
}
