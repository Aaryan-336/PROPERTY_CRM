"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { ChipGroup } from "@/components/Sheet";
import { Card } from "@/components/ui";

const LISTING_TYPES = [
  { value: "outright", label: "Outright" },
  { value: "rent", label: "Rent" },
] as const;

const PROPERTY_TYPES = [
  { value: "apartment", label: "Apartment" },
  { value: "villa", label: "Villa" },
  { value: "plot", label: "Plot" },
  { value: "commercial", label: "Commercial" },
] as const;

const STATUSES = [
  { value: "available", label: "Available" },
  { value: "blocked", label: "Blocked" },
  { value: "sold", label: "Sold" },
] as const;

export function NewPropertyForm() {
  const router = useRouter();
  const [form, setForm] = useState({
    title: "",
    building: "",
    location: "",
    price: "",
  });
  const [listingType, setListingType] = useState<string>("outright");
  const [propertyType, setPropertyType] = useState<string | null>("apartment");
  const [status, setStatus] = useState<string>("available");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set(field: keyof typeof form, value: string) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);

    const res = await fetch("/api/crm/properties", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        title: form.title.trim() || null,
        building: form.building.trim() || null,
        location: form.location.trim(),
        price: form.price ? Number(form.price) : null,
        listing_type: listingType,
        property_type: propertyType,
        status,
      }),
    }).catch(() => null);

    const body = await res?.json().catch(() => null);
    if (!res || !res.ok) {
      setError(body?.error?.message ?? "Could not save this listing.");
      setBusy(false);
      return;
    }

    router.push(`/properties/${body.id}`);
    router.refresh();
  }

  return (
    <form onSubmit={submit} className="space-y-5">
      <Card className="space-y-4 p-5">
        <Field label="Title">
          <input
            value={form.title}
            onChange={(e) => set("title", e.target.value)}
            placeholder="3 BHK in Rustomjee Seasons"
            className={inputClass}
          />
        </Field>
        <Field label="Building / Society">
          <input
            value={form.building}
            onChange={(e) => set("building", e.target.value)}
            className={inputClass}
          />
        </Field>
        <Field label="Location" required>
          <input
            required
            value={form.location}
            onChange={(e) => set("location", e.target.value)}
            placeholder="Bandra West"
            className={inputClass}
          />
        </Field>
        <Field label="Price (₹)">
          <input
            type="number"
            inputMode="numeric"
            value={form.price}
            onChange={(e) => set("price", e.target.value)}
            className={`${inputClass} tabular`}
          />
        </Field>
      </Card>

      <Card className="space-y-4 p-5">
        <ChipGroup
          label="Rent or outright"
          options={LISTING_TYPES}
          value={listingType as never}
          onChange={(v) => v && setListingType(v)}
        />
        <ChipGroup
          label="Property type"
          options={PROPERTY_TYPES}
          value={propertyType as never}
          onChange={(v) => setPropertyType(v)}
          allowClear
        />
        <ChipGroup
          label="Status"
          options={STATUSES}
          value={status as never}
          onChange={(v) => v && setStatus(v)}
          columns={3}
        />
      </Card>

      {error && (
        <p role="alert" className="rounded-tile bg-signal-soft px-4 py-3 text-sm text-signal">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={busy || !form.location.trim()}
        className="tap w-full rounded-pill bg-sandstone px-5 text-[15px] font-semibold text-white disabled:opacity-50"
      >
        {busy ? "Saving…" : "Save listing"}
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
