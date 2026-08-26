"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

/**
 * Remove a listing from inventory. Owner only.
 *
 * Deliberately narrower than editing. Agents add and correct listings all day,
 * and `EditProperty` exists so a wrong price is fixed rather than deleted. This
 * is different in kind: inventory arrives automatically from the WhatsApp feed
 * and is shared by the whole firm, so removing a row takes a flat out of
 * everyone's search along with the sourcing history behind it.
 *
 * The API enforces the same rule under `properties.delete`; hiding the button
 * is a courtesy, not the control.
 *
 * Asks twice, and names what it is deleting in the confirmation, because the
 * listings most likely to look wrong are the automatically sourced ones — and
 * those are exactly the ones where "wrong" often means "extracted badly" and
 * the fix is Edit, not delete.
 */
export function DeleteProperty({
  propertyId,
  title,
}: {
  propertyId: number;
  title: string;
}) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function remove() {
    setBusy(true);
    setError(null);
    const res = await fetch(`/api/crm/properties/${propertyId}`, {
      method: "DELETE",
    }).catch(() => null);

    if (!res || (!res.ok && res.status !== 204)) {
      setBusy(false);
      setError(
        res?.status === 403
          ? "Only the owner can remove a listing."
          : "Could not remove it. Try again in a moment.",
      );
      return;
    }
    // Back to the list, then refresh it: the deleted row is still in the
    // server-rendered page this navigation came from.
    router.push("/properties");
    router.refresh();
  }

  if (!confirming) {
    return (
      <button
        type="button"
        onClick={() => setConfirming(true)}
        className="text-xs font-semibold text-sandstone underline-offset-4 hover:underline"
      >
        Delete listing
      </button>
    );
  }

  return (
    <div className="rounded-tile bg-signal-soft px-3.5 py-3 text-left">
      <p className="text-xs leading-relaxed text-signal">
        Remove <strong>{title}</strong> from inventory? It disappears from
        everyone&rsquo;s search and from matches. If the details are simply
        wrong, Edit listing fixes them instead.
      </p>
      {error && <p className="mt-2 text-xs font-semibold text-signal">{error}</p>}
      <div className="mt-2.5 flex gap-2">
        <button
          type="button"
          onClick={remove}
          disabled={busy}
          className="tap rounded-pill bg-signal px-4 text-xs font-semibold text-white disabled:opacity-60"
        >
          {busy ? "Removing…" : "Yes, remove it"}
        </button>
        <button
          type="button"
          onClick={() => {
            setConfirming(false);
            setError(null);
          }}
          className="tap rounded-pill border border-hairline bg-card px-4 text-xs font-semibold text-ink"
        >
          Keep it
        </button>
      </div>
    </div>
  );
}
