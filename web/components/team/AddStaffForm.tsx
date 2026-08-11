"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ChipGroup, Sheet } from "@/components/Sheet";

const ROLES = [
  { value: "agent", label: "Agent" },
  { value: "cold_caller", label: "Cold Caller" },
  { value: "owner", label: "Owner" },
] as const;

type RoleValue = (typeof ROLES)[number]["value"];

/**
 * Create a staff account.
 *
 * The password is set here rather than emailed as an invite: this is a small
 * firm where the owner hands over credentials in person, and an invite flow
 * would mean standing up mail delivery for a four-person team. It is shown
 * once, on success, so the owner can pass it on.
 */
export function AddStaffForm({
  open,
  onClose,
}: {
  open: boolean;
  onClose: () => void;
}) {
  const router = useRouter();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<RoleValue>("agent");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [created, setCreated] = useState<string | null>(null);

  function reset() {
    setName("");
    setEmail("");
    setPhone("");
    setPassword("");
    setRole("agent");
    setError(null);
    setCreated(null);
  }

  async function submit() {
    if (!name.trim() || !email.trim() || password.length < 8) {
      setError("Name, email, and a password of at least 8 characters are required.");
      return;
    }
    setBusy(true);
    setError(null);

    const res = await fetch("/api/crm/users", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        name: name.trim(),
        email: email.trim(),
        phone: phone.trim() || null,
        password,
        role,
      }),
    }).catch(() => null);

    if (!res || !res.ok) {
      const body = await res?.json().catch(() => null);
      setError(body?.error?.message ?? "Could not create this account.");
      setBusy(false);
      return;
    }

    setCreated(email.trim());
    setBusy(false);
    router.refresh();
  }

  return (
    <Sheet
      open={open}
      onClose={() => {
        reset();
        onClose();
      }}
      title="Add staff"
      subtitle="They can sign in as soon as you save"
    >
      {created ? (
        <div className="space-y-4 py-4 text-center">
          <p className="font-display text-lg text-ink">Account created</p>
          <div className="rounded-tile bg-parchment px-4 py-3 text-left">
            <p className="text-xs text-slate">Sign-in email</p>
            <p className="tabular text-sm font-semibold text-ink">{created}</p>
            <p className="mt-3 text-xs text-slate">Password</p>
            <p className="tabular text-sm font-semibold text-ink">{password}</p>
          </div>
          <p className="text-xs text-slate">
            Pass these on now — the password is not shown again.
          </p>
          <button
            type="button"
            onClick={() => {
              reset();
              onClose();
            }}
            className="tap w-full rounded-pill bg-ink px-5 text-sm font-semibold text-white"
          >
            Done
          </button>
        </div>
      ) : (
        <div className="space-y-5">
          <Field label="Full name" value={name} onChange={setName} autoFocus />
          <Field
            label="Email"
            value={email}
            onChange={setEmail}
            type="email"
            hint="They sign in with this"
          />
          <Field label="Phone (optional)" value={phone} onChange={setPhone} type="tel" />
          <Field
            label="Temporary password"
            value={password}
            onChange={setPassword}
            hint="At least 8 characters"
          />

          <ChipGroup
            label="Role"
            options={ROLES}
            value={role}
            onChange={(v) => v && setRole(v)}
            columns={3}
          />

          <p className="rounded-tile bg-parchment px-4 py-3 text-xs leading-relaxed text-slate">
            {role === "cold_caller" &&
              "Cold Callers see only leads assigned to them, can log calls and escalate, and cannot export or edit budgets."}
            {role === "agent" &&
              "Agents see only their own leads, can add inventory and log site visits, and cannot export the client list."}
            {role === "owner" &&
              "Owners see everything across the firm, including the audit log and the client export. Add sparingly."}
          </p>

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
            {busy ? "Creating…" : "Create account"}
          </button>
        </div>
      )}
    </Sheet>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  hint,
  autoFocus,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  hint?: string;
  autoFocus?: boolean;
}) {
  const id = label.toLowerCase().replace(/\W+/g, "-");
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-xs font-semibold text-slate">
        {label}
      </label>
      <input
        id={id}
        type={type}
        value={value}
        autoFocus={autoFocus}
        onChange={(e) => onChange(e.target.value)}
        /* 16px keeps iOS from zooming the viewport on focus. */
        className="w-full rounded-tile border border-hairline bg-card px-4 py-3 text-[16px] outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft"
      />
      {hint && <p className="mt-1 text-[11px] text-slate">{hint}</p>}
    </div>
  );
}
