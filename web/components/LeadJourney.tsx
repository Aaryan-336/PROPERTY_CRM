import { JourneyTimeline, type JourneyNode } from "@/components/JourneyTimeline";
import { StatusPill, TEMPERATURE_TONE } from "@/components/ui";
import { outcomeLabel, stageLabel } from "@/lib/format";
import { STAGES, type Activity, type CallLog, type Contact, type Task } from "@/lib/types";

/**
 * A lead's journey: the pipeline it has reached, then everything that actually
 * happened, newest first.
 *
 * The pipeline strip answers "where is this now"; the event list answers "who
 * touched it". Both are the same checkpoint vocabulary, which is the point.
 */
export function LeadJourney({
  contact,
  calls,
  activities,
  tasks,
}: {
  contact: Contact;
  calls: CallLog[];
  activities: Activity[];
  tasks: Task[];
}) {
  const events: JourneyNode[] = [];

  for (const call of calls) {
    events.push({
      id: `call-${call.id}`,
      title: `Call — ${outcomeLabel(call.outcome)}`,
      detail: call.notes,
      actor: call.caller_name,
      at: call.created_at,
      state: call.flagged_for_owner
        ? "signal"
        : ["connected", "interested"].includes(call.outcome)
          ? "done"
          : "current",
      meta:
        call.temperature || call.flagged_for_owner ? (
          <div className="flex flex-wrap gap-1.5">
            {call.temperature && (
              <StatusPill
                label={call.temperature.toUpperCase()}
                tone={TEMPERATURE_TONE[call.temperature] ?? "neutral"}
              />
            )}
            {call.flagged_for_owner && (
              <StatusPill label="Escalated to owner" tone="signal" />
            )}
          </div>
        ) : undefined,
    });
  }

  for (const activity of activities) {
    events.push({
      id: `activity-${activity.id}`,
      title:
        activity.type === "site_visit"
          ? "Site visit"
          : activity.type === "stage_change"
            ? "Stage changed"
            : activity.type === "follow_up"
              ? "Follow-up"
              : "Note",
      detail: activity.body,
      actor: activity.user_name,
      at: activity.occurred_at,
      state: activity.type === "site_visit" ? "done" : "current",
    });
  }

  for (const task of tasks) {
    events.push({
      id: `task-${task.id}`,
      title: task.title,
      detail: "Follow-up reminder",
      actor: task.assigned_to_name,
      at: task.due_at,
      state: "upcoming",
    });
  }

  events.sort(
    (a, b) => new Date(b.at ?? 0).getTime() - new Date(a.at ?? 0).getTime(),
  );

  return (
    <div className="space-y-5">
      <PipelineStrip stage={contact.stage} />
      <div className="border-t border-hairline pt-4">
        <JourneyTimeline
          nodes={events}
          showDayStamps
          emptyMessage="Nothing logged on this lead yet. Log a call or a site visit to start the trail."
        />
      </div>
    </div>
  );
}

const PIPELINE = STAGES.filter((s) => s.value !== "lost");

/** New → Contacted → Visit → Visited → Negotiating → Closed, as checkpoints. */
function PipelineStrip({ stage }: { stage: string | null }) {
  if (stage === "lost") {
    return (
      <div className="rounded-tile bg-signal-soft px-4 py-3">
        <StatusPill label="Lost" tone="signal" />
        <p className="mt-1.5 text-xs text-signal">
          This lead was marked lost and has left the pipeline.
        </p>
      </div>
    );
  }

  const index = PIPELINE.findIndex((s) => s.value === (stage ?? "new"));

  return (
    <div>
      <p className="mb-2.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate">
        Pipeline · {stageLabel(stage)}
      </p>
      <ol className="flex items-center gap-1">
        {PIPELINE.map((step, i) => {
          const done = i < index;
          const current = i === index;
          return (
            <li key={step.value} className="flex flex-1 flex-col gap-1.5">
              <span
                className={`h-1.5 rounded-pill ${
                  done ? "bg-teal" : current ? "bg-sandstone" : "bg-hairline"
                }`}
              />
              <span
                className={`text-[9px] font-semibold uppercase leading-tight tracking-[0.04em] ${
                  current ? "text-sandstone-deep" : done ? "text-teal" : "text-slate opacity-60"
                }`}
              >
                {step.label}
              </span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
