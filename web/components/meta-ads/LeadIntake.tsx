"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Card, SectionHeading, StatusPill, type Tone } from "@/components/ui";
import type { MetaAdsStatus, MetaLeadRecord, MetaPage } from "@/lib/types";

const LEAD_TONE: Record<MetaLeadRecord["status"], [string, Tone]> = {
  created: ["New lead", "positive"],
  linked: ["Existing lead", "neutral"],
  pending: ["Retrying", "warning"],
  failed: ["Failed", "signal"],
};

/**
 * Where Meta Lead Ads land in the CRM: which Page leads come from, whether
 * delivery is live, and the last few leads with what became of each. "Sync
 * now" reads the lead forms directly, so a lead missed while the server slept
 * is never lost.
 */
export function LeadIntake({
  status,
  pages,
  recent,
}: {
  status: MetaAdsStatus;
  pages: MetaPage[];
  recent: MetaLeadRecord[];
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function post(path: string, body?: unknown) {
    const res = await fetch(`/api/crm/meta-ads/${path}`, {
      method: "POST",
      headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    }).catch(() => null);
    const json = res ? await res.json().catch(() => null) : null;
    return { ok: !!res?.ok, json };
  }

  async function choosePage(id: string) {
    setBusy("page");
    setError(null);
    const { ok, json } = await post("page", { page_id: id });
    setBusy(null);
    if (!ok) return setError(json?.error?.message ?? "Could not switch Page.");
    router.refresh();
  }

  async function sync() {
    setBusy("sync");
    setError(null);
    setMessage(null);
    const { ok, json } = await post("leads/sync");
    setBusy(null);
    if (!ok) return setError(json?.error?.message ?? "Could not sync leads.");
    setMessage(
      json.new
        ? `Imported ${json.new} lead${json.new === 1 ? "" : "s"} that had not arrived yet.`
        : "Nothing missing — every lead is already in the CRM.",
    );
    router.refresh();
  }

  const live = status.leads_live;
  return (
    <Card className="p-5">
      <SectionHeading
        title="Lead intake"
        hint="Facebook & Instagram lead forms flow straight into your Leads."
        action={
          <StatusPill
            label={live ? "Live" : status.webhook_configured ? "Not subscribed" : "Webhook not set up"}
            tone={live ? "positive" : "warning"}
          />
        }
      />

      {pages.length === 0 ? (
        <p className="text-sm text-slate">
          No Facebook Page found on this Meta login. Lead forms belong to a Page — reconnect
          and allow access to your Page.
        </p>
      ) : (
        <div className="grid gap-2 text-sm sm:grid-cols-2">
          <div>
            <p className="text-[11px] uppercase tracking-[0.12em] text-slate">Facebook Page</p>
            {pages.length > 1 && status.can_manage ? (
              <select
                className="tap mt-1 w-full rounded-tile border border-hairline bg-card px-2 text-sm"
                value={status.page_id ?? ""}
                disabled={busy !== null}
                onChange={(e) => choosePage(e.target.value)}
              >
                {!status.page_id && <option value="">Choose…</option>}
                {pages.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            ) : (
              <p className="font-semibold text-ink">{status.page_name ?? "—"}</p>
            )}
          </div>
          <div>
            <p className="text-[11px] uppercase tracking-[0.12em] text-slate">Instagram</p>
            <p className="font-semibold text-ink">
              {status.instagram_username ? `@${status.instagram_username}` : "Not linked to this Page"}
            </p>
          </div>
        </div>
      )}

      {!status.webhook_configured && (
        <p className="mt-3 rounded-tile bg-sandstone-soft px-3.5 py-2.5 text-xs text-sandstone-deep">
          Instant delivery needs <code>META_WEBHOOK_VERIFY_TOKEN</code> on the server and the
          webhook registered in your Meta app. Until then, “Sync now” still pulls leads in.
        </p>
      )}

      {status.page_id && status.can_manage && (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={sync}
            disabled={busy !== null}
            className="press tap rounded-pill bg-ink px-4 text-xs font-semibold text-white disabled:opacity-60"
          >
            {busy === "sync" ? "Syncing…" : "Sync now"}
          </button>
          {message && <span className="text-xs font-semibold text-teal">{message}</span>}
        </div>
      )}
      {error && <p className="mt-3 text-xs font-semibold text-signal">{error}</p>}

      {recent.length > 0 && (
        <ul className="mt-4 divide-y divide-hairline border-t border-hairline">
          {recent.slice(0, 8).map((l) => {
            const [label, tone] = LEAD_TONE[l.status];
            return (
              <li key={l.id} className="flex items-center justify-between gap-3 py-2.5 text-sm">
                <div className="min-w-0">
                  <p className="truncate text-ink">
                    {l.contact_id ? (
                      <Link href={`/contacts/${l.contact_id}`} className="font-semibold underline-offset-4 hover:underline">
                        {l.campaign_name ?? "Meta lead"}
                      </Link>
                    ) : (
                      (l.campaign_name ?? "Meta lead")
                    )}
                  </p>
                  <p className="truncate text-xs text-slate">
                    {new Date(l.received_at).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}
                    {l.error ? ` · ${l.error}` : ""}
                  </p>
                </div>
                <StatusPill label={label} tone={tone} />
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
