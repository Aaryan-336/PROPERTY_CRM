"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Sheet } from "@/components/Sheet";

/**
 * Add a WhatsApp group by its id — the manual fallback.
 *
 * This used to be the only way in, and it was rough: the owner had to copy a
 * `120363…@g.us` identifier out of a terminal and paste it correctly, with a
 * typo showing up much later as a group that looked configured and silently
 * received nothing. The group picker on this screen is now the normal route.
 *
 * Kept because the picker depends on the gateway having uploaded its list, and
 * a group somebody has the id for should not be un-addable just because that
 * has not happened yet. Still validates the shape before sending.
 */
export function AddGroupForm({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const [jid, setJid] = useState("");
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function reset() {
    setJid("");
    setName("");
    setNote("");
    setError(null);
  }

  async function submit() {
    const trimmed = jid.trim();
    if (!trimmed.endsWith("@g.us")) {
      setError(
        "That does not look like a group id — it should end in @g.us. Easier: pick the group by name in “Groups on this account” above.",
      );
      return;
    }
    if (!name.trim()) {
      setError("Give the group a name so you can recognise it here.");
      return;
    }

    setBusy(true);
    setError(null);
    const res = await fetch("/api/crm/whatsapp/groups", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        group_jid: trimmed,
        name: name.trim(),
        note: note.trim() || null,
        is_active: true,
      }),
    }).catch(() => null);

    if (!res || !res.ok) {
      const body = await res?.json().catch(() => null);
      setError(body?.error?.message ?? "Could not add this group.");
      setBusy(false);
      return;
    }

    setBusy(false);
    reset();
    onClose();
    router.refresh();
  }

  return (
    <Sheet
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title="Add a group"
      subtitle="Only groups listed here are ever read"
    >
      <div className="space-y-5">
        <div className="rounded-tile bg-parchment px-4 py-3 text-xs leading-relaxed text-slate">
          Only needed if the group is not in the list on this screen — pick it by
          name up there instead. Paste an id ending in{" "}
          <code className="tabular">@g.us</code> to add one by hand.
        </div>

        <div>
          <label
            htmlFor="jid"
            className="mb-1.5 block text-xs font-semibold text-slate"
          >
            Group id
          </label>
          <input
            id="jid"
            value={jid}
            onChange={(e) => setJid(e.target.value)}
            placeholder="120363012345678901@g.us"
            autoFocus
            className="tabular w-full rounded-tile border border-hairline bg-card px-4 py-3 text-[16px] outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft"
          />
        </div>

        <div>
          <label
            htmlFor="group-name"
            className="mb-1.5 block text-xs font-semibold text-slate"
          >
            Name
          </label>
          <input
            id="group-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Thane Brokers Network"
            className="w-full rounded-tile border border-hairline bg-card px-4 py-3 text-[16px] outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft"
          />
        </div>

        <div>
          <label
            htmlFor="note"
            className="mb-1.5 block text-xs font-semibold text-slate"
          >
            What&rsquo;s in this group? (optional)
          </label>
          <input
            id="note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Andheri West rentals only"
            className="w-full rounded-tile border border-hairline bg-card px-4 py-3 text-[16px] outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft"
          />
          <p className="mt-1 text-[11px] text-slate">
            Passed to the extractor as context. Helps it read terse messages
            that assume everyone knows the area.
          </p>
        </div>

        {error && (
          <p role="alert" className="rounded-tile bg-signal-soft px-4 py-3 text-sm text-signal">
            {error}
          </p>
        )}

        <button
          type="button"
          onClick={submit}
          disabled={busy}
          className="tap w-full rounded-pill bg-sandstone px-5 text-[15px] font-semibold text-white disabled:opacity-60"
        >
          {busy ? "Adding…" : "Start monitoring"}
        </button>
      </div>
    </Sheet>
  );
}
