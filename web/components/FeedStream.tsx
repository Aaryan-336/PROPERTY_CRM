import { JourneyTimeline, type JourneyNode } from "@/components/JourneyTimeline";
import { outcomeLabel } from "@/lib/format";
import type { FeedItem } from "@/lib/types";
import { StatusPill, TEMPERATURE_TONE } from "@/components/ui";

/**
 * The live activity feed, rendered as the Journey Timeline.
 *
 * Same component as a lead's pipeline and a property's showing history — the
 * owner learns one visual language and reads all three the same way.
 */
export function FeedStream({ items }: { items: FeedItem[] }) {
  const nodes: JourneyNode[] = items.map((item, index) => ({
    id: `${item.kind}-${item.occurred_at}-${index}`,
    title: item.title,
    detail: item.detail,
    actor: item.user_name,
    at: item.occurred_at,
    state: item.flagged ? "signal" : item.tone === "positive" ? "done" : "current",
    meta:
      item.outcome || item.temperature ? (
        <div className="flex flex-wrap gap-1.5">
          {item.outcome && (
            <StatusPill
              label={outcomeLabel(item.outcome)}
              tone={item.tone === "warning" ? "signal" : "neutral"}
            />
          )}
          {item.temperature && (
            <StatusPill
              label={item.temperature.toUpperCase()}
              tone={TEMPERATURE_TONE[item.temperature] ?? "neutral"}
            />
          )}
          {item.flagged && <StatusPill label="Escalated" tone="signal" />}
        </div>
      ) : undefined,
  }));

  return (
    <JourneyTimeline
      nodes={nodes}
      showDayStamps
      emptyMessage="No activity in this period yet."
    />
  );
}
