"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Sheet } from "@/components/Sheet";
import { Avatar, StatusPill } from "@/components/ui";
import { relativeTime, roleLabel } from "@/lib/format";
import type { UserWorkload } from "@/lib/types";

/**
 * One staff member, with the numbers that make "remove this person" a safe
 * decision.
 *
 * Deactivating someone who still holds live leads strands every one of them —
 * they stop appearing in anybody's queue and quietly rot. So the lead count is
 * on the card, and if it is non-zero the removal flow insists on a handover
 * before it will let the account be switched off.
 */
export function StaffCard({
  row,
  colleagues,
  isSelf,
}: {
  row: UserWorkload;
  colleagues: UserWorkload[];
  isSelf: boolean;
}) {
  const router = useRouter();
  const [removing, setRemoving] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [handoverTo, setHandoverTo] = useState<number | null>(null);
  // Shown once, then gone. There is nowhere to look it up again — it is stored
  // hashed — so the owner has to hand it over before dismissing this.
  const [resetPassword, setResetPassword] = useState<string | null>(null);

  const { user } = row;
  const deactivated = Boolean(user.deleted_at);

  async function call(path: string, body?: unknown, method = "POST") {
    const res = await fetch(`/api/crm/${path}`, {
      method,
      headers: body ? { "content-type": "application/json" } : undefined,
      body: body ? JSON.stringify(body) : undefined,
    }).catch(() => null);
    if (!res || !res.ok) {
      const payload = await res?.json().catch(() => null);
      throw new Error(payload?.error?.message ?? "Request failed.");
    }
    return res.status === 204 ? null : res.json();
  }

  async function resetTheirPassword() {
    setBusy(true);
    setError(null);
    try {
      const result = await call(`users/${user.id}/reset-password`, {});
      setResetPassword(result.generated_password);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function reactivate() {
    setBusy(true);
    setError(null);
    try {
      await call(`users/${user.id}`, { deactivate: false }, "PATCH");
      router.refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function confirmRemoval() {
    setBusy(true);
    setError(null);
    try {
      // Hand the book over first. Doing it in this order means a failure
      // halfway leaves the account still active and still owning its leads,
      // rather than switched off with its leads orphaned.
      if (row.active_leads > 0) {
        if (!handoverTo) {
          setError("Choose who inherits these leads.");
          setBusy(false);
          return;
        }
        await call(`users/${user.id}/reassign-leads`, {
          to_user_id: handoverTo,
          reason: "Staff member removed",
        });
      }
      await call(`users/${user.id}`, { deactivate: true }, "PATCH");
      setRemoving(false);
      router.refresh();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const candidates = colleagues.filter(
    (c) => c.user.id !== user.id && !c.user.deleted_at,
  );

  return (
    <>
      <div
        className={`rounded-card border border-hairline bg-card p-4 ${
          deactivated ? "opacity-60" : ""
        }`}
      >
        <div className="flex items-start gap-3">
          <Avatar name={user.name} id={user.id} />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <p className="truncate text-sm font-semibold text-ink">{user.name}</p>
              <StatusPill
                label={roleLabel(user.role)}
                tone={user.role === "owner" ? "ink" : "neutral"}
              />
              {deactivated && <StatusPill label="Removed" tone="signal" />}
            </div>
            <p className="tabular truncate text-xs text-slate">{user.email}</p>
            {user.phone && (
              <p className="tabular truncate text-xs text-slate">{user.phone}</p>
            )}
          </div>
        </div>

        <dl className="mt-3 grid grid-cols-4 gap-2 border-t border-hairline pt-3">
          <Stat label="Leads" value={row.active_leads} />
          <Stat
            label="Follow-ups"
            value={row.open_tasks}
            tone={row.overdue_tasks > 0 ? "signal" : undefined}
            sub={row.overdue_tasks > 0 ? `${row.overdue_tasks} overdue` : undefined}
          />
          <Stat label="Calls 7d" value={row.calls_last_7d} />
          <Stat label="Visits 7d" value={row.showings_last_7d} />
        </dl>

        <div className="mt-3 flex items-center justify-between gap-3">
          <p className="text-[11px] text-slate">
            {row.last_active_at
              ? `Last call ${relativeTime(row.last_active_at)}`
              : "No calls logged yet"}
          </p>
          {isSelf ? (
            <span className="text-[11px] text-slate">This is you</span>
          ) : deactivated ? (
            <button
              type="button"
              onClick={reactivate}
              disabled={busy}
              className="text-xs font-semibold text-teal disabled:opacity-60"
            >
              Restore access
            </button>
          ) : (
            <div className="flex items-center gap-3">
              {/* Owners are excluded server-side too: resetting one from here
                  would bypass the current-password check that stops a borrowed
                  session becoming a permanent takeover. */}
              {user.role !== "owner" && (
                <button
                  type="button"
                  onClick={resetTheirPassword}
                  disabled={busy}
                  className="text-xs font-semibold text-sandstone-deep disabled:opacity-60"
                >
                  {busy ? "Resetting…" : "Reset password"}
                </button>
              )}
              <button
                type="button"
                onClick={() => {
                  setError(null);
                  setHandoverTo(candidates[0]?.user.id ?? null);
                  setRemoving(true);
                }}
                className="text-xs font-semibold text-signal"
              >
                Remove
              </button>
            </div>
          )}
        </div>

        {error && !removing && (
          <p role="alert" className="mt-2 text-xs text-signal">
            {error}
          </p>
        )}
      </div>

      <Sheet
        open={resetPassword !== null}
        onClose={() => {
          setResetPassword(null);
          router.refresh();
        }}
        title={`New password for ${user.name}`}
        subtitle="Shown once — it is stored hashed and cannot be looked up again."
      >
        <p className="tabular select-all break-all rounded-tile border border-hairline bg-parchment-deep px-4 py-3.5 text-center text-lg font-semibold text-ink">
          {resetPassword}
        </p>
        <p className="mt-3 text-xs leading-relaxed text-slate">
          Every device they were signed in on has been signed out. Give them
          this password directly, and have them set their own from{" "}
          <span className="font-semibold text-ink">Your account</span> once they
          are back in.
        </p>
        <button
          type="button"
          onClick={() => {
            setResetPassword(null);
            router.refresh();
          }}
          className="tap mt-4 w-full rounded-pill bg-ink px-5 text-sm font-semibold text-white"
        >
          I have saved it
        </button>
      </Sheet>

      <Sheet
        open={removing}
        onClose={() => setRemoving(false)}
        title={`Remove ${user.name}?`}
        subtitle="They lose access immediately, on every device"
      >
        <div className="space-y-5">
          <div className="rounded-tile bg-parchment px-4 py-3 text-sm leading-relaxed text-slate">
            Their account is deactivated and every signed-in session is revoked
            straight away — not just blocked at next login. Their call history
            and site visits stay in the record, so past work is still
            attributable to them.
          </div>

          {row.active_leads > 0 ? (
            <div>
              <p className="mb-2 text-sm font-semibold text-ink">
                {row.active_leads} live lead{row.active_leads === 1 ? "" : "s"}{" "}
                must go to someone
              </p>
              <p className="mb-3 text-xs text-slate">
                Leads left with a removed account stop appearing in anyone&rsquo;s
                queue. Closed and lost leads stay where they are.
              </p>
              {candidates.length === 0 ? (
                <p className="rounded-tile bg-signal-soft px-4 py-3 text-sm text-signal">
                  There is nobody else active to take these leads. Add a staff
                  member first.
                </p>
              ) : (
                <div className="space-y-2">
                  {candidates.map((c) => (
                    <button
                      key={c.user.id}
                      type="button"
                      onClick={() => setHandoverTo(c.user.id)}
                      aria-pressed={handoverTo === c.user.id}
                      className={`tap flex w-full items-center justify-between rounded-tile border px-4 text-sm transition-colors ${
                        handoverTo === c.user.id
                          ? "border-ink bg-ink text-white"
                          : "border-hairline bg-card text-ink"
                      }`}
                    >
                      <span className="font-semibold">{c.user.name}</span>
                      <span className="text-xs opacity-70">
                        {roleLabel(c.user.role)} · {c.active_leads} leads
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="rounded-tile bg-teal-soft px-4 py-3 text-sm text-teal">
              No live leads to hand over.
            </p>
          )}

          {error && (
            <p role="alert" className="rounded-tile bg-signal-soft px-4 py-3 text-sm text-signal">
              {error}
            </p>
          )}

          <button
            type="button"
            onClick={confirmRemoval}
            disabled={busy || (row.active_leads > 0 && candidates.length === 0)}
            className="tap w-full rounded-pill bg-signal px-5 text-[15px] font-semibold text-white disabled:opacity-50"
          >
            {busy
              ? "Removing…"
              : row.active_leads > 0
                ? `Hand over ${row.active_leads} lead${row.active_leads === 1 ? "" : "s"} and remove`
                : "Remove access"}
          </button>
        </div>
      </Sheet>
    </>
  );
}

function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: number;
  sub?: string;
  tone?: "signal";
}) {
  return (
    <div>
      <dt className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate">
        {label}
      </dt>
      <dd
        className={`tabular font-display text-lg leading-none ${
          tone === "signal" ? "text-signal" : "text-ink"
        }`}
      >
        {value}
      </dd>
      {sub && <p className="text-[10px] text-signal">{sub}</p>}
    </div>
  );
}
