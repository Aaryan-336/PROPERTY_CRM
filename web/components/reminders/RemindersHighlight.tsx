import Link from "next/link";

import { BellIcon, ChevronRight } from "@/components/icons";
import { Card, SectionHeading, StatusPill } from "@/components/ui";
import { api } from "@/lib/api";
import type { Paged, Task } from "@/lib/types";

import { dueLabel, groupReminders, isOverdue } from "./format";
import { PriorityPill } from "./PriorityPill";

/**
 * The dashboard's reminders card: what is overdue or due today, most urgent
 * first. Outlined in red when something is overdue so it cannot be missed.
 */
export async function RemindersHighlight({ hideWhenEmpty = false }: { hideWhenEmpty?: boolean }) {
  const pending = await api<Paged<Task>>("/tasks?mine=true&status=pending&limit=50");
  const { now, overdue, today: dueToday, later } = groupReminders(pending.items);
  const next = later[0];
  // Today's reminders must never hide behind a backlog of old overdue ones.
  const shown = [...overdue.slice(0, 3), ...dueToday.slice(0, 4)];
  const hidden = overdue.length + dueToday.length - shown.length;

  if (hideWhenEmpty && shown.length === 0) return null;

  const hint = [
    overdue.length ? `${overdue.length} overdue` : null,
    dueToday.length ? `${dueToday.length} due today` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <Card className={`p-5 ${overdue.length ? "border-signal/40" : "border-sandstone/40"}`}>
      <SectionHeading
        title="Reminders"
        hint={hint || "Nothing due today"}
        action={
          <Link
            href="/reminders"
            className="flex items-center gap-1 text-xs font-semibold text-sandstone-deep"
          >
            All reminders
            <ChevronRight className="h-3.5 w-3.5" />
          </Link>
        }
      />
      {shown.length > 0 ? (
        <ul className="space-y-2">
          {shown.map((t) => {
            const late = isOverdue(t, now);
            return (
              <li key={t.id}>
                <Link
                  href="/reminders"
                  className={`press-soft flex items-center gap-3 rounded-tile px-3.5 py-2.5 ${
                    t.priority === "high" || late ? "bg-signal-soft/60" : "bg-parchment"
                  }`}
                >
                  <BellIcon className={`h-4 w-4 shrink-0 ${late ? "text-signal" : "text-sandstone-deep"}`} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-semibold text-ink">{t.title}</span>
                    <span className={`tabular block text-xs ${late ? "text-signal" : "text-slate"}`}>
                      {dueLabel(t.due_at)}
                      {t.contact_name ? ` · ${t.contact_name}` : ""}
                    </span>
                  </span>
                  <PriorityPill priority={t.priority} />
                </Link>
              </li>
            );
          })}
          {hidden > 0 && (
            <li className="pt-1 text-xs text-slate">+{hidden} more on the Reminders page</li>
          )}
        </ul>
      ) : (
        <div className="flex items-center justify-between gap-3 rounded-tile bg-parchment px-3.5 py-3">
          <p className="min-w-0 truncate text-sm text-slate">
            {next ? `Next: ${next.title} · ${dueLabel(next.due_at)}` : "No upcoming reminders."}
          </p>
          <StatusPill label="Clear" tone="positive" />
        </div>
      )}
    </Card>
  );
}
