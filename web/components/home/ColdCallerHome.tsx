import Link from "next/link";

import { QueueCard } from "@/components/QueueCard";
import { ChevronRight } from "@/components/icons";
import { Card, EmptyState, InkCard, MetricTile, SectionHeading } from "@/components/ui";
import { api } from "@/lib/api";
import type { Paged, QueueItem, Task, User } from "@/lib/types";

/**
 * Cold caller home: the next lead front and centre, one tap to start logging.
 *
 * Kept the calmest screen in the app — high call volume is stressful enough
 * without competing panels, so there is one card, one action, and a count.
 */
export async function ColdCallerHome({ user }: { user: User }) {
  const [queue, tasks] = await Promise.all([
    api<Paged<QueueItem>>("/call-queue?limit=25"),
    api<Paged<Task>>("/tasks?status=pending&limit=50"),
  ]);

  const [next, ...rest] = queue.items;
  const overdue = tasks.items.filter(
    (t) => t.due_at && new Date(t.due_at).getTime() <= Date.now(),
  ).length;

  return (
    <div className="space-y-5">
      <InkCard className="p-5">
        <p className="text-[11px] uppercase tracking-[0.18em] text-ink-muted">
          Your queue
        </p>
        <h1 className="font-display mt-1.5 text-2xl leading-tight text-white">
          {queue.total
            ? `${queue.total} lead${queue.total === 1 ? "" : "s"} to call`
            : "Queue is clear"}
        </h1>
        <div className="mt-5 grid grid-cols-2 gap-2.5">
          <MetricTile label="In queue" value={queue.total} ink />
          <MetricTile
            label="Callbacks due"
            value={overdue}
            sub={overdue ? "overdue" : "none overdue"}
            ink
          />
        </div>
      </InkCard>

      {next ? (
        <>
          {/* The single primary action on the calmest screen in the app:
              start working, rather than browse a list first. */}
          <Link
            href="/queue/session"
            className="tap flex w-full items-center justify-center gap-2 rounded-pill bg-sandstone px-5 text-[15px] font-semibold text-white"
          >
            Start calling
            <ChevronRight className="h-4 w-4" />
          </Link>

          <div>
            <SectionHeading title="Next up" hint={next.reason} />
            <QueueCard item={next} featured />
          </div>

          {rest.length > 0 && (
            <Card className="p-5">
              <SectionHeading
                title="After that"
                hint="In priority order"
                action={
                  <Link
                    href="/queue"
                    className="flex items-center gap-1 text-xs font-semibold text-sandstone-deep"
                  >
                    Full queue
                    <ChevronRight className="h-3.5 w-3.5" />
                  </Link>
                }
              />
              <ul className="space-y-2.5">
                {rest.slice(0, 4).map((item) => (
                  <li key={item.contact.id}>
                    <QueueCard item={item} />
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </>
      ) : (
        <EmptyState title="No leads assigned to you yet — ask the owner to assign leads to your queue." />
      )}
    </div>
  );
}
