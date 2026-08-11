import Link from "next/link";
import { redirect } from "next/navigation";

import { ChevronRight } from "@/components/icons";
import {
  Card,
  EmptyState,
  InkCard,
  MetricTile,
  OUTCOME_TONE,
  SectionHeading,
  StatusPill,
  TEMPERATURE_TONE,
} from "@/components/ui";
import { api } from "@/lib/api";
import { clockTime, dayStamp, outcomeLabel, relativeTime } from "@/lib/format";
import { getCurrentUser } from "@/lib/session";
import type { CallLog, Paged, Task } from "@/lib/types";

export const metadata = { title: "My calls · Balaji CRM" };

/**
 * The caller's own record of their work.
 *
 * DESIGN_RULES.md, "Trust & transparency in the UI": staff-facing screens
 * should visibly show what has been logged about them, so logging reads as
 * part of the job rather than as covert monitoring. This is that screen — the
 * same data the owner sees in the firm-wide feed, presented back to the person
 * who generated it, plus their own numbers for the week.
 */
export default async function MyCallsPage() {
  const user = await getCurrentUser();
  if (!user) redirect("/login");

  const [calls, tasks] = await Promise.all([
    api<Paged<CallLog>>("/calls?limit=50"),
    api<Paged<Task>>("/tasks?status=pending&limit=50"),
  ]);

  // The API already scopes /calls to what this user may see. For an Owner that
  // is firm-wide, so narrow to their own calls to keep the page honest to its
  // title.
  const mine = calls.items.filter((c) => c.caller_id === user.id);

  const today = new Date().toDateString();
  const todaysCalls = mine.filter(
    (c) => new Date(c.created_at).toDateString() === today,
  );
  const connected = todaysCalls.filter((c) =>
    ["connected", "interested", "callback_requested"].includes(c.outcome),
  ).length;
  const flagged = mine.filter((c) => c.flagged_for_owner).length;
  const overdue = tasks.items.filter(
    (t) => t.due_at && new Date(t.due_at).getTime() <= Date.now(),
  ).length;

  // Grouped by day so a caller can see a shift as a shift.
  const byDay = new Map<string, CallLog[]>();
  for (const call of mine) {
    const key = dayStamp(call.created_at);
    byDay.set(key, [...(byDay.get(key) ?? []), call]);
  }

  return (
    <div className="space-y-5">
      <InkCard className="p-5 lg:p-6">
        <p className="text-[11px] uppercase tracking-[0.18em] text-ink-muted">
          Your record
        </p>
        <h1 className="font-display mt-1.5 text-2xl leading-tight text-white">
          Calls you&rsquo;ve logged
        </h1>
        <p className="mt-1 text-sm text-ink-dim">
          Everything here is timestamped to you and visible to the owner.
        </p>

        <div className="mt-5 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
          <MetricTile label="Calls today" value={todaysCalls.length} ink />
          <MetricTile
            label="Reached"
            value={connected}
            sub={todaysCalls.length ? `of ${todaysCalls.length}` : "today"}
            ink
          />
          <MetricTile
            label="Follow-ups"
            value={tasks.total}
            sub={overdue ? `${overdue} overdue` : "on track"}
            ink
          />
          <MetricTile label="Escalated" value={flagged} sub="to the owner" ink />
        </div>
      </InkCard>

      {mine.length === 0 ? (
        <EmptyState
          title="No calls logged yet. Open your queue and start working through it."
          action={
            <Link
              href="/queue/session"
              className="tap inline-flex items-center rounded-pill bg-ink px-5 text-sm font-semibold text-white"
            >
              Start calling
            </Link>
          }
        />
      ) : (
        [...byDay.entries()].map(([day, dayCalls]) => (
          <Card key={day} className="p-5">
            <SectionHeading
              title={day}
              hint={`${dayCalls.length} call${dayCalls.length === 1 ? "" : "s"}`}
            />
            <ul className="divide-y divide-hairline">
              {dayCalls.map((call) => (
                <li key={call.id} className="py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      {call.contact_id ? (
                        <Link
                          href={`/contacts/${call.contact_id}`}
                          className="flex items-center gap-1 truncate text-sm font-semibold text-ink"
                        >
                          {call.contact_name ?? "Lead"}
                          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate" />
                        </Link>
                      ) : (
                        <p className="truncate text-sm font-semibold text-ink">
                          {call.contact_name ?? "Lead"}
                        </p>
                      )}
                      {call.notes && (
                        <p className="mt-0.5 line-clamp-2 text-xs text-slate">
                          {call.notes}
                        </p>
                      )}
                      <p className="tabular mt-1 text-[11px] text-slate">
                        {clockTime(call.created_at)}
                        {call.follow_up_at
                          ? ` · follow-up ${relativeTime(call.follow_up_at)}`
                          : ""}
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-1">
                      <StatusPill
                        label={outcomeLabel(call.outcome)}
                        tone={OUTCOME_TONE[call.outcome] ?? "neutral"}
                      />
                      {call.temperature && (
                        <StatusPill
                          label={call.temperature}
                          tone={TEMPERATURE_TONE[call.temperature] ?? "neutral"}
                        />
                      )}
                      {call.flagged_for_owner && (
                        <StatusPill label="Escalated" tone="signal" />
                      )}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </Card>
        ))
      )}
    </div>
  );
}
