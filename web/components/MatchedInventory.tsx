import Link from "next/link";

import { ChevronRight } from "@/components/icons";
import { Card, EmptyState, SectionHeading, StatusPill } from "@/components/ui";
import { money, relativeTime } from "@/lib/format";
import type { PropertyMatch } from "@/lib/types";

/**
 * Inventory suggested for one lead.
 *
 * The PRD's agent story is "suggest matching properties for a client's stated
 * budget/location, so I don't manually cross-reference listings". The reasons
 * are rendered next to every row on purpose: a suggestion an agent cannot
 * explain to themselves is one they will not put in front of a client, so an
 * unexplained ranking would simply go unused.
 *
 * Listings sourced from WhatsApp carry their group and repost count, because
 * "six brokers pushed this in a fortnight" is a real signal about how live the
 * listing actually is.
 */
export function MatchedInventory({ matches }: { matches: PropertyMatch[] }) {
  return (
    <Card className="p-5">
      <SectionHeading
        title="Matching inventory"
        hint="Based on this lead's budget and preferred areas"
        action={
          <Link
            href="/properties"
            className="flex items-center gap-1 text-xs font-semibold text-sandstone-deep"
          >
            All inventory
            <ChevronRight className="h-3.5 w-3.5" />
          </Link>
        }
      />

      {matches.length === 0 ? (
        <EmptyState title="Nothing in inventory fits this lead's budget and areas yet. Widen the budget on the lead, or check back as the WhatsApp feed brings new listings in." />
      ) : (
        <ul className="divide-y divide-hairline">
          {matches.map(({ property, reasons }) => (
            <li key={property.id}>
              <Link
                href={`/properties/${property.id}`}
                className="flex items-start justify-between gap-3 py-3"
              >
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-ink">
                    {property.title ??
                      `${property.bhk ? `${property.bhk}BHK` : "Listing"} in ${property.location}`}
                  </p>
                  <p className="tabular truncate text-xs text-slate">
                    {money(property.price)}
                    {property.listing_type === "rent" ? " / month" : ""}
                    {property.building ? ` · ${property.building}` : ""}
                    {property.area_sqft ? ` · ${property.area_sqft} sqft` : ""}
                  </p>
                  <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
                    {reasons.slice(0, 3).map((reason) => (
                      <span
                        key={reason}
                        className="rounded-pill bg-parchment-deep px-2 py-0.5 text-[10px] font-semibold text-slate"
                      >
                        {reason}
                      </span>
                    ))}
                    {property.source === "whatsapp_group" && (
                      <span className="rounded-pill bg-teal-soft px-2 py-0.5 text-[10px] font-semibold text-teal">
                        {property.sighting_count && property.sighting_count > 1
                          ? `Reposted ${property.sighting_count}×`
                          : "From WhatsApp"}
                      </span>
                    )}
                  </div>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  <StatusPill
                    label={property.listing_type === "rent" ? "Rent" : "Sale"}
                    tone={property.listing_type === "rent" ? "warning" : "sand"}
                  />
                  {property.last_seen_at && (
                    <span className="tabular text-[10px] text-slate">
                      {relativeTime(property.last_seen_at)}
                    </span>
                  )}
                </div>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
