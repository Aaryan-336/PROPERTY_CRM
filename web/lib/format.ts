import { STAGES, CALL_OUTCOMES, INTEREST_LEVELS } from "./types";

/** ₹ figures the way a Mumbai brokerage actually says them: lakh and crore. */
export function money(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = typeof value === "string" ? Number(value) : value;
  if (Number.isNaN(n)) return "—";
  if (n >= 10_000_000) return `₹${trim(n / 10_000_000)} Cr`;
  if (n >= 100_000) return `₹${trim(n / 100_000)} L`;
  if (n >= 1_000) return `₹${trim(n / 1_000)}K`;
  return `₹${n}`;
}

function trim(n: number): string {
  return n.toFixed(2).replace(/\.?0+$/, "");
}

export function budgetRange(
  min: string | null | undefined,
  max: string | null | undefined,
): string {
  if (!min && !max) return "Budget not set";
  if (min && max) return `${money(min)} – ${money(max)}`;
  return money(min ?? max);
}

export function relativeTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const then = new Date(iso).getTime();
  const diff = Date.now() - then;
  const mins = Math.round(diff / 60_000);
  if (Math.abs(mins) < 1) return "just now";
  if (mins < 0) {
    const ahead = Math.abs(mins);
    if (ahead < 60) return `in ${ahead}m`;
    if (ahead < 60 * 24) return `in ${Math.round(ahead / 60)}h`;
    return `in ${Math.round(ahead / 1440)}d`;
  }
  if (mins < 60) return `${mins}m ago`;
  if (mins < 60 * 24) return `${Math.round(mins / 60)}h ago`;
  if (mins < 60 * 24 * 7) return `${Math.round(mins / 1440)}d ago`;
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
  });
}

export function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-IN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: true,
  });
}

export function dayStamp(iso: string): string {
  return new Date(iso).toLocaleDateString("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

export function initials(name: string | null | undefined): string {
  if (!name) return "··";
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function labelFor(
  value: string | null | undefined,
  set: readonly { value: string; label: string }[],
): string {
  if (!value) return "—";
  return set.find((s) => s.value === value)?.label ?? titleCase(value);
}

export function titleCase(value: string): string {
  return value
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

export const stageLabel = (v: string | null | undefined) => labelFor(v, STAGES);
export const outcomeLabel = (v: string | null | undefined) =>
  labelFor(v, CALL_OUTCOMES);
export const interestLabel = (v: string | null | undefined) =>
  labelFor(v, INTEREST_LEVELS);

export function fullName(c: { first_name: string; last_name: string | null }) {
  return `${c.first_name} ${c.last_name ?? ""}`.trim();
}

export function roleLabel(role: string): string {
  return (
    { owner: "Owner", manager: "Manager", agent: "Agent", cold_caller: "Cold Caller" }[
      role
    ] ?? titleCase(role)
  );
}
