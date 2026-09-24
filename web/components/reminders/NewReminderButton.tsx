"use client";

import { useState } from "react";

import { PlusIcon } from "@/components/icons";
import { Sheet } from "@/components/Sheet";

import { ReminderForm } from "./ReminderForm";

export function NewReminderButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="press tap flex items-center gap-2 rounded-pill bg-ink px-4 text-sm font-semibold text-white"
      >
        <PlusIcon className="h-4 w-4" />
        <span>New reminder</span>
      </button>
      <Sheet
        open={open}
        onClose={() => setOpen(false)}
        title="New reminder"
        subtitle="You'll get a notification at the time you choose."
      >
        {open && <ReminderForm onSaved={() => setOpen(false)} />}
      </Sheet>
    </>
  );
}
