import type { ReactNode } from "react";

import { initials } from "@/lib/format";

/* -------------------------------------------------------------------------
   Status pills.
   DESIGN_RULES.md: status is always colour *and* label, never colour alone —
   colourblind-safe, and the label is what gets read at a glance in sun glare.
------------------------------------------------------------------------- */

export type Tone = "neutral" | "positive" | "warning" | "signal" | "ink" | "sand";

const TONES: Record<Tone, string> = {
  neutral: "bg-parchment-deep text-slate",
  positive: "bg-teal-soft text-teal",
  warning: "bg-sandstone-soft text-sandstone-deep",
  signal: "bg-signal-soft text-signal",
  ink: "bg-ink text-white",
  sand: "bg-sandstone text-white",
};

export function StatusPill({
  label,
  tone = "neutral",
  className = "",
}: {
  label: string;
  tone?: Tone;
  className?: string;
}) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-pill px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.06em] ${TONES[tone]} ${className}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current opacity-70" aria-hidden />
      {label}
    </span>
  );
}

export const STAGE_TONE: Record<string, Tone> = {
  new: "neutral",
  contacted: "warning",
  site_visit_scheduled: "warning",
  visited: "positive",
  negotiating: "sand",
  closed: "positive",
  lost: "signal",
};

export const OUTCOME_TONE: Record<string, Tone> = {
  connected: "positive",
  interested: "positive",
  callback_requested: "warning",
  not_reachable: "neutral",
  not_interested: "signal",
  wrong_number: "signal",
};

export const TEMPERATURE_TONE: Record<string, Tone> = {
  hot: "signal",
  warm: "warning",
  cold: "neutral",
};

/* -------------------------------------------------------------- skeletons */

/**
 * A placeholder with the shape of the thing that is coming.
 *
 * The API is on a free tier that sleeps, so the gap between a tap and a screen
 * is sometimes seconds. A spinner in the middle of an empty page says only
 * "wait"; a block where the row will be says "a row is coming, this many of
 * them, about this wide" -- and because the layout does not change when the
 * data lands, the screen resolves instead of reflowing.
 */
export function Skeleton({
  className = "",
  width,
}: {
  className?: string;
  width?: string;
}) {
  return (
    <span
      aria-hidden
      className={`skeleton block h-3.5 ${className}`}
      style={width ? { width } : undefined}
    />
  );
}

/** A stand-in for one list row, matched to the real row's height and rhythm. */
export function SkeletonRow() {
  return (
    <div className="rounded-card border border-hairline bg-card p-4">
      <div className="flex items-center gap-3">
        <span className="skeleton h-10 w-10 shrink-0 rounded-full" aria-hidden />
        <div className="min-w-0 flex-1 space-y-2">
          <Skeleton width="55%" />
          <Skeleton className="h-3" width="35%" />
        </div>
        <span className="skeleton h-6 w-16 shrink-0 rounded-pill" aria-hidden />
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ cards */

export function Card({
  children,
  className = "",
  as: Tag = "div",
}: {
  children: ReactNode;
  className?: string;
  as?: "div" | "section" | "article" | "li";
}) {
  return (
    <Tag
      className={`rounded-card border border-hairline bg-card shadow-card ${className}`}
    >
      {children}
    </Tag>
  );
}

/**
 * The Ink surface, reserved for what the owner most needs to trust: the day's
 * hero summary, the escalation inbox, audit-adjacent UI. Using it for routine
 * browsing would flatten the "this matters / this is routine" read that a
 * white-everywhere dashboard cannot give you.
 */
export function InkCard({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`rounded-card bg-ink text-white shadow-ink ${className}`}
    >
      {children}
    </div>
  );
}

export function SectionHeading({
  title,
  action,
  hint,
  ink = false,
}: {
  title: string;
  action?: ReactNode;
  hint?: string;
  ink?: boolean;
}) {
  return (
    /* `min-w-0` on the text column and `shrink-0` on the action: without them
       a long hint pushes the action ("See all", "Filter") past the card edge
       and it gets clipped on a phone. The text truncates instead. */
    <div className="mb-3 flex items-end justify-between gap-3">
      <div className="min-w-0">
        <h2
          className={`font-display text-[17px] leading-tight ${ink ? "text-white" : "text-ink"}`}
        >
          {title}
        </h2>
        {hint && (
          <p className={`mt-0.5 text-xs ${ink ? "text-ink-muted" : "text-slate"}`}>
            {hint}
          </p>
        )}
      </div>
      {action && <div className="shrink-0">{action}</div>}
    </div>
  );
}

/* ---------------------------------------------------------------- avatars */

const AVATAR_COLORS = [
  "bg-teal text-white",
  "bg-sandstone text-white",
  "bg-ink text-white",
  "bg-signal text-white",
  "bg-slate text-white",
];

export function Avatar({
  name,
  size = "md",
  id,
  onInk = false,
}: {
  name: string | null | undefined;
  size?: "sm" | "md";
  id?: number | null;
  /** Set when the avatar sits on an Ink surface, so the separating ring
   *  matches the card instead of drawing a white halo around it. */
  onInk?: boolean;
}) {
  const dimension = size === "sm" ? "h-7 w-7 text-[10px]" : "h-8 w-8 text-[11px]";
  const color = AVATAR_COLORS[(id ?? name?.length ?? 0) % AVATAR_COLORS.length];
  return (
    <span
      title={name ?? undefined}
      className={`inline-flex ${dimension} shrink-0 items-center justify-center rounded-full font-semibold ring-2 ${
        onInk ? "ring-ink" : "ring-card"
      } ${color}`}
    >
      {initials(name)}
    </span>
  );
}

/** Small overlapping stack for anything team-visible.
 *
 *  Overlap is 4px, not 8px: at 8px a 28px circle leaves too little of the
 *  neighbour visible and two-letter initials get clipped by the one in front,
 *  which reads as broken rather than as a stack. */
export function AvatarStack({
  people,
  max = 4,
  onInk = false,
}: {
  people: { id?: number | null; name: string | null }[];
  max?: number;
  onInk?: boolean;
}) {
  const shown = people.slice(0, max);
  const extra = people.length - shown.length;
  return (
    <div className="flex items-center">
      <div className="flex -space-x-1">
        {shown.map((p, i) => (
          <Avatar
            key={`${p.id ?? p.name}-${i}`}
            name={p.name}
            id={p.id}
            size="sm"
            onInk={onInk}
          />
        ))}
      </div>
      {extra > 0 && (
        <span
          className={`tabular ml-2 text-xs ${onInk ? "text-ink-muted" : "text-slate"}`}
        >
          +{extra}
        </span>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ empty state */

/** Empty states say what to do next — a blank screen teaches nothing. */
export function EmptyState({
  title,
  action,
  icon,
}: {
  title: string;
  action?: ReactNode;
  icon?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center rounded-card border border-dashed border-hairline bg-card/60 px-6 py-10 text-center">
      {icon && <div className="mb-3 text-slate opacity-60">{icon}</div>}
      <p className="max-w-xs text-sm text-slate">{title}</p>
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function MetricTile({
  label,
  value,
  sub,
  ink = false,
}: {
  label: string;
  value: string | number;
  sub?: string;
  ink?: boolean;
}) {
  return (
    /* Padding and tracking tighten on the narrowest screens. At 390px a
       three-up grid gives each tile ~106px, and the roomier desktop values
       push labels like "FOLLOW-UPS" onto a second line, splitting them at the
       hyphen — which reads as a layout bug rather than a label. */
    <div
      className={`rounded-tile px-3 py-3 sm:px-4 ${ink ? "bg-ink-soft" : "border border-hairline bg-card"}`}
    >
      {/* A three-up grid on a 390px phone leaves ~75px for the label, and
          longer ones ("Active leads", "Follow-ups") genuinely need two lines.
          Rather than fight that, reserve both lines on small screens so the
          numbers underneath still align across tiles — a ragged baseline is
          what actually reads as broken, not the wrap itself. */}
      <p
        className={`block min-h-[2.3em] text-[10px] font-semibold uppercase leading-[1.15] tracking-[0.08em] sm:min-h-0 sm:leading-normal sm:tracking-[0.14em] ${ink ? "text-ink-muted" : "text-slate"}`}
      >
        {label}
      </p>
      <p
        className={`font-display mt-1 text-2xl leading-none ${ink ? "text-white" : "text-ink"}`}
      >
        {value}
      </p>
      {sub && (
        <p className={`mt-1 text-xs ${ink ? "text-ink-dim" : "text-slate"}`}>{sub}</p>
      )}
    </div>
  );
}

/** Shown wherever a value was withheld, so staff know why rather than assuming a bug. */
export function MaskedHint({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1 text-xs text-slate">
      <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" aria-hidden>
        <path
          d="M12 15v2m-6 4h12a2 2 0 0 0 2-2v-6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v6a2 2 0 0 0 2 2Zm10-10V7a4 4 0 0 0-8 0v4"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      {children}
    </span>
  );
}
