"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Sheet } from "@/components/Sheet";
import { Field, Select } from "@/components/EditLead";
import type { Property } from "@/lib/types";

const PROPERTY_TYPES = ["apartment", "villa", "plot", "commercial"];
const LISTING_TYPES = [
  { value: "rent", label: "Rent" },
  { value: "outright", label: "Sale" },
];
const STATUSES = [
  { value: "available", label: "Available" },
  { value: "blocked", label: "Blocked" },
  { value: "sold", label: "Sold / Let" },
];
const REVIEW_STATES = [
  { value: "confirmed", label: "Confirmed" },
  { value: "needs_review", label: "Needs review" },
  { value: "auto_accepted", label: "Auto accepted" },
  { value: "rejected", label: "Rejected" },
];

/**
 * Edit a listing.
 *
 * This matters most for WhatsApp-sourced inventory. Extraction is
 * probabilistic, and a listing flagged for review is flagged precisely because
 * a human needs to look at it — but until now the review queue offered only
 * accept or delete. A slightly wrong price meant deleting a real flat.
 *
 * The raw message stays untouched and visible on the listing. Corrections
 * change the structured fields; the source of truth for what a broker actually
 * wrote is never rewritten.
 */
export function EditProperty({ property }: { property: Property }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [form, setForm] = useState({
    title: property.title ?? "",
    location: property.location ?? "",
    building: property.building ?? "",
    property_type: property.property_type ?? "",
    listing_type: property.listing_type ?? "outright",
    price: property.price != null ? String(property.price) : "",
    status: property.status ?? "available",
    bhk: property.bhk != null ? String(property.bhk) : "",
    area_sqft: property.area_sqft != null ? String(property.area_sqft) : "",
    furnishing: property.furnishing ?? "",
    contact_name: property.contact_name ?? "",
    contact_phone: property.contact_phone ?? "",
    review_state: property.review_state ?? "",
  });

  function set<K extends keyof typeof form>(key: K, value: string) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  async function save() {
    setBusy(true);
    setError(null);

    const num = (v: string) => (v === "" ? null : Number(v));
    const body: Record<string, unknown> = {
      title: form.title.trim() || null,
      location: form.location.trim(),
      building: form.building.trim() || null,
      property_type: form.property_type || null,
      listing_type: form.listing_type,
      price: num(form.price),
      status: form.status,
      bhk: num(form.bhk),
      area_sqft: num(form.area_sqft),
      furnishing: form.furnishing.trim() || null,
      contact_name: form.contact_name.trim() || null,
      contact_phone: form.contact_phone.trim() || null,
    };
    // Only sent for ingested listings; a manually added one has no review state
    // and should not acquire one just by being edited.
    if (form.review_state) body.review_state = form.review_state;

    const res = await fetch(`/api/crm/properties/${property.id}`, {
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

  const ingested = property.source === "whatsapp_group";

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
        Edit listing
      </button>

      <Sheet
        open={open}
        onClose={() => setOpen(false)}
        title="Edit listing"
        subtitle={property.title ?? property.location}
      >
        <div className="space-y-3">
          <Field label="Title" value={form.title} onChange={(v) => set("title", v)} />

          <div className="grid grid-cols-2 gap-3">
            <Field label="Locality" value={form.location} onChange={(v) => set("location", v)} />
            <Field label="Building" value={form.building} onChange={(v) => set("building", v)} />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <Select
              label="Type"
              value={form.property_type}
              onChange={(v) => set("property_type", v)}
              options={PROPERTY_TYPES.map((t) => ({
                value: t,
                label: t.charAt(0).toUpperCase() + t.slice(1),
              }))}
              allowEmpty
            />
            <Select
              label="Rent or sale"
              value={form.listing_type}
              onChange={(v) => set("listing_type", v)}
              options={LISTING_TYPES}
            />
          </div>

          <Field
            label="Price (₹)"
            value={form.price}
            onChange={(v) => set("price", v)}
            inputMode="numeric"
            hint="Whole rupees — 13500000 for 1.35 Cr"
          />

          <div className="grid grid-cols-2 gap-3">
            <Field
              label="BHK"
              value={form.bhk}
              onChange={(v) => set("bhk", v)}
              inputMode="numeric"
            />
            <Field
              label="Area (sqft)"
              value={form.area_sqft}
              onChange={(v) => set("area_sqft", v)}
              inputMode="numeric"
            />
          </div>

          <Field
            label="Furnishing"
            value={form.furnishing}
            onChange={(v) => set("furnishing", v)}
            hint="furnished / semi furnished / unfurnished"
          />

          <div className="grid grid-cols-2 gap-3">
            <Field
              label="Contact name"
              value={form.contact_name}
              onChange={(v) => set("contact_name", v)}
            />
            <Field
              label="Contact phone"
              value={form.contact_phone}
              onChange={(v) => set("contact_phone", v)}
              inputMode="tel"
            />
          </div>

          <Select
            label="Status"
            value={form.status}
            onChange={(v) => set("status", v)}
            options={STATUSES}
          />

          {ingested && (
            <Select
              label="Review"
              value={form.review_state}
              onChange={(v) => set("review_state", v)}
              options={REVIEW_STATES}
              allowEmpty
            />
          )}

          {ingested && (
            <p className="text-[11px] leading-relaxed text-slate">
              Read out of a WhatsApp message. Your corrections replace the
              extracted values; the original message is kept as it was.
            </p>
          )}

          {error && (
            <p role="alert" className="rounded-tile bg-signal-soft px-4 py-2.5 text-sm text-signal">
              {error}
            </p>
          )}

          <button
            type="button"
            onClick={save}
            disabled={busy || !form.location.trim()}
            className="tap w-full rounded-pill bg-sandstone px-5 text-[15px] font-semibold text-white disabled:opacity-50"
          >
            {busy ? "Saving…" : "Save changes"}
          </button>
        </div>
      </Sheet>
    </>
  );
}
