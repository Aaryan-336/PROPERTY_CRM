"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Sheet } from "@/components/Sheet";
import { PeopleIcon } from "@/components/icons";
import { StatusPill } from "@/components/ui";
import { roleLabel } from "@/lib/format";
import type { Assignee, UserWorkload } from "@/lib/types";

/**
 * Owner-only: put a lead in front of one or more staff members.
 *
 * Checkboxes rather than a picker because the point is that several people can
 * hold the same lead — a closer brought in alongside the caller, two agents
 * splitting site visits. The lead's owner is unchanged; one person stays
 * accountable and the call queue is still built from that.
 *
 * The whole set is sent on save rather than a diff, so unticking somebody
 * removes them in the same request that adds somebody else.
 */
export function AssignLead({
  contactId,
  contactName,
  assignees,
  staff,
}: {
  contactId: number;
  contactName: string;
  assignees: Assignee[];
  staff: UserWorkload[];
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<number[]>(
    assignees.map((a) => a.user_id),
  );
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Anyone who can hold a lead. The owner is excluded because they already see
  // every lead — assigning to themselves would create a task and change nothing.
  const assignable = staff.filter(
    (s) => !s.user.deleted_at && s.user.role !== "owner",
  );

  const current = new Set(assignees.map((a) => a.user_id));
  const changed =
    selected.length !== current.size || selected.some((id) => !current.has(id));

  function toggle(id: number) {
    setSelected((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id],
    );
  }

  async function save() {
    setBusy(true);
    setError(null);

    const res = await fetch(`/api/crm/contacts/${contactId}/assignees`, {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ user_ids: selected, note: note.trim() || null }),
    }).catch(() => null);

    if (!res || !res.ok) {
      const body = await res?.json().catch(() => null);
      setError(body?.error?.message ?? "Could not save the assignment.");
      setBusy(false);
      return;
    }

    setBusy(false);
    setOpen(false);
    setNote("");
    router.refresh();
  }

  return (
    <>
      <div className="flex flex-wrap items-center gap-2">
        {assignees.length > 0 ? (
          assignees.map((a) => (
            <StatusPill key={a.user_id} label={a.name} tone="sand" />
          ))
        ) : (
          <span className="text-xs text-slate">Nobody else assigned</span>
        )}
        <button
          type="button"
          onClick={() => {
            setSelected(assignees.map((a) => a.user_id));
            setError(null);
            setOpen(true);
          }}
          className="flex items-center gap-1.5 text-xs font-semibold text-sandstone-deep"
        >
          <PeopleIcon className="h-3.5 w-3.5" />
          {assignees.length > 0 ? "Change" : "Assign"}
        </button>
      </div>

      <Sheet
        open={open}
        onClose={() => setOpen(false)}
        title="Assign this lead"
        subtitle={contactName}
      >
        {assignable.length === 0 ? (
          <p className="rounded-tile bg-signal-soft px-4 py-3 text-sm text-signal">
            There are no agents or cold callers to assign to. Add staff on the
            Team screen first.
          </p>
        ) : (
          <>
            <ul className="space-y-2">
              {assignable.map((member) => {
                const checked = selected.includes(member.user.id);
                return (
                  <li key={member.user.id}>
                    <label
                      className={`tap flex cursor-pointer items-center gap-3 rounded-tile border px-4 py-3 transition-colors ${
                        checked
                          ? "border-ink bg-ink text-white"
                          : "border-hairline bg-card text-ink"
                      }`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggle(member.user.id)}
                        className="h-5 w-5 shrink-0 accent-sandstone"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-semibold">
                          {member.user.name}
                        </span>
                        <span
                          className={`block truncate text-xs ${checked ? "text-ink-dim" : "text-slate"}`}
                        >
                          {roleLabel(member.user.role)} · {member.active_leads}{" "}
                          live leads
                        </span>
                      </span>
                    </label>
                  </li>
                );
              })}
            </ul>

            <label className="mt-4 block">
              <span className="mb-1.5 block text-xs font-semibold text-slate">
                Note (optional)
              </span>
              <input
                type="text"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                maxLength={280}
                placeholder="e.g. show the Powai flats this week"
                className="w-full rounded-tile border border-hairline bg-card px-4 py-3 text-[16px] outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft"
              />
              <span className="mt-1.5 block text-[11px] text-slate">
                Appears on the follow-up task each person gets.
              </span>
            </label>

            {error && (
              <p
                role="alert"
                className="mt-3 rounded-tile bg-signal-soft px-4 py-2.5 text-sm text-signal"
              >
                {error}
              </p>
            )}

            <button
              type="button"
              onClick={save}
              disabled={busy || !changed}
              className="tap mt-4 w-full rounded-pill bg-sandstone px-5 text-[15px] font-semibold text-white disabled:opacity-50"
            >
              {busy
                ? "Saving…"
                : selected.length === 0
                  ? "Remove everyone"
                  : `Assign ${selected.length} ${selected.length === 1 ? "person" : "people"}`}
            </button>
            <p className="mt-2 text-center text-[11px] text-slate">
              Each person gets a follow-up task and can open this lead. The
              lead&rsquo;s owner does not change.
            </p>
          </>
        )}
      </Sheet>
    </>
  );
}
