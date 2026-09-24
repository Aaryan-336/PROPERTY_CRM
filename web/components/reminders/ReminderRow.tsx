"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { CheckIcon } from "@/components/icons";
import { Sheet } from "@/components/Sheet";
import type { Task } from "@/lib/types";

import { dueLabel, isOverdue } from "./format";
import { PriorityPill } from "./PriorityPill";
import { ReminderForm } from "./ReminderForm";

/** One reminder: tick it off, edit it, or delete it. */
export function ReminderRow({ task }: { task: Task }) {
  const router = useRouter();
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const done = task.status === "done";
  const overdue = !done && isOverdue(task);

  async function setStatus(status: "done" | "pending" | "cancelled") {
    setBusy(true);
    setError(null);
    const res = await fetch(`/api/crm/tasks/${task.id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ status }),
    }).catch(() => null);
    setBusy(false);
    if (!res?.ok) {
      setError("Could not update. Try again.");
      return;
    }
    router.refresh();
  }

  return (
    <li
      className={`rounded-tile border px-3.5 py-3 ${
        task.priority === "high" && !done
          ? "border-signal/30 bg-signal-soft/40"
          : "border-hairline bg-card"
      }`}
    >
      <div className="flex items-start gap-3">
        <button
          type="button"
          onClick={() => setStatus(done ? "pending" : "done")}
          disabled={busy}
          aria-label={done ? "Mark as not done" : "Mark as done"}
          className={`press tap -ml-1.5 -mt-1.5 flex shrink-0 items-center justify-center rounded-full disabled:opacity-50`}
        >
          <span
            className={`flex h-6 w-6 items-center justify-center rounded-full border-2 ${
              done ? "border-teal bg-teal text-white" : "border-slate/50 bg-card text-transparent"
            }`}
          >
            <CheckIcon className="h-3.5 w-3.5" />
          </span>
        </button>

        <div className="min-w-0 flex-1">
          <p
            className={`text-sm leading-snug ${
              done ? "text-slate line-through" : "font-semibold text-ink"
            }`}
          >
            {task.title}
          </p>
          <p className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
            <span className={`tabular ${overdue ? "font-semibold text-signal" : "text-slate"}`}>
              {done && task.completed_at
                ? `Done ${new Date(task.completed_at).toLocaleDateString("en-IN", { day: "numeric", month: "short" })}`
                : dueLabel(task.due_at)}
            </span>
            {task.contact_id && task.contact_name && (
              <Link
                href={`/contacts/${task.contact_id}`}
                className="font-semibold text-sandstone-deep underline-offset-4 hover:underline"
              >
                {task.contact_name}
              </Link>
            )}
          </p>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {!done && <PriorityPill priority={task.priority} />}
        </div>
      </div>

      {!done && (
        <div className="mt-2 flex items-center gap-4 pl-8">
          <button
            type="button"
            onClick={() => setEditing(true)}
            className="text-xs font-semibold text-sandstone-deep underline-offset-4 hover:underline"
          >
            Edit
          </button>
          {confirmDelete ? (
            <span className="flex items-center gap-3 text-xs">
              <span className="text-signal">Delete this reminder?</span>
              <button
                type="button"
                onClick={() => setStatus("cancelled")}
                disabled={busy}
                className="font-semibold text-signal"
              >
                Delete
              </button>
              <button
                type="button"
                onClick={() => setConfirmDelete(false)}
                className="font-semibold text-slate"
              >
                Keep
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={() => setConfirmDelete(true)}
              className="text-xs font-semibold text-slate underline-offset-4 hover:underline"
            >
              Delete
            </button>
          )}
        </div>
      )}
      {error && <p className="mt-2 pl-8 text-xs font-semibold text-signal">{error}</p>}

      <Sheet open={editing} onClose={() => setEditing(false)} title="Edit reminder">
        {editing && (
          <ReminderForm
            taskId={task.id}
            initialTitle={task.title}
            initialDueAt={task.due_at}
            initialPriority={task.priority}
            onSaved={() => setEditing(false)}
          />
        )}
      </Sheet>
    </li>
  );
}
