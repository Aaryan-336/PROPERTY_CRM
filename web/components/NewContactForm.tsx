"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { budgetRange } from "@/lib/format";

import { ChipGroup } from "@/components/Sheet";
import { Card } from "@/components/ui";
import { BHK_OPTIONS, LISTING_TYPES } from "@/lib/types";
import type { DuplicateCandidate } from "@/lib/types";

const SOURCES = [
  { value: "walk_in", label: "Walk-in" },
  { value: "referral", label: "Referral" },
  { value: "instagram", label: "Instagram" },
  { value: "portal", label: "Portal" },
] as const;

const BUYER_TYPES = [
  { value: "end_user", label: "End user" },
  { value: "investor", label: "Investor" },
] as const;

const PROPERTY_TYPES = [
  { value: "apartment", label: "Apartment" },
  { value: "villa", label: "Villa" },
  { value: "plot", label: "Plot" },
  { value: "commercial", label: "Commercial" },
] as const;

export function NewContactForm() {
  const router = useRouter();
  const [form, setForm] = useState({
    first_name: "",
    last_name: "",
    phone: "",
    email: "",
    budget_min: "",
    budget_max: "",
    preferred_locations: "",
    remarks: "",
  });
  const [source, setSource] = useState<string | null>("walk_in");
  const [buyerType, setBuyerType] = useState<string | null>(null);
  const [propertyType, setPropertyType] = useState<string | null>(null);
  const [bhk, setBhk] = useState<string | null>(null);
  const [listingType, setListingType] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [duplicates, setDuplicates] = useState<DuplicateCandidate[] | null>(null);

  function set(field: keyof typeof form, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function submit(force = false) {
    setBusy(true);
    setError(null);

    const res = await fetch(`/api/crm/contacts${force ? "?force=true" : ""}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        first_name: form.first_name.trim(),
        last_name: form.last_name.trim() || null,
        phone: form.phone.trim() || null,
        email: form.email.trim() || null,
        budget_min: form.budget_min ? Number(form.budget_min) : null,
        budget_max: form.budget_max ? Number(form.budget_max) : null,
        preferred_locations: form.preferred_locations
          ? form.preferred_locations.split(",").map((s) => s.trim()).filter(Boolean)
          : null,
        lead_source: source,
        buyer_type: buyerType,
        property_type_interest: propertyType,
        bhk: bhk ? Number(bhk) : null,
        listing_type_interest: listingType,
        remarks: form.remarks.trim() || null,
      }),
    }).catch(() => null);

    if (!res) {
      setError("Could not reach the server. Check your connection.");
      setBusy(false);
      return;
    }

    const body = await res.json().catch(() => null);

    // The backend refuses a likely duplicate rather than quietly creating one,
    // so the decision to create anyway is explicit and gets audited.
    if (res.status === 409 && body?.candidates) {
      setDuplicates(body.candidates);
      setBusy(false);
      return;
    }

    if (!res.ok) {
      setError(body?.error?.message ?? "Could not save this lead.");
      setBusy(false);
      return;
    }

    router.push(`/contacts/${body.id}`);
    router.refresh();
  }

  if (duplicates) {
    return (
      <Card className="p-5">
        <h2 className="font-display text-lg text-ink">This may already be in the system</h2>
        <p className="mt-1 text-sm text-slate">
          We found {duplicates.length === 1 ? "a lead" : "leads"} that look like the
          same person.
        </p>

        <ul className="mt-4 space-y-2">
          {duplicates.map((candidate) => (
            <li
              key={candidate.id}
              className="rounded-tile border border-hairline bg-parchment px-4 py-3"
            >
              <p className="text-sm font-semibold text-ink">{candidate.name}</p>
              <p className="tabular mt-0.5 text-xs text-slate">
                {candidate.match === "phone_exact"
                  ? `Same phone · ends ${candidate.phone_last4 ?? "····"}`
                  : `Similar name · ${candidate.score}% match`}
                {candidate.owner_name ? ` · with ${candidate.owner_name}` : ""}
              </p>
            </li>
          ))}
        </ul>

        <div className="mt-5 space-y-2">
          <button
            onClick={() => setDuplicates(null)}
            className="tap w-full rounded-pill bg-ink px-5 text-sm font-semibold text-white"
          >
            Go back and edit
          </button>
          <button
            onClick={() => {
              setDuplicates(null);
              void submit(true);
            }}
            disabled={busy}
            className="tap w-full rounded-pill border border-hairline bg-card px-5 text-sm font-semibold text-slate"
          >
            Create anyway — this is a different person
          </button>
        </div>
        <p className="mt-3 text-center text-[11px] text-slate">
          Creating a duplicate is recorded in the audit log.
        </p>
      </Card>
    );
  }

  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        void submit(false);
      }}
      className="space-y-5"
    >
      <Card className="space-y-4 p-5">
        <div className="grid grid-cols-2 gap-3">
          <Field label="First name" required>
            <input
              required
              value={form.first_name}
              onChange={(e) => set("first_name", e.target.value)}
              className={inputClass}
            />
          </Field>
          <Field label="Last name">
            <input
              value={form.last_name}
              onChange={(e) => set("last_name", e.target.value)}
              className={inputClass}
            />
          </Field>
        </div>

        <Field label="Phone">
          <input
            type="tel"
            inputMode="tel"
            value={form.phone}
            onChange={(e) => set("phone", e.target.value)}
            placeholder="+91 98765 43210"
            className={`${inputClass} tabular`}
          />
        </Field>

        <Field label="Email">
          <input
            type="email"
            value={form.email}
            onChange={(e) => set("email", e.target.value)}
            className={inputClass}
          />
        </Field>
      </Card>

      <Card className="space-y-4 p-5">
        <ChipGroup
          label="Rent or buy"
          options={LISTING_TYPES}
          value={listingType as never}
          onChange={(v) => setListingType(v)}
          allowClear
        />

        <div className="grid grid-cols-2 gap-3">
          <Field label={`Budget from (₹${listingType === "rent" ? "/month" : ""})`}>
            <input
              type="number"
              inputMode="numeric"
              value={form.budget_min}
              onChange={(e) => set("budget_min", e.target.value)}
              className={`${inputClass} tabular`}
            />
          </Field>
          <Field label={`Budget to (₹${listingType === "rent" ? "/month" : ""})`}>
            <input
              type="number"
              inputMode="numeric"
              value={form.budget_max}
              onChange={(e) => set("budget_max", e.target.value)}
              className={`${inputClass} tabular`}
            />
          </Field>
        </div>
        {/* Typing 15000000 is easy to get wrong by a zero, and the mistake is
            invisible until the matcher stops suggesting anything. Saying the
            figure back in the words a broker uses is what catches it. */}
        {(form.budget_min || form.budget_max) && (
          <p className="tabular -mt-1 text-[11px] text-slate">
            {budgetRange(form.budget_min || null, form.budget_max || null)}
            {listingType === "rent" ? " per month" : ""}
          </p>
        )}

        <Field label="Preferred locations">
          <input
            value={form.preferred_locations}
            onChange={(e) => set("preferred_locations", e.target.value)}
            placeholder="Bandra West, Powai"
            className={inputClass}
          />
        </Field>

        <ChipGroup
          label="Looking for"
          options={PROPERTY_TYPES}
          value={propertyType as never}
          onChange={(v) => setPropertyType(v)}
          allowClear
        />

        <ChipGroup
          label="Size"
          options={BHK_OPTIONS}
          value={bhk as never}
          onChange={(v) => setBhk(v)}
          columns={4}
          allowClear
        />

        <ChipGroup
          label="Buyer type"
          options={BUYER_TYPES}
          value={buyerType as never}
          onChange={(v) => setBuyerType(v)}
          allowClear
        />

        <ChipGroup
          label="Source"
          options={SOURCES}
          value={source as never}
          onChange={(v) => setSource(v)}
          allowClear
        />
      </Card>

      <Card className="p-5">
        <Field label="Remarks">
          <textarea
            value={form.remarks}
            onChange={(e) => set("remarks", e.target.value)}
            rows={4}
            maxLength={4000}
            placeholder="Wants possession before June. Husband decides. Already seen Lodha Amara."
            className={`${inputClass} resize-y py-3 leading-relaxed`}
          />
        </Field>
        <p className="mt-1.5 text-[11px] text-slate">
          Anything the fields above cannot hold. Visible to whoever works this
          lead — not to the client.
        </p>
      </Card>

      {error && (
        <p role="alert" className="rounded-tile bg-signal-soft px-4 py-3 text-sm text-signal">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={busy || !form.first_name.trim()}
        className="tap w-full rounded-pill bg-sandstone px-5 text-[15px] font-semibold text-white disabled:opacity-50"
      >
        {busy ? "Saving…" : "Save lead"}
      </button>
    </form>
  );
}

const inputClass =
  "tap w-full rounded-tile border border-hairline bg-card px-4 text-[16px] outline-none focus:border-sandstone focus:ring-2 focus:ring-sandstone-soft";

function Field({
  label,
  required = false,
  children,
}: {
  label: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-xs font-semibold text-slate">
        {label}
        {required && <span className="text-signal"> *</span>}
      </span>
      {children}
    </label>
  );
}
