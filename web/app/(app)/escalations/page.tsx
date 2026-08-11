import Link from "next/link";

import { JourneyTimeline, type JourneyNode } from "@/components/JourneyTimeline";
import { Pagination } from "@/components/Pagination";
import { Avatar, EmptyState, InkCard, StatusPill } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { outcomeLabel } from "@/lib/format";
import type { CallLog, Paged } from "@/lib/types";

export const metadata = { title: "Escalations · Balaji CRM" };

/**
 * The owner's inbox of leads staff flagged for attention.
 *
 * Rendered on the Ink surface: this is a page to act on, not browse, and the
 * dark treatment is reserved for exactly that.
 */
export default async function EscalationsPage({
  searchParams,
}: {
  searchParams: Promise<{ offset?: string }>;
}) {
  const { offset: offsetParam } = await searchParams;
  const offset = Number(offsetParam ?? 0);

  const escalations = await api<Paged<CallLog>>(
    `/owner/escalations${qs({ limit: 25, offset })}`,
  );

  const nodes: JourneyNode[] = escalations.items.map((call) => ({
    id: `escalation-${call.id}`,
    title: call.contact_name ?? "Lead",
    detail: call.notes ?? `Flagged after a ${outcomeLabel(call.outcome).toLowerCase()} call`,
    actor: call.caller_name,
    at: call.created_at,
    state: "signal",
    meta: (
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill label={outcomeLabel(call.outcome)} tone="signal" />
        {call.temperature && (
          <StatusPill label={call.temperature.toUpperCase()} tone="sand" />
        )}
        <Link
          href={`/contacts/${call.contact_id}`}
          className="text-[11px] font-semibold text-sandstone underline-offset-2 hover:underline"
        >
          Open lead
        </Link>
      </div>
    ),
  }));

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <header className="flex items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl leading-tight text-ink">
            Escalation inbox
          </h1>
          <p className="tabular mt-0.5 text-sm text-slate">
            {escalations.total} flagged by your team
          </p>
        </div>
        <div className="flex -space-x-2">
          {[
            ...new Map(
              escalations.items.map((c) => [c.caller_id, c]),
            ).values(),
          ]
            .slice(0, 4)
            .map((call) => (
              <Avatar
                key={call.caller_id}
                name={call.caller_name}
                id={call.caller_id}
                size="sm"
              />
            ))}
        </div>
      </header>

      {escalations.items.length === 0 ? (
        <EmptyState title="Nothing flagged right now. Staff can raise a lead to you with one tap while logging a call." />
      ) : (
        <>
          <InkCard className="p-5">
            <JourneyTimeline nodes={nodes} variant="ink" showDayStamps />
          </InkCard>
          <Pagination
            total={escalations.total}
            limit={escalations.limit}
            offset={escalations.offset}
          />
        </>
      )}
    </div>
  );
}
