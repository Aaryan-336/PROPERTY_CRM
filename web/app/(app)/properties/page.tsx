import Link from "next/link";

import { FilterBar } from "@/components/FilterBar";
import { Pagination } from "@/components/Pagination";
import { PlusIcon } from "@/components/icons";
import { Card, EmptyState, StatusPill, type Tone } from "@/components/ui";
import { api, qs } from "@/lib/api";
import { money, relativeTime, titleCase } from "@/lib/format";
import { getCurrentUser } from "@/lib/session";
import type { Paged, Property } from "@/lib/types";

export const metadata = { title: "Inventory · Balaji CRM" };

const STATUS_TONE: Record<string, Tone> = {
  available: "positive",
  blocked: "warning",
  sold: "neutral",
};

export default async function PropertiesPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const params = await searchParams;
  const user = await getCurrentUser();
  const limit = 25;
  const offset = Number(params.offset ?? 0);

  const properties = await api<Paged<Property>>(
    `/properties${qs({
      limit,
      offset,
      q: params.q,
      listing_type: params.listing_type,
      property_type: params.property_type,
      status: params.status,
      min_price: params.min_price,
      max_price: params.max_price,
      bhk: params.bhk,
      source: params.source,
    })}`,
  );

  const canAdd = user?.role === "owner" || user?.role === "agent";

  return (
    <div>
      <header className="mb-4 flex items-end justify-between gap-4">
        <div>
          <h1 className="font-display text-2xl leading-tight text-ink">Inventory</h1>
          <p className="tabular mt-0.5 text-sm text-slate">
            {properties.total} listings
          </p>
        </div>
        {canAdd && (
          <Link
            href="/properties/new"
            className="tap flex items-center gap-2 rounded-pill bg-ink px-4 text-sm font-semibold text-white"
          >
            <PlusIcon className="h-4 w-4" />
            <span className="hidden sm:inline">Add listing</span>
          </Link>
        )}
      </header>

      <FilterBar
        searchPlaceholder="Search building or locality"
        selects={[
          {
            name: "listing_type",
            label: "Rent / Sale",
            options: [
              { value: "rent", label: "Rent" },
              { value: "outright", label: "Outright" },
            ],
          },
          {
            name: "bhk",
            label: "BHK",
            options: [
              { value: "1", label: "1 BHK" },
              { value: "2", label: "2 BHK" },
              { value: "3", label: "3 BHK" },
              { value: "4", label: "4+ BHK" },
            ],
          },
          {
            // Lets an agent separate the firm's own curated listings from the
            // WhatsApp firehose when they want only one or the other.
            name: "source",
            label: "Source",
            options: [
              { value: "whatsapp_group", label: "From WhatsApp" },
              { value: "manual", label: "Added by us" },
            ],
          },
          {
            name: "property_type",
            label: "Type",
            options: [
              { value: "apartment", label: "Apartment" },
              { value: "villa", label: "Villa" },
              { value: "plot", label: "Plot" },
              { value: "commercial", label: "Commercial" },
            ],
          },
          {
            name: "status",
            label: "Status",
            options: [
              { value: "available", label: "Available" },
              { value: "blocked", label: "Blocked" },
              { value: "sold", label: "Sold" },
            ],
          },
        ]}
      />

      {properties.items.length === 0 ? (
        <EmptyState
          title="No listings match these filters. Clear them, or add the listing you're working with."
          action={
            canAdd ? (
              <Link
                href="/properties/new"
                className="tap inline-flex items-center rounded-pill bg-ink px-5 text-sm font-semibold text-white"
              >
                Add a listing
              </Link>
            ) : undefined
          }
        />
      ) : (
        <>
          <div className="grid gap-2.5 lg:hidden">
            {properties.items.map((property) => (
              <Link key={property.id} href={`/properties/${property.id}`}>
                <Card className="p-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-[15px] font-semibold text-ink">
                        {property.title ?? property.building ?? "Listing"}
                      </p>
                      <p className="mt-0.5 truncate text-xs text-slate">
                        {property.bhk !== null ? `${property.bhk}BHK · ` : ""}
                        {property.building ? `${property.building} · ` : ""}
                        {property.location}
                        {property.area_sqft ? ` · ${property.area_sqft} sqft` : ""}
                      </p>
                    </div>
                    <StatusPill
                      label={titleCase(property.status ?? "available")}
                      tone={STATUS_TONE[property.status ?? "available"] ?? "neutral"}
                    />
                  </div>
                  <div className="mt-3 flex items-center justify-between border-t border-hairline pt-3">
                    <span className="tabular font-display text-lg text-ink">
                      {money(property.price)}
                    </span>
                    <div className="flex items-center gap-1.5">
                      {/* Where a listing came from changes how an agent treats
                          it: a WhatsApp listing is someone else's flat, and a
                          heavily reposted one is usually stale. */}
                      {property.source === "whatsapp_group" && (
                        <StatusPill
                          label={
                            property.sighting_count && property.sighting_count > 1
                              ? `${property.sighting_count}× posted`
                              : "WhatsApp"
                          }
                          tone="positive"
                        />
                      )}
                      {property.review_state === "needs_review" && (
                        <StatusPill label="Unverified" tone="signal" />
                      )}
                      <StatusPill
                        label={property.listing_type === "rent" ? "Rent" : "Outright"}
                        tone="neutral"
                      />
                    </div>
                  </div>
                </Card>
              </Link>
            ))}
          </div>

          <Card className="hidden overflow-hidden lg:block">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-hairline bg-parchment text-left">
                  {["Listing", "Building", "Location", "Config", "Rent / Sale", "Price", "Source", "Status", "Added"].map(
                    (heading) => (
                      <th
                        key={heading}
                        className="px-4 py-2.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-slate"
                      >
                        {heading}
                      </th>
                    ),
                  )}
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {properties.items.map((property) => (
                  <tr key={property.id} className="hover:bg-parchment/60">
                    <td className="px-4 py-2.5">
                      <Link
                        href={`/properties/${property.id}`}
                        className="font-semibold text-ink hover:text-sandstone-deep"
                      >
                        {property.title ?? "Listing"}
                      </Link>
                    </td>
                    <td className="px-4 py-2.5 text-slate">{property.building ?? "—"}</td>
                    <td className="px-4 py-2.5 text-slate">{property.location}</td>
                    <td className="tabular px-4 py-2.5 text-slate">
                      {property.bhk !== null ? `${property.bhk}BHK` : (property.property_type ? titleCase(property.property_type) : "—")}
                      {property.area_sqft ? ` · ${property.area_sqft} sqft` : ""}
                    </td>
                    <td className="px-4 py-2.5 text-slate">
                      {property.listing_type === "rent" ? "Rent" : "Outright"}
                    </td>
                    <td className="tabular px-4 py-2.5 font-semibold text-ink">
                      {money(property.price)}
                    </td>
                    <td className="px-4 py-2.5 text-xs text-slate">
                      {property.source === "whatsapp_group" ? (
                        <span title={property.source_group ?? undefined}>
                          {property.source_group ?? "WhatsApp"}
                          {property.sighting_count && property.sighting_count > 1
                            ? ` (${property.sighting_count}×)`
                            : ""}
                        </span>
                      ) : (
                        (property.posted_by_name ?? "Manual")
                      )}
                    </td>
                    <td className="px-4 py-2.5">
                      <StatusPill
                        label={titleCase(property.status ?? "available")}
                        tone={STATUS_TONE[property.status ?? "available"] ?? "neutral"}
                      />
                    </td>
                    <td className="tabular px-4 py-2.5 text-slate">
                      {relativeTime(property.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>

          <Pagination
            total={properties.total}
            limit={properties.limit}
            offset={properties.offset}
          />
        </>
      )}
    </div>
  );
}
