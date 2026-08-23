/**
 * The budget bands the leads filter speaks in.
 *
 * Nobody in a Mumbai brokerage says "fifteen million". They say "1.5 Cr", and a
 * filter that asked for rupees would be asking the wrong question. Budgets are
 * typed as figures on the lead form -- that is where the exact number belongs --
 * but *narrowing a list* is a coarse question, and these are the six answers
 * anyone actually gives to it.
 */

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
