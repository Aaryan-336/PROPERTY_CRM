import type { Task } from "@/lib/types";

export function isOverdue(t: Task, now = Date.now()): boolean {
  return !!t.due_at && new Date(t.due_at).getTime() <= now;
}

export function endOfToday(): number {
  const d = new Date();
  d.setHours(23, 59, 59, 999);
  return d.getTime();
}

/** "Overdue · 2 h", "Today, 5:00 pm", "Tomorrow, 10:00 am", "Fri 26 Sep, 9:00 am". */
export function dueLabel(iso: string | null): string {
  if (!iso) return "No time set";
  const d = new Date(iso);
  const now = new Date();
  const time = d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" });
  const tomorrow = new Date(now);
  tomorrow.setDate(now.getDate() + 1);
  if (d.getTime() <= now.getTime()) {
    const mins = Math.round((now.getTime() - d.getTime()) / 60_000);
    const ago =
      mins < 60 ? `${Math.max(mins, 1)} min` : mins < 1440 ? `${Math.round(mins / 60)} h` : `${Math.round(mins / 1440)} d`;
    return `Overdue · ${ago}`;
  }
  if (d.toDateString() === now.toDateString()) return `Today, ${time}`;
  if (d.toDateString() === tomorrow.toDateString()) return `Tomorrow, ${time}`;
  return `${d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" })}, ${time}`;
}

const RANK = { high: 0, normal: 1, low: 2 } as const;

/** Soonest first; within the same minute, more important first. */
export function byDue(a: Task, b: Task): number {
  const ta = a.due_at ? new Date(a.due_at).getTime() : Infinity;
  const tb = b.due_at ? new Date(b.due_at).getTime() : Infinity;
  if (ta !== tb) return ta - tb;
  return (RANK[a.priority] ?? 1) - (RANK[b.priority] ?? 1);
}

/** Split open reminders by when they are due, relative to now. */
export function groupReminders(tasks: Task[]) {
  const now = Date.now();
  const eod = endOfToday();
  const sorted = [...tasks].sort(byDue);
  const due = (t: Task) => (t.due_at ? new Date(t.due_at).getTime() : null);
  return {
    now,
    overdue: sorted.filter((t) => isOverdue(t, now)),
    today: sorted.filter((t) => due(t) !== null && due(t)! > now && due(t)! <= eod),
    later: sorted.filter((t) => due(t) !== null && due(t)! > eod),
    undated: sorted.filter((t) => due(t) === null),
  };
}
