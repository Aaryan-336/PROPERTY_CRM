import Link from "next/link";

import { JourneyTimeline, type JourneyNode } from "@/components/JourneyTimeline";
import { StatusPill } from "@/components/ui";
import { interestLabel } from "@/lib/format";
import type { Showing } from "@/lib/types";

const LEVEL_STATE: Record<string, JourneyNode["state"]> = {
  inquired: "upcoming",
  site_visit_scheduled: "current",
  site_visit_done: "done",
  negotiating: "done",
};

/**
 * "Who showed what to whom", as a timeline rather than a data dump.
 *
 * Each node answers all three parts of the question in one line: the agent,
 * the client, the property, and when.
 */
export function ShowingsTimeline({
  showings,
  hideAgent = false,
  ink = false,
}: {
  showings: Showing[];
  hideAgent?: boolean;
  ink?: boolean;
}) {
  const nodes: JourneyNode[] = showings.map((s, index) => ({
    id: `${s.contact_id}-${s.property_id}-${s.shown_at}-${index}`,
    title: `${s.property_title ?? "Property"} → ${s.contact_name ?? "Client"}`,
    detail: s.property_location,
    actor: hideAgent ? null : s.shown_by_name,
    at: s.shown_at,
    state: LEVEL_STATE[s.interest_level ?? ""] ?? "current",
    meta: (
      <div className="flex flex-wrap items-center gap-2">
        <StatusPill
          label={interestLabel(s.interest_level)}
          tone={s.interest_level === "negotiating" ? "sand" : "neutral"}
        />
        <Link
          href={`/contacts/${s.contact_id}`}
          className="text-[11px] font-semibold text-sandstone-deep underline-offset-2 hover:underline"
        >
          Open lead
        </Link>
      </div>
    ),
  }));

  return (
    <JourneyTimeline
      nodes={nodes}
      variant={ink ? "ink" : "light"}
      showDayStamps
      emptyMessage="No showings recorded yet."
    />
  );
}
