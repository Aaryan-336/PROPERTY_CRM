import Link from "next/link";
import { redirect } from "next/navigation";

import { CampaignControls } from "@/components/meta-ads/CampaignControls";
import { ConnectMetaAds } from "@/components/meta-ads/ConnectMetaAds";
import { LeadIntake } from "@/components/meta-ads/LeadIntake";
import { ReelSuggestions } from "@/components/meta-ads/ReelSuggestions";
import { Card, EmptyState, InkCard, MetricTile, SectionHeading, StatusPill, type Tone } from "@/components/ui";
import { ApiRequestError, api } from "@/lib/api";
import { currencyAmount, titleCase } from "@/lib/format";
import { SESSION_EXPIRED_ROUTE, getCurrentUser } from "@/lib/session";
import type {
  MetaAdAccount,
  MetaAdsStatus,
  MetaCampaignList,
  MetaLeadForm,
  MetaLeadPerformance,
  MetaLeadRecord,
  MetaPage,
  MetaInsightRow,
  MetaInsights,
} from "@/lib/types";

export const metadata = { title: "Meta Ads · Balaji CRM" };

const RANGES: [string, string][] = [
  ["today", "Today"],
  ["last_7d", "7 days"],
  ["last_30d", "30 days"],
  ["this_month", "This month"],
];

function statusTone(status: string): Tone {
  if (status === "ACTIVE") return "positive";
  if (status === "PAUSED" || status === "CAMPAIGN_PAUSED") return "neutral";
  if (["IN_PROCESS", "PENDING_REVIEW", "PREAPPROVED"].includes(status)) return "warning";
  return "signal";
}

type Attempt<T> = { data?: T; error?: string; status?: number };

async function attempt<T>(fn: () => Promise<T>): Promise<Attempt<T>> {
  try {
    return { data: await fn() };
  } catch (err) {
    if (err instanceof ApiRequestError) return { error: err.message, status: err.status };
    throw err;
  }
}

/**
 * Native Meta Ads dashboard. Owner only (the API enforces `meta_ads.*`); every
 * figure comes from the owner's own Meta connection, never a shared one.
 */
export default async function MetaAdsPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const user = await getCurrentUser();
  if (!user) redirect(SESSION_EXPIRED_ROUTE);
  if (user.role !== "owner") redirect("/");

  const params = await searchParams;
  const range = RANGES.some(([k]) => k === params.range) ? params.range! : "last_7d";

  // Never let this screen crash: if the API is older than this frontend (the
  // route 404s) or asleep, say so and what to do, instead of an error page.
  const statusResult = await attempt(() => api<MetaAdsStatus>("/meta-ads/status"));
  if (!statusResult.data) {
    const notDeployed = statusResult.status === 404;
    return (
      <Card className="p-5">
        <SectionHeading
          title="Meta Ads"
          action={<StatusPill label="Unavailable" tone="warning" />}
        />
        <p className="text-sm text-slate">
          {notDeployed
            ? "The API server is running an older version without Meta Ads. Redeploy the backend with this update — it adds the Meta Ads endpoints and runs its database migration on start."
            : `Couldn't load Meta Ads right now: ${statusResult.error}`}
        </p>
        <Link
          href="/meta-ads"
          className="press tap mt-4 inline-flex items-center rounded-pill border border-hairline bg-card px-4 text-sm font-semibold text-ink"
        >
          Try again
        </Link>
      </Card>
    );
  }
  const status = statusResult.data;
  const live = status.state === "connected";

  const none = Promise.resolve({});
  const [accounts, campaigns, insights, pages, recent, forms, perf]: [
    Attempt<MetaAdAccount[]>,
    Attempt<MetaCampaignList>,
    Attempt<MetaInsights>,
    Attempt<MetaPage[]>,
    Attempt<MetaLeadRecord[]>,
    Attempt<MetaLeadForm[]>,
    Attempt<MetaLeadPerformance>,
  ] = await Promise.all([
    live ? attempt(() => api<MetaAdAccount[]>("/meta-ads/ad-accounts")) : none,
    live && status.ad_account_id
      ? attempt(() => api<MetaCampaignList>("/meta-ads/campaigns"))
      : none,
    live && status.ad_account_id
      ? attempt(() => api<MetaInsights>(`/meta-ads/insights?date_preset=${range}`))
      : none,
    live ? attempt(() => api<MetaPage[]>("/meta-ads/pages")) : none,
    live ? attempt(() => api<MetaLeadRecord[]>("/meta-ads/leads/recent?limit=8")) : none,
    live && status.page_id ? attempt(() => api<MetaLeadForm[]>("/meta-ads/lead-forms")) : none,
    live && status.ad_account_id
      ? attempt(() => api<MetaLeadPerformance>(`/meta-ads/lead-performance?date_preset=${range}`))
      : none,
  ]);

  // A call may have just discovered the token is dead; re-read so the card
  // says "Reconnect required" on this very render instead of the next one.
  const freshStatus =
    live && (campaigns.error || insights.error)
      ? ((await attempt(() => api<MetaAdsStatus>("/meta-ads/status"))).data ?? status)
      : status;

  const currency = status.currency;
  const byCampaign = new Map<string, MetaInsightRow>(
    (insights.data?.rows ?? []).map((r) => [r.campaign_id, r]),
  );
  const totals = insights.data?.totals;
  const activeCount = (campaigns.data?.campaigns ?? []).filter((c) => c.status === "ACTIVE").length;

  return (
    <div className="space-y-5">
      <ConnectMetaAds status={freshStatus} accounts={accounts.data ?? []} result={params.meta} />

      {freshStatus.state === "connected" && (
        <LeadIntake status={freshStatus} pages={pages.data ?? []} recent={recent.data ?? []} />
      )}

      {freshStatus.state === "connected" && status.ad_account_id && (
        <>
          <InkCard className="p-5">
            <div className="flex flex-wrap items-end justify-between gap-3">
              <div>
                <p className="text-[11px] uppercase tracking-[0.18em] text-ink-muted">
                  {status.ad_account_name}
                </p>
                <h1 className="font-display mt-1.5 text-2xl leading-tight text-white">
                  Ad performance
                </h1>
              </div>
              <nav aria-label="Date range" className="flex flex-wrap gap-1">
                {RANGES.map(([key, label]) => (
                  <Link
                    key={key}
                    href={`/meta-ads?range=${key}`}
                    aria-current={key === range ? "page" : undefined}
                    className={`press tap flex items-center rounded-pill px-3 text-xs font-semibold ${
                      key === range ? "bg-sandstone text-white" : "text-ink-dim hover:text-white"
                    }`}
                  >
                    {label}
                  </Link>
                ))}
              </nav>
            </div>
            {insights.error ? (
              <p className="mt-4 text-sm text-ink-dim">{insights.error}</p>
            ) : (
              <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
                <MetricTile ink label="Spend" value={currencyAmount(totals?.spend ?? 0, currency)} />
                <MetricTile ink label="Leads" value={totals?.leads ?? 0}
                  sub={totals?.leads ? `${currencyAmount((totals.spend ?? 0) / totals.leads, currency)} per lead` : undefined} />
                <MetricTile ink label="Clicks" value={(totals?.clicks ?? 0).toLocaleString("en-IN")}
                  sub={`${(totals?.ctr ?? 0).toFixed(2)}% CTR`} />
                <MetricTile ink label="Active campaigns" value={activeCount} />
              </div>
            )}
          </InkCard>

          <section>
            <SectionHeading
              title="Campaigns"
              hint="Pause, resume or change a daily budget. Every change asks first and is recorded in the audit log."
            />
            {campaigns.error ? (
              <Card className="p-5 text-sm text-signal">{campaigns.error}</Card>
            ) : (campaigns.data?.campaigns.length ?? 0) === 0 ? (
              <EmptyState title="No campaigns in this ad account yet. Create one in Ads Manager and it will appear here." />
            ) : (
              <ul className="space-y-3">
                {campaigns.data!.campaigns.map((c) => {
                  const m = byCampaign.get(c.id);
                  return (
                    <Card as="li" key={c.id} className="p-4">
                      <div className="flex flex-wrap items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="truncate font-semibold text-ink">{c.name}</p>
                          <p className="mt-0.5 text-xs text-slate">
                            {c.objective ? titleCase(c.objective.replace(/^OUTCOME_/, "").toLowerCase()) : "Campaign"}
                            {" · "}
                            {c.daily_budget !== null
                              ? `${currencyAmount(c.daily_budget, currency)} / day`
                              : c.lifetime_budget !== null
                                ? `${currencyAmount(c.lifetime_budget, currency)} lifetime`
                                : "Budget set on ad sets"}
                          </p>
                        </div>
                        <StatusPill label={titleCase(c.effective_status.toLowerCase().replace(/_/g, " "))} tone={statusTone(c.effective_status)} />
                      </div>
                      <dl className="tabular mt-3 grid grid-cols-4 gap-2 text-xs">
                        {[
                          ["Spend", currencyAmount(m?.spend ?? 0, currency)],
                          ["Leads", String(m?.leads ?? 0)],
                          ["Clicks", (m?.clicks ?? 0).toLocaleString("en-IN")],
                          ["CPC", m?.clicks ? currencyAmount(m.cpc, currency) : "—"],
                        ].map(([k, v]) => (
                          <div key={k}>
                            <dt className="text-[10px] uppercase tracking-[0.1em] text-slate">{k}</dt>
                            <dd className="font-semibold text-ink">{v}</dd>
                          </div>
                        ))}
                      </dl>
                      {status.can_manage && (
                        <div className="mt-3 border-t border-hairline pt-3">
                          <CampaignControls campaign={c} currency={currency} />
                        </div>
                      )}
                    </Card>
                  );
                })}
              </ul>
            )}
          </section>

          <section>
            <SectionHeading
              title="What your ad spend turned into"
              hint="Leads that reached the CRM, and how far they got — so you see cost per site visit, not just cost per lead."
            />
            {perf.error ? (
              <Card className="p-5 text-sm text-signal">{perf.error}</Card>
            ) : (perf.data?.rows.length ?? 0) === 0 ? (
              <EmptyState title="No leads from Meta in this period yet." />
            ) : (
              <Card className="overflow-x-auto p-0">
                <table className="tabular w-full min-w-[560px] text-left text-xs">
                  <thead className="text-[10px] uppercase tracking-[0.1em] text-slate">
                    <tr>
                      {["Campaign", "Spend", "Leads", "Qualified", "Visited", "Closed", "Per lead", "Per visit"].map((h) => (
                        <th key={h} className="px-3 py-2.5 font-semibold">{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-hairline">
                    {[...perf.data!.rows, perf.data!.totals].map((r, i, all) => (
                      <tr key={r.campaign_id || "total"} className={i === all.length - 1 ? "font-semibold text-ink" : "text-ink"}>
                        <td className="max-w-[200px] truncate px-3 py-2.5">{r.campaign_name}</td>
                        <td className="px-3 py-2.5">{currencyAmount(r.spend, currency)}</td>
                        <td className="px-3 py-2.5">{r.crm_leads}{r.meta_leads && r.meta_leads !== r.crm_leads ? ` / ${r.meta_leads}` : ""}</td>
                        <td className="px-3 py-2.5">{r.qualified}</td>
                        <td className="px-3 py-2.5">{r.visited}</td>
                        <td className="px-3 py-2.5">{r.closed}</td>
                        <td className="px-3 py-2.5">{r.cost_per_lead !== null ? currencyAmount(r.cost_per_lead, currency) : "—"}</td>
                        <td className="px-3 py-2.5">{r.cost_per_visit !== null ? currencyAmount(r.cost_per_visit, currency) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            )}
            {(perf.data?.failed_leads ?? 0) > 0 && (
              <p className="mt-2 text-xs font-semibold text-signal">
                {perf.data!.failed_leads} lead{perf.data!.failed_leads === 1 ? "" : "s"} could not be imported. Press “Sync now” above to retry.
              </p>
            )}
          </section>

          {freshStatus.instagram_username && (
            <ReelSuggestions currency={currency} canManage={status.can_manage} forms={forms.data ?? []} />
          )}
        </>
      )}
    </div>
  );
}
