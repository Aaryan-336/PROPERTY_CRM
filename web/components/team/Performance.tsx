import Link from "next/link";

import {
  Avatar,
  Card,
  EmptyState,
  InkCard,
  MetricTile,
  SectionHeading,
  StatusPill,
} from "@/components/ui";
import { outcomeLabel, relativeTime, roleLabel } from "@/lib/format";
import { CALL_OUTCOMES, type TeamPerformance } from "@/lib/types";

const WINDOWS = [7, 30, 90] as const;

/**
 * Who did how much, side by side, over one window.
 *
 * The PRD's owner story is spotting underperformance. A per-person page would
 * not do that — the number that means something is the comparison, so everyone
 * is on one screen over the same period, sorted by activity.
 *
 * Rates are shown only where there is a denominator. "0%" and "hasn't started"
 * look identical otherwise, and they call for opposite conversations.
 */
export function Performance({ data }: { data: TeamPerformance }) {
  const staff = [...data.staff]
    .filter((s) => !s.user.deleted_at)
    .sort((a, b) => b.calls + b.showings - (a.calls + a.showings));

  const pct = (v: number | null) =>
    v === null ? "—" : `${Math.round(v * 100)}%`;

  return (
    <div className="space-y-5">
      <InkCard className="p-5 lg:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[11px] uppercase tracking-[0.18em] text-ink-muted">
              Team
            </p>
            <h1 className="font-display mt-1.5 text-2xl leading-tight text-white">
              Performance
            </h1>
            <p className="mt-1 text-sm text-ink-dim">
              Last {data.days} days · everyone, on the same window.
            </p>
          </div>
          <div className="flex gap-1.5">
            {WINDOWS.map((d) => (
              <Link
                key={d}
                href={`/team/performance?days=${d}`}
                className={`tap flex items-center rounded-pill px-4 text-xs font-semibold transition-colors ${
                  data.days === d
                    ? "bg-sandstone text-white"
                    : "border border-ink-line text-ink-dim"
                }`}
              >
                {d}d
              </Link>
            ))}
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
          <MetricTile label="Calls" value={data.total_calls} ink />
          <MetricTile label="Showings" value={data.total_showings} ink />
          <MetricTile label="Closed" value={data.total_closed} ink />
          <MetricTile label="On the team" value={staff.length} ink />
        </div>
      </InkCard>

      {staff.length === 0 ? (
        <EmptyState title="No staff yet. Add someone on the Team screen." />
      ) : (
        <>
          {/* Mobile: a card each. */}
          <div className="space-y-3 lg:hidden">
            {staff.map((s) => (
              <Card key={s.user.id} className="p-4">
                <div className="flex items-start gap-3">
                  <Avatar name={s.user.name} id={s.user.id} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-semibold text-ink">
                      {s.user.name}
                    </p>
                    <p className="text-xs text-slate">{roleLabel(s.user.role)}</p>
                  </div>
                  {s.tasks_overdue > 0 && (
                    <StatusPill label={`${s.tasks_overdue} overdue`} tone="signal" />
                  )}
                </div>
                <dl className="mt-3 grid grid-cols-4 gap-2 border-t border-hairline pt-3">
                  <Stat label="Calls" value={s.calls} />
                  <Stat label="Reached" value={pct(s.connect_rate)} />
                  <Stat label="Visits" value={s.showings} />
                  <Stat label="Leads" value={s.leads_assigned} />
                </dl>
                {s.calls > 0 && <OutcomeBar row={s} />}
              </Card>
            ))}
          </div>

          {/* Laptop: a real table — comparison is the point, and columns make
              it scannable in a way stacked cards never do. */}
          <Card className="hidden overflow-x-auto lg:block">
            <table className="w-full min-w-[900px] text-sm">
              <thead>
                <tr className="border-b border-hairline bg-parchment text-left">
                  {[
                    "Staff",
                    "Calls",
                    "Reached",
                    "Connect %",
                    "Showings",
                    "Leads",
                    "Closed",
                    "Conv %",
                    "Overdue",
                    "Median response",
                    "Last active",
                  ].map((h) => (
                    <th
                      key={h}
                      className="px-3 py-2.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {staff.map((s) => (
                  <tr key={s.user.id} className="hover:bg-parchment/60">
                    <td className="px-3 py-2.5">
                      <div className="flex items-center gap-2">
                        <Avatar name={s.user.name} id={s.user.id} size="sm" />
                        <div className="min-w-0">
                          <p className="truncate font-semibold text-ink">
                            {s.user.name}
                          </p>
                          <p className="text-[11px] text-slate">
                            {roleLabel(s.user.role)}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="tabular px-3 py-2.5 font-semibold text-ink">
                      {s.calls}
                    </td>
                    <td className="tabular px-3 py-2.5 text-slate">{s.connected}</td>
                    <td className="tabular px-3 py-2.5 text-slate">
                      {pct(s.connect_rate)}
                    </td>
                    <td className="tabular px-3 py-2.5 text-slate">{s.showings}</td>
                    <td className="tabular px-3 py-2.5 text-slate">
                      {s.leads_assigned}
                    </td>
                    <td className="tabular px-3 py-2.5 text-slate">{s.closed}</td>
                    <td className="tabular px-3 py-2.5 text-slate">
                      {pct(s.conversion_rate)}
                    </td>
                    <td className="tabular px-3 py-2.5">
                      {s.tasks_overdue > 0 ? (
                        <span className="font-semibold text-signal">
                          {s.tasks_overdue}
                        </span>
                      ) : (
                        <span className="text-slate">—</span>
                      )}
                    </td>
                    <td className="tabular px-3 py-2.5 text-slate">
                      {s.median_response_hours === null
                        ? "—"
                        : s.median_response_hours < 24
                          ? `${s.median_response_hours.toFixed(1)}h`
                          : `${Math.round(s.median_response_hours / 24)}d`}
                    </td>
                    <td className="tabular px-3 py-2.5 text-slate">
                      {relativeTime(s.last_active_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <Card className="p-5">
            <SectionHeading
              title="Call outcomes"
              hint={`How each person's ${data.total_calls} calls actually went`}
            />
            <div className="space-y-4">
              {staff
                .filter((s) => s.calls > 0)
                .map((s) => (
                  <div key={s.user.id}>
                    <div className="mb-1.5 flex items-center justify-between gap-3">
                      <p className="truncate text-sm font-semibold text-ink">
                        {s.user.name}
                      </p>
                      <p className="tabular shrink-0 text-xs text-slate">
                        {s.calls} calls
                      </p>
                    </div>
                    <OutcomeBar row={s} />
                  </div>
                ))}
            </div>
            <p className="mt-4 text-[11px] leading-relaxed text-slate">
              &ldquo;Reached&rdquo; counts connected, interested and callback
              requested — the outcomes where someone actually picked up. Median
              response is the time from a lead arriving to that person&rsquo;s
              first call on it.
            </p>
          </Card>
        </>
      )}
    </div>
  );
}

/** Proportional bar of a person's outcomes — shape is read faster than digits. */
function OutcomeBar({ row }: { row: TeamPerformance["staff"][number] }) {
  const colors: Record<string, string> = {
    connected: "bg-teal",
    interested: "bg-sandstone",
    callback_requested: "bg-sandstone-soft",
    not_reachable: "bg-hairline",
    not_interested: "bg-signal-soft",
    wrong_number: "bg-signal",
  };

  return (
    <>
      <div className="flex h-2 w-full overflow-hidden rounded-pill bg-parchment-deep">
        {CALL_OUTCOMES.map(({ value }) => {
          const count = row.calls_by_outcome[value] ?? 0;
          if (!count) return null;
          return (
            <div
              key={value}
              className={colors[value] ?? "bg-slate"}
              style={{ width: `${(count / row.calls) * 100}%` }}
              title={`${outcomeLabel(value)}: ${count}`}
            />
          );
        })}
      </div>
      <div className="mt-1.5 flex flex-wrap gap-x-3 gap-y-1">
        {CALL_OUTCOMES.map(({ value, label }) => {
          const count = row.calls_by_outcome[value] ?? 0;
          if (!count) return null;
          return (
            <span
              key={value}
              className="flex items-center gap-1 text-[11px] text-slate"
            >
              <span
                className={`h-2 w-2 rounded-full ${colors[value] ?? "bg-slate"}`}
              />
              {label} {count}
            </span>
          );
        })}
      </div>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt className="text-[10px] font-semibold uppercase tracking-[0.1em] text-slate">
        {label}
      </dt>
      <dd className="tabular font-display text-lg leading-none text-ink">
        {value}
      </dd>
    </div>
  );
}
