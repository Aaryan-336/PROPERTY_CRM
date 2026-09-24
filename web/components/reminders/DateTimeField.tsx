"use client";

import { useRef } from "react";

import { inputClass } from "@/components/forms";

/** `datetime-local` speaks local wall time with no zone. */
export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Date(d.getTime() - d.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export function fromLocalInput(value: string): string | null {
  if (!value) return null;
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
}

function at(daysAhead: number, hour: number): Date {
  const d = new Date();
  d.setDate(d.getDate() + daysAhead);
  d.setHours(hour, 0, 0, 0);
  return d;
}

function readable(value: string): string {
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date();
  const tomorrow = at(1, 0);
  const sameDay = (a: Date, b: Date) => a.toDateString() === b.toDateString();
  const day = sameDay(d, today)
    ? "Today"
    : sameDay(d, tomorrow)
      ? "Tomorrow"
      : d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
  return `${day}, ${d.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit" })}`;
}

/**
 * Date and time for a reminder: one-tap presets for the times people actually
 * say ("in an hour", "this evening", "tomorrow morning"), the native picker
 * for anything else, and the chosen moment read back in words -- the bare
 * browser control shows `mm/dd/yyyy, --:--`, which reads as broken.
 */
export function DateTimeField({
  value,
  onChange,
  allowNone = true,
}: {
  value: string;
  onChange: (value: string) => void;
  allowNone?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const now = new Date();
  const inAnHour = new Date(now.getTime() + 60 * 60_000);
  inAnHour.setSeconds(0, 0);
  const presets: { label: string; date: Date }[] = [
    { label: "In 1 hour", date: inAnHour },
    ...(now.getHours() < 18 ? [{ label: "This evening", date: at(0, 18) }] : []),
    { label: "Tomorrow 10 am", date: at(1, 10) },
  ];
  const presetValues = presets.map((p) => toLocalInput(p.date.toISOString()));
  const custom = !!value && !presetValues.includes(value);

  function pick() {
    if (!value) onChange(toLocalInput(at(1, 10).toISOString()));
    // Open the native picker once the input has rendered.
    setTimeout(() => {
      try {
        input.current?.showPicker?.();
      } catch {
        input.current?.focus();
      }
    }, 0);
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {presets.map(({ label, date }) => {
          const v = toLocalInput(date.toISOString());
          const selected = v === value;
          return (
            <Chip key={label} selected={selected} onClick={() => onChange(v)}>
              {label}
            </Chip>
          );
        })}
        <Chip selected={custom} onClick={pick}>
          Pick date…
        </Chip>
        {allowNone && (
          <Chip selected={!value} onClick={() => onChange("")}>
            No time
          </Chip>
        )}
      </div>
      {value && (
        <input
          ref={input}
          type="datetime-local"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          aria-label="Date and time"
          className={`${inputClass} tabular min-h-[44px] appearance-none text-left [&::-webkit-date-and-time-value]:text-left`}
        />
      )}
      <p className="text-[11px] text-slate">
        {!value
          ? "No time set — it stays on your list without a notification."
          : new Date(value).getTime() <= now.getTime()
            ? "That time has already passed — pick a later one to be notified."
            : `Reminds you ${readable(value)}.`}
      </p>
    </div>
  );
}

function Chip({
  selected,
  onClick,
  children,
}: {
  selected: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={`press rounded-pill border px-3 py-1.5 text-xs font-semibold transition-colors ${
        selected ? "border-ink bg-ink text-white" : "border-hairline bg-card text-ink"
      }`}
    >
      {children}
    </button>
  );
}
