import type { ReactNode } from "react";

import { clockTime, dayStamp, relativeTime } from "@/lib/format";

/**
 * The Journey Timeline — the product's signature element.
 *
 * A vertical run of circular checkpoint nodes on a connecting rail, borrowed
 * from package tracking and pointed at leads instead of parcels. It answers the
 * same question the owner actually asks: where is this thing now, and who
 * touched it. It is reused, unrotated, for a lead's pipeline progress, a
 * property's "shown to" history, and a call → follow-up → escalation chain —
 * and stays vertical on desktop, where a horizontal stepper would lose exactly
 * the legibility that makes it work.
 */

export type JourneyNode = {
  id: string;
  title: string;
  detail?: string | null;
  /** Who did it. Rendered as the attribution line — the "who" half. */
  actor?: string | null;
  at?: string | null;
  /** done = happened, current = where the lead is now, upcoming = not yet. */
  state: "done" | "current" | "upcoming" | "signal";
  icon?: ReactNode;
  meta?: ReactNode;
  href?: string;
};

const NODE_STYLES: Record<JourneyNode["state"], string> = {
  done: "bg-teal text-white border-teal",
  current: "bg-sandstone text-white border-sandstone ring-4 ring-sandstone-soft",
  upcoming: "bg-card text-slate border-hairline",
  signal: "bg-signal text-white border-signal ring-4 ring-signal-soft",
};

const NODE_STYLES_INK: Record<JourneyNode["state"], string> = {
  done: "bg-teal text-white border-teal",
  current: "bg-sandstone text-white border-sandstone ring-4 ring-sandstone/25",
  upcoming: "bg-ink-soft text-ink-muted border-ink-line",
  signal: "bg-signal text-white border-signal ring-4 ring-signal/25",
};

function CheckIcon() {
  return (
    <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" aria-hidden="true">
      <path
        d="M20 6 9 17l-5-5"
        fill="none"
        stroke="currentColor"
        strokeWidth="3.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function DotIcon() {
  return <span className="block h-2 w-2 rounded-full bg-current" aria-hidden="true" />;
}

export function JourneyTimeline({
  nodes,
  variant = "light",
  showDayStamps = false,
  emptyMessage = "Nothing logged yet.",
}: {
  nodes: JourneyNode[];
  variant?: "light" | "ink";
  showDayStamps?: boolean;
  emptyMessage?: string;
}) {
  const ink = variant === "ink";

  if (nodes.length === 0) {
    return (
      <p className={`py-6 text-sm ${ink ? "text-ink-muted" : "text-slate"}`}>
        {emptyMessage}
      </p>
    );
  }

  let lastDay = "";

  return (
    <ol className="relative">
      {nodes.map((node, index) => {
        const isLast = index === nodes.length - 1;
        const day = node.at ? dayStamp(node.at) : "";
        const showDay = showDayStamps && day && day !== lastDay;
        if (showDay) lastDay = day;

        return (
          <li key={node.id} className="relative">
            {showDay && (
              <p
                className={`tabular mb-2 ml-11 text-[11px] uppercase tracking-[0.12em] ${
                  ink ? "text-ink-muted" : "text-slate"
                }`}
              >
                {day}
              </p>
            )}

            <div className="relative flex gap-3 pb-5">
              {/* Rail. Hidden on the final node so the line ends with the journey. */}
              {!isLast && (
                <span
                  aria-hidden="true"
                  className={`absolute left-[15px] top-8 bottom-0 w-px ${
                    ink ? "journey-rail-ink" : "journey-rail"
                  }`}
                />
              )}

              <span
                className={`relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 ${
                  (ink ? NODE_STYLES_INK : NODE_STYLES)[node.state]
                }`}
              >
                {node.icon ??
                  (node.state === "done" ? <CheckIcon /> : <DotIcon />)}
              </span>

              <div className="min-w-0 flex-1 pt-0.5">
                <div className="flex items-baseline justify-between gap-3">
                  <p
                    className={`text-[15px] font-semibold leading-snug ${
                      ink ? "text-white" : "text-ink"
                    } ${node.state === "upcoming" ? "opacity-60" : ""}`}
                  >
                    {node.title}
                  </p>
                  {node.at && (
                    <time
                      dateTime={node.at}
                      title={`${dayStamp(node.at)} ${clockTime(node.at)}`}
                      className={`tabular shrink-0 text-[11px] ${
                        ink ? "text-ink-muted" : "text-slate"
                      }`}
                    >
                      {relativeTime(node.at)}
                    </time>
                  )}
                </div>

                {node.detail && (
                  <p
                    className={`mt-0.5 text-sm leading-snug ${
                      ink ? "text-ink-dim" : "text-slate"
                    }`}
                  >
                    {node.detail}
                  </p>
                )}

                {node.actor && (
                  <p
                    className={`mt-1 text-xs ${ink ? "text-ink-muted" : "text-slate"}`}
                  >
                    <span className="opacity-70">by</span> {node.actor}
                    {node.at && (
                      <>
                        <span className="opacity-70"> at </span>
                        <span className="tabular">{clockTime(node.at)}</span>
                      </>
                    )}
                  </p>
                )}

                {node.meta && <div className="mt-2">{node.meta}</div>}
              </div>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
