"use client";

import Link from "next/link";
import { useState } from "react";

import { PlusIcon } from "@/components/icons";
import { AddStaffForm } from "@/components/team/AddStaffForm";
import { StaffCard } from "@/components/team/StaffCard";
import { EmptyState, InkCard, MetricTile, SectionHeading } from "@/components/ui";
import type { UserWorkload } from "@/lib/types";

/**
 * The team screen, grouped by role.
 *
 * Grouping by role rather than listing alphabetically is what makes the screen
 * answer the owner's actual questions — "is anyone carrying too much?", "who
 * is idle?" — at a glance, because those questions are only meaningful within
 * a role. A cold caller with 40 leads is normal; an agent with 40 is not.
 */
export function TeamBoard({
  rows,
  currentUserId,
}: {
  rows: UserWorkload[];
  currentUserId: number;
}) {
  const [adding, setAdding] = useState(false);

  const active = rows.filter((r) => !r.user.deleted_at);
  const removed = rows.filter((r) => r.user.deleted_at);

  const byRole = (role: string) => active.filter((r) => r.user.role === role);
  const agents = byRole("agent");
  const callers = byRole("cold_caller");
  const owners = byRole("owner");

  // Leads owned by someone who can no longer sign in. This is the number that
  // quietly costs the firm money, so it gets called out rather than buried.
  const strandedLeads = removed.reduce((sum, r) => sum + r.active_leads, 0);

  return (
    <div className="space-y-5">
      <InkCard className="p-5 lg:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-[11px] uppercase tracking-[0.18em] text-ink-muted">
              Staff
            </p>
            <h1 className="font-display mt-1.5 text-2xl leading-tight text-white">
              Your team
            </h1>
            <p className="mt-1 text-sm text-ink-dim">
              Add or remove staff, and see what each person is carrying.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href="/team/performance"
              className="tap flex items-center rounded-pill border border-ink-line px-4 text-sm font-semibold text-ink-dim"
            >
              Performance
            </Link>
            <button
              type="button"
              onClick={() => setAdding(true)}
              className="tap flex items-center gap-2 rounded-pill bg-sandstone px-5 text-sm font-semibold text-white"
            >
              <PlusIcon className="h-4 w-4" />
              Add staff
            </button>
          </div>
        </div>

        <div className="mt-5 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
          <MetricTile label="Agents" value={agents.length} ink />
          <MetricTile label="Cold callers" value={callers.length} ink />
          <MetricTile
            label="Live leads"
            value={active.reduce((sum, r) => sum + r.active_leads, 0)}
            ink
          />
          <MetricTile
            label="Stranded leads"
            value={strandedLeads}
            sub={strandedLeads ? "owned by removed staff" : "none"}
            ink
          />
        </div>
      </InkCard>

      {strandedLeads > 0 && (
        <p className="rounded-card border border-signal/40 bg-signal-soft px-4 py-3 text-sm text-signal">
          {strandedLeads} lead{strandedLeads === 1 ? " is" : "s are"} still owned
          by a removed account and will not appear in anyone&rsquo;s queue. Open
          the removed staff member below and hand the leads over.
        </p>
      )}

      <Group title="Agents" hint="Close deals and log site visits" rows={agents}>
        {agents.length === 0 && (
          <EmptyState title="No agents yet. Add one so leads have somewhere to go." />
        )}
      </Group>

      <Group
        title="Cold callers"
        hint="Work the call queue and escalate hot leads"
        rows={callers}
      >
        {callers.length === 0 && (
          <EmptyState title="No cold callers yet. Add one to start working the queue." />
        )}
      </Group>

      <Group title="Owners" hint="Full visibility across the firm" rows={owners} />

      {removed.length > 0 && (
        <Group
          title="Removed"
          hint="No access. Past work stays attributed to them."
          rows={removed}
        />
      )}

      <AddStaffForm open={adding} onClose={() => setAdding(false)} />
    </div>
  );

  function Group({
    title,
    hint,
    rows: groupRows,
    children,
  }: {
    title: string;
    hint: string;
    rows: UserWorkload[];
    children?: React.ReactNode;
  }) {
    if (groupRows.length === 0 && !children) return null;
    return (
      <section>
        <SectionHeading title={title} hint={hint} />
        {groupRows.length === 0 ? (
          children
        ) : (
          <div className="grid gap-3 [&>*]:min-w-0 lg:grid-cols-2">
            {groupRows.map((row) => (
              <StaffCard
                key={row.user.id}
                row={row}
                colleagues={rows}
                isSelf={row.user.id === currentUserId}
              />
            ))}
          </div>
        )}
      </section>
    );
  }
}
