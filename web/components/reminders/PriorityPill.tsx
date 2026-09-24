import { StatusPill } from "@/components/ui";
import type { ReminderPriority } from "@/lib/types";

/** Only the exceptions get a pill; "normal" is the unmarked default. */
export function PriorityPill({ priority }: { priority: ReminderPriority }) {
  if (priority === "high") return <StatusPill label="High" tone="signal" />;
  if (priority === "low") return <StatusPill label="Low" tone="neutral" />;
  return null;
}
