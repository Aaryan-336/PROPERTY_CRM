"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Card, SectionHeading, StatusPill, type Tone } from "@/components/ui";
import type { MetaAdAccount, MetaAdsStatus } from "@/lib/types";

const STATE_LABEL: Record<MetaAdsStatus["state"], [string, Tone]> = {
  connected: ["Connected", "positive"],
  disconnected: ["Not connected", "neutral"],
  reauth_required: ["Reconnect required", "signal"],
};

const RESULT_MESSAGE: Record<string, [string, Tone]> = {
  connected: ["Meta Ads connected.", "positive"],
  cancelled: ["Connection cancelled on Meta. Nothing was changed.", "warning"],
  expired: ["That sign-in link expired. Press Connect again.", "warning"],
  error: ["Meta did not complete the connection. Try again.", "signal"],
};

/**
 * Connect *your own* Meta account. The browser only ever holds Meta's
 * authorize URL; the code is exchanged and the token encrypted on the API.
 */
export function ConnectMetaAds({
  status,
  accounts = [],
  result,
}: {
  status: MetaAdsStatus;
  accounts?: MetaAdAccount[];
  result?: string;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [confirmingDisconnect, setConfirmingDisconnect] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [label, tone] = STATE_LABEL[status.state];
  const banner = result ? RESULT_MESSAGE[result] : undefined;

  async function connect() {
    setBusy("connect");
    setError(null);
    const res = await fetch("/api/crm/meta-ads/oauth/start", { method: "POST" }).catch(
      () => null,
    );
    const body = res ? await res.json().catch(() => null) : null;
    if (!res?.ok || !body?.authorize_url) {
      setBusy(null);
      setError(body?.error?.message ?? "Could not start the connection. Try again.");
      return;
    }
    window.location.assign(body.authorize_url);
  }

  async function disconnect() {
    setBusy("disconnect");
    setError(null);
    const res = await fetch("/api/crm/meta-ads/disconnect", { method: "POST" }).catch(
      () => null,
    );
    setBusy(null);
    setConfirmingDisconnect(false);
    if (!res?.ok) {
      setError("Could not disconnect. Try again.");
      return;
    }
    router.replace("/meta-ads");
    router.refresh();
  }

  async function chooseAccount(id: string) {
    setBusy("account");
    setError(null);
    const res = await fetch("/api/crm/meta-ads/ad-account", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ ad_account_id: id }),
    }).catch(() => null);
    setBusy(null);
    if (!res?.ok) {
      setError("Could not switch ad account.");
      return;
    }
    router.refresh();
  }

  return (
    <Card className="p-5">
      <SectionHeading
        title="Meta Ads"
        hint="Your own Facebook & Instagram ad account, managed from here."
        action={<StatusPill label={label} tone={tone} />}
      />

      {banner && (
        <p
          className={`mb-3 rounded-tile px-3.5 py-2.5 text-xs font-semibold ${
            banner[1] === "positive"
              ? "bg-teal-soft text-teal"
              : banner[1] === "signal"
                ? "bg-signal-soft text-signal"
                : "bg-sandstone-soft text-sandstone-deep"
          }`}
        >
          {banner[0]}
        </p>
      )}

      {!status.configured ? (
        <p className="text-sm text-slate">
          Meta Ads is not set up on the server yet. The Meta app ID, secret,
          redirect URL and token encryption key need to be added to the API&rsquo;s
          environment.
        </p>
      ) : status.state === "disconnected" ? (
        <>
          <p className="text-sm text-slate">
            Sign in with Meta to see spend, leads and campaign performance here, and
            pause, resume or change daily budgets without opening Ads Manager.
          </p>
          {status.can_manage && (
            <button
              type="button"
              onClick={connect}
              disabled={busy !== null}
              className="press tap mt-4 rounded-pill bg-ink px-5 text-sm font-semibold text-white disabled:opacity-60"
            >
              {busy === "connect" ? "Opening Meta…" : "Connect Meta Ads"}
            </button>
          )}
        </>
      ) : (
        <>
          <dl className="grid gap-2 text-sm sm:grid-cols-2">
            <div>
              <dt className="text-[11px] uppercase tracking-[0.12em] text-slate">Signed in as</dt>
              <dd className="font-semibold text-ink">{status.meta_user_name ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-[11px] uppercase tracking-[0.12em] text-slate">Ad account</dt>
              <dd className="font-semibold text-ink">
                {accounts.length > 1 && status.can_manage ? (
                  <select
                    className="tap w-full rounded-tile border border-hairline bg-card px-2 text-sm"
                    value={status.ad_account_id ?? ""}
                    disabled={busy !== null}
                    onChange={(e) => chooseAccount(e.target.value)}
                  >
                    {!status.ad_account_id && <option value="">Choose…</option>}
                    {accounts.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.name} ({a.currency ?? "—"})
                      </option>
                    ))}
                  </select>
                ) : (
                  (status.ad_account_name ?? "No ad account found on this Meta login")
                )}
              </dd>
            </div>
          </dl>

          {status.state === "reauth_required" && (
            <p className="mt-3 rounded-tile bg-signal-soft px-3.5 py-2.5 text-xs text-signal">
              Meta no longer accepts this connection (it expired or was removed in
              Facebook settings). Reconnect to keep managing campaigns.
            </p>
          )}
          {status.state === "connected" && status.missing_scopes.length > 0 && (
            <p className="mt-3 rounded-tile bg-sandstone-soft px-3.5 py-2.5 text-xs text-sandstone-deep">
              Missing permission: {status.missing_scopes.join(", ")}. Reconnect and allow
              every permission Meta asks for.
            </p>
          )}

          {status.can_manage && (
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={connect}
                disabled={busy !== null}
                className={`press tap rounded-pill px-4 text-xs font-semibold disabled:opacity-60 ${
                  status.state === "reauth_required"
                    ? "bg-ink text-white"
                    : "border border-hairline bg-card text-ink"
                }`}
              >
                {busy === "connect" ? "Opening Meta…" : "Reconnect"}
              </button>
              {confirmingDisconnect ? (
                <span className="flex flex-wrap items-center gap-2 rounded-tile bg-signal-soft px-3 py-2 text-xs text-signal">
                  Disconnect and delete the stored authorization?
                  <button
                    type="button"
                    onClick={disconnect}
                    disabled={busy !== null}
                    className="tap rounded-pill bg-signal px-3 font-semibold text-white disabled:opacity-60"
                  >
                    {busy === "disconnect" ? "Disconnecting…" : "Yes, disconnect"}
                  </button>
                  <button
                    type="button"
                    onClick={() => setConfirmingDisconnect(false)}
                    className="tap rounded-pill border border-hairline bg-card px-3 font-semibold text-ink"
                  >
                    Keep
                  </button>
                </span>
              ) : (
                <button
                  type="button"
                  onClick={() => setConfirmingDisconnect(true)}
                  className="tap px-2 text-xs font-semibold text-sandstone underline-offset-4 hover:underline"
                >
                  Disconnect
                </button>
              )}
            </div>
          )}
        </>
      )}

      {error && <p className="mt-3 text-xs font-semibold text-signal">{error}</p>}
    </Card>
  );
}
