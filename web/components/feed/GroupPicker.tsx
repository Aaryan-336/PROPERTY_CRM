"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { Card, SectionHeading } from "@/components/ui";
import { relativeTime } from "@/lib/format";
import type { WhatsAppGroupCandidate, WhatsAppSession } from "@/lib/types";

/** Rendered at once. A brokerage account sits in hundreds; the search is how
 *  you find one, not the scroll. */
const VISIBLE = 40;

/**
 * Pick which WhatsApp groups get read, from a list of names.
 *
 * This replaced the worst flow in the product. Adding a group used to mean
 * running `npm run groups` on the gateway box, finding the right
 * `120363043…@g.us` in a wall of several hundred, and pasting it into a form —
 * a machine identifier, transcribed by hand, by someone whose job is selling
 * flats. A typo produced a group that looked configured and silently received
 * nothing.
 *
 * The gateway already knows every group the linked account is in, so it uploads
 * that list and this renders it. Tapping a row is the whole interaction.
 *
 * Nothing here reads a group: a row in this list only means WhatsApp told us the
 * group exists. Ingestion starts when the owner taps, which creates the
 * whatsapp_groups row the webhook actually checks.
 */
export function GroupPicker({
  initial,
  session,
}: {
  initial: WhatsAppGroupCandidate[];
  session: WhatsAppSession;
}) {
  const router = useRouter();
  const [rows, setRows] = useState(initial);
  const [query, setQuery] = useState("");
  const [busyJid, setBusyJid] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const reload = useCallback(async () => {
    const res = await fetch("/api/crm/whatsapp/available-groups").catch(
      () => null,
    );
    if (res?.ok) setRows(await res.json());
  }, []);

  // The gateway uploads its list a moment after connecting, which is usually
  // just after this screen was rendered server-side with an empty one. Without
  // this the owner scans a code, lands on "no groups", and has to work out that
  // a reload fixes it.
  //
  // Bounded, and deliberately not conditional on the connection state: that
  // arrives as a server-rendered prop and is exactly as stale as the empty list
  // it would be gating. Fifteen tries at four seconds covers a scan-and-sync
  // with room to spare, and then it stops rather than polling a screen nobody
  // is watching.
  const [attempts, setAttempts] = useState(0);
  useEffect(() => {
    if (rows.length > 0 || attempts >= 15) return;
    const timer = setTimeout(() => {
      setAttempts((n) => n + 1);
      void reload();
    }, 4000);
    return () => clearTimeout(timer);
  }, [rows.length, attempts, reload]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return rows;
    // Matched on the id too: a group whose name has not synced can still be
    // found by pasting the id, which is the one case the old flow handled.
    return rows.filter(
      (r) =>
        r.name.toLowerCase().includes(needle) ||
        r.group_jid.toLowerCase().includes(needle),
    );
  }, [rows, query]);

  const shown = showAll ? filtered : filtered.slice(0, VISIBLE);
  const watchedCount = rows.filter((r) => r.watched).length;

  async function toggle(row: WhatsAppGroupCandidate) {
    setBusyJid(row.group_jid);
    setError(null);

    const res = row.watched
      ? await fetch(`/api/crm/whatsapp/groups/${row.group_id}`, {
          method: "DELETE",
        }).catch(() => null)
      : await fetch("/api/crm/whatsapp/groups", {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            group_jid: row.group_jid,
            name: displayName(row),
            is_active: true,
          }),
        }).catch(() => null);

    if (!res || !res.ok) {
      const body = await res?.json().catch(() => null);
      setError(
        body?.error?.message ??
          `Could not ${row.watched ? "stop reading" : "add"} ${displayName(row)}.`,
      );
      setBusyJid(null);
      return;
    }

    await reload();
    setBusyJid(null);
    // The console above this counts groups and lists them; it is server
    // rendered, so it needs telling.
    router.refresh();
  }

  async function resync() {
    setSyncing(true);
    setError(null);
    const res = await fetch("/api/crm/whatsapp/sync-groups", {
      method: "POST",
    }).catch(() => null);
    if (!res || !res.ok) {
      setError("Could not ask the gateway for a fresh list.");
      setSyncing(false);
      return;
    }
    // The gateway polls every few seconds, then reads the list off WhatsApp and
    // uploads it. Waiting is honest here — there is nothing to show until it
    // lands, and a spinner that stops too early looks like "no new groups".
    await new Promise((resolve) => setTimeout(resolve, 6000));
    await reload();
    setSyncing(false);
  }

  const linked = session.state === "connected" && !session.stale;

  return (
    <Card className="p-5">
      <SectionHeading
        title="Groups on this account"
        hint={
          rows.length > 0
            ? `${watchedCount} of ${rows.length} being read`
            : "Tap one to start reading it"
        }
        action={
          <button
            type="button"
            onClick={resync}
            disabled={syncing || !linked}
            className="text-xs font-semibold text-sandstone-deep disabled:opacity-50"
          >
            {syncing ? "Refreshing…" : "Refresh list"}
          </button>
        }
      />

      {!linked && rows.length === 0 ? (
        <p className="rounded-tile bg-parchment px-4 py-3 text-xs leading-relaxed text-slate">
          Link an account above and its groups appear here to pick from.
        </p>
      ) : rows.length === 0 ? (
        <p className="rounded-tile bg-parchment px-4 py-3 text-xs leading-relaxed text-slate">
          Connected — waiting for the gateway to send its group list. This takes
          a few seconds after linking.
        </p>
      ) : (
        <>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search groups…"
            aria-label="Search groups"
            className="w-full rounded-tile border border-hairline bg-card px-4 py-3 text-[16px] outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft"
          />

          <ul className="mt-3 space-y-2">
            {shown.map((row) => (
              <li key={row.group_jid}>
                <button
                  type="button"
                  onClick={() => void toggle(row)}
                  disabled={busyJid === row.group_jid}
                  aria-pressed={row.watched}
                  className={`flex w-full items-center gap-3 rounded-tile border px-3.5 py-3 text-left disabled:opacity-60 ${
                    row.watched
                      ? "border-sandstone bg-sandstone-soft"
                      : "border-hairline bg-card"
                  }`}
                >
                  <Tick on={row.watched} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold text-ink">
                      {displayName(row)}
                    </span>
                    <span className="tabular block truncate text-[11px] text-slate">
                      {row.participants > 0
                        ? `${row.participants} members · `
                        : ""}
                      {row.group_jid.replace("@g.us", "")}
                    </span>
                  </span>
                  <span className="shrink-0 text-[11px] font-semibold text-slate">
                    {busyJid === row.group_jid
                      ? "…"
                      : row.watched
                        ? "Reading"
                        : "Add"}
                  </span>
                </button>
              </li>
            ))}
          </ul>

          {filtered.length === 0 && (
            <p className="mt-3 text-xs text-slate">
              No group matches “{query}”. Try a shorter word, or Refresh list if
              you were added recently.
            </p>
          )}

          {!showAll && filtered.length > VISIBLE && (
            <button
              type="button"
              onClick={() => setShowAll(true)}
              className="tap mt-3 w-full rounded-pill border border-hairline bg-card px-5 text-sm font-semibold text-ink"
            >
              Show all {filtered.length}
            </button>
          )}

          {session.directory_synced_at && (
            <p className="mt-3 text-[11px] text-slate">
              List read off WhatsApp {relativeTime(session.directory_synced_at)}.
              Groups you were added to since then appear after a refresh.
            </p>
          )}
        </>
      )}

      {error && (
        <p
          role="alert"
          className="mt-3 rounded-tile bg-signal-soft px-4 py-2.5 text-sm text-signal"
        >
          {error}
        </p>
      )}
    </Card>
  );
}

/**
 * Something to recognise the group by.
 *
 * A group whose subject has not synced yet still has to be tappable and still
 * has to be given a name when added — WhatsApp usually sends the real one
 * minutes later, and the next sync replaces this.
 */
function displayName(row: WhatsAppGroupCandidate) {
  if (row.name.trim()) return row.name.trim();
  return `Unnamed group ${row.group_jid.slice(0, 6)}`;
}

function Tick({ on }: { on: boolean }) {
  return (
    <span
      aria-hidden
      className={`flex h-5 w-5 shrink-0 items-center justify-center rounded-full border ${
        on ? "border-sandstone bg-sandstone text-white" : "border-hairline"
      }`}
    >
      {on && (
        <svg viewBox="0 0 24 24" className="h-3 w-3">
          <path
            d="m5 13 4 4L19 7"
            fill="none"
            stroke="currentColor"
            strokeWidth="3"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      )}
    </span>
  );
}
