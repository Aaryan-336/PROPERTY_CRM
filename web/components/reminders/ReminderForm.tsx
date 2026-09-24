"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Field, inputClass, primaryButtonClass } from "@/components/forms";
import { ChipGroup } from "@/components/Sheet";
import { Card } from "@/components/ui";
import { REMINDER_PRIORITIES, type ReminderPriority } from "@/lib/types";

import { DateTimeField, fromLocalInput, toLocalInput } from "./DateTimeField";

/**
 * Create or edit a reminder. One form for the voice sheet, the Reminders
 * page and editing, so the three can never drift apart.
 */
export function ReminderForm({
  taskId,
  initialTitle = "",
  initialDueAt = null,
  initialPriority = "normal",
  contactId,
  submitLabel,
  onSaved,
}: {
  taskId?: number;
  initialTitle?: string;
  initialDueAt?: string | null;
  initialPriority?: ReminderPriority;
  contactId?: number | null;
  submitLabel?: string;
  onSaved?: () => void;
}) {
  const router = useRouter();
  const [title, setTitle] = useState(initialTitle);
  const [due, setDue] = useState(toLocalInput(initialDueAt));
  const [priority, setPriority] = useState<ReminderPriority>(initialPriority);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function save(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim()) {
      setError("Say what the reminder is for.");
      return;
    }
    setBusy(true);
    setError(null);
    const body = {
      title: title.trim(),
      due_at: fromLocalInput(due),
      priority,
      ...(taskId || !contactId ? {} : { contact_id: contactId }),
    };
    const res = await fetch(taskId ? `/api/crm/tasks/${taskId}` : "/api/crm/tasks", {
      method: taskId ? "PATCH" : "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).catch(() => null);
    setBusy(false);
    if (!res?.ok) {
      const json = await res?.json().catch(() => null);
      setError(json?.error?.message ?? "Could not save the reminder. Try again.");
      return;
    }
    setSaved(true);
    router.refresh();
    if (onSaved) setTimeout(onSaved, 700);
  }

  if (saved) {
    return (
      <p className="rounded-tile bg-teal-soft px-4 py-3 text-sm font-semibold text-teal">
        {taskId ? "Reminder updated." : "Reminder saved."}
      </p>
    );
  }

  return (
    <form onSubmit={save} className="space-y-5">
      <Card className="space-y-4 p-5">
        <Field label="Remind me to" required>
          <textarea
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            rows={3}
            maxLength={500}
            className={`${inputClass} resize-none py-3 leading-relaxed`}
          />
        </Field>
        <div>
          <span className="mb-1.5 block text-xs font-semibold text-slate">When</span>
          <DateTimeField value={due} onChange={setDue} />
        </div>
        <ChipGroup
          label="Importance"
          options={REMINDER_PRIORITIES}
          value={priority}
          onChange={(v) => v && setPriority(v)}
          columns={3}
        />
        {priority === "high" && (
          <p className="-mt-2 text-[11px] text-slate">
            High-importance notifications stay on screen until you dismiss them.
          </p>
        )}
      </Card>

      {error && (
        <p role="alert" className="rounded-tile bg-signal-soft px-4 py-3 text-sm text-signal">
          {error}
        </p>
      )}

      <button type="submit" disabled={busy || !title.trim()} className={primaryButtonClass}>
        {busy ? "Saving…" : (submitLabel ?? (taskId ? "Save changes" : "Save reminder"))}
      </button>
    </form>
  );
}
