import { QueueCard } from "@/components/QueueCard";
import { EmptyState, SectionHeading } from "@/components/ui";
import { api } from "@/lib/api";
import type { Paged, QueueItem } from "@/lib/types";

export const metadata = { title: "Call queue · Balaji CRM" };

export default async function QueuePage() {
  const page = await api<Paged<QueueItem>>("/call-queue?limit=50");
  const queue = page.items;
  const [next, ...rest] = queue;

  // Grouped by the reason each lead surfaced, so the order is legible rather
  // than something the caller has to take on faith.
  const groups = new Map<string, QueueItem[]>();
  for (const item of rest) {
    const list = groups.get(item.reason) ?? [];
    list.push(item);
    groups.set(item.reason, list);
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <header>
        <h1 className="font-display text-2xl leading-tight text-ink">Call queue</h1>
        <p className="tabular mt-0.5 text-sm text-slate">
          {page.total} lead{page.total === 1 ? "" : "s"} · your assigned leads only
          {page.has_more ? ` · showing the first ${queue.length}` : ""}
        </p>
      </header>

      {!next ? (
        <EmptyState title="Your queue is empty. Leads assigned to you will appear here in priority order." />
      ) : (
        <>
          <section>
            <SectionHeading title="Next up" hint={next.reason} />
            <QueueCard item={next} featured />
          </section>

          {[...groups.entries()].map(([reason, items]) => (
            <section key={reason}>
              <SectionHeading title={reason} hint={`${items.length} waiting`} />
              <ul className="space-y-2.5">
                {items.map((item) => (
                  <li key={item.contact.id}>
                    <QueueCard item={item} />
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </>
      )}
    </div>
  );
}
