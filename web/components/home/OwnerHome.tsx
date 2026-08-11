import Link from "next/link";

import { FeedStream } from "@/components/FeedStream";
import { ShowingsTimeline } from "@/components/ShowingsTimeline";
import { ChevronRight } from "@/components/icons";
import {
  Avatar,
  AvatarStack,
  Card,
  EmptyState,
  InkCard,
  MetricTile,
  SectionHeading,
  StatusPill,
} from "@/components/ui";
import { api, qs } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import type { CallLog, FeedItem, Paged, Showing, User } from "@/lib/types";

export async function OwnerHome({ user }: { user: User }) {
  const [feed, escalations, showings, staff, todaysCalls] = await Promise.all([
    api<FeedItem[]>("/activities/feed?limit=50&since_hours=168"),
    api<Paged<CallLog>>("/owner/escalations?limit=6"),
    api<Paged<Showing>>("/property-interests?limit=12"),
    api<User[]>("/users"),
    api<Paged<CallLog>>(`/calls${qs({ limit: 50 })}`),
  ]);

  const today = new Date().toDateString();
  const callsToday = todaysCalls.items.filter(
    (c) => new Date(c.created_at).toDateString() === today,
  ).length;
  const visitsToday = showings.items.filter(
    (s) => new Date(s.shown_at).toDateString() === today,
  ).length;
  const activeStaff = staff.filter((s) => s.role !== "owner" && !s.deleted_at);

  return (
    <div className="space-y-5">
      {/* The Ink hero: the day's read on the firm, weighted so the eye lands
          here first. Reserved for what the owner most needs to trust. */}
      <InkCard className="p-5 lg:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[11px] uppercase tracking-[0.18em] text-ink-muted">
              {new Date().toLocaleDateString("en-IN", {
                weekday: "long",
                day: "numeric",
                month: "long",
              })}
            </p>
            <h1 className="font-display mt-1.5 text-2xl leading-tight text-white lg:text-3xl">
              Good {greeting()}, {user.name.split(" ")[0]}
            </h1>
            <p className="mt-1 text-sm text-ink-dim">
              Everything your team did today, as it happens.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <AvatarStack
              people={activeStaff.map((s) => ({ id: s.id, name: s.name }))}
              max={5}
              onInk
            />
            <span className="tabular text-xs text-ink-muted">
              {activeStaff.length} on the team
            </span>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
          <MetricTile label="Calls today" value={callsToday} ink />
          <MetricTile label="Showings today" value={visitsToday} ink />
          <MetricTile
            label="Escalations"
            value={escalations.total}
            sub={escalations.total ? "Needs your attention" : "All clear"}
            ink
          />
          <MetricTile label="Live activity" value={feed.length} sub="last 7 days" ink />
        </div>
      </InkCard>

      {/* Desktop earns its keep here: three panels side by side instead of the
          stacked mobile view — a command centre, not a scaled-up phone. */}
      <div className="grid gap-5 [&>*]:min-w-0 lg:grid-cols-[1.15fr_0.85fr]">
        <Card className="p-5">
          <SectionHeading
            title="Live activity"
            hint="Every call, visit and stage change across the firm"
            action={
              <Link
                href="/feed"
                className="flex items-center gap-1 text-xs font-semibold text-sandstone-deep"
              >
                All activity
                <ChevronRight className="h-3.5 w-3.5" />
              </Link>
            }
          />
          <FeedStream items={feed.slice(0, 12)} />
        </Card>

        <div className="space-y-5">
          {/* Escalations get the Ink treatment: this is the one panel the
              owner is expected to act on rather than browse. */}
          <InkCard className="p-5">
            <SectionHeading
              title="Escalation inbox"
              hint="Flagged by staff for you"
              ink
              action={
                escalations.total > 0 ? (
                  <StatusPill label={`${escalations.total} open`} tone="signal" />
                ) : undefined
              }
            />
            {escalations.items.length === 0 ? (
              <p className="py-4 text-sm text-ink-dim">
                Nothing flagged. Staff can raise a lead to you with one tap when
                logging a call.
              </p>
            ) : (
              <ul className="space-y-2.5">
                {escalations.items.map((call) => (
                  <li key={call.id}>
                    <Link
                      href={`/contacts/${call.contact_id}`}
                      className="flex items-start gap-3 rounded-tile bg-ink-soft px-3.5 py-3 transition-colors hover:bg-ink-line"
                    >
                      <Avatar name={call.caller_name} id={call.caller_id} size="sm" onInk />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold text-white">
                          {call.contact_name ?? "Lead"}
                        </span>
                        <span className="block truncate text-xs text-ink-dim">
                          {call.notes ?? "Flagged for your attention"}
                        </span>
                        <span className="tabular mt-1 block text-[11px] text-ink-muted">
                          {call.caller_name} · {relativeTime(call.created_at)}
                        </span>
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
            <Link
              href="/escalations"
              className="tap mt-3 flex items-center justify-center rounded-pill border border-ink-line text-xs font-semibold text-ink-dim"
            >
              Open inbox
            </Link>
          </InkCard>

          <Card className="p-5">
            <SectionHeading
              title="Who showed what to whom"
              hint="The firm's showing history"
              action={
                <Link
                  href="/showings"
                  className="flex items-center gap-1 text-xs font-semibold text-sandstone-deep"
                >
                  Filter
                  <ChevronRight className="h-3.5 w-3.5" />
                </Link>
              }
            />
            {showings.items.length === 0 ? (
              <EmptyState title="No showings logged yet. Agents log these from a lead's page after a site visit." />
            ) : (
              <ShowingsTimeline showings={showings.items.slice(0, 6)} />
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return "morning";
  if (hour < 17) return "afternoon";
  return "evening";
}
