"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Card, SectionHeading } from "@/components/ui";

const MIN_LENGTH = 8;

/**
 * Change your own password.
 *
 * The current password is asked for even though you are already signed in.
 * A session is a temporary thing; a changed password is not, so a borrowed
 * unlocked laptop should not be able to take the account permanently.
 *
 * Everything else signed in as you is signed out when this succeeds — that is
 * the point of changing it, if the reason is that somebody else has it.
 */
export function ChangePassword({ signedOutCount }: { signedOutCount?: number }) {
  const router = useRouter();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  // Checked here as well as on the server so the mistake is caught before a
  // round trip, not because the client is trusted — the server rejects both.
  const mismatch = confirm.length > 0 && next !== confirm;
  const tooShort = next.length > 0 && next.length < MIN_LENGTH;
  const submittable =
    current.length > 0 && next.length >= MIN_LENGTH && next === confirm && !busy;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setDone(null);

    const res = await fetch("/api/auth/change-password", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ current_password: current, new_password: next }),
    }).catch(() => null);

    if (!res || !res.ok) {
      const body = await res?.json().catch(() => null);
      setError(body?.error?.message ?? "Could not change your password.");
      setBusy(false);
      return;
    }

    const data = (await res.json()) as { sessions_revoked?: number };
    setCurrent("");
    setNext("");
    setConfirm("");
    setDone(
      data.sessions_revoked
        ? `Password changed. ${data.sessions_revoked} other ${
            data.sessions_revoked === 1 ? "device was" : "devices were"
          } signed out.`
        : "Password changed.",
    );
    setBusy(false);
    // The route above swapped the cookie for the freshly issued token, so this
    // device stays signed in; refresh so any cached render re-reads it.
    router.refresh();
  }

  return (
    <Card className="p-5">
      <SectionHeading
        title="Change password"
        hint="Signs out every other device"
      />
      <form onSubmit={submit} className="space-y-3">
        <Field
          id="current-password"
          label="Current password"
          value={current}
          onChange={setCurrent}
          autoComplete="current-password"
        />
        <Field
          id="new-password"
          label="New password"
          value={next}
          onChange={setNext}
          autoComplete="new-password"
          hint={`At least ${MIN_LENGTH} characters`}
          problem={tooShort ? `Too short — ${MIN_LENGTH} characters minimum.` : null}
        />
        <Field
          id="confirm-password"
          label="Confirm new password"
          value={confirm}
          onChange={setConfirm}
          autoComplete="new-password"
          problem={mismatch ? "These do not match." : null}
        />

        {error && (
          <p
            role="alert"
            className="rounded-tile bg-signal-soft px-4 py-2.5 text-sm text-signal"
          >
            {error}
          </p>
        )}
        {done && (
          <p
            role="status"
            className="rounded-tile bg-teal-soft px-4 py-2.5 text-sm text-teal"
          >
            {done}
          </p>
        )}

        <button
          type="submit"
          disabled={!submittable}
          className="tap w-full rounded-pill bg-ink px-5 text-sm font-semibold text-white transition-opacity disabled:opacity-50"
        >
          {busy ? "Changing…" : "Change password"}
        </button>
      </form>

      {signedOutCount === undefined && (
        <p className="mt-3 text-[11px] leading-relaxed text-slate">
          Forgotten it instead? Ask the owner to reset it from the Team screen —
          there is no email on this system, so there is no reset link.
        </p>
      )}
    </Card>
  );
}

function Field({
  id,
  label,
  value,
  onChange,
  autoComplete,
  hint,
  problem,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (v: string) => void;
  autoComplete: string;
  hint?: string;
  problem?: string | null;
}) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-xs font-semibold text-slate">
        {label}
      </label>
      <input
        id={id}
        type="password"
        required
        autoComplete={autoComplete}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className={`tap w-full rounded-tile border bg-card px-4 text-[16px] outline-none focus:ring-2 focus:ring-sandstone-soft ${
          problem ? "border-signal" : "border-hairline focus:border-sandstone"
        }`}
      />
      {problem ? (
        <p className="mt-1 text-[11px] text-signal">{problem}</p>
      ) : hint ? (
        <p className="mt-1 text-[11px] text-slate">{hint}</p>
      ) : null}
    </div>
  );
}
