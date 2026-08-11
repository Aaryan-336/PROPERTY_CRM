import Link from "next/link";
import { notFound, redirect } from "next/navigation";

import { ListingProvenance } from "@/components/ListingProvenance";
import { ShowingsTimeline } from "@/components/ShowingsTimeline";
import {
  Card,
  InkCard,
  SectionHeading,
  StatusPill,
  type Tone,
} from "@/components/ui";
import { ApiRequestError, api, apiOptional, qs } from "@/lib/api";
import { money, relativeTime, titleCase } from "@/lib/format";
import { getCurrentUser } from "@/lib/session";
import type { Paged, Property, PropertySource, Showing } from "@/lib/types";

const STATUS_TONE: Record<string, Tone> = {
  available: "positive",
  blocked: "warning",
  sold: "neutral",
};

export default async function PropertyDetail({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const user = await getCurrentUser();
  // Cold Callers have no access to the lead book or the inventory — the API
  // refuses both for this role. This redirect is a courtesy so a stale link or
  // a bookmark lands somewhere useful rather than on an error.
  if (user?.role === "cold_caller") redirect("/queue");

  let property: Property;
  try {
    property = await api<Property>(`/properties/${id}`);
  } catch (error) {
    if (error instanceof ApiRequestError && error.status === 404) notFound();
    throw error;
  }

  // Cold callers have no access to showing history at all, so the panel is
  // skipped rather than rendered empty.
  const canSeeShowings = user?.role === "owner" || user?.role === "agent";
  const [showings, sources] = await Promise.all([
    canSeeShowings
      ? api<Paged<Showing>>(
          `/property-interests${qs({ property_id: id, limit: 50 })}`,
        )
      : Promise.resolve(null),
    // Only WhatsApp-sourced listings have provenance; skipping the call for
    // manual ones avoids a pointless round trip on most of the inventory.
    property.source === "whatsapp_group"
      ? apiOptional<PropertySource[]>(`/properties/${id}/sources`)
      : Promise.resolve(null),
  ]);

  return (
    <div className="space-y-5">
      <Link
        href="/properties"
        className="inline-flex items-center gap-1 text-xs font-semibold text-slate"
      >
        ← Inventory
      </Link>

      <InkCard className="p-5 lg:p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="font-display text-2xl leading-tight text-white lg:text-3xl">
              {property.title ?? property.building ?? "Listing"}
            </h1>
            <p className="mt-1.5 text-sm text-ink-dim">
              {property.building ? `${property.building} · ` : ""}
              {property.location}
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <StatusPill
              label={titleCase(property.status ?? "available")}
              tone={STATUS_TONE[property.status ?? "available"] ?? "neutral"}
            />
            <span className="tabular font-display text-2xl text-white">
              {money(property.price)}
            </span>
          </div>
        </div>

        <dl className="mt-5 grid grid-cols-2 gap-4 border-t border-ink-line pt-4 lg:grid-cols-4">
          <Detail
            label="Rent / Sale"
            value={property.listing_type === "rent" ? "Rent" : "Outright"}
          />
          <Detail
            label="Type"
            value={property.property_type ? titleCase(property.property_type) : "—"}
          />
          {/* Extraction fills these on WhatsApp-sourced listings; a manually
              entered one leaves them null and they simply do not render. */}
          {property.bhk !== null && (
            <Detail label="Config" value={`${property.bhk} BHK`} />
          )}
          {property.area_sqft !== null && (
            <Detail label="Area" value={`${property.area_sqft} sqft`} mono />
          )}
          {property.furnishing && (
            <Detail label="Furnishing" value={titleCase(property.furnishing)} />
          )}
          <Detail
            label="Listed by"
            value={
              property.source === "whatsapp_group"
                ? (property.source_group ?? "WhatsApp group")
                : (property.posted_by_name ?? "—")
            }
          />
          <Detail label="Added" value={relativeTime(property.created_at)} mono />
        </dl>
      </InkCard>

      {sources && <ListingProvenance property={property} sources={sources} />}

      {canSeeShowings && showings && (
        <Card className="p-5">
          <SectionHeading
            title="Shown to"
            hint={
              user?.role === "owner"
                ? `${showings.total} showings across the firm`
                : `${showings.total} showings by you`
            }
          />
          <ShowingsTimeline
            showings={showings.items}
            hideAgent={user?.role !== "owner"}
          />
        </Card>
      )}
    </div>
  );
}

function Detail({
  label,
  value,
  mono = false,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <dt className="text-[10px] font-semibold uppercase tracking-[0.12em] text-ink-muted">
        {label}
      </dt>
      <dd className={`mt-1 text-sm text-white ${mono ? "tabular" : ""}`}>{value}</dd>
    </div>
  );
}
