/**
 * The budget ladder every lead screen shares.
 *
 * Nobody in a Mumbai brokerage says "fifteen million". They say "1.5 Cr", and
 * they say it in quarter-crore jumps. Typing 15000000 into a number box invites
 * exactly one mistake -- a zero too many or too few -- and that mistake is
 * invisible until the matcher silently stops suggesting anything.
 *
 * So budgets are picked off a fixed ladder rather than typed. The rungs get
 * coarser as the figures get larger, because the difference between 40L and 50L
 * matters to a first-time buyer and the difference between 40Cr and 41Cr
 * matters to nobody. Every rung lands on a round lakh or crore, so whatever is
 * stored reads back the way it was said.
 */

function ladder(): number[] {
  const steps: number[] = [0];
  const push = (from: number, to: number, by: number) => {
    for (let n = from; n <= to; n += by) steps.push(n);
  };
  const L = 100_000;
  const CR = 10_000_000;

  push(10 * L, 1 * CR, 10 * L); // 10L → 1Cr in 10L steps
  push(1.25 * CR, 5 * CR, 25 * L); // 1.25Cr → 5Cr in 25L steps
  push(5.5 * CR, 10 * CR, 50 * L); // 5.5Cr → 10Cr in 50L steps
  push(11 * CR, 25 * CR, 1 * CR); // 11Cr → 25Cr in 1Cr steps
  push(30 * CR, 50 * CR, 5 * CR); // 30Cr → 50Cr in 5Cr steps
  return steps;
}

export const BUDGET_STEPS: readonly number[] = ladder();

export const BUDGET_MAX = BUDGET_STEPS[BUDGET_STEPS.length - 1];

/** Where a rupee figure sits on the ladder — nearest rung, never off the end. */
export function budgetIndex(value: number | string | null | undefined): number {
  if (value === null || value === undefined || value === "") return 0;
  const n = typeof value === "string" ? Number(value) : value;
  if (!Number.isFinite(n) || n <= 0) return 0;

  let best = 0;
  let bestGap = Infinity;
  for (let i = 0; i < BUDGET_STEPS.length; i += 1) {
    const gap = Math.abs(BUDGET_STEPS[i] - n);
    if (gap < bestGap) {
      bestGap = gap;
      best = i;
    }
  }
  return best;
}

/**
 * A rung, spoken the way a broker speaks it.
 *
 * Deliberately not `money()` from format.ts: that one is for figures that came
 * out of the database and may be anything, and it renders ₹90 L as "₹90 L".
 * This one is for figures that came off the ladder, where index 0 is not
 * "₹0" but "no limit stated".
 */
export function budgetStepLabel(index: number, whenZero = "Any"): string {
  const value = BUDGET_STEPS[Math.max(0, Math.min(index, BUDGET_STEPS.length - 1))];
  if (!value) return whenZero;
  if (value >= 10_000_000) return `₹${strip(value / 10_000_000)} Cr`;
  return `₹${strip(value / 100_000)} L`;
}

function strip(n: number): string {
  return n.toFixed(2).replace(/\.?0+$/, "");
}

/**
 * Bands for the leads filter, as `min-max` in rupees.
 *
 * An open top end is written `50000000-` rather than being left out, so the
 * filter's own value always says which band it is and the page can split it
 * without a lookup table.
 */
export const BUDGET_BANDS = [
  { value: "0-5000000", label: "Under ₹50 L" },
  { value: "5000000-10000000", label: "₹50 L – ₹1 Cr" },
  { value: "10000000-20000000", label: "₹1 – 2 Cr" },
  { value: "20000000-50000000", label: "₹2 – 5 Cr" },
  { value: "50000000-100000000", label: "₹5 – 10 Cr" },
  { value: "100000000-", label: "Above ₹10 Cr" },
] as const;

/** Split a band back into the two figures the API takes. */
export function splitBudgetBand(
  band: string | undefined,
): { min?: string; max?: string } {
  if (!band) return {};
  const [min, max] = band.split("-");
  return { min: min || undefined, max: max || undefined };
}
