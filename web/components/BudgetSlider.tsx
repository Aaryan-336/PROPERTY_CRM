"use client";

import { BUDGET_STEPS, budgetIndex, budgetStepLabel } from "@/lib/budget";

/**
 * Pick a budget range off the ladder instead of typing rupees.
 *
 * Two separate sliders rather than one dual-thumb track. A dual-thumb control
 * has two hit targets a few pixels apart at the bottom of the range, which on a
 * phone means grabbing the wrong one and dragging someone's floor to where
 * their ceiling was. Two labelled tracks cost one extra row and are unambiguous
 * under a thumb.
 *
 * Either end may be left unset — a lead who says "at least 2Cr" and refuses to
 * name a ceiling is a real lead, and forcing an invented ceiling on them would
 * make the matcher hide everything above it. Index 0 on either track means
 * "not stated" and is saved as null.
 */
export function BudgetSlider({
  min,
  max,
  onChange,
}: {
  /** Rupee figures as stored — string from the API, "" when unset. */
  min: string | number | null;
  max: string | number | null;
  onChange: (next: { min: number | null; max: number | null }) => void;
}) {
  const from = budgetIndex(min);
  const to = budgetIndex(max);
  const last = BUDGET_STEPS.length - 1;

  function emit(nextFrom: number, nextTo: number) {
    onChange({
      min: nextFrom === 0 ? null : BUDGET_STEPS[nextFrom],
      max: nextTo === 0 ? null : BUDGET_STEPS[nextTo],
    });
  }

  // Only clamp when both ends are actually stated. Nudging an unset ceiling
  // upward the moment someone touches the floor would silently invent a number
  // nobody said.
  function setFrom(next: number) {
    emit(next, to !== 0 && next > to ? next : to);
  }

  function setTo(next: number) {
    emit(from !== 0 && next !== 0 && next < from ? next : from, next);
  }

  return (
    <fieldset>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <legend className="text-xs font-semibold text-slate">Budget</legend>
        <span className="tabular text-sm font-semibold text-ink">
          {readout(from, to)}
        </span>
      </div>

      <div className="space-y-3 rounded-tile border border-hairline bg-card px-4 py-3.5">
        <Track
          label="From"
          value={from}
          max={last}
          onChange={setFrom}
          display={budgetStepLabel(from, "No minimum")}
        />
        <Track
          label="Up to"
          value={to}
          max={last}
          onChange={setTo}
          display={budgetStepLabel(to, "No maximum")}
        />
      </div>

      {(from !== 0 || to !== 0) && (
        <button
          type="button"
          onClick={() => emit(0, 0)}
          className="mt-1.5 text-[11px] font-semibold text-sandstone-deep"
        >
          Clear budget
        </button>
      )}
    </fieldset>
  );
}

function Track({
  label,
  value,
  max,
  onChange,
  display,
}: {
  label: string;
  value: number;
  max: number;
  onChange: (next: number) => void;
  display: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 flex items-baseline justify-between gap-3">
        <span className="text-[11px] font-semibold uppercase tracking-[0.1em] text-slate">
          {label}
        </span>
        <span className="tabular text-sm text-ink">{display}</span>
      </span>
      <input
        type="range"
        min={0}
        max={max}
        step={1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-label={`Budget ${label.toLowerCase()}`}
        aria-valuetext={display}
        className="budget-slider w-full"
      />
    </label>
  );
}

function readout(from: number, to: number): string {
  if (!from && !to) return "Not set";
  if (from && !to) return `${budgetStepLabel(from)} and above`;
  if (!from && to) return `Up to ${budgetStepLabel(to)}`;
  return `${budgetStepLabel(from)} – ${budgetStepLabel(to)}`;
}
