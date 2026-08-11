import { Card, SectionHeading, StatusPill } from "@/components/ui";
import { relativeTime } from "@/lib/format";
import type { Property, PropertySource } from "@/lib/types";

/**
 * Where a WhatsApp-sourced listing came from, and how often it has resurfaced.
 *
 * This is the visible half of dedup. Merging a repost into an existing row
 * would otherwise be invisible and slightly untrustworthy — an agent has no
 * way to know whether the price they are quoting came from one broker or six.
 * Showing every sighting makes the merge auditable, and the raw message means
 * a suspect extraction can always be checked against what was actually posted.
 *
 * The repost count is also a genuine trading signal: a flat six brokers are
 * pushing in a fortnight is usually stale, overpriced, or distressed.
 */
export function ListingProvenance({
  property,
  sources,
}: {
  property: Property;
  sources: PropertySource[];
}) {
  if (property.source !== "whatsapp_group") return null;

  const reposts = sources.filter((s) => s.relation === "duplicate").length;

  return (
    <Card className="p-5">
      <SectionHeading
        title="Where this came from"
        hint={
          reposts > 0
            ? `Seen ${sources.length} times across your groups`
            : "Sourced automatically from WhatsApp"
        }
        action={
          property.review_state === "needs_review" ? (
            <StatusPill label="Unverified" tone="signal" />
          ) : undefined
        }
      />

      {property.review_state === "needs_review" && (
        <p className="mb-3 rounded-tile bg-signal-soft px-3.5 py-2.5 text-xs leading-relaxed text-signal">
          The extractor was unsure about this one. Check the original message
          below before quoting it to a client.
        </p>
      )}

      {sources.length === 0 ? (
        <p className="text-sm text-slate">
          No message history recorded for this listing.
        </p>
      ) : (
        <ul className="space-y-2.5">
          {sources.map((source) => (
            <li
              key={source.id}
              className="rounded-tile border border-hairline bg-parchment px-3.5 py-3"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="truncate text-xs font-semibold text-ink">
                    {source.posted_by_name ?? "Unknown broker"}
                    {source.posted_by_phone && (
                      <span className="tabular font-normal text-slate">
                        {" "}
                        · {source.posted_by_phone}
                      </span>
                    )}
                  </p>
                  <p className="tabular text-[11px] text-slate">
                    {source.group_name ?? "—"} · {relativeTime(source.seen_at)}
                  </p>
                </div>
                <StatusPill
                  label={source.relation === "origin" ? "First seen" : "Repost"}
                  tone={source.relation === "origin" ? "positive" : "neutral"}
                />
              </div>
              {source.raw_message && (
                <p className="mt-2 whitespace-pre-wrap border-t border-hairline pt-2 text-[11px] leading-relaxed text-slate">
                  {source.raw_message}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}

      {property.contact_phone && (
        <a
          href={`tel:${property.contact_phone}`}
          className="tap mt-4 flex items-center justify-center gap-2 rounded-pill bg-teal px-5 text-sm font-semibold text-white"
        >
          <span className="tabular">
            Call {property.contact_name ?? "the broker"} · {property.contact_phone}
          </span>
        </a>
      )}
    </Card>
  );
}
