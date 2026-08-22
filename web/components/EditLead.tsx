"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { BudgetSlider } from "@/components/BudgetSlider";
import { ChipGroup, Sheet } from "@/components/Sheet";
import { BHK_OPTIONS, STAGES } from "@/lib/types";
import type { Contact } from "@/lib/types";

const SOURCES = [
  "walk_in",
  "referral",
  "portal",
  "instagram",
  "imported_list",
  "whatsapp_group",
];

const PROPERTY_TYPES = ["apartment", "villa", "plot", "commercial"];
const BUYER_TYPES = ["end_user", "investor"];

/**
 * Edit a lead's details.
 *
 * Everything a lead's record holds was previously write-once at creation, so a
 * mistyped number or a budget that moved could only be fixed by whoever had
 * database access. The API has always accepted PATCH; there was simply nothing
 * that sent one.
 *
 * Only fields that were actually touched are sent. The endpoint applies
 * exclude_unset, so an untouched field is left alone rather than overwritten
 * with what the form happened to be showing — which matters when two people
 * have the same lead open.
 */
export function EditLead({ contact }: { contact: Contact }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [form, setForm] = useState({
    first_name: contact.first_name ?? "",
    last_name: contact.last_name ?? "",
    phone: contact.phone ?? "",
    email: contact.email ?? "",
    stage: contact.stage ?? "new",
    lead_source: contact.lead_source ?? "",
    budget_min: contact.budget_min ?? "",
    budget_max: contact.budget_max ?? "",
    preferred_locations: (contact.preferred_locations ?? []).join(", "),
    property_type_interest: contact.property_type_interest ?? "",
    buyer_type: contact.buyer_type ?? "",
    bhk: contact.bhk === null ? "" : String(contact.bhk),
    remarks: contact.remarks ?? "",
  });

  function set<K extends keyof typeof form>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function save() {
    setBusy(true);
    setError(null);

    // Empty string means "cleared" for text, but for a number it means "not
    // set" — sending "" would fail validation, so those become null.
    const body: Record<string, unknown> = {
      first_name: form.first_name.trim(),
      last_name: form.last_name.trim() || null,
      phone: form.phone.trim() || null,
      email: form.email.trim() || null,
      stage: form.stage,
      lead_source: form.lead_source || null,
      budget_min: form.budget_min === "" ? null : Number(form.budget_min),
      budget_max: form.budget_max === "" ? null : Number(form.budget_max),
      preferred_locations: form.preferred_locations
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
      property_type_interest: form.property_type_interest || null,
      buyer_type: form.buyer_type || null,
      bhk: form.bhk === "" ? null : Number(form.bhk),
      remarks: form.remarks.trim() || null,
    };

    const res = await fetch(`/api/crm/contacts/${contact.id}`, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    }).catch(() => null);

    if (!res || !res.ok) {
      const payload = await res?.json().catch(() => null);
      setError(payload?.error?.message ?? "Could not save the changes.");
      setBusy(false);
      return;
    }

    setBusy(false);
    setOpen(false);
    router.refresh();
  }

  return (
    <>
      <button
        type="button"
        onClick={() => {
          setError(null);
          setOpen(true);
        }}
        className="text-xs font-semibold text-sandstone-deep"
      >
        Edit details
      </button>

      <Sheet
        open={open}
        onClose={() => setOpen(false)}
        title="Edit lead"
        subtitle={`${contact.first_name} ${contact.last_name ?? ""}`.trim()}
      >
        <div className="space-y-3">
          <div className="grid grid-cols-2 gap-3">
            <Field label="First name" value={form.first_name} onChange={(v) => set("first_name", v)} />
            <Field label="Last name" value={form.last_name} onChange={(v) => set("last_name", v)} />
          </div>

          <Field
            label="Phone"
            value={form.phone}
            onChange={(v) => set("phone", v)}
            inputMode="tel"
          />
          <Field
            label="Email"
            value={form.email}
            onChange={(v) => set("email", v)}
            type="email"
          />

          <Select
            label="Stage"
            value={form.stage}
            onChange={(v) => set("stage", v)}
            options={STAGES.map((s) => ({ value: s.value, label: s.label }))}
          />

          <BudgetSlider
            min={form.budget_min}
            max={form.budget_max}
            onChange={({ min, max }) =>
              setForm((f) => ({
                ...f,
                budget_min: min === null ? "" : String(min),
                budget_max: max === null ? "" : String(max),
              }))
            }
          />

          <ChipGroup
            label="Size"
            options={BHK_OPTIONS}
            value={(form.bhk || null) as never}
            onChange={(v) => set("bhk", v ?? "")}
            columns={4}
            allowClear
          />

          <Field
            label="Preferred areas"
            value={form.preferred_locations}
            onChange={(v) => set("preferred_locations", v)}
            hint="Comma separated — Powai, Thane West"
          />

          <div className="grid grid-cols-2 gap-3">
            <Select
              label="Looking for"
              value={form.property_type_interest}
              onChange={(v) => set("property_type_interest", v)}
              options={PROPERTY_TYPES.map((t) => ({ value: t, label: titleish(t) }))}
              allowEmpty
            />
            <Select
              label="Buyer type"
              value={form.buyer_type}
              onChange={(v) => set("buyer_type", v)}
              options={BUYER_TYPES.map((t) => ({ value: t, label: titleish(t) }))}
              allowEmpty
            />
          </div>

          <Select
            label="Source"
            value={form.lead_source}
            onChange={(v) => set("lead_source", v)}
            options={SOURCES.map((t) => ({ value: t, label: titleish(t) }))}
            allowEmpty
          />

          <label className="block">
            <span className="mb-1.5 block text-xs font-semibold text-slate">
              Remarks
            </span>
            <textarea
              value={form.remarks}
              onChange={(e) => set("remarks", e.target.value)}
              rows={4}
              maxLength={4000}
              placeholder="Possession timeline, who decides, what they have already rejected."
              className="w-full resize-y rounded-tile border border-hairline bg-card px-4 py-3 text-[16px] leading-relaxed outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft"
            />
          </label>

          {error && (
            <p role="alert" className="rounded-tile bg-signal-soft px-4 py-2.5 text-sm text-signal">
              {error}
            </p>
          )}

          <button
            type="button"
            onClick={save}
            disabled={busy || !form.first_name.trim()}
            className="tap w-full rounded-pill bg-sandstone px-5 text-[15px] font-semibold text-white disabled:opacity-50"
          >
            {busy ? "Saving…" : "Save changes"}
          </button>
        </div>
      </Sheet>
    </>
  );
}

function titleish(value: string) {
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function Field({
  label,
  value,
  onChange,
  hint,
  type = "text",
  inputMode,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  hint?: string;
  type?: string;
  inputMode?: "tel" | "numeric" | "email";
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-semibold text-slate">{label}</span>
      <input
        type={type}
        inputMode={inputMode}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-tile border border-hairline bg-card px-4 py-3 text-[16px] outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft"
      />
      {hint && <span className="mt-1 block text-[11px] text-slate">{hint}</span>}
    </label>
  );
}

export function Select({
  label,
  value,
  onChange,
  options,
  allowEmpty = false,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
  allowEmpty?: boolean;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-semibold text-slate">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-tile border border-hairline bg-card px-4 py-3 text-[16px] outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft"
      >
        {allowEmpty && <option value="">—</option>}
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
