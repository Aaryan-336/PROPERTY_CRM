import { redirect } from "next/navigation";

import { BellIcon } from "@/components/icons";
import { NewReminderButton } from "@/components/reminders/NewReminderButton";
import { NotificationsCard } from "@/components/reminders/NotificationsCard";
import { ReminderRow } from "@/components/reminders/ReminderRow";
import { groupReminders } from "@/components/reminders/format";
import { EmptyState, SectionHeading, StatusPill } from "@/components/ui";
import { api } from "@/lib/api";
import { SESSION_EXPIRED_ROUTE, getCurrentUser } from "@/lib/session";
import type { Paged, Task } from "@/lib/types";

export const metadata = { title: "Reminders · Balaji CRM" };

/**
 * Your own reminders -- typed, spoken, or created by a call outcome -- grouped
 * by when they are due. Each one is pushed to your devices at its time.
 */
export default async function RemindersPage() {
  const user = await getCurrentUser();
  if (!user) redirect(SESSION_EXPIRED_ROUTE);

  const [pending, done] = await Promise.all([
    api<Paged<Task>>("/tasks?mine=true&status=pending&limit=50"),
    api<Paged<Task>>("/tasks?mine=true&status=done&limit=10"),
  ]);

  const { overdue, today, later, undated } = groupReminders(pending.items);
  const items = [...overdue, ...today, ...later, ...undated];
  const recentDone = [...done.items].sort(
    (a, b) => new Date(b.completed_at ?? b.created_at).getTime() - new Date(a.completed_at ?? a.created_at).getTime(),
  );

  const groups: { title: string; hint?: string; tasks: Task[]; tone?: "signal" }[] = [
    { title: "Overdue", hint: "Past their time and still open", tasks: overdue, tone: "signal" },
    { title: "Today", tasks: today },
    { title: "Upcoming", tasks: later },
    { title: "No time set", hint: "On your list, without a notification", tasks: undated },
  ];

  return (
    <div className="mx-auto max-w-2xl">
      <header className="mb-4 flex items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl leading-tight text-ink">Reminders</h1>
          <p className="tabular mt-0.5 text-sm text-slate">
            {pending.total} open
            {overdue.length ? ` · ${overdue.length} overdue` : ""}
          </p>
        </div>
        <NewReminderButton />
      </header>

      <div className="space-y-5">
        <NotificationsCard />

        {items.length === 0 ? (
          <EmptyState
            icon={<BellIcon className="h-7 w-7" />}
            title="No open reminders. Add one here, say one into the mic, or log a call with a follow-up time."
          />
        ) : (
          groups
            .filter((g) => g.tasks.length > 0)
            .map((g) => (
              <section key={g.title}>
                <SectionHeading
                  title={g.title}
                  hint={g.hint}
                  action={
                    <StatusPill label={String(g.tasks.length)} tone={g.tone ?? "neutral"} />
                  }
                />
                <ul className="space-y-2">
                  {g.tasks.map((t) => (
                    <ReminderRow key={t.id} task={t} />
                  ))}
                </ul>
              </section>
            ))
        )}

        {recentDone.length > 0 && (
          <section>
            <SectionHeading title="Recently done" />
            <ul className="space-y-2">
              {recentDone.map((t) => (
                <ReminderRow key={t.id} task={t} />
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
